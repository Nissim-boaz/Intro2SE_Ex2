import io
from datetime import datetime

import pytest
from werkzeug.datastructures import FileStorage

from moodleplus.db import connect
from moodleplus.errors import ValidationError
from moodleplus.services.assignments import AssignmentService, left_he, parse_due
from moodleplus.services.content import FileStore
from moodleplus.services.courses import CourseService, EnrollmentService
from moodleplus.services.users import UserService
from tests.conftest import login

DUE = "2026-11-25T23:59"
DUE_TS = datetime(2026, 11, 25, 23, 59).timestamp()


def _file(name="hw.pdf", data=b"%PDF-1"):
    return FileStorage(io.BytesIO(data), name)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock(DUE_TS - 3600)


@pytest.fixture
def asg(db, tmp_path, clock):
    return AssignmentService(db, FileStore(str(tmp_path / "files")), clock=clock)


def test_create_needs_title_and_due(asg, people):
    c = people["course"].id
    with pytest.raises(ValidationError):
        asg.create(c, "  ", "", DUE)
    with pytest.raises(ValidationError):
        asg.create(c, "מטלה 1", "", "")
    a = asg.create(c, "מטלה 1", "להגיש PDF", DUE, "brief.pdf", _file("brief.pdf"))
    assert a.due_at == DUE_TS and a.file_name == "brief.pdf" and a.due_input == DUE
    assert asg.files.path(a.file_path).read_bytes() == b"%PDF-1"


def test_submit_resubmit_replaces_file(asg, people):
    a = asg.create(people["course"].id, "מטלה", "", DUE)
    first = asg.submit(a.id, people["s1"], "v1.pdf", _file("v1.pdf", b"one"))
    second = asg.submit(a.id, people["s1"], "v2.pdf", _file("v2.pdf", b"two"))
    assert second.id == first.id and second.file_name == "v2.pdf" and not second.late
    assert not asg.files.path(first.file_path).exists()  # the old file is gone
    with pytest.raises(ValidationError):
        asg.submit(a.id, people["s1"], "", None)


def test_late_submission_is_allowed_and_marked(asg, people, clock):
    a = asg.create(people["course"].id, "מטלה", "", DUE)
    clock.t = DUE_TS + 60
    sub = asg.submit(a.id, people["s1"], "late.pdf", _file())
    assert sub.late
    # an extension from the lecturer fixes the mark on work already sent
    asg.update(a.id, "מטלה", "", "2026-11-27T23:59")
    assert not asg.get_submission(sub.id).late


def test_grade_validation_and_resubmit_until_published(asg, people):
    a = asg.create(people["course"].id, "מטלה", "", DUE)
    sub = asg.submit(a.id, people["s1"], "a.pdf", _file())
    for bad in ("abc", "101", "-1"):
        with pytest.raises(ValidationError):
            asg.grade(sub.id, bad, "")
    graded = asg.grade(sub.id, "95", "יפה מאוד")
    assert graded.grade == 95 and graded.feedback == "יפה מאוד"
    # the student can't tell it was graded, so resubmitting still works, and the old grade goes away
    again = asg.submit(a.id, people["s1"], "b.pdf", _file())
    assert again.id == sub.id and again.grade is None and again.feedback == ""
    asg.grade(sub.id, "90", "")
    asg.set_grades_published(a.id, True)
    with pytest.raises(ValidationError):
        asg.submit(a.id, people["s1"], "c.pdf", _file())


def test_roster_and_counts(asg, people):
    c = people["course"].id
    a = asg.create(c, "מטלה", "", DUE)
    s = asg.submit(a.id, people["s2"], "a.pdf", _file())
    roster = asg.roster(a.id)
    assert [u.id for u, _ in roster] == [people["s2"].id, people["s1"].id]  # waiting for grading comes first
    assert roster[1][1] is None
    assert asg.counts(c)[a.id] == {"submitted": 1, "ungraded": 1, "appeals": 0}
    asg.grade(s.id, "80", "")
    assert asg.counts(c)[a.id] == {"submitted": 1, "ungraded": 0, "appeals": 0}
    assert asg.my_submissions(c, people["s2"].id)[a.id].grade == 80


def test_delete_removes_files(asg, people):
    a = asg.create(people["course"].id, "מטלה", "", DUE, "b.pdf", _file())
    sub = asg.submit(a.id, people["s1"], "a.pdf", _file())
    asg.delete(a.id)
    assert not asg.files.path(a.file_path).exists() and not asg.files.path(sub.file_path).exists()


def test_parse_due_and_time_left():
    assert parse_due(DUE) == DUE_TS
    assert left_he(-5) == "המועד עבר"
    assert left_he(30 * 60) == "פחות משעה"
    assert left_he(2 * 3600 + 5) == "עוד שעתיים"
    assert left_he(5 * 3600) == "עוד 5 שעות"
    assert left_he(2 * 86400 + 10) == "עוד יומיים"
    assert left_he(9 * 86400) == "עוד 9 ימים"


def test_routes_permissions(app, client):
    conn = connect(app.config["DATABASE"])
    users = UserService(conn)
    lect = users.create("l@test.ac.il", "מרצה", "lecturer")
    s1 = users.create("s1@test.ac.il", "סטודנטית", "student")
    s2 = users.create("s2@test.ac.il", "סטודנט", "student")
    course = CourseService(conn).create("קורס")
    EnrollmentService(conn).enroll_many(course.id, [lect, s1, s2])
    conn.close()

    login(client, s1.id)  # a student can't publish
    client.post(f"/courses/{course.id}/assignments", data={"title": "x", "due": DUE})
    conn = connect(app.config["DATABASE"])
    assert conn.execute("SELECT COUNT(*) FROM assignments").fetchone()[0] == 0

    login(client, lect.id)
    r = client.post(f"/courses/{course.id}/assignments", data={"title": "מטלה 1", "due": DUE})
    assert r.status_code == 302 and conn.execute("SELECT COUNT(*) FROM assignments").fetchone()[0] == 1
    assert "מטלה 1" in client.get(f"/courses/{course.id}").get_data(as_text=True)

    login(client, s1.id)
    client.post("/assignments/1/submit", data={"file": (io.BytesIO(b"mine"), "mine.pdf")},
                content_type="multipart/form-data")
    page = client.get("/assignments/1").get_data(as_text=True)
    assert "mine.pdf" in page and "ההגשה שלך" in page
    assert client.get("/submissions/1/file").status_code == 200
    client.post("/submissions/1/grade", data={"grade": "100"})  # can't grade herself
    assert conn.execute("SELECT grade FROM submissions").fetchone()[0] is None

    login(client, s2.id)  # another student sees neither the file nor the grade
    assert client.get("/submissions/1/file").status_code != 200
    assert "mine.pdf" not in client.get("/assignments/1").get_data(as_text=True)

    login(client, lect.id)
    page = client.get("/assignments/1").get_data(as_text=True)
    assert "סטודנטית" in page and "mine.pdf" in page and "1 מתוך 2" in page
    client.post("/submissions/1/grade", data={"grade": "92", "feedback": "מצוין"})
    login(client, s1.id)
    page = client.get("/assignments/1").get_data(as_text=True)
    assert "מצוין" not in page and ">92<" not in page and "נבדק" not in page  # graded, but nothing shows yet
    login(client, lect.id)
    client.post("/assignments/1/publish-grades", data={"published": "1"})
    login(client, s1.id)
    page = client.get("/assignments/1").get_data(as_text=True)
    assert "92" in page and "מצוין" in page and "הגש מחדש" not in page
    conn.close()


def test_grades_stay_hidden_until_published(asg, people):
    c = people["course"].id
    a = asg.create(c, "מטלה", "", DUE)
    assert not a.grades_published
    sub_ = asg.submit(a.id, people["s1"], "a.pdf", _file())
    asg.grade(sub_.id, "88", "טוב")
    mine = asg.submission_of(a.id, people["s1"].id)
    assert mine.graded and not mine.grade_visible and not mine.can_appeal
    assert asg.set_grades_published(a.id, True) == 1
    mine = asg.my_submissions(c, people["s1"].id)[a.id]
    assert mine.grade_visible and mine.can_appeal
    asg.set_grades_published(a.id, False)  # the lecturer can hide them again
    assert not asg.submission_of(a.id, people["s1"].id).grade_visible


def test_appeal_once_then_accept_or_reject(asg, people):
    c = people["course"].id
    a = asg.create(c, "מטלה", "", DUE)
    s1 = asg.submit(a.id, people["s1"], "a.pdf", _file())
    s2 = asg.submit(a.id, people["s2"], "b.pdf", _file())
    asg.grade(s1.id, "70", "")
    asg.grade(s2.id, "60", "")
    with pytest.raises(ValidationError):
        asg.appeal(s1.id, people["s1"], "not published yet")
    asg.set_grades_published(a.id, True)
    with pytest.raises(ValidationError):
        asg.appeal(s1.id, people["s2"], "not mine")
    with pytest.raises(ValidationError):
        asg.appeal(s1.id, people["s1"], "  ")
    pending = asg.appeal(s1.id, people["s1"], "שאלה 2 נבדקה לא נכון")
    assert pending.appeal_status == "pending" and not pending.can_appeal
    with pytest.raises(ValidationError):
        asg.appeal(s1.id, people["s1"], "again")  # one appeal per assignment
    assert asg.counts(c)[a.id]["appeals"] == 1
    assert asg.roster(a.id)[0][1].id == s1.id  # open appeals come first

    with pytest.raises(ValidationError):
        asg.resolve_appeal(s1.id, True, "", "")  # accepting needs a new grade
    done = asg.resolve_appeal(s1.id, True, "צודק, תוקן", "85")
    assert (done.appeal_status, done.grade, done.original_grade) == ("accepted", 85, 70)

    asg.appeal(s2.id, people["s2"], "בבקשה")
    rejected = asg.resolve_appeal(s2.id, False, "")  # a reason is optional
    assert (rejected.appeal_status, rejected.grade) == ("rejected", 60)
    with pytest.raises(ValidationError):
        asg.resolve_appeal(s2.id, True, "", "90")  # already decided


def test_appeal_routes(app, client):
    conn = connect(app.config["DATABASE"])
    users = UserService(conn)
    lect = users.create("l@test.ac.il", "מרצה", "lecturer")
    stud = users.create("s1@test.ac.il", "סטודנטית", "student")
    course = CourseService(conn).create("קורס")
    EnrollmentService(conn).enroll_many(course.id, [lect, stud])
    conn.close()
    login(client, lect.id)
    client.post(f"/courses/{course.id}/assignments", data={"title": "מטלה", "due": DUE})
    login(client, stud.id)
    client.post("/assignments/1/submit", data={"file": (io.BytesIO(b"x"), "a.pdf")}, content_type="multipart/form-data")
    login(client, lect.id)
    client.post("/submissions/1/grade", data={"grade": "70"})
    client.post("/assignments/1/publish-grades", data={"published": "1"})

    login(client, stud.id)
    assert "ערעור על הציון" in client.get("/assignments/1").get_data(as_text=True)
    client.post("/submissions/1/appeal", data={"text": "בדקו שוב את שאלה 3"})
    client.post("/submissions/1/appeal/resolve", data={"decision": "accept", "grade": "100"})  # not allowed
    page = client.get("/assignments/1").get_data(as_text=True)
    assert "ממתין לתשובת המרצה" in page and ">70<" in page

    login(client, lect.id)
    assert "בדקו שוב את שאלה 3" in client.get("/assignments/1").get_data(as_text=True)
    client.post("/submissions/1/appeal/resolve", data={"decision": "accept", "grade": "80", "reply": "תוקן"})
    login(client, stud.id)
    page = client.get("/assignments/1").get_data(as_text=True)
    assert "התקבל, הציון עודכן" in page and ">80<" in page and "תוקן" in page
