import pytest

from modelplus.db import connect
from modelplus.errors import ValidationError
from modelplus.services.attendance import (AlreadyCheckedIn, AttendanceReport, AttendanceService, SampleClosed,
                                           SampleLimitReached)
from modelplus.services.courses import CourseService, EnrollmentService
from modelplus.services.network import CampusNetworkPolicy
from modelplus.services.tokens import AudioTokenService, QrTokenService
from modelplus.services.users import UserService
from tests.conftest import login
from tests.fakes import FakeClock

CAMPUS_IP = "10.1.2.3"
HOME_IP = "84.95.1.1"


@pytest.fixture
def clock():
    return FakeClock(start=600.0)


@pytest.fixture
def svc(db, clock):
    return AttendanceService(
        db, QrTokenService("s", clock), AudioTokenService("s", clock), CampusNetworkPolicy(["10.0.0.0/8"]), clock
    )


def _open(svc, people, lesson=1, seconds=120):
    return svc.open_sample(people["course"].id, lesson, seconds, people["lecturer"])


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


# ---------- scan & check-in ----------
def test_scan_rejects_old_token(svc, people, clock):
    s = _open(svc, people)
    token = svc.qr.token(s.id)
    svc.scan(s.id, token)
    clock.advance(12)
    with pytest.raises(ValidationError):
        svc.scan(s.id, token)


def test_scan_rejects_closed_sample(svc, people):
    s = _open(svc, people)
    token = svc.qr.token(s.id)
    svc.close_sample(s.id)
    with pytest.raises(SampleClosed):
        svc.scan(s.id, token)


def test_check_in_with_audio_is_ok(svc, people):
    s = _open(svc, people)
    r = svc.check_in(s.id, people["s1"], CAMPUS_IP, svc.audio.code(s.id))
    assert (r.status, r.method, r.reasons) == ("ok", "qr_audio", [])


def test_audio_fallback_marks_suspicious(svc, people):
    s = _open(svc, people)
    r = svc.check_in(s.id, people["s1"], CAMPUS_IP, audio_code=None)
    assert (r.status, r.method, r.reasons) == ("suspicious", "qr_only", ["no_audio"])


def test_wrong_audio_code_marks_suspicious(svc, people):
    s = _open(svc, people)
    wrong = (svc.audio.code(s.id) + 1) % 4096
    r = svc.check_in(s.id, people["s1"], CAMPUS_IP, wrong)
    assert r.status == "suspicious" and r.reasons == ["audio_mismatch"]


def test_off_campus_marks_suspicious_even_with_audio(svc, people):
    s = _open(svc, people)
    r = svc.check_in(s.id, people["s1"], HOME_IP, svc.audio.code(s.id))
    assert r.status == "suspicious" and r.method == "qr_audio" and r.reasons == ["off_campus"]


def test_no_campus_list_means_no_ip_check():
    assert CampusNetworkPolicy([]).is_campus("8.8.8.8")
    assert not CampusNetworkPolicy(["10.0.0.0/8"]).is_campus("not-an-ip")


def test_campus_policy_reads_file_with_comments(tmp_path):
    f = tmp_path / "c.txt"
    f.write_text("# comment\n132.64.0.0/16  # Ariel\n\n", encoding="utf-8")
    p = CampusNetworkPolicy.from_file(str(f))
    assert p.is_campus("132.64.5.5") and not p.is_campus("1.1.1.1")


def test_duplicate_check_in_blocked(svc, people):
    s = _open(svc, people)
    svc.check_in(s.id, people["s1"], CAMPUS_IP, svc.audio.code(s.id))
    with pytest.raises(AlreadyCheckedIn):
        svc.check_in(s.id, people["s1"], CAMPUS_IP, svc.audio.code(s.id))
    assert svc.count(s.id) == 1


def test_manual_approval(svc, people):
    s = _open(svc, people)
    r = svc.check_in(s.id, people["s1"], HOME_IP)
    assert not r.counts
    assert svc.set_status(r.id, "approved").counts
    with pytest.raises(ValidationError):
        svc.set_status(r.id, "ok")


# ---------- report ----------
def test_report_matrix_and_percent(svc, people):
    students = [people["s1"], people["s2"]]
    a = _open(svc, people)
    svc.check_in(a.id, people["s1"], CAMPUS_IP, svc.audio.code(a.id))
    svc.check_in(a.id, people["s2"], HOME_IP)  # חשוד, לא נספר עד אישור
    svc.close_sample(a.id)
    b = _open(svc, people)
    svc.check_in(b.id, people["s1"], CAMPUS_IP, svc.audio.code(b.id))

    samples, rows = AttendanceReport(svc).build(a.lesson_id, students)
    assert [s.seq for s in samples] == [1, 2]
    by_name = {r.student.id: r for r in rows}
    assert by_name[people["s1"].id].percent == 100
    assert by_name[people["s2"].id].percent == 0
    assert by_name[people["s2"].id].cells[0].status == "suspicious"
    assert by_name[people["s2"].id].cells[1] is None


def test_csv_has_bom_and_hebrew(svc, people):
    a = _open(svc, people)
    svc.check_in(a.id, people["s1"], CAMPUS_IP, svc.audio.code(a.id))
    data = AttendanceReport(svc).to_csv(svc.get_lesson(a.lesson_id), [people["s1"], people["s2"]])
    assert data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig")
    assert "סטודנט אחד" in text and "נוכח" in text and "100%" in text and "חסר" in text


# ---------- HTTP flow ----------
def _http_setup(app):
    clock = FakeClock(start=600.0)
    app.extensions["token_clock"] = clock
    conn = connect(app.config["DATABASE"])
    users = UserService(conn)
    lect = users.create("l@test.ac.il", "מרצה", "lecturer")
    stud = users.create("s@test.ac.il", "סטודנט", "student")
    course = CourseService(conn).create("קורס")
    EnrollmentService(conn).enroll_many(course.id, [lect, stud])
    conn.close()
    return clock, lect, stud, course


def test_full_check_in_flow_with_audio(app, client):
    clock, lect, stud, course = _http_setup(app)
    login(client, lect.id)
    client.post(f"/courses/{course.id}/attendance/samples", data={"lesson_number": 1, "minutes": 2})
    live = client.get("/api/attendance/samples/1/live").get_json()
    assert live["open"] and "<svg" in live["qr_svg"] and len(live["audio_symbols"]) == 5

    login(client, stud.id)
    res = client.get(f"/attend/1?t={live['token']}")
    assert res.status_code == 302
    clock.advance(5)
    code = AudioTokenService.decode(live["audio_symbols"])
    res = client.post("/api/attend/1", json={"audio_code": code}, environ_base={"REMOTE_ADDR": "10.0.0.5"})
    assert res.get_json()["status"] == "ok"
    # בפעם השנייה: כבר רשום
    client.get(f"/attend/1?t={live['token']}")
    res = client.post("/api/attend/1", json={"audio_code": code}, environ_base={"REMOTE_ADDR": "10.0.0.5"})
    assert res.status_code == 409


def test_flow_without_audio_is_suspicious_not_blocked(app, client):
    clock, lect, stud, course = _http_setup(app)
    login(client, lect.id)
    client.post(f"/courses/{course.id}/attendance/samples", data={"lesson_number": 1})
    token = client.get("/api/attendance/samples/1/live").get_json()["token"]
    login(client, stud.id)
    client.get(f"/attend/1?t={token}")
    res = client.post("/api/attend/1", json={"audio_failed": True}, environ_base={"REMOTE_ADDR": "10.0.0.5"})
    body = res.get_json()
    assert res.status_code == 200 and body["status"] == "suspicious"


def test_check_in_without_scan_rejected(app, client):
    clock, lect, stud, course = _http_setup(app)
    login(client, lect.id)
    client.post(f"/courses/{course.id}/attendance/samples", data={"lesson_number": 1})
    login(client, stud.id)
    res = client.post("/api/attend/1", json={"audio_failed": True})
    assert res.status_code == 400


def test_expired_qr_link_shows_message(app, client):
    clock, lect, stud, course = _http_setup(app)
    login(client, lect.id)
    client.post(f"/courses/{course.id}/attendance/samples", data={"lesson_number": 1})
    token = client.get("/api/attendance/samples/1/live").get_json()["token"]
    clock.advance(13)
    login(client, stud.id)
    res = client.get(f"/attend/1?t={token}")
    assert "הקוד פג" in res.get_data(as_text=True)


def test_student_cannot_open_sample_or_see_live(app, client):
    clock, lect, stud, course = _http_setup(app)
    login(client, stud.id)
    client.post(f"/courses/{course.id}/attendance/samples", data={"lesson_number": 1})
    conn = connect(app.config["DATABASE"])
    assert conn.execute("SELECT COUNT(*) FROM attendance_samples").fetchone()[0] == 0
    login(client, lect.id)
    client.post(f"/courses/{course.id}/attendance/samples", data={"lesson_number": 1})
    login(client, stud.id)
    assert client.get("/api/attendance/samples/1/live").status_code == 403
