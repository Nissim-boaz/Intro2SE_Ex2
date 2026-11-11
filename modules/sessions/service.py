import hmac
import hashlib
import time
import uuid
from datetime import datetime, timezone, timedelta
import io
import qrcode
from flask import current_app
from config import Config
from database.db import get_db
from modules.students.service import StudentsService

def _get_cfg(key, default=None):
    try:
        if current_app:
            return current_app.config.get(key, getattr(Config, key, default))
    except RuntimeError:
        pass
    return getattr(Config, key, default)

class SessionsService:
    @staticmethod
    def get_window(ts: float | None = None) -> int:
        if ts is None:
            ts = time.time()
        window_sec = _get_cfg("QR_WINDOW_SECONDS", 6)
        return int(ts // window_sec)

    @classmethod
    def generate_qr_token(cls, session_id: str, ts: float | None = None) -> str:
        """Generates HMAC token for the session and specific 6-second window."""
        window = cls.get_window(ts)
        secret = _get_cfg("HMAC_SECRET", Config.HMAC_SECRET)
        message = f"{session_id}:{window}".encode("utf-8")
        signature = hmac.new(
            secret.encode("utf-8"),
            message,
            hashlib.sha256
        ).hexdigest()
        return signature[:32]

    @classmethod
    def verify_qr_token(cls, session_id: str, token: str, ts: float | None = None) -> bool:
        """
        Validates that the token exactly matches the current 6-second window.
        Tokens from previous or future windows are strictly rejected (F3).
        """
        if not token or not session_id:
            return False
        expected_token = cls.generate_qr_token(session_id, ts)
        return hmac.compare_digest(token, expected_token)

    @classmethod
    def get_active_session(cls):
        """Returns the currently active session or None."""
        db = get_db()
        row = db.execute(
            "SELECT * FROM sessions WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    @classmethod
    def get_session_by_id(cls, session_id: str):
        db = get_db()
        row = db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    @classmethod
    def get_latest_closed_session(cls):
        db = get_db()
        row = db.execute(
            "SELECT * FROM sessions WHERE status = 'closed' ORDER BY closed_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    @classmethod
    def create_session(cls, title: str = "שיעור נוכחות", duration_minutes: int = 90, session_type: str = "attendance"):
        """
        F1 & F6: Validates student CSV first. Ensures only one active session exists.
        """
        csv_path = _get_cfg("CLASS_CSV_PATH", Config.CLASS_CSV_PATH)
        valid, err_msg, _ = StudentsService.validate_csv(csv_path)
        if not valid:
            raise ValueError(f"לא ניתן לפתוח סשן: {err_msg}")

        # Check if active session already exists (F1)
        active = cls.get_active_session()
        if active:
            raise ValueError(f"קיים כבר סשן פעיל (מזהה: {active['id']}). יש לסגור אותו תחילה.")

        now = datetime.now(timezone.utc)
        start_time_iso = now.isoformat()
        end_time_iso = (now + timedelta(minutes=duration_minutes)).isoformat()
        session_id = uuid.uuid4().hex[:12]

        db = get_db()
        with db:
            db.execute("""
                INSERT INTO sessions (id, title, type, status, start_time, end_time, duration_minutes, created_at)
                VALUES (?, ?, ?, 'active', ?, ?, ?, ?)
            """, (session_id, title, session_type, start_time_iso, end_time_iso, duration_minutes, start_time_iso))

        return cls.get_session_by_id(session_id)

    @classmethod
    def close_session(cls, session_id: str):
        """Closes an active session (F1)."""
        now_iso = datetime.now(timezone.utc).isoformat()
        db = get_db()
        with db:
            db.execute("""
                UPDATE sessions
                SET status = 'closed', closed_at = ?
                WHERE id = ? AND status = 'active'
            """, (now_iso, session_id))
        return cls.get_session_by_id(session_id)

    @classmethod
    def generate_qr_image_bytes(cls, url: str) -> io.BytesIO:
        """Generates PNG image bytes for QR code."""
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf
