import pytest

from moodleplus.db import connect, init_schema
from moodleplus.errors import ValidationError
from moodleplus.services.attendance import (MAX_WRONG_CODES, AlreadyCheckedIn, AttendanceReport, AttendanceService,
                                           SampleClosed, SampleLimitReached, TooManyAttempts, WrongCode)
from moodleplus.services.courses import CourseService, EnrollmentService
from moodleplus.services.tokens import AudioTokenService
from moodleplus.services.users import UserService
from tests.conftest import login
from tests.fakes import FakeClock


@pytest.fixture
def clock():
    return FakeClock(start=600.0)


@pytest.fixture
def svc(db, clock):
    return AttendanceService(db, AudioTokenService("s", clock), clock)


def _open(svc, people, lesson=1, seconds=120):
    return svc.open_sample(people["course"].id, lesson, seconds, people["lecturer"])


def _wrong(svc, sample_id):
    """קוד שלא תקף עכשיו (לא בחלון הנוכחי ולא בקודם)."""
    valid = {svc.audio.code(sample_id, svc.clock.window() - b) for b in range(2)}
    return next(c for c in range(4096) if c not in valid)


# ---------- samples ----------
def test_first_sample_creates_lesson(svc, people):
    s = _open(svc, people, lesson=3)
    assert s.seq == 1 and s.lesson_number == 3
    assert [l.number for l in svc.lessons(people["course"].id)] == [3]


def test_same_lesson_number_joins_existing_lesson(svc, people, clock):
    a = _open(svc, people, lesson=2)
    svc.close_sample(a.id)
    b = _open(svc, people, lesson=2)
    assert b.lesson_id == a.lesson_id and b.seq == 2


def test_sixth_sample_is_refused(svc, people):
    for _ in range(5):
        svc.close_sample(_open(svc, people).id)
    with pytest.raises(SampleLimitReached) as err:
        _open(svc, people)
    assert "5" in err.value.message
    # שיעור אחר עדיין פתוח לדגימות
    assert _open(svc, people, lesson=2).seq == 1


def test_only_one_open_sample_per_course(svc, people):
    _open(svc, people)
    with pytest.raises(ValidationError):
        _open(svc, people, lesson=2)


def test_sample_closes_by_time(svc, people, clock):
    s = _open(svc, people, seconds=60)
    assert svc.open_sample_for(people["course"].id).id == s.id
    clock.advance(61)
    assert svc.open_sample_for(people["course"].id) is None


def test_duration_validation(svc, people):
    with pytest.raises(ValidationError):
        _open(svc, people, seconds=5)
    with pytest.raises(ValidationError):
        _open(svc, people, lesson=0)


# ---------- check-in by audio ----------
def test_check_in_with_current_code(svc, people):
    s = _open(svc, people)
    r = svc.check_in(s.id, people["s1"], svc.audio.code(s.id))
    assert r.method == "audio" and not r.manual


def test_code_heard_a_few_seconds_ago_still_counts(svc, people, clock):
    """השהיה של פענוח בטלפון ושל הרשת: הקוד מהחלון הקודם עוד מתקבל."""
    s = _open(svc, people)
    code = svc.audio.code(s.id)
    clock.advance(5)
    assert svc.check_in(s.id, people["s1"], code).method == "audio"


def test_replayed_recording_is_rejected(svc, people, clock):
    """הקלטה שנשלחה בוואטסאפ והושמעה אחרי יותר מ-8 שניות: הקוד כבר לא תקף."""
    s = _open(svc, people)
    code = svc.audio.code(s.id)
    clock.advance(9)
    with pytest.raises(WrongCode):
        svc.check_in(s.id, people["s1"], code)
    assert svc.record_for(s.id, people["s1"].id) is None


def test_missing_or_garbage_code_is_rejected(svc, people):
    s = _open(svc, people)
    for bad in (None, "", "abc"):
        with pytest.raises(WrongCode):
            svc.check_in(s.id, people["s1"], bad)
    assert svc.count(s.id) == 0


def test_code_of_another_sample_is_rejected(svc, people):
    a = _open(svc, people)
    other = AudioTokenService("s", svc.clock).code(a.id + 1)
    if other == svc.audio.code(a.id):
        pytest.skip("צירוף מקרים של 1 ל-4096")
    with pytest.raises(WrongCode):
        svc.check_in(a.id, people["s1"], other)


def test_wrong_codes_lock_the_student_out(svc, people):
    s = _open(svc, people)
    for i in range(MAX_WRONG_CODES):
        with pytest.raises(WrongCode):
            svc.check_in(s.id, people["s1"], _wrong(svc, s.id))
    assert svc.attempts_left(s.id, people["s1"].id) == 0
    # גם הקוד הנכון כבר לא עוזר, כך שאי אפשר לנחש
    with pytest.raises(TooManyAttempts):
        svc.check_in(s.id, people["s1"], svc.audio.code(s.id))
    # סטודנט אחר לא מושפע
    assert svc.check_in(s.id, people["s2"], svc.audio.code(s.id))


def test_closed_sample_rejects_check_in(svc, people, clock):
    s = _open(svc, people, seconds=60)
    clock.advance(61 + svc.clock.window_seconds)
    with pytest.raises(SampleClosed):
        svc.check_in(s.id, people["s1"], svc.audio.code(s.id))


def test_code_caught_just_before_closing_still_counts(svc, people, clock):
    """הטלפון פענח שנייה לפני הסגירה והבקשה הגיעה שנייה אחריה."""
    s = _open(svc, people, seconds=60)
    clock.advance(59)
    code = svc.audio.code(s.id)
    clock.advance(2)
    assert svc.check_in(s.id, people["s1"], code)


def test_duplicate_check_in_blocked(svc, people):
    s = _open(svc, people)
    svc.check_in(s.id, people["s1"], svc.audio.code(s.id))
    with pytest.raises(AlreadyCheckedIn):
        svc.check_in(s.id, people["s1"], svc.audio.code(s.id))
    assert svc.count(s.id) == 1


def test_attendees_newest_first(svc, people, clock):
    s = _open(svc, people)
    svc.check_in(s.id, people["s1"], svc.audio.code(s.id))
    clock.advance(1)
    svc.check_in(s.id, people["s2"], svc.audio.code(s.id))
    assert [a.name for a in svc.attendees(s.id)] == ["סטודנט שתיים", "סטודנט אחד"]


# ---------- lecturer corrections ----------
def test_manual_mark_and_remove(svc, people):
    s = _open(svc, people)
    svc.close_sample(s.id)  # אפשר לתקן גם אחרי שהדגימה נסגרה
    r = svc.mark_manual(s.id, people["s1"].id, people["lecturer"])
    assert r.manual and r.marked_by == people["lecturer"].id
    with pytest.raises(AlreadyCheckedIn):
        svc.mark_manual(s.id, people["s1"].id, people["lecturer"])
    svc.remove_record(r.id)
    assert svc.record_for(s.id, people["s1"].id) is None


# ---------- report ----------
def test_report_matrix_and_percent(svc, people):
    students = [people["s1"], people["s2"]]
    a = _open(svc, people)
    svc.check_in(a.id, people["s1"], svc.audio.code(a.id))
    svc.mark_manual(a.id, people["s2"].id, people["lecturer"])
    svc.close_sample(a.id)
    b = _open(svc, people)
    svc.check_in(b.id, people["s1"], svc.audio.code(b.id))

    samples, rows = AttendanceReport(svc).build(a.lesson_id, students)
    assert [s.seq for s in samples] == [1, 2]
    by_id = {r.student.id: r for r in rows}
    assert by_id[people["s1"].id].percent == 100
    assert by_id[people["s2"].id].percent == 50
    assert by_id[people["s2"].id].cells[0].manual
    assert by_id[people["s2"].id].cells[1] is None


def test_csv_has_bom_and_hebrew(svc, people):
    a = _open(svc, people)
    svc.check_in(a.id, people["s1"], svc.audio.code(a.id))
    svc.mark_manual(a.id, people["s2"].id, people["lecturer"])
    data = AttendanceReport(svc).to_csv(svc.get_lesson(a.lesson_id), [people["s1"], people["s2"]])
    assert data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig")
    assert "סטודנט אחד" in text and "נוכח" in text and "סימון ידני" in text and "100%" in text


# ---------- migration from the QR era ----------
def test_legacy_records_are_migrated(tmp_path):
    conn = connect(str(tmp_path / "old.db"))
    conn.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, name TEXT, role TEXT);
        CREATE TABLE attendance_records (
            id INTEGER PRIMARY KEY, sample_id INTEGER, student_id INTEGER, at REAL,
            ip TEXT NOT NULL DEFAULT '', method TEXT NOT NULL CHECK (method IN ('qr_audio', 'qr_only')),
            status TEXT NOT NULL, reasons TEXT NOT NULL DEFAULT '');
        CREATE UNIQUE INDEX ux_record_sample_student ON attendance_records (sample_id, student_id);
        INSERT INTO attendance_records (id, sample_id, student_id, at, method, status) VALUES
            (1, 1, 1, 1.0, 'qr_audio', 'ok'), (2, 1, 2, 1.0, 'qr_only', 'approved'),
            (3, 1, 3, 1.0, 'qr_only', 'suspicious'), (4, 1, 4, 1.0, 'qr_only', 'rejected');
    """)
    conn.execute("PRAGMA foreign_keys=OFF")  # בטבלה הישנה אין דגימות אמיתיות
    init_schema(conn)
    rows = conn.execute("SELECT id, method FROM attendance_records ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [(1, "audio"), (2, "manual")]
    indexes = {r[1] for r in conn.execute("PRAGMA index_list(attendance_records)")}
    assert "ux_record_sample_student" in indexes
    conn.close()


# ---------- HTTP flow ----------
def _http_setup(app):
    clock = FakeClock(start=600.0)
    app.extensions["token_clock"] = clock
    conn = connect(app.config["DATABASE"])
    users = UserService(conn)
    lect = users.create("l@test.ac.il", "מרצה", "lecturer")
    stud = users.create("s@test.ac.il", "סטודנט", "student")
    other = users.create("o@test.ac.il", "סטודנטית", "student")
    course = CourseService(conn).create("קורס")
    EnrollmentService(conn).enroll_many(course.id, [lect, stud, other])
    conn.close()
    return clock, lect, stud, course


def test_full_check_in_flow(app, client):
    clock, lect, stud, course = _http_setup(app)
    login(client, stud.id)
    assert "אין דגימה פתוחה" in client.get(f"/api/courses/{course.id}/attendance/panel").get_data(as_text=True)

    login(client, lect.id)
    client.post(f"/courses/{course.id}/attendance/samples", data={"lesson_number": 1, "minutes": 2})
    live = client.get("/api/attendance/samples/1/live").get_json()
    assert live["open"] and len(live["audio_symbols"]) == 5 and live["attendees"] == []
    assert "qr_svg" not in live and "token" not in live

    # הכפתור מופיע אצל הסטודנט בלי לרענן את העמוד
    login(client, stud.id)
    assert "בצע נוכחות" in client.get(f"/api/courses/{course.id}/attendance/panel").get_data(as_text=True)
    clock.advance(2)
    code = AudioTokenService.decode(live["audio_symbols"])
    res = client.post("/api/attend/1", json={"audio_code": code})
    assert res.status_code == 200 and res.get_json()["ok"]
    assert "נרשמת" in client.get(f"/api/courses/{course.id}/attendance/panel").get_data(as_text=True)
    assert client.post("/api/attend/1", json={"audio_code": code}).status_code == 409

    # השם מופיע ברשימה החיה של המרצה
    login(client, lect.id)
    live = client.get("/api/attendance/samples/1/live").get_json()
    assert [a["name"] for a in live["attendees"]] == ["סטודנט"] and live["count"] == 1


def test_wrong_code_returns_message_and_does_not_register(app, client):
    clock, lect, stud, course = _http_setup(app)
    login(client, lect.id)
    client.post(f"/courses/{course.id}/attendance/samples", data={"lesson_number": 1})
    code = AudioTokenService.decode(client.get("/api/attendance/samples/1/live").get_json()["audio_symbols"])
    clock.advance(10)  # כמו הקלטה שהושמעה מאוחר
    login(client, stud.id)
    res = client.post("/api/attend/1", json={"audio_code": code})
    assert res.status_code == 422 and "לא תאם" in res.get_json()["error"]
    login(client, lect.id)
    assert client.get("/api/attendance/samples/1/live").get_json()["count"] == 0


def test_lecturer_marks_and_unmarks_in_report(app, client):
    clock, lect, stud, course = _http_setup(app)
    login(client, lect.id)
    client.post(f"/courses/{course.id}/attendance/samples", data={"lesson_number": 1})
    res = client.post(f"/attendance/samples/1/students/{stud.id}/mark")
    assert res.status_code == 302 and f"#st-{stud.id}" in res.headers["Location"]
    page = client.get("/attendance/lessons/1").get_data(as_text=True)
    assert "ידני" in page
    live = client.get("/api/attendance/samples/1/live").get_json()
    assert live["attendees"][0]["manual"]
    client.post("/attendance/records/1/delete")
    assert client.get("/api/attendance/samples/1/live").get_json()["count"] == 0
    # מרצה לא יכול לסמן את עצמו או מישהו שאינו סטודנט בקורס
    res = client.post(f"/attendance/samples/1/students/{lect.id}/mark")
    assert res.status_code == 302
    assert client.get("/api/attendance/samples/1/live").get_json()["count"] == 0


def test_student_cannot_manage_or_see_live(app, client):
    clock, lect, stud, course = _http_setup(app)
    login(client, stud.id)
    client.post(f"/courses/{course.id}/attendance/samples", data={"lesson_number": 1})
    conn = connect(app.config["DATABASE"])
    assert conn.execute("SELECT COUNT(*) FROM attendance_samples").fetchone()[0] == 0
    login(client, lect.id)
    client.post(f"/courses/{course.id}/attendance/samples", data={"lesson_number": 1})
    login(client, stud.id)
    assert client.get("/api/attendance/samples/1/live").status_code == 403
    client.post(f"/attendance/samples/1/students/{stud.id}/mark")
    assert conn.execute("SELECT COUNT(*) FROM attendance_records").fetchone()[0] == 0
    conn.close()


def test_lecturer_cannot_check_in_or_see_student_panel(app, client):
    clock, lect, stud, course = _http_setup(app)
    login(client, lect.id)
    client.post(f"/courses/{course.id}/attendance/samples", data={"lesson_number": 1})
    code = AudioTokenService.decode(client.get("/api/attendance/samples/1/live").get_json()["audio_symbols"])
    assert client.post("/api/attend/1", json={"audio_code": code}).status_code == 403
    assert client.get(f"/api/courses/{course.id}/attendance/panel").status_code == 403
