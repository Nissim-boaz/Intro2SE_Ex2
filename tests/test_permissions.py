import pytest

from modelplus.db import connect
from modelplus.errors import Forbidden
from modelplus.services.courses import CourseService, EnrollmentService
from modelplus.services.users import UserService
from tests.conftest import login


def test_enrollment_roles(db, people):
    e = EnrollmentService(db)
    c = people["course"].id
    assert e.role_in(c, people["lecturer"]) == "lecturer"
    assert e.role_in(c, people["s1"]) == "student"
    assert e.role_in(c, people["admin"]) == "admin"
    assert e.role_in(c, people["outsider"]) is None


def test_require_manager(db, people):
    e = EnrollmentService(db)
    c = people["course"].id
    e.require_manager(c, people["lecturer"])
    e.require_manager(c, people["admin"])
    with pytest.raises(Forbidden):
        e.require_manager(c, people["s1"])


def test_require_member_blocks_outsider(db, people):
    with pytest.raises(Forbidden):
        EnrollmentService(db).require_member(people["course"].id, people["outsider"])


def test_courses_for_user(db, people):
    e = EnrollmentService(db)
    CourseService(db).create("קורס אחר")
    assert [c.id for c in e.courses_for(people["s1"])] == [people["course"].id]
    assert len(e.courses_for(people["admin"])) == 2
    assert e.courses_for(people["outsider"]) == []


# ---- HTTP level ----
def _seed(app):
    conn = connect(app.config["DATABASE"])
    users = UserService(conn)
    admin = users.find_by_email("admin@test.ac.il")
    lect = users.create("l@test.ac.il", "מרצה", "lecturer")
    stud = users.create("s@test.ac.il", "סטודנט", "student")
    course = CourseService(conn).create("קורס")
    EnrollmentService(conn).enroll_many(course.id, [lect, stud])
    conn.close()
    return admin, lect, stud, course


def test_anonymous_redirected_to_login(client):
    res = client.get("/")
    assert res.status_code == 302 and "/login" in res.headers["Location"]


def test_admin_pages_only_for_admin(app, client):
    admin, lect, stud, _ = _seed(app)
    for user, expected in ((stud, 403), (lect, 403), (admin, 200)):
        login(client, user.id)
        assert client.get("/admin/").status_code == expected


def test_course_page_only_for_members(app, client):
    admin, lect, stud, course = _seed(app)
    outsider = UserService(connect(app.config["DATABASE"])).create("o@test.ac.il", "זר", "student")
    login(client, stud.id)
    assert client.get(f"/courses/{course.id}").status_code == 200
    login(client, outsider.id)
    assert client.get(f"/courses/{course.id}", follow_redirects=False).status_code == 302


def test_mock_login_flow(app, client):
    _, _, stud, _ = _seed(app)
    res = client.post("/auth/mock", data={"user_id": stud.id})
    assert res.status_code == 302
    assert "סטודנט" in client.get("/").get_data(as_text=True)


def test_google_login_unknown_email(app, client):
    class FakeVerifier:
        def verify(self, credential):
            return {"email": "nobody@gmail.com", "name": "x"}

    app.extensions["google_verifier"] = FakeVerifier()
    res = client.post("/auth/google", data={"credential": "x"}, follow_redirects=True)
    assert "לא רשום במערכת" in res.get_data(as_text=True)


def test_google_login_known_email(app, client):
    _, _, stud, _ = _seed(app)

    class FakeVerifier:
        def verify(self, credential):
            return {"email": "s@test.ac.il", "name": "x"}

    app.extensions["google_verifier"] = FakeVerifier()
    client.post("/auth/google", data={"credential": "x"})
    with client.session_transaction() as s:
        assert s["user_id"] == stud.id


def test_admin_cannot_change_own_role(app, client):
    admin, *_ = _seed(app)
    login(client, admin.id)
    res = client.post(f"/admin/users/{admin.id}", data={"name": admin.name, "role": "student"}, follow_redirects=True)
    assert "אי אפשר לשנות את התפקיד של עצמך" in res.get_data(as_text=True)
    assert UserService(connect(app.config["DATABASE"])).get(admin.id).role == "admin"


def test_back_link_on_report_points_to_course(app, client):
    admin, lect, stud, course = _seed(app)
    login(client, lect.id)
    client.post(f"/courses/{course.id}/attendance/samples", data={"lesson_number": 1})
    html = client.get("/attendance/lessons/1").get_data(as_text=True)
    assert f'class="back-link" href="/courses/{course.id}#attendance"' in html
