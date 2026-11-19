import io

import pytest
from werkzeug.datastructures import FileStorage

from modelplus.db import connect
from modelplus.errors import ValidationError
from modelplus.services.content import FileStore
from modelplus.services.courses import CourseService, EnrollmentService
from modelplus.services.llm import LessonSummarizer, LLMError, LLMProvider, fmt_time, parse_json
from modelplus.services.recordings import RecordingService
from modelplus.services.transcription import Segment, Transcriber
from modelplus.services.users import UserService
from tests.conftest import login

SEGMENTS = [Segment(0.0, 30.0, "שלום לכולם, היום נדבר על UML"), Segment(300.0, 330.0, "עכשיו נעבור ל-Design Patterns")]


class FakeTranscriber(Transcriber):
    def __init__(self):
        self.calls = 0

    def transcribe(self, media_path):
        self.calls += 1
        return SEGMENTS


class FakeLLM(LLMProvider):
    def __init__(self, response=None, fail=False):
        self.response = response or {
            "summary": "שיעור על UML ותבניות עיצוב.",
            "key_points": ["UML מתאר מבנה", "Patterns הם פתרונות חוזרים"],
            "chapters": [{"start": 300, "title": "Design Patterns"}, {"start": 0, "title": "UML"},
                         {"start": 9999, "title": "מחוץ להקלטה"}, {"start": "x", "title": "שבור"}],
        }
        self.fail = fail
        self.prompts = []

    def generate_json(self, prompt):
        self.prompts.append(prompt)
        if self.fail:
            raise LLMError("המכסה נגמרה")
        return self.response


def _upload(service, course_id, name="lesson.mp4", data=b"fake-video"):
    return service.create(course_id, "שיעור 1", name, "video/mp4", FileStorage(io.BytesIO(data), name))


@pytest.fixture
def recs(db, tmp_path):
    return RecordingService(db, FileStore(str(tmp_path / "files")))


def test_upload_saves_file(recs, people):
    rec = _upload(recs, people["course"].id)
    assert rec.status == "uploaded" and rec.processing and rec.is_video
    assert recs.files.path(rec.file_path).read_bytes() == b"fake-video"


def test_upload_rejects_non_media(recs, people):
    with pytest.raises(ValidationError):
        _upload(recs, people["course"].id, name="notes.pdf")


def test_process_pipeline(recs, people):
    rec = _upload(recs, people["course"].id)
    llm = FakeLLM()
    done = recs.process(rec.id, FakeTranscriber(), LessonSummarizer(llm))
    assert done.status == "ready"
    assert done.summary.startswith("שיעור על UML")
    assert len(done.key_points) == 2
    # ממוין, ובלי פרקים שמחוץ להקלטה או שבורים
    assert done.chapters == [{"start": 0, "title": "UML"}, {"start": 300, "title": "Design Patterns"}]
    assert done.transcript[0]["text"].startswith("שלום")
    assert "[300] עכשיו נעבור" in llm.prompts[0]


def test_summary_failure_keeps_transcript_and_retry_skips_transcription(recs, people):
    rec = _upload(recs, people["course"].id)
    transcriber = FakeTranscriber()
    failed = recs.process(rec.id, transcriber, LessonSummarizer(FakeLLM(fail=True)))
    assert failed.status == "failed" and "המכסה" in failed.error
    assert failed.transcript

    recs.retry(rec.id)
    ok = recs.process(rec.id, transcriber, LessonSummarizer(FakeLLM()))
    assert ok.status == "ready"
    assert transcriber.calls == 1  # לא תמללנו שוב


def test_transcriber_crash_marks_failed(recs, people):
    class Broken(Transcriber):
        def transcribe(self, media_path):
            raise RuntimeError("ffmpeg לא מותקן במחשב")

    rec = _upload(recs, people["course"].id)
    assert recs.process(rec.id, Broken(), LessonSummarizer(FakeLLM())).status == "failed"


def test_retry_only_failed(recs, people):
    rec = _upload(recs, people["course"].id)
    with pytest.raises(ValidationError):
        recs.retry(rec.id)


def test_parse_json_handles_code_fence():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('הנה: {"a": 2}') == {"a": 2}
    with pytest.raises(LLMError):
        parse_json("לא JSON")


def test_fmt_time():
    assert fmt_time(0) == "0:00"
    assert fmt_time(75) == "1:15"
    assert fmt_time(3725) == "1:02:05"


def test_gemini_requires_key():
    from modelplus.services.llm import GeminiProvider

    with pytest.raises(LLMError):
        GeminiProvider("", "gemini-3.8-flash")


def test_media_only_for_members_and_upload_only_for_lecturer(app, client):
    conn = connect(app.config["DATABASE"])
    users = UserService(conn)
    lect = users.create("l@test.ac.il", "מרצה", "lecturer")
    stud = users.create("s@test.ac.il", "סטודנט", "student")
    outsider = users.create("o@test.ac.il", "זר", "student")
    course = CourseService(conn).create("קורס")
    EnrollmentService(conn).enroll_many(course.id, [lect, stud])
    conn.close()

    login(client, stud.id)
    client.post(f"/courses/{course.id}/recordings", data={"file": (io.BytesIO(b"x"), "a.mp4")},
                content_type="multipart/form-data")
    conn = connect(app.config["DATABASE"])
    assert conn.execute("SELECT COUNT(*) FROM recordings").fetchone()[0] == 0

    login(client, lect.id)
    client.post(f"/courses/{course.id}/recordings", data={"title": "שיעור", "file": (io.BytesIO(b"video"), "a.mp4")},
                content_type="multipart/form-data")
    assert conn.execute("SELECT COUNT(*) FROM recordings").fetchone()[0] == 1

    login(client, stud.id)
    res = client.get("/recordings/1/media", headers={"Range": "bytes=1-3"})
    assert res.status_code == 206 and res.data == b"ide"  # Range עובד, כך שאפשר לקפוץ לפרק
    res.close()
    login(client, outsider.id)
    assert client.get("/recordings/1/media").status_code == 302
