from functools import wraps
from flask import session, redirect, url_for, request, jsonify, current_app
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from config import Config

def _get_cfg(key, default=None):
    try:
        if current_app:
            return current_app.config.get(key, getattr(Config, key, default))
    except RuntimeError:
        pass
    return getattr(Config, key, default)

class AuthService:
    @staticmethod
    def verify_lecturer_password(password: str) -> bool:
        expected = _get_cfg("LECTURER_PASSWORD", Config.LECTURER_PASSWORD)
        return password == expected

    @staticmethod
    def verify_google_id_token(token_str: str) -> dict:
        """
        Verifies Google ID token locally using google-auth library.
        Returns dict with 'email' and 'name' on success.
        Raises ValueError on invalid token.
        """
        if not token_str:
            raise ValueError("טוקן אימות חסר")

        mock_auth = _get_cfg("MOCK_AUTH", Config.MOCK_AUTH)
        client_id = _get_cfg("GOOGLE_CLIENT_ID", Config.GOOGLE_CLIENT_ID)

        # In mock mode, allow simulated token format: mock:<email>:<name>
        if mock_auth and token_str.startswith("mock:"):
            parts = token_str.split(":", 2)
            email = parts[1] if len(parts) > 1 else "student@campus.edu"
            name = parts[2] if len(parts) > 2 else "סטודנט לדוגמה"
            return {"email": email.strip().lower(), "name": name.strip()}

        if not client_id:
            raise ValueError("מזהה לקוח Google (Client ID) לא הוגדר בשרת. יש להפעיל MOCK_AUTH=1 לבדיקות מקומיות.")

        try:
            req = google_requests.Request()
            id_info = id_token.verify_oauth2_token(token_str, req, client_id)

            # Check email verified
            if not id_info.get("email_verified", False):
                raise ValueError("כתובת האימייל ב-Google אינה מאומתת")

            email = id_info.get("email", "").strip().lower()
            name = id_info.get("name", "")
            return {"email": email, "name": name, "sub": id_info.get("sub")}
        except Exception as e:
            raise ValueError(f"שגיאה באימות Google ID Token: {str(e)}")

def lecturer_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("lecturer_authenticated"):
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"error": "נדרשת התחברות מרצה"}), 401
            return redirect(url_for("auth.lecturer_login", next=request.url))
        return f(*args, **kwargs)
    return decorated_function
