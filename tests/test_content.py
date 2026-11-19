import pytest

from modelplus.db import connect
from modelplus.errors import ValidationError
from modelplus.services.content import ContentService, FileStore
from modelplus.services.courses import CourseService, EnrollmentService
from modelplus.services.users import UserService
from tests.conftest import login


@pytest.fixture
def content(db, tmp_path):
    return ContentService(db, FileStore(str(tmp_path / "files")))


def test_add_blocks_in_order(content, people):
    c = people["course"].id
    a = content.add(c, "text", title="ברוכים הבאים", body="סילבוס")
    b = content.add(c, "link", title="Moodle", url="https://moodle.ariel.ac.il")
    f = content.add(c, "file", file_name="slides.pdf", file_data=b"%PDF")
    assert [x.id for x in content.list(c)] == [a.id, b.id, f.id]
    assert f.title == "slides.pdf"
    assert content.files.path(f.file_path).read_bytes() == b"%PDF"


def test_validation(content, people):
    c = people["course"].id
    with pytest.raises(ValidationError):
        content.add(c, "text")
    with pytest.raises(ValidationError):
        content.add(c, "link", url="javascript:alert(1)")
    with pytest.raises(ValidationError):
        content.add(c, "file", file_name="x")
    with pytest.raises(ValidationError):
        content.add(c, "video")


def test_move_and_edges(content, people):
    c = people["course"].id
    a = content.add(c, "text", title="א")
    b = content.add(c, "text", title="ב")
    content.move(b.id, -1)
    assert [x.title for x in content.list(c)] == ["ב", "א"]
    content.move(b.id, -1)  # כבר ראשון, לא משתנה
    assert [x.title for x in content.list(c)] == ["ב", "א"]
    content.move(b.id, +1)
    assert [x.title for x in content.list(c)] == ["א", "ב"]


def test_update_and_delete(content, people):
    c = people["course"].id
    f = content.add(c, "file", file_name="a.txt", file_data=b"x")
    content.update(f.id, "כותרת חדשה", "תיאור")
    assert content.get(f.id).title == "כותרת חדשה"
    content.delete(f.id)
    assert content.list(c) == []
    assert not content.files.path(f.file_path).exists()


def test_student_cannot_add_content(app, client):
    conn = connect(app.config["DATABASE"])
    stud = UserService(conn).create("s@test.ac.il", "סטודנט", "student")
    course = CourseService(conn).create("קורס")
    EnrollmentService(conn).enroll(course.id, stud)
    conn.close()
    login(client, stud.id)
    client.post(f"/courses/{course.id}/content", data={"kind": "text", "title": "פריצה"})
    conn = connect(app.config["DATABASE"])
    assert conn.execute("SELECT COUNT(*) FROM content_blocks").fetchone()[0] == 0
