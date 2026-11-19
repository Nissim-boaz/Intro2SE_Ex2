"""הגדרות האפליקציה. הכול נקרא ממשתני סביבה (או מקובץ .env)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    DATABASE = os.environ.get("DATABASE", str(ROOT / "instance" / "modelplus.db"))
    UPLOAD_DIR = os.environ.get("UPLOAD_DIR", str(ROOT / "instance" / "uploads"))
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024 * 1024  # 2GB, הקלטות ארוכות
    SESSION_COOKIE_SAMESITE = "Lax"  # חוסם POST מאתרים אחרים (הגנת CSRF בסיסית)
    SESSION_COOKIE_HTTPONLY = True

    MOCK_AUTH = _flag("MOCK_AUTH", "1")
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")

    CAMPUS_CIDRS_FILE = os.environ.get("CAMPUS_CIDRS_FILE", str(ROOT / "data" / "campus_ips.txt"))
    TRUST_PROXY = _flag("TRUST_PROXY", "1")  # מאחורי cloudflared

    TOKEN_WINDOW_SECONDS = 6
    MAX_SAMPLES_PER_LESSON = 5
    DEFAULT_SAMPLE_SECONDS = 120
    CHECKIN_GRACE_SECONDS = 15

    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
    START_JOB_RUNNER = True


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    MOCK_AUTH = True
    START_JOB_RUNNER = False
