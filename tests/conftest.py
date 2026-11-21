import pytest

from moodleplus import create_app
from moodleplus.config import TestConfig
from moodleplus.db import connect, init_schema
from moodleplus.services.courses import CourseService, EnrollmentService
from moodleplus.services.users import UserService


@pytest.fixture
def db(tmp_path):
    conn = connect(str(tmp_path / "test.db"))
    init_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def people(db):
    """אדמין, מרצה, שני סטודנטים וקורס שבו כולם משויכים."""
    users = UserService(db)
    admin = users.create("admin@test.ac.il", "אדמין", "admin")
    lecturer = users.create("lect@test.ac.il", "ד״ר מרצה", "lecturer")
    s1 = users.create("s1@test.ac.il", "סטודנט אחד", "student")
    s2 = users.create("s2@test.ac.il", "סטודנט שתיים", "student")
    outsider = users.create("out@test.ac.il", "לא בקורס", "student")
    course = CourseService(db).create("מבוא להנדסת תוכנה", "7036")
    EnrollmentService(db).enroll_many(course.id, [lecturer, s1, s2])
    return dict(admin=admin, lecturer=lecturer, s1=s1, s2=s2, outsider=outsider, course=course)


@pytest.fixture
def app(tmp_path):
    app = create_app(
        TestConfig,
        DATABASE=str(tmp_path / "app.db"),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        ADMIN_EMAIL="admin@test.ac.il",
    )
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, user_id: int):
    with client.session_transaction() as s:
        s["user_id"] = user_id
