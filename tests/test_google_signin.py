"""Real Google sign-in: start-up checks, the ID token check, the main admin's email, and the dev banner."""
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth import crypt, jwt

from moodleplus import ConfigError, create_app
from moodleplus.config import TestConfig
from moodleplus.db import connect
from moodleplus.errors import Forbidden, ValidationError
from moodleplus.services.courses import CourseService, EnrollmentService
from moodleplus.services.google_auth import GoogleTokenVerifier
from moodleplus.services.users import UserService
from tests.conftest import login

CLIENT_ID = "1234-test.apps.googleusercontent.com"


# ---------- the server does not start without a Client ID ----------
def test_no_client_id_with_mock_off_stops_the_server(tmp_path):
    with pytest.raises(ConfigError) as err:
        create_app(TestConfig, DATABASE=str(tmp_path / "a.db"), MOCK_AUTH=False, GOOGLE_CLIENT_ID="")
    assert "GOOGLE_CLIENT_ID" in str(err.value)
    create_app(TestConfig, DATABASE=str(tmp_path / "b.db"), MOCK_AUTH=False, GOOGLE_CLIENT_ID=CLIENT_ID)
    create_app(TestConfig, DATABASE=str(tmp_path / "c.db"), MOCK_AUTH=True, GOOGLE_CLIENT_ID="")


# ---------- the ID token is checked for real, with a test signing key ----------
@pytest.fixture(scope="module")
def keys():
    def make():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()).decode()
        public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                               serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        return private, public
    return make(), make()


@pytest.fixture
def google_keys(monkeypatch, keys):
    """Google's public keys, as far as the verifier knows, are only our first test key."""
    (_, public), _ = keys
    monkeypatch.setattr("google.oauth2.id_token._fetch_certs", lambda request, url: {"k1": public})
    return keys


def _token(private_pem, **claims):
    now = int(time.time())
    payload = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "iat": now, "exp": now + 600,
               "email": "Student@Gmail.com", "email_verified": True, "name": "סטודנטית"}
    payload.update(claims)
    signer = crypt.RSASigner.from_string(private_pem, key_id="k1")
    return jwt.encode(signer, payload).decode()


def test_a_valid_token_passes(google_keys):
    (private, _), _ = google_keys
    assert GoogleTokenVerifier(CLIENT_ID).verify(_token(private)) == {"email": "student@gmail.com", "name": "סטודנטית"}


@pytest.mark.parametrize("claims", [
    {"aud": "someone-else.apps.googleusercontent.com"},   # made for another site
    {"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200},  # expired
    {"iss": "https://evil.example.com"},                   # not issued by Google
    {"email_verified": False},                             # Google never confirmed the address
])
def test_bad_tokens_are_rejected(google_keys, claims):
    (private, _), _ = google_keys
    with pytest.raises(Forbidden):
        GoogleTokenVerifier(CLIENT_ID).verify(_token(private, **claims))


def test_a_token_signed_by_someone_else_is_rejected(google_keys):
    _, (other_private, _) = google_keys
    with pytest.raises(Forbidden):
        GoogleTokenVerifier(CLIENT_ID).verify(_token(other_private))
    with pytest.raises(Forbidden):
        GoogleTokenVerifier(CLIENT_ID).verify("not-a-token")


class _FakeVerifier:
    def __init__(self, email):
        self.email = email

    def verify(self, credential):
        return {"email": self.email, "name": ""}


def test_only_registered_users_get_in(app, client):
    conn = connect(app.config["DATABASE"])
    UserService(conn).create("known@gmail.com", "רשום", "student")
    conn.close()
    app.extensions["google_verifier"] = _FakeVerifier("stranger@gmail.com")
    r = client.post("/auth/google", json={"credential": "x"})
    assert r.status_code == 403 and "לא רשום" in r.get_json()["error"]
    assert client.get("/").status_code == 302  # still signed out
    app.extensions["google_verifier"] = _FakeVerifier("known@gmail.com")
    assert client.post("/auth/google", json={"credential": "x"}).get_json()["ok"]
    assert client.get("/").status_code == 200


# ---------- the main admin follows ADMIN_EMAIL ----------
def test_new_admin_email_moves_the_existing_admin(db):
    users = UserService(db)
    first = users.ensure_admin("admin@example.com")
    course = CourseService(db).create("קורס")
    db.execute("INSERT INTO requests (user_id, subject, status, created_at, updated_at) VALUES (?, 'x', 'new', 0, 0)",
               (first.id,))
    db.commit()
    moved = users.ensure_admin("Me@Gmail.com")
    assert moved.id == first.id and moved.email == "me@gmail.com" and moved.is_admin
    assert [u.email for u in users.list("admin")] == ["me@gmail.com"]  # no second admin
    assert db.execute("SELECT user_id FROM requests").fetchone()[0] == first.id
    assert users.ensure_admin("me@gmail.com").id == first.id  # the next start changes nothing
    assert course.id


def test_new_admin_email_that_already_exists_gets_the_old_admins_data(db, people):
    users = UserService(db)
    old = users.ensure_admin("admin@example.com")
    mine = users.create("me@gmail.com", "אני", "student")
    EnrollmentService(db).enroll(people["course"].id, mine)
    from moodleplus.services.chat import ChatService
    msg = ChatService(db).send(people["course"].id, mine, "שלום")
    db.execute("INSERT INTO message_reads (message_id, user_id, read_at) VALUES (?, ?, 0)", (msg, old.id))
    db.execute("INSERT INTO message_reads (message_id, user_id, read_at) VALUES (?, ?, 0)", (msg, mine.id))
    db.execute("INSERT INTO requests (user_id, subject, status, created_at, updated_at) VALUES (?, 'x', 'new', 0, 0)",
               (old.id,))
    db.commit()
    admin = users.ensure_admin("me@gmail.com")
    assert admin.id == mine.id and admin.is_admin
    assert users.find_by_email("admin@example.com") is None
    assert db.execute("SELECT user_id FROM requests").fetchone()[0] == mine.id         # moved over
    assert db.execute("SELECT COUNT(*) FROM message_reads WHERE message_id = ?", (msg,)).fetchone()[0] == 1
    assert EnrollmentService(db).role_in(people["course"].id, admin) == "admin"
    assert len(users.list("admin")) == 2  # the conftest admin and me: admin@example.com is gone, nobody doubled


# ---------- editing a user's email ----------
def test_admin_changes_a_users_email_and_keeps_their_data(app, client):
    conn = connect(app.config["DATABASE"])
    users = UserService(conn)
    admin = users.find_by_email("admin@test.ac.il")
    stud = users.create("old@test.ac.il", "סטודנטית", "student")
    other = users.create("taken@test.ac.il", "אחר", "student")
    course = CourseService(conn).create("קורס")
    EnrollmentService(conn).enroll(course.id, stud)
    conn.close()
    login(client, admin.id)
    client.post(f"/admin/users/{stud.id}", data={"name": "סטודנטית", "email": "New@Gmail.com", "role": "student"})
    conn = connect(app.config["DATABASE"])
    users = UserService(conn)
    assert users.get(stud.id).email == "new@gmail.com"
    assert EnrollmentService(conn).role_in(course.id, users.get(stud.id)) == "student"  # same account, same courses
    client.post(f"/admin/users/{stud.id}", data={"name": "סטודנטית", "email": "taken@test.ac.il", "role": "student"})
    client.post(f"/admin/users/{stud.id}", data={"name": "סטודנטית", "email": "not-an-email", "role": "student"})
    assert users.get(stud.id).email == "new@gmail.com"
    client.post(f"/admin/users/{stud.id}", data={"name": "סטודנטית", "role": "lecturer"})  # the role picker
    assert users.get(stud.id).email == "new@gmail.com" and users.get(stud.id).role == "lecturer"
    assert other.id
    conn.close()


def test_the_main_admins_email_is_locked(db):
    users = UserService(db)
    main = users.ensure_admin("me@gmail.com")
    with pytest.raises(ValidationError):
        users.update(main.id, main.name, "admin", email="else@gmail.com")
    users.update(main.id, "שם חדש", "admin", email="me@gmail.com")  # unchanged email is fine


def test_the_admin_page_locks_only_that_email(app, client):
    conn = connect(app.config["DATABASE"])
    admin = UserService(conn).find_by_email("admin@test.ac.il")
    conn.close()
    login(client, admin.id)
    page = client.get("/admin/").get_data(as_text=True)
    assert page.count("data-email-locked") == 1


# ---------- HTTPS through the Funnel ----------
def test_session_cookie_is_secure_over_https_only(client):
    over_https = client.get("/login", headers={"X-Forwarded-Proto": "https"}).headers.get("Set-Cookie", "")
    assert "Secure" in over_https
    plain = client.get("/login").headers.get("Set-Cookie", "")
    assert plain and "Secure" not in plain


# ---------- the dev banner ----------
def test_dev_banner_only_in_mock_mode(tmp_path):
    def page(**cfg):
        app = create_app(TestConfig, DATABASE=str(tmp_path / f"{len(cfg)}{cfg.get('MOCK_AUTH')}.db"),
                         UPLOAD_DIR=str(tmp_path / "u"), **cfg)
        return app.test_client().get("/login").get_data(as_text=True)
    assert "מצב פיתוח: התחברות ללא אימות" in page(MOCK_AUTH=True)
    assert "מצב פיתוח" not in page(MOCK_AUTH=False, GOOGLE_CLIENT_ID=CLIENT_ID)


def test_mock_sessions_end_when_mock_mode_is_turned_off(tmp_path):
    from moodleplus.config import TestConfig

    db_path, uploads = str(tmp_path / "s.db"), str(tmp_path / "u")
    dev = create_app(TestConfig, DATABASE=db_path, UPLOAD_DIR=uploads, MOCK_AUTH=True)
    conn = connect(db_path)
    stud = UserService(conn).create("m@test.ac.il", "סטודנט", "student")
    conn.close()
    client = dev.test_client()
    client.post("/auth/mock", data={"user_id": stud.id})
    assert client.get("/").status_code == 200
    real = create_app(TestConfig, DATABASE=db_path, UPLOAD_DIR=uploads, MOCK_AUTH=False, GOOGLE_CLIENT_ID=CLIENT_ID)
    with real.test_client() as same_browser:
        same_browser._cookies = client._cookies  # the same signed cookie, after the restart
        assert same_browser.get("/").status_code == 302  # back to the sign-in page
        real.extensions["google_verifier"] = _FakeVerifier("m@test.ac.il")
        assert same_browser.post("/auth/google", json={"credential": "x"}).get_json()["ok"]
        assert same_browser.get("/").status_code == 200  # a Google session is fine
