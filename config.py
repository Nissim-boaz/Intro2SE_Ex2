import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Load .env file
load_dotenv(BASE_DIR / ".env")

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production-123456789")
    HMAC_SECRET = os.getenv("HMAC_SECRET", "dev-hmac-secret-for-qr-tokens-987654321")
    LECTURER_PASSWORD = os.getenv("LECTURER_PASSWORD", "admin123")

    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
    MOCK_AUTH = os.getenv("MOCK_AUTH", "1").lower() in ("1", "true", "yes")

    CAMPUS_IP_FILE = os.getenv("CAMPUS_IP_FILE", str(BASE_DIR / "data" / "campus_ips.txt"))
    CAMPUS_IP_RANGES = [
        cidr.strip() for cidr in os.getenv("CAMPUS_IP_RANGES", "127.0.0.1/32,10.0.0.0/8,192.168.0.0/16").split(",")
        if cidr.strip()
    ]

    CLASS_CSV_PATH = os.getenv("CLASS_CSV_PATH", str(BASE_DIR / "data" / "students.csv"))
    DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "attendance.db"))

    QR_WINDOW_SECONDS = int(os.getenv("QR_WINDOW_SECONDS", "6"))
    COOKIE_MAX_AGE_SECONDS = int(os.getenv("COOKIE_MAX_AGE_SECONDS", "300"))
    DEFAULT_SESSION_DURATION_MINUTES = int(os.getenv("DEFAULT_SESSION_DURATION_MINUTES", "90"))
    SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", "")
