import os
import tempfile
import pytest
from app import create_app
from database.db import init_db

@pytest.fixture
def temp_csv(tmp_path):
    csv_file = tmp_path / "test_students.csv"
    csv_file.write_text(
        "name,email\n"
        "ישראל ישראלי,israel@campus.edu\n"
        "שרה כהן,sarah@campus.edu\n"
        "דוד לוי,david@campus.edu\n",
        encoding="utf-8"
    )
    return str(csv_file)

@pytest.fixture
def app(temp_csv, tmp_path):
    db_file = tmp_path / "test_attendance.db"
    test_config = {
        "TESTING": True,
        "SECRET_KEY": "test-secret-key",
        "HMAC_SECRET": "test-hmac-secret",
        "LECTURER_PASSWORD": "testpassword",
        "DATABASE_PATH": str(db_file),
        "CLASS_CSV_PATH": temp_csv,
        "CAMPUS_IP_RANGES": ["127.0.0.1/32", "192.168.1.0/24", "10.0.0.0/8"],
        "CAMPUS_IP_FILE": str(tmp_path / "empty_ips.txt"),
        "QR_WINDOW_SECONDS": 6,
        "COOKIE_MAX_AGE_SECONDS": 300,
        "MOCK_AUTH": True
    }
    app = create_app(test_config)
    with app.app_context():
        init_db(str(db_file))
    return app

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def authenticated_lecturer_client(client):
    with client.session_transaction() as sess:
        sess["lecturer_authenticated"] = True
    return client
