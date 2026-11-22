import io
from datetime import datetime

import pytest
from werkzeug.datastructures import FileStorage

from moodleplus.db import connect
from moodleplus.errors import ValidationError
from moodleplus.services.assignments import AssignmentService
from moodleplus.services.content import FileStore
from moodleplus.services.courses import CourseService, EnrollmentService
from moodleplus.services.gradebook import ExamService, Gradebook, fmt_grade, parse_grade
from moodleplus.services.users import UserService
from tests.conftest import login

DUE = "2026-11-25T23:59"
DUE_TS = datetime(2026, 11, 25, 23, 59).timestamp()


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def _file(name="hw.pdf", data=b"x"):
    return FileStorage(io.BytesIO(data), name)


@pytest.fixture
def clock():
    return Clock(DUE_TS - 3600)


@pytest.fixture
def asg(db, tmp_path, clock):
    return AssignmentService(db, FileStore(str(tmp_path / "files")), clock=clock)


@pytest.fixture
def exams(db):
    return ExamService(db)


# ---------- parsing ----------
def test_parse_grade():
    assert parse_grade("87,5") == 87.5 and parse_grade(" 0 ") == 0 and parse_grade("") is None
    for bad in ("abc", "101", "-1", "nan", "inf"):
        with pytest.raises(ValidationError):
            parse_grade(bad)
    assert (fmt_grade(87.0), fmt_grade(87.5), fmt_grade(None), fmt_grade(0)) == ("87", "87.5", "–", "0")


# ---------- weights and the weighted grade ----------
def test_weights_cannot_pass_100(db, exams, asg, people):
    c = people["course"].id
    a = asg.create(c, "מטלה", "", DUE)
    e = exams.create(c, "מבחן", "exam", weight="60")
    book = Gradebook(db)
    with pytest.raises(ValidationError):
        exams.create(c, "בוחן", "quiz", weight="41")
    with pytest.raises(ValidationError):
        book.set_weights(c, {f"a{a.id}": "50", f"e{e.id}": "60"})
    assert book.total_weight(c) == 60  # nothing was saved
    assert book.set_weights(c, {f"a{a.id}": "30", f"e{e.id}": "70"}) == 100


def test_weighted_grade_counts_only_published_grades(db, exams, asg, people):
    c, s1 = people["course"].id, people["s1"]
    a = asg.create(c, "מטלה", "", DUE)
    e = exams.create(c, "מבחן", "exam", weight="60")
    Gradebook(db).set_weights(c, {f"a{a.id}": "20", f"e{e.id}": "60"})
    sub = asg.submit(a.id, s1, "a.pdf", _file())
    asg.grade(sub.id, "100", "")
    exams.save_grades(e.id, {s1.id: "80"})
    row = Gradebook(db).for_student(c, s1.id)
    assert row.weighted is None and all(cell.grade is None for cell in row.cells)  # nothing leaks before publishing
    asg.set_grades_published(a.id, True)
    row = Gradebook(db).for_student(c, s1.id)
    assert (row.weighted, row.covered) == (100, 20)
    exams.set_published(e.id, True)
    row = Gradebook(db).for_student(c, s1.id)
    assert (row.weighted, row.covered) == (85, 80)  # (20*100 + 60*80) / 80
    # a missing grade is not a zero
    assert Gradebook(db).for_student(c, people["s2"].id).weighted is None


def test_lecturer_table_includes_unpublished_and_csv(db, exams, people):
    c = people["course"].id
    e = exams.create(c, "מבחן", "exam", weight="50")
    exams.save_grades(e.id, {people["s1"].id: "77.5"})
    components, rows = Gradebook(db).table(c)
    by_id = {r.student.id: r for r in rows}
    assert len(components) == 1 and by_id[people["s1"].id].weighted == 77.5
    assert by_id[people["s2"].id].weighted is None
    csv = Gradebook(db).to_csv(c)
    assert csv.startswith(b"\xef\xbb\xbf") and "77.5" in csv.decode("utf-8-sig")


# ---------- exam grades ----------
def test_save_grades_is_all_or_nothing_and_blank_clears(exams, people):
    e = exams.create(people["course"].id, "בוחן", "quiz")
    s1, s2 = people["s1"], people["s2"]
    with pytest.raises(ValidationError) as err:
        exams.save_grades(e.id, {s1.id: "90", s2.id: "900"})
    assert s2.name in str(err.value) and exams.grades(e.id) == {}
    with pytest.raises(ValidationError):
        exams.save_grades(e.id, {people["outsider"].id: "90"})
    exams.save_grades(e.id, {s1.id: "90", s2.id: "0"})
    assert exams.grades(e.id)[s2.id].grade == 0
    exams.save_grades(e.id, {s1.id: ""})
    assert s1.id not in exams.grades(e.id)


def test_import_grades_from_file(exams, people):
    e = exams.create(people["course"].id, "מבחן", "exam")
    data = "Email address,Grade/100.00\ns1@test.ac.il,88.5\nS2@test.ac.il,-\nout@test.ac.il,70\n,60\n".encode("utf-8-sig")
    report = exams.import_file(e.id, "grades.csv", data)
    assert (report.updated, report.unknown, report.invalid) == (1, 1, 1)
    assert exams.grades(e.id)[people["s1"].id].grade == 88.5 and people["s2"].id not in exams.grades(e.id)
    with pytest.raises(ValidationError):
        exams.import_file(e.id, "x.csv", "email,name\ns1@test.ac.il,x\n".encode())
    with pytest.raises(ValidationError):
        exams.import_file(e.id, "x.xlsx", b"not really xlsx")


def test_exam_appeal(exams, people):
    e = exams.create(people["course"].id, "מבחן", "exam")
    s1, s2 = people["s1"], people["s2"]
    exams.save_grades(e.id, {s1.id: "70", s2.id: "60"})
    g1, g2 = exams.grades(e.id)[s1.id], exams.grades(e.id)[s2.id]
    with pytest.raises(ValidationError):
        exams.appeal(g1.id, s1, "not published yet")
    exams.set_published(e.id, True)
    with pytest.raises(ValidationError):
        exams.appeal(g1.id, s2, "not mine")
    exams.appeal(g1.id, s1, "שאלה 3")
    with pytest.raises(ValidationError):
        exams.appeal(g1.id, s1, "again")
    with pytest.raises(ValidationError):
        exams.resolve_appeal(g1.id, True, "", "")
    done = exams.resolve_appeal(g1.id, True, "", "82")
    assert (done.grade, done.original_grade, done.appeal_status) == (82, 70, "accepted")
    exams.appeal(g2.id, s2, "בבקשה")
    assert exams.counts(people["course"].id)[e.id] == {"graded": 2, "appeals": 1}
    assert exams.resolve_appeal(g2.id, False, "").appeal_status == "rejected"


# ---------- solution and zeros ----------
def test_solution_publishes_only_after_due_and_closes_submission(asg, people, clock):
    a = asg.create(people["course"].id, "מטלה", "", DUE)
    with pytest.raises(ValidationError):
        asg.set_solution_published(a.id, True)  # no file
    a = asg.save_solution(a.id, "sol.pdf", _file("sol.pdf"))
    with pytest.raises(ValidationError):
        asg.set_solution_published(a.id, True)  # too early
    clock.t = DUE_TS + 60
    assert asg.submit(a.id, people["s1"], "late.pdf", _file()).late  # late is fine until the solution is out
    asg.set_solution_published(a.id, True)
    for st in (people["s1"], people["s2"]):
        with pytest.raises(ValidationError):
            asg.submit(a.id, st, "x.pdf", _file())
    asg.set_solution_published(a.id, False)
    asg.submit(a.id, people["s2"], "x.pdf", _file())
    old = asg.get(a.id).solution_path
    asg.save_solution(a.id, "sol2.pdf", _file("sol2.pdf"))
    assert not asg.files.path(old).exists()
    asg.remove_solution(a.id)
    assert asg.get(a.id).solution_name == ""


def test_zero_for_not_submitting(db, asg, people, clock):
    c = people["course"].id
    a = asg.create(c, "מטלה", "", DUE)
    Gradebook(db).set_weights(c, {f"a{a.id}": "40"})
    asg.submit(a.id, people["s1"], "a.pdf", _file())
    with pytest.raises(ValidationError):
        asg.zero_all_missing(a.id)  # before the due date
    clock.t = DUE_TS + 60
    with pytest.raises(ValidationError):
        asg.set_zero(a.id, people["s1"].id, True)  # did submit
    assert asg.zero_all_missing(a.id) == 1 and asg.zeros(a.id) == {people["s2"].id}
    assert asg.my_zeros(c, people["s2"].id) == set()  # hidden until grades are published
    assert Gradebook(db).for_student(c, people["s2"].id).weighted is None
    asg.submit(a.id, people["s2"], "late.pdf", _file())  # submitting late cancels the zero
    assert asg.zeros(a.id) == set()


def test_published_zero_counts_and_blocks_submitting(db, asg, people, clock):
    c, s2 = people["course"].id, people["s2"]
    a = asg.create(c, "מטלה", "", DUE)
    Gradebook(db).set_weights(c, {f"a{a.id}": "40"})
    clock.t = DUE_TS + 60
    asg.set_zero(a.id, s2.id, True)
    asg.set_grades_published(a.id, True)
    assert Gradebook(db).for_student(c, s2.id).weighted == 0 and asg.my_zeros(c, s2.id) == {a.id}
    with pytest.raises(ValidationError):
        asg.submit(a.id, s2, "x.pdf", _file())
    asg.set_zero(a.id, s2.id, False)
    assert Gradebook(db).for_student(c, s2.id).weighted is None


# ---------- routes ----------
def _setup(app):
    conn = connect(app.config["DATABASE"])
    users = UserService(conn)
    lect = users.create("l@test.ac.il", "מרצה", "lecturer")
    s1 = users.create("s1@test.ac.il", "סטודנטית", "student")
    s2 = users.create("s2@test.ac.il", "סטודנט", "student")
    course = CourseService(conn).create("קורס")
    EnrollmentService(conn).enroll_many(course.id, [lect, s1, s2])
    return conn, lect, s1, s2, course


def test_grade_routes_and_privacy(app, client):
    conn, lect, s1, s2, course = _setup(app)
    login(client, s1.id)
    client.post(f"/courses/{course.id}/exams", data={"title": "x", "kind": "exam"})
    assert conn.execute("SELECT COUNT(*) FROM exams").fetchone()[0] == 0  # students can't create

    login(client, lect.id)
    client.post(f"/courses/{course.id}/exams", data={"title": "מבחן אמצע", "kind": "exam", "weight": "40"})
    client.post("/exams/1/grades", data={f"g_{s1.id}": "91", f"o_{s1.id}": "", f"g_{s2.id}": "", f"o_{s2.id}": ""})
    assert "מבחן אמצע" in client.get(f"/courses/{course.id}/grades").get_data(as_text=True)

    login(client, s1.id)
    page = client.get(f"/courses/{course.id}").get_data(as_text=True)
    assert "מבחן אמצע" in page and "עוד לא פורסם" in page and ">91<" not in page
    for url in ("/exams/1", f"/courses/{course.id}/grades", f"/courses/{course.id}/grades.csv"):
        assert client.get(url).status_code == 302  # lecturer only
    client.post("/exams/1/publish", data={"published": "1"})
    assert conn.execute("SELECT published FROM exams").fetchone()[0] == 0

    login(client, lect.id)
    client.post("/exams/1/publish", data={"published": "1"})
    login(client, s1.id)
    page = client.get(f"/courses/{course.id}").get_data(as_text=True)
    assert ">91<" in page and "ציון משוקלל עד כה" in page and "מבוסס על 40% מהציון הסופי" in page
    login(client, s2.id)
    assert ">91<" not in client.get(f"/courses/{course.id}").get_data(as_text=True)
    client.post("/exam-grades/1/appeal", data={"text": "not mine"})
    login(client, s1.id)
    client.post("/exam-grades/1/appeal/resolve", data={"decision": "accept", "grade": "100"})
    client.post("/exam-grades/1/appeal", data={"text": "שאלה 2"})
    assert conn.execute("SELECT grade, appeal_status FROM exam_grades").fetchone()[:] == (91, "pending")

    login(client, lect.id)
    assert "שאלה 2" in client.get("/exams/1").get_data(as_text=True)
    client.post("/exam-grades/1/appeal/resolve", data={"decision": "accept", "grade": "95"})
    # an old form still showing 91 must not overwrite the new grade
    client.post("/exams/1/grades", data={f"g_{s1.id}": "91", f"o_{s1.id}": "91", f"g_{s2.id}": "70", f"o_{s2.id}": ""})
    assert [r[0] for r in conn.execute("SELECT grade FROM exam_grades ORDER BY id")] == [95, 70]
    conn.close()


def test_solution_route_is_hidden_until_published(app, client):
    conn, lect, s1, s2, course = _setup(app)
    login(client, lect.id)
    client.post(f"/courses/{course.id}/assignments", data={"title": "מטלה", "due": "2020-01-01T10:00"})
    client.post("/assignments/1/solution", data={"file": (io.BytesIO(b"answer"), "sol.pdf")},
                content_type="multipart/form-data")
    assert client.get("/assignments/1/solution").status_code == 200
    login(client, s1.id)
    assert client.get("/assignments/1/solution").status_code == 302
    assert "sol.pdf" not in client.get("/assignments/1").get_data(as_text=True)
    client.post("/assignments/1/solution/publish", data={"published": "1"})  # not a lecturer
    assert client.get("/assignments/1/solution").status_code == 302
    login(client, lect.id)
    client.post("/assignments/1/solution/publish", data={"published": "1"})
    login(client, s1.id)
    page = client.get("/assignments/1").get_data(as_text=True)
    assert "sol.pdf" in page and "ההגשה נסגרה" in page and 'name="file"' not in page
    assert client.get("/assignments/1/solution").data == b"answer"
    conn.close()


def test_filters_send_the_whole_list(app, client):
    conn, lect, s1, s2, course = _setup(app)
    admin = UserService(conn).find_by_email("admin@test.ac.il")
    login(client, s1.id)
    client.post("/requests", data={"subject": "נושא ראשון", "body": "גוף"})
    login(client, admin.id)
    client.post("/requests/1/status", data={"status": "resolved"})
    inbox = client.get("/admin/requests").get_data(as_text=True)
    assert "נושא ראשון" in inbox and 'data-filter-tags="resolved"' in inbox and "data-explicit" not in inbox
    assert 'data-current="open"' in inbox
    users = client.get("/admin/?role=lecturer").get_data(as_text=True)
    assert "סטודנטית" in users and 'data-filter-tags="lecturer"' in users and 'data-current="lecturer" data-explicit' in users
    conn.close()
