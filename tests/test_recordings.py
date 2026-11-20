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


class _ApiError(Exception):
    def __init__(self, code):
        super().__init__(f"{code} error")
        self.code = code


def _scripted_provider(script):
    """GeminiProvider שבמקום רשת מחזיר תשובות לפי תסריט: {model: [תשובה או שגיאה, ...]}."""
    from modelplus.services.llm import GeminiProvider

    class Scripted(GeminiProvider):
        calls = []

        def _call(self, model, prompt):
            self.calls.append(model)
            result = script[model].pop(0)
            if isinstance(result, Exception):
                raise result
            return result

    return Scripted("key", "main", fallbacks=["backup"], attempts=2, backoff_seconds=0)


def test_gemini_retries_busy_model_then_succeeds():
    p = _scripted_provider({"main": [_ApiError(503), '{"ok": 1}']})
    assert p.generate_json("x") == {"ok": 1}
    assert p.calls == ["main", "main"]


def test_gemini_falls_back_when_main_keeps_failing():
    p = _scripted_provider({"main": [_ApiError(503), _ApiError(504)], "backup": ['{"ok": 2}']})
    assert p.generate_json("x") == {"ok": 2}
    assert p.calls == ["main", "main", "backup"]


def test_gemini_skips_retry_on_non_retryable_error():
    p = _scripted_provider({"main": [_ApiError(404)], "backup": ['{"ok": 3}']})
    assert p.generate_json("x") == {"ok": 3}
    assert p.calls == ["main", "backup"]


def test_gemini_gives_clear_error_when_all_fail():
    p = _scripted_provider({"main": [_ApiError(503)] * 2, "backup": [_ApiError(503)] * 2})
    with pytest.raises(LLMError) as err:
        p.generate_json("x")
    assert "נסה שוב" in str(err.value)


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
    assert client.get("/recordings/1/media").status_code == 302  # עדיין טיוטה: הסרטון לא נשלח, מפנים חזרה
    login(client, lect.id)
    client.post("/recordings/1/publish", data={"published": "1"})
    login(client, stud.id)
    res = client.get("/recordings/1/media", headers={"Range": "bytes=1-3"})
    assert res.status_code == 206 and res.data == b"ide"  # Range עובד, כך שאפשר לקפוץ לפרק
    res.close()
    login(client, outsider.id)
    assert client.get("/recordings/1/media").status_code == 302


def test_course_shows_cards_and_recording_page_has_details(app, client):
    conn = connect(app.config["DATABASE"])
    users = UserService(conn)
    lect = users.create("l9@test.ac.il", "מרצה", "lecturer")
    stud = users.create("s9@test.ac.il", "סטודנט", "student")
    course = CourseService(conn).create("קורס")
    EnrollmentService(conn).enroll_many(course.id, [lect, stud])
    recs = RecordingService(conn, FileStore(app.config["UPLOAD_DIR"]))
    rec = _upload(recs, course.id)
    recs.process(rec.id, FakeTranscriber(), LessonSummarizer(FakeLLM()))
    recs.set_published(rec.id, True)
    conn.close()

    login(client, stud.id)
    course_page = client.get(f"/courses/{course.id}").get_data(as_text=True)
    assert f'href="/recordings/{rec.id}"' in course_page and "rec-card" in course_page
    assert "ראשי פרקים" not in course_page  # הפרטים רק בעמוד ההקלטה

    page = client.get(f"/recordings/{rec.id}").get_data(as_text=True)
    assert "ראשי פרקים" in page and "Design Patterns" in page and "שיעור על UML" in page
    assert f'class="back-link" href="/courses/{course.id}#recordings"' in page
    assert "מחק הקלטה" not in page  # סטודנט לא רואה כפתורי ניהול
    login(client, lect.id)
    assert "מחק הקלטה" in client.get(f"/recordings/{rec.id}").get_data(as_text=True)


def test_hebrew_date_filter():
    from modelplus import date_he

    assert date_he("2026-11-20 10:00:00").endswith("בנובמבר 2026")
    assert date_he("garbage") == "garbage"


# ---------- drafts, publishing and editing ----------
def test_new_recording_is_a_draft_hidden_from_students(recs, people):
    from modelplus.errors import NotFound

    rec = _upload(recs, people["course"].id)
    assert not rec.published
    assert recs.list(people["course"].id, include_drafts=False) == []
    assert len(recs.list(people["course"].id)) == 1
    with pytest.raises(NotFound):
        recs.get_visible(rec.id, can_manage=False)
    recs.set_published(rec.id, True)
    assert recs.get_visible(rec.id, can_manage=False).published


def test_parse_clock():
    from modelplus.services.recordings import parse_clock

    assert parse_clock("75") == 75
    assert parse_clock("1:15") == 75
    assert parse_clock("1:02:30") == 3750
    for bad in ("", "1:75", "a:10", "-1", "1:2:3:4"):
        with pytest.raises(ValidationError):
            parse_clock(bad)


def test_edit_details_chapters_sorted_and_validated(recs, people):
    rec = _upload(recs, people["course"].id)
    recs.process(rec.id, FakeTranscriber(), LessonSummarizer(FakeLLM()))
    done = recs.update_details(rec.id, "שם חדש", "סיכום שלי", ["נקודה א", "", "נקודה ב"],
                               [("5:00", "פרק שני"), ("0:00", "פתיחה"), ("", "")])
    assert done.title == "שם חדש" and done.summary == "סיכום שלי"
    assert done.key_points == ["נקודה א", "נקודה ב"]
    assert done.chapters == [{"start": 0, "title": "פתיחה"}, {"start": 300, "title": "פרק שני"}]
    with pytest.raises(ValidationError):
        recs.update_details(rec.id, "", "", [], [])                   # בלי שם
    with pytest.raises(ValidationError):
        recs.update_details(rec.id, "שם", "", [], [("1:00", "")])     # פרק בלי כותרת
    with pytest.raises(ValidationError):
        recs.update_details(rec.id, "שם", "", [], [("1:00", "א"), ("1:00", "ב")])  # אותו זמן


def test_edit_transcript_keeps_times(recs, people):
    rec = _upload(recs, people["course"].id)
    recs.process(rec.id, FakeTranscriber(), LessonSummarizer(FakeLLM()))
    done = recs.update_transcript(rec.id, ["טקסט מתוקן", "עוד תיקון"])
    assert [s["text"] for s in done.transcript] == ["טקסט מתוקן", "עוד תיקון"]
    assert [s["start"] for s in done.transcript] == [0.0, 300.0]
    with pytest.raises(ValidationError):
        recs.update_transcript(rec.id, ["רק אחד"])


def test_cannot_edit_while_processing(recs, people):
    rec = _upload(recs, people["course"].id)  # עדיין 'uploaded'
    with pytest.raises(ValidationError):
        recs.update_details(rec.id, "שם", "", [], [])


def test_only_lecturer_edits_and_publishes(app, client):
    conn = connect(app.config["DATABASE"])
    users = UserService(conn)
    lect = users.create("l8@test.ac.il", "מרצה", "lecturer")
    stud = users.create("s8@test.ac.il", "סטודנט", "student")
    course = CourseService(conn).create("קורס")
    EnrollmentService(conn).enroll_many(course.id, [lect, stud])
    recs = RecordingService(conn, FileStore(app.config["UPLOAD_DIR"]))
    rec = _upload(recs, course.id)
    recs.process(rec.id, FakeTranscriber(), LessonSummarizer(FakeLLM()))
    conn.close()

    login(client, stud.id)
    assert client.get(f"/recordings/{rec.id}").status_code == 302  # טיוטה: כאילו לא קיימת
    client.post(f"/recordings/{rec.id}/publish", data={"published": "1"})
    client.post(f"/recordings/{rec.id}/edit", data={"title": "פריצה"})
    conn = connect(app.config["DATABASE"])
    row = conn.execute("SELECT published, title FROM recordings WHERE id = ?", (rec.id,)).fetchone()
    assert row["published"] == 0 and row["title"] == "שיעור 1"

    login(client, lect.id)
    page = client.get(f"/recordings/{rec.id}?edit=1").get_data(as_text=True)
    assert 'id="rec-edit"' in page and "פרסם לסטודנטים" in page
    client.post(f"/recordings/{rec.id}/edit", data={
        "title": "UML מתוקן", "summary": "ס", "key_point": ["א"],
        "chapter_time": ["0:00", "2:00"], "chapter_title": ["פתיחה", "סיום"],
        "segment": ["אחד", "שתיים"],
    })
    client.post(f"/recordings/{rec.id}/publish", data={"published": "1"})
    login(client, stud.id)
    page = client.get(f"/recordings/{rec.id}").get_data(as_text=True)
    assert "UML מתוקן" in page and "סיום" in page and "שתיים" in page
    assert 'id="rec-edit"' not in client.get(f"/recordings/{rec.id}?edit=1").get_data(as_text=True)


def test_existing_recordings_stay_published_after_migration(tmp_path):
    import sqlite3

    from modelplus.db import connect, init_schema

    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE recordings (id INTEGER PRIMARY KEY, course_id INT, title TEXT, file_path TEXT, mime TEXT, "
                "status TEXT, transcript_json TEXT, summary TEXT, key_points_json TEXT, chapters_json TEXT, error TEXT, "
                "created_at TEXT)")
    old.execute("INSERT INTO recordings VALUES (1, 1, 'ישנה', 'x', 'video/mp4', 'ready', '[]', '', '[]', '[]', '', '')")
    old.commit()
    old.close()
    conn = connect(path)
    init_schema(conn)
    assert conn.execute("SELECT published FROM recordings WHERE id = 1").fetchone()[0] == 1
