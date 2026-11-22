import pytest

from moodleplus.errors import ValidationError
from moodleplus.services.attendance import AttendanceService
from moodleplus.services.attendance_appeals import AttendanceAppealService
from moodleplus.services.tokens import AudioTokenService
from tests.conftest import login
from tests.fakes import FakeClock


@pytest.fixture
def setup(db, people):
    clock = FakeClock()
    attendance = AttendanceService(db, AudioTokenService("secret", clock), clock)
    appeals = AttendanceAppealService(db, attendance)
    sample = attendance.open_sample(people["course"].id, 1, 60, people["lecturer"])
    return attendance, appeals, sample, clock


def test_appeal_only_after_the_sample_closes_and_only_once(setup, people):
    attendance, appeals, sample, clock = setup
    with pytest.raises(ValidationError):
        appeals.appeal(sample.id, people["s1"], "still open")
    clock.advance(120)
    with pytest.raises(ValidationError):
        appeals.appeal(sample.id, people["s1"], "   ")
    ap = appeals.appeal(sample.id, people["s1"], "הטלפון לא קלט")
    assert ap.status == "pending" and ap.lesson_number == 1 and ap.seq == 1
    with pytest.raises(ValidationError):
        appeals.appeal(sample.id, people["s1"], "again")
    attendance.mark_manual(sample.id, people["s2"].id, people["lecturer"])
    with pytest.raises(ValidationError):
        appeals.appeal(sample.id, people["s2"], "already present")


def test_accept_marks_present_and_reject_needs_a_reason(setup, people):
    attendance, appeals, sample, clock = setup
    clock.advance(120)
    a1 = appeals.appeal(sample.id, people["s1"], "הייתי")
    a2 = appeals.appeal(sample.id, people["s2"], "גם אני")
    assert appeals.pending_counts(people["course"].id) == {sample.lesson_id: 2}
    done = appeals.resolve(a1.id, people["lecturer"], True, "")
    assert done.status == "accepted" and attendance.record_for(sample.id, people["s1"].id).manual
    appeals.resolve(a2.id, people["lecturer"], False, "")  # a reason is optional
    assert attendance.record_for(sample.id, people["s2"].id) is None
    with pytest.raises(ValidationError):
        appeals.resolve(a2.id, people["lecturer"], True, "")
    assert appeals.pending_for_lesson(sample.lesson_id) == []


def test_history_shows_closed_samples_with_appeals(setup, people):
    attendance, appeals, sample, clock = setup
    clock.advance(120)
    appeals.appeal(sample.id, people["s1"], "הייתי")
    second = attendance.open_sample(people["course"].id, 1, 60, people["lecturer"])
    history = appeals.history(people["course"].id, people["s1"].id)
    assert len(history) == 1 and [c.sample.id for c in history[0].cells] == [sample.id]  # the open one is hidden
    assert history[0].cells[0].appeal.status == "pending" and not history[0].cells[0].can_appeal
    clock.advance(120)
    cells = appeals.history(people["course"].id, people["s1"].id)[0].cells
    assert [c.can_appeal for c in cells] == [False, True] and cells[1].sample.id == second.id


def test_routes(app, client):
    from moodleplus.db import connect
    from moodleplus.services.courses import CourseService, EnrollmentService
    from moodleplus.services.users import UserService

    conn = connect(app.config["DATABASE"])
    users = UserService(conn)
    lect = users.create("l@test.ac.il", "מרצה", "lecturer")
    stud = users.create("s@test.ac.il", "סטודנטית", "student")
    course = CourseService(conn).create("קורס")
    EnrollmentService(conn).enroll_many(course.id, [lect, stud])
    conn.close()
    login(client, lect.id)
    client.post(f"/courses/{course.id}/attendance/samples", data={"lesson_number": "1", "minutes": "1"})
    client.post("/attendance/samples/1/close")

    login(client, stud.id)
    page = client.get(f"/courses/{course.id}").get_data(as_text=True)
    assert "הנוכחות שלי" in page and "ערעור" in page and ">חסר<" in page
    client.post("/attendance/samples/1/appeal", data={"text": "הייתי בשורה האחרונה"})
    client.post("/attendance/appeals/1/resolve", data={"decision": "accept"})  # a student can't decide
    assert "ערעור ממתין לתשובת המרצה" in client.get(f"/courses/{course.id}").get_data(as_text=True)

    login(client, lect.id)
    report = client.get("/attendance/lessons/1").get_data(as_text=True)
    assert "הייתי בשורה האחרונה" in report and "ערעורים על נוכחות" in report
    client.post("/attendance/appeals/1/resolve", data={"decision": "accept"})
    login(client, stud.id)
    page = client.get(f"/courses/{course.id}").get_data(as_text=True)
    assert "ערעור" not in page.split("הנוכחות שלי")[1].split("</section>")[0].replace("ערעורים", "")  # now just present
    assert "סומן ידנית" not in page and "המרצה סימן" not in page  # students don't see manual marks
