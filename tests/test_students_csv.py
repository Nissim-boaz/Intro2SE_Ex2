import pytest
from modules.students.service import StudentsService
from modules.sessions.service import SessionsService

def test_students_csv_validation(temp_csv):
    valid, err, students = StudentsService.validate_csv(temp_csv)
    assert valid is True
    assert len(students) == 3
    assert students[0]["email"] == "israel@campus.edu"

def test_cannot_start_session_with_missing_csv(app, tmp_path):
    with app.app_context():
        app.config["CLASS_CSV_PATH"] = str(tmp_path / "non_existing.csv")
        with pytest.raises(ValueError, match="לא ניתן לפתוח סשן"):
            SessionsService.create_session("שיעור בדיקה")

def test_cannot_start_session_with_corrupt_csv(app, tmp_path):
    corrupt_file = tmp_path / "bad.csv"
    corrupt_file.write_text("invalid_column1,invalid_column2\nval1,val2\n", encoding="utf-8")
    with app.app_context():
        app.config["CLASS_CSV_PATH"] = str(corrupt_file)
        with pytest.raises(ValueError, match="חייב להכיל עמודות"):
            SessionsService.create_session("שיעור בדיקה")

def test_absent_students_calculation(temp_csv):
    attended = {"israel@campus.edu"}
    absent = StudentsService.get_absent_students(temp_csv, attended)
    absent_emails = [s["email"] for s in absent]
    assert "sarah@campus.edu" in absent_emails
    assert "david@campus.edu" in absent_emails
    assert "israel@campus.edu" not in absent_emails
