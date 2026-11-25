import pytest

from moodleplus.db import connect
from moodleplus.errors import ValidationError
from moodleplus.services.signups import SignupService
from moodleplus.services.users import UserService
from tests.conftest import login


def test_submit_validates(db, people):
    s = SignupService(db)
    for name, email, role in (("", "a@gmail.com", "student"), ("אבי", "not-an-email", "student"),
                              ("אבי", "a@gmail.com", "admin"),          # nobody asks to be admin
                              ("אבי", "s1@test.ac.il", "student")):     # already has access
        with pytest.raises(ValidationError):
            s.submit(name, email, role)
    req = s.submit(" אבי כהן ", "Avi@Gmail.com", "lecturer")
    assert (req.name, req.email, req.role) == ("אבי כהן", "avi@gmail.com", "lecturer")
    with pytest.raises(ValidationError):
        s.submit("אבי", "avi@gmail.com", "student")  # one waiting request per email


def test_approve_creates_the_user_and_reject_removes(db, people):
    s = SignupService(db)
    a = s.submit("אבי", "avi@gmail.com", "lecturer")
    b = s.submit("בתיה", "batya@gmail.com", "student")
    user = s.approve(a.id, role="student")  # the admin may change the role
    assert (user.email, user.role, user.name) == ("avi@gmail.com", "student", "אבי")
    s.reject(b.id)
    assert s.pending() == [] and UserService(db).find_by_email("batya@gmail.com") is None


class _FakeVerifier:
    def __init__(self, email):
        self.email = email

    def verify(self, credential):
        return {"email": self.email, "name": ""}


def test_the_whole_way_from_form_to_google_sign_in(app, client):
    page = client.get("/signup")  # open without signing in
    assert page.status_code == 200 and "בקשת הרשמה" in page.get_data(as_text=True)
    assert 'href="/signup"' in client.get("/login").get_data(as_text=True)
    r = client.post("/signup", data={"name": "נועה", "email": "noa@gmail.com", "role": "student"})
    assert "הבקשה נשלחה" in r.get_data(as_text=True)
    app.extensions["google_verifier"] = _FakeVerifier("noa@gmail.com")
    r = client.post("/auth/google", json={"credential": "x"})
    assert r.status_code == 403 and "בקשת הרשמה" in r.get_json()["error"]  # not approved yet

    conn = connect(app.config["DATABASE"])
    users = UserService(conn)
    admin = users.find_by_email("admin@test.ac.il")
    stud = users.create("s@test.ac.il", "סטודנט", "student")
    conn.close()
    login(client, stud.id)
    client.post("/admin/signups/1/approve", data={"role": "student"})  # students can't approve
    login(client, admin.id)
    page = client.get("/admin/").get_data(as_text=True)
    assert "noa@gmail.com" in page and "בקשות הרשמה" in page
    client.post("/admin/signups/1/approve", data={"role": "student"})
    client.post("/logout")
    assert client.post("/auth/google", json={"credential": "x"}).get_json()["ok"]  # now Google lets her in


def test_a_bot_filling_the_hidden_field_saves_nothing(app, client):
    r = client.post("/signup", data={"name": "bot", "email": "bot@spam.com", "role": "student", "website": "x"})
    assert r.status_code == 200
    conn = connect(app.config["DATABASE"])
    assert SignupService(conn).pending() == []
    conn.close()
