from pathlib import Path

import pytest

from moodleplus.errors import ValidationError
from moodleplus.services.users import StudentImporter, UserService

DATA = Path(__file__).resolve().parent.parent / "data"


def test_create_and_find_user(db):
    users = UserService(db)
    u = users.create("Someone@Test.ac.il", "מישהו", "student")
    assert u.email == "someone@test.ac.il"
    assert users.find_by_email("SOMEONE@test.ac.il").id == u.id


def test_duplicate_email_rejected(db):
    users = UserService(db)
    users.create("a@test.ac.il", "א", "student")
    with pytest.raises(ValidationError):
        users.create("a@test.ac.il", "ב", "lecturer")


def test_invalid_role_and_email(db):
    users = UserService(db)
    with pytest.raises(ValidationError):
        users.create("a@test.ac.il", "א", "superuser")
    with pytest.raises(ValidationError):
        users.create("not-an-email", "א", "student")


def test_import_csv_sample_file(db):
    data = (DATA / "students.csv").read_bytes()
    result = StudentImporter(UserService(db)).import_file("students.csv", data)
    assert result.created == 104
    assert all(u.role == "student" for u in result.users)
    # ייבוא חוזר לא יוצר כפילויות
    again = StudentImporter(UserService(db)).import_file("students.csv", data)
    assert again.created == 0 and again.existing == 104


def test_import_moodle_xlsx(db):
    data = (DATA / "courseid_130158_participants (1).xlsx").read_bytes()
    result = StudentImporter(UserService(db)).import_file("participants.xlsx", data)
    assert result.created == 104
    first = UserService(db).find_by_email("guygg197@gmail.com")
    assert first.name == "גיא אביב"


def test_import_skips_rows_without_email(db):
    csv = "name,email\nא,a@test.ac.il\nב,\nג,bad\n".encode("utf-8")
    result = StudentImporter(UserService(db)).import_file("x.csv", csv)
    assert result.created == 1
    assert len(result.skipped) == 2


def test_import_rejects_other_formats(db):
    with pytest.raises(ValidationError):
        StudentImporter(UserService(db)).import_file("x.pdf", b"")


def test_last_admin_cannot_be_demoted_or_deleted(db):
    users = UserService(db)
    admin = users.create("boss@test.ac.il", "מנהל", "admin")
    with pytest.raises(ValidationError):
        users.update(admin.id, "מנהל", "student")
    with pytest.raises(ValidationError):
        users.delete(admin.id)
    # כשיש מנהל נוסף, מותר
    users.create("boss2@test.ac.il", "מנהל 2", "admin")
    assert users.update(admin.id, "מנהל", "lecturer").role == "lecturer"


def test_ensure_admin_restores_role(db):
    users = UserService(db)
    users.create("boss@test.ac.il", "מנהל", "admin")
    users.create("other@test.ac.il", "מנהל 2", "admin")
    users.update(users.find_by_email("boss@test.ac.il").id, "מנהל", "student")
    assert users.ensure_admin("boss@test.ac.il").role == "admin"


def test_legacy_db_file_is_moved_to_the_new_name(tmp_path):
    from moodleplus.db import LEGACY_DB_NAME, move_legacy_db

    old = tmp_path / LEGACY_DB_NAME
    old.write_bytes(b"data")
    (tmp_path / (LEGACY_DB_NAME + "-wal")).write_bytes(b"wal")
    new = tmp_path / "moodleplus.db"
    assert move_legacy_db(str(new))
    assert new.read_bytes() == b"data" and (tmp_path / "moodleplus.db-wal").read_bytes() == b"wal"
    assert not old.exists()
    assert not move_legacy_db(str(new))  # אין מה להעביר בפעם השנייה


def test_role_change_applies_to_existing_courses(db):
    from moodleplus.services.courses import CourseService, EnrollmentService
    from moodleplus.db import init_schema

    users = UserService(db)
    enrollments = EnrollmentService(db)
    course = CourseService(db).create("קורס", "1", "")
    u = users.create("t@test.ac.il", "מתרגל", "student")
    enrollments.enroll(course.id, u)
    assert enrollments.role_in(course.id, u) == "student"

    u = users.update(u.id, u.name, "lecturer")
    assert enrollments.role_in(course.id, u) == "lecturer"
    assert enrollments.can_manage(course.id, u)

    # DB ישן שבו התפקיד בקורס נשאר מאחור מתיישר בהפעלה הבאה
    db.execute("UPDATE enrollments SET role = 'student' WHERE user_id = ?", (u.id,))
    init_schema(db)
    assert enrollments.role_in(course.id, u) == "lecturer"
