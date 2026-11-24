"""הגדרות האפליקציה. הכול נקרא ממשתני סביבה (או מקובץ .env)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    DATABASE = os.environ.get("DATABASE", str(ROOT / "instance" / "moodleplus.db"))
    UPLOAD_DIR = os.environ.get("UPLOAD_DIR", str(ROOT / "instance" / "uploads"))
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024 * 1024  # 2GB, הקלטות ארוכות
    SESSION_COOKIE_SAMESITE = "Lax"  # חוסם POST מאתרים אחרים (הגנת CSRF בסיסית)
    SESSION_COOKIE_HTTPONLY = True

    MOCK_AUTH = _flag("MOCK_AUTH", "1")
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
    # הכתובת הקבועה שדרכה נכנסים מבחוץ (Tailscale Funnel). מודפסת כשהשרת עולה
    PUBLIC_URL = os.environ.get("PUBLIC_URL", "").strip().rstrip("/")

    # מאחורי Tailscale Funnel: הבקשה מגיעה ב-HTTPS ל-Funnel, והוא מעביר אותה לשרת ב-HTTP עם
    # X-Forwarded-Proto. ProxyFix קורא את הכותרת, כך ש-Flask יודע שהגלישה מאובטחת
    TRUST_PROXY = _flag("TRUST_PROXY", "1")

    # הקוד הקולי מתחלף כל 4 שניות ומתקבל עד סוף החלון שאחריו (8 שניות לכל היותר)
    TOKEN_WINDOW_SECONDS = 4
    MAX_SAMPLES_PER_LESSON = 5
    DEFAULT_SAMPLE_SECONDS = 120

    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    # הפסקה בין הגשות בבדיקה עם AI, כי ה-free tier מגביל כמה בקשות בדקה
    AI_GRADING_DELAY = float(os.environ.get("AI_GRADING_DELAY", "4"))
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    # מודלים לגיבוי כשהראשי עמוס, מופרדים בפסיק
    GEMINI_FALLBACK_MODELS = [
        m.strip() for m in os.environ.get("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash-lite").split(",") if m.strip()
    ]
    WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
    START_JOB_RUNNER = True


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    MOCK_AUTH = True
    START_JOB_RUNNER = False
