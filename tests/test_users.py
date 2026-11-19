from pathlib import Path

import pytest

from modelplus.errors import ValidationError
from modelplus.services.users import StudentImporter, UserService

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
