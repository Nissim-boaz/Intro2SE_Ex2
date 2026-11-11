import concurrent.futures
import time
from database.db import get_db
from modules.sessions.service import SessionsService
from modules.attendance.service import AttendanceService

def test_60_concurrent_students(app, tmp_path):
    # 1. Create CSV with 60 students
    csv_lines = ["name,email\n"]
    for i in range(1, 61):
        csv_lines.append(f"סטודנט {i},student{i}@campus.edu\n")
    big_csv = tmp_path / "students_60.csv"
    big_csv.write_text("".join(csv_lines), encoding="utf-8")

    app.config["CLASS_CSV_PATH"] = str(big_csv)

    # 2. Start session and issue signed cookie inside app context
    with app.app_context():
        session_obj = SessionsService.create_session("בדיקת עומס 60 סטודנטים")
        session_id = session_obj["id"]
        signed_cookie = AttendanceService.create_signed_session_token(session_id)

    # 3. Define client worker function
    def send_attendance(student_idx):
        client = app.test_client()
        client.set_cookie("attend_session_token", signed_cookie)
        t_start = time.time()
        res = client.post("/attend/submit", json={
            "google_token": f"mock:student{student_idx}@campus.edu:סטודנט {student_idx}"
        }, environ_base={"REMOTE_ADDR": "127.0.0.1"})
        elapsed = time.time() - t_start
        return {
            "status_code": res.status_code,
            "data": res.get_json(),
            "elapsed": elapsed
        }

    # 4. Execute 60 concurrent requests
    total_start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=60) as executor:
        futures = [executor.submit(send_attendance, i) for i in range(1, 61)]
        results = [f.result() for f in futures]
    total_time = time.time() - total_start

    # 5. Verify assertions: all 60 succeeded
    assert len(results) == 60
    for r in results:
        assert r["status_code"] == 200, f"Failed request: {r}"
        assert r["data"]["success"] is True
        # Response time under 1 second
        assert r["elapsed"] < 1.0, f"Request took {r['elapsed']} seconds (exceeded 1.0s limit)"

    # Verify 60 records in DB
    with app.app_context():
        db = get_db()
        count = db.execute("SELECT COUNT(*) FROM attendance WHERE session_id = ?", (session_id,)).fetchone()[0]
        assert count == 60
