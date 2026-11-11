import sqlite3
from datetime import datetime, timezone
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask import Request, current_app
from config import Config
from database.db import get_db
from modules.sessions.service import SessionsService
from modules.students.service import StudentsService
from modules.campus_check.service import CampusCheckService
from modules.auth.service import AuthService

COOKIE_SALT = "attendance_session_salt"

def _get_cfg(key, default=None):
    try:
        if current_app:
            return current_app.config.get(key, getattr(Config, key, default))
    except RuntimeError:
        pass
    return getattr(Config, key, default)

class AttendanceService:
    @staticmethod
    def get_serializer() -> URLSafeTimedSerializer:
        secret = _get_cfg("SECRET_KEY", Config.SECRET_KEY)
        return URLSafeTimedSerializer(secret)

    @classmethod
    def create_signed_session_token(cls, session_id: str) -> str:
        """Issues a signed token for cookie with session_id (F4)."""
        s = cls.get_serializer()
        return s.dumps({"session_id": session_id}, salt=COOKIE_SALT)

    @classmethod
    def verify_signed_session_token(cls, token_str: str) -> str | None:
        """
        Verifies signed cookie. Must be within COOKIE_MAX_AGE_SECONDS (5 minutes).
        Returns session_id or None if invalid/expired.
        """
        if not token_str:
            return None
        s = cls.get_serializer()
        max_age = _get_cfg("COOKIE_MAX_AGE_SECONDS", 300)
        try:
            data = s.loads(token_str, salt=COOKIE_SALT, max_age=max_age)
            return data.get("session_id")
        except (BadSignature, SignatureExpired):
            return None

    @classmethod
    def record_rejected_attempt(cls, session_id: str, email: str, student_name: str | None, ip_address: str, reason: str):
        """F11: Logs rejected attempt for lecturer dashboard."""
        now_iso = datetime.now(timezone.utc).isoformat()
        db = get_db()
        with db:
            db.execute("""
                INSERT INTO rejected_attempts (session_id, email, student_name, timestamp, ip_address, reason)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (session_id, email, student_name or "", now_iso, ip_address, reason))

    @classmethod
    def register_attendance(
        cls,
        session_id: str,
        google_token: str,
        request: Request
    ) -> dict:
        """
        Processes student attendance according to specification.
        """
        # 1. Verify session exists and is active
        session_obj = SessionsService.get_session_by_id(session_id)
        if not session_obj:
            raise ValueError("הסשן המבוקש לא קיים")
        if session_obj["status"] != "active":
            raise ValueError("הסשן כבר נסגר לקבלת נוכחות")

        # 2. Extract client IP and user agent
        client_ip = CampusCheckService.get_client_ip(request)
        user_agent = request.headers.get("User-Agent", "")

        # 3. Verify Google OAuth token (F5)
        try:
            google_user = AuthService.verify_google_id_token(google_token)
        except ValueError as e:
            raise ValueError(f"אימות Google נכשל: {str(e)}")

        email = google_user["email"].strip().lower()
        oauth_name = google_user.get("name", "")

        # 4. Check if student in CSV class list (F11)
        csv_path = _get_cfg("CLASS_CSV_PATH", Config.CLASS_CSV_PATH)
        student = StudentsService.get_student_by_email(csv_path, email)
        if not student:
            cls.record_rejected_attempt(
                session_id=session_id,
                email=email,
                student_name=oauth_name,
                ip_address=client_ip,
                reason="אימייל אינו מופיע ברשימת הכיתה"
            )
            return {
                "success": False,
                "error_code": "EMAIL_NOT_IN_LIST",
                "message": f"האימייל {email} אינו מופיע ברשימת הכיתה. ניסיון זה תועד עבור המרצה."
            }

        student_name = student["name"]

        # 5. Check if already attended in this session (F7)
        db = get_db()
        existing = db.execute(
            "SELECT * FROM attendance WHERE session_id = ? AND email = ?",
            (session_id, email)
        ).fetchone()

        if existing:
            return {
                "success": True,
                "already_registered": True,
                "message": f"כבר נרשמת לסשן זה בהצלחה בשעה {existing['timestamp']}.",
                "attendance": dict(existing)
            }

        # 6. Check campus IP range (F9)
        is_campus = CampusCheckService.is_campus_ip(client_ip)
        status = "present" if is_campus else "suspicious"

        # 7. Record attendance (F8)
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            with db:
                cursor = db.execute("""
                    INSERT INTO attendance (
                        session_id, student_name, email, timestamp, ip_address, user_agent, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (session_id, student_name, email, now_iso, client_ip, user_agent, status))
                rec_id = cursor.lastrowid

            record = db.execute("SELECT * FROM attendance WHERE id = ?", (rec_id,)).fetchone()
            return {
                "success": True,
                "already_registered": False,
                "status": status,
                "is_suspicious": (status == "suspicious"),
                "message": "נוכחותך נקלטה בהצלחה!" if status == "present" else "נוכחותך נקלטה (סומן לבדיקת מרצה עקב חיבור מחוץ לקמפוס).",
                "attendance": dict(record)
            }
        except sqlite3.IntegrityError:
            # Race condition catch: duplicate concurrent insert
            existing = db.execute(
                "SELECT * FROM attendance WHERE session_id = ? AND email = ?",
                (session_id, email)
            ).fetchone()
            return {
                "success": True,
                "already_registered": True,
                "message": f"כבר נרשמת לסשן זה.",
                "attendance": dict(existing) if existing else {}
            }
