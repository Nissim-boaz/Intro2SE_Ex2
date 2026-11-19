"""אימות ID Token של Google בצד השרת."""
from ..errors import Forbidden


class GoogleTokenVerifier:
    def __init__(self, client_id: str):
        self.client_id = client_id

    def verify(self, credential: str) -> dict:
        """מחזיר {email, name} אם הטוקן תקף. אחרת זורק Forbidden."""
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        if not self.client_id:
            raise Forbidden("התחברות עם Google לא הוגדרה בשרת")
        try:
            info = id_token.verify_oauth2_token(credential, google_requests.Request(), self.client_id)
        except ValueError:
            raise Forbidden("ההתחברות עם Google נכשלה. נסה שוב")
        if not info.get("email_verified"):
            raise Forbidden("כתובת המייל בחשבון Google לא מאומתת")
        return {"email": info["email"].lower(), "name": info.get("name", "")}
