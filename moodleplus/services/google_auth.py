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
        from google.auth import exceptions

        # verify_oauth2_token בודק את החתימה מול המפתחות של Google, ש-aud הוא ה-Client ID שלנו,
        # שהטוקן לא פג ושהוא הונפק על ידי accounts.google.com
        try:
            info = id_token.verify_oauth2_token(credential, google_requests.Request(), self.client_id)
        except exceptions.TransportError:
            raise Forbidden("לא הצלחנו לבדוק את ההתחברות מול Google. נסה שוב בעוד רגע")
        except (ValueError, exceptions.GoogleAuthError):
            raise Forbidden("ההתחברות עם Google נכשלה. נסה שוב")
        if not info.get("email_verified"):
            raise Forbidden("כתובת המייל בחשבון Google לא מאומתת")
        return {"email": info["email"].lower(), "name": info.get("name", "")}
