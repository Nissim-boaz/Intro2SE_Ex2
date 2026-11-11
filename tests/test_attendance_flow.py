import time
from modules.sessions.service import SessionsService
from database.db import get_db

def test_full_attendance_flow(app, authenticated_lecturer_client):
    # 1. Lecturer starts session (F1)
    res = authenticated_lecturer_client.post("/sessions/start", json={"title": "שיעור תוכנה", "duration": 90})
    assert res.status_code == 200
    session_data = res.get_json()["session"]
    session_id = session_data["id"]

    # F1: Cannot start another session while active
    res_second = authenticated_lecturer_client.post("/sessions/start", json={"title": "סשן כפול"})
    assert res_second.status_code == 400

    # 2. Get QR token for active session
    res_token = authenticated_lecturer_client.get("/sessions/active/token")
    assert res_token.status_code == 200
    token = res_token.get_json()["token"]

    # 3. Student scans QR -> /attend?t=<token> (F4: issued signed cookie for 5 minutes)
    student_client = app.test_client()
    res_attend = student_client.get(f"/attend?t={token}")
    assert res_attend.status_code == 200
    assert "attend_session_token" in res_attend.headers.get("Set-Cookie", "")

    # 4. Student connects with Google (F5 & F8)
    res_submit = student_client.post("/attend/submit", json={
        "google_token": "mock:israel@campus.edu:ישראל ישראלי"
    }, environ_base={"REMOTE_ADDR": "127.0.0.1"}) # On campus IP

    assert res_submit.status_code == 200
    submit_data = res_submit.get_json()
    assert submit_data["success"] is True
    assert submit_data["status"] == "present"
    assert submit_data["attendance"]["student_name"] == "ישראל ישראלי"

    # 5. F7: Duplicate attempt does not create another record
    res_dup = student_client.post("/attend/submit", json={
        "google_token": "mock:israel@campus.edu:ישראל ישראלי"
    })
    assert res_dup.status_code == 200
    dup_data = res_dup.get_json()
    assert dup_data["already_registered"] is True

    # Check DB count for this email is still 1
    with app.app_context():
        db = get_db()
        count = db.execute("SELECT COUNT(*) FROM attendance WHERE session_id = ? AND email = ?", (session_id, "israel@campus.edu")).fetchone()[0]
        assert count == 1

    # 6. F9: Student from outside campus IP is marked suspicious
    res_suspicious = student_client.post("/attend/submit", json={
        "google_token": "mock:sarah@campus.edu:שרה כהן"
    }, environ_base={"REMOTE_ADDR": "8.8.8.8"}) # External IP

    assert res_suspicious.status_code == 200
    susp_data = res_suspicious.get_json()
    assert susp_data["success"] is True
    assert susp_data["status"] == "suspicious"
    sarah_attendance_id = susp_data["attendance"]["id"]

    # 7. F11: Student with email NOT in CSV is rejected and logged
    res_unknown = student_client.post("/attend/submit", json={
        "google_token": "mock:intruder@other.edu:פורץ"
    })
    assert res_unknown.status_code == 400
    unk_data = res_unknown.get_json()
    assert unk_data["error_code"] == "EMAIL_NOT_IN_LIST"

    # Verify rejected attempt logged for lecturer
    with app.app_context():
        db = get_db()
        rej = db.execute("SELECT * FROM rejected_attempts WHERE session_id = ?", (session_id,)).fetchone()
        assert rej is not None
        assert rej["email"] == "intruder@other.edu"

    # 8. Check Dashboard stats API
    res_stats = authenticated_lecturer_client.get("/api/dashboard/stats")
    stats = res_stats.get_json()
    assert stats["total_attendees"] == 2
    assert stats["present_count"] == 1
    assert stats["suspicious_count"] == 1
    assert len(stats["rejected_attempts"]) == 1

    # 9. F10: Lecturer approves suspicious attendance manually
    res_approve = authenticated_lecturer_client.post(f"/api/attendance/{sarah_attendance_id}/approve")
    assert res_approve.status_code == 200
    appr_data = res_approve.get_json()
    assert appr_data["success"] is True
    assert appr_data["attendance"]["status"] == "present"
    assert appr_data["attendance"]["approved_at"] is not None

    # 10. Close session
    res_close = authenticated_lecturer_client.post(f"/sessions/{session_id}/close")
    assert res_close.status_code == 200

    # 11. Export CSV
    res_csv = authenticated_lecturer_client.get(f"/dashboard/export/{session_id}")
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers["Content-Type"]
    csv_text = res_csv.data.decode("utf-8")
    assert "israel@campus.edu" in csv_text
    assert "sarah@campus.edu" in csv_text
    assert "david@campus.edu" in csv_text  # absent student included
    assert "לא הגיע" in csv_text


def test_expired_qr_token_rejected_at_attend_endpoint(app, authenticated_lecturer_client):
    # Start session
    res = authenticated_lecturer_client.post("/sessions/start", json={"title": "שיעור בדיקת טוקן פג תוקף"})
    assert res.status_code == 200

    student_client = app.test_client()
    # Bad token
    res_attend = student_client.get("/attend?t=invalid_fake_token_123")
    assert res_attend.status_code == 400
    assert "קוד ה-QR התחלף או שאינו תקף" in res_attend.data.decode("utf-8")

def test_expired_cookie_rejected_at_submit(app, authenticated_lecturer_client):
    from unittest.mock import patch
    # Start session
    res = authenticated_lecturer_client.post("/sessions/start", json={"title": "שיעור בדיקת עוגייה"})
    session_id = res.get_json()["session"]["id"]

    student_client = app.test_client()
    from modules.attendance.service import AttendanceService
    with app.app_context():
        # Issue token at t = 1000.0
        with patch("time.time", return_value=1000.0):
            token = AttendanceService.create_signed_session_token(session_id)

    student_client.set_cookie("attend_session_token", token)

    # Now verify at t = 1350.0 (350 seconds later, > 300 seconds max_age)
    with patch("time.time", return_value=1350.0):
        res_submit = student_client.post("/attend/submit", json={
            "google_token": "mock:israel@campus.edu:ישראל ישראלי"
        })
        assert res_submit.status_code == 400
        data = res_submit.get_json()
        assert data["error_code"] == "COOKIE_EXPIRED"

def test_lecturer_login_authentication(client):
    # Wrong password
    res_bad = client.post("/lecturer/login", data={"password": "wrongpassword"})
    assert res_bad.status_code == 200
    assert "סיסמת מרצה שגויה" in res_bad.data.decode("utf-8")

    # Correct password
    res_ok = client.post("/lecturer/login", data={"password": "testpassword"}, follow_redirects=False)
    assert res_ok.status_code == 302
    assert "/lecturer" in res_ok.headers["Location"]
