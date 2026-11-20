"""טוקנים מתחלפים לדגימת נוכחות: QR וקוד קולי.

שני הטוקנים נגזרים ב-HMAC מסוד השרת, ממזהה הדגימה ומחלון הזמן.
לא שומרים אותם ב-DB: השרת פשוט מחשב מחדש ומשווה.
"""
import base64
import hashlib
import hmac
import time


class TokenClock:
    """מחלק את הזמן לחלונות קבועים. אפשר להזריק now בבדיקות."""

    def __init__(self, window_seconds: int = 6):
        self.window_seconds = window_seconds

    def now(self) -> float:
        return time.time()

    def window(self, at: float | None = None) -> int:
        return int((self.now() if at is None else at) // self.window_seconds)

    def seconds_left(self, at: float | None = None) -> float:
        at = self.now() if at is None else at
        return self.window_seconds - (at % self.window_seconds)


class _HmacTokens:
    purpose = ""

    def __init__(self, secret: str, clock: TokenClock):
        self.secret = secret.encode()
        self.clock = clock

    def _digest(self, sample_id: int, window: int) -> bytes:
        msg = f"{self.purpose}:{sample_id}:{window}".encode()
        return hmac.new(self.secret, msg, hashlib.sha256).digest()


class QrTokenService(_HmacTokens):
    """טוקן של 10 תווים שמתחלף בכל חלון. מתקבל רק בחלון הנוכחי ובזה שלפניו."""

    purpose = "qr"
    ACCEPTED_WINDOWS = 2  # הנוכחי + הקודם: זמן לפתיחת המצלמה והדף

    def token(self, sample_id: int, window: int | None = None) -> str:
        window = self.clock.window() if window is None else window
        return base64.b32encode(self._digest(sample_id, window)).decode()[:10].lower()

    def verify(self, sample_id: int, token: str, at: float | None = None) -> bool:
        current = self.clock.window(at)
        token = (token or "").strip().lower()
        return any(
            hmac.compare_digest(token, self.token(sample_id, current - back))
            for back in range(self.ACCEPTED_WINDOWS)
        )


class AudioTokenService(_HmacTokens):
    """קוד של 12 ביט שמושמע כ-4 סמלים (3 ביט כל אחד) ועוד סמל בדיקה.

    הקוד מתחלף יחד עם ה-QR. בגלל שהפענוח בטלפון לוקח כמה שניות,
    מקבלים את החלון הנוכחי ושני החלונות שלפניו.
    """

    purpose = "audio"
    BITS = 12
    SYMBOLS = 4
    ALPHABET = 8
    ACCEPTED_WINDOWS = 3

    def code(self, sample_id: int, window: int | None = None) -> int:
        window = self.clock.window() if window is None else window
        return int.from_bytes(self._digest(sample_id, window)[:2], "big") % (1 << self.BITS)

    @classmethod
    def symbols(cls, code: int) -> list[int]:
        """4 סמלי נתונים ואחריהם סמל בדיקה (סכום מודולו 8)."""
        data = [(code >> (3 * (cls.SYMBOLS - 1 - i))) & 7 for i in range(cls.SYMBOLS)]
        return data + [sum(data) % cls.ALPHABET]

    @classmethod
    def decode(cls, symbols: list[int]) -> int | None:
        """הפעולה ההפוכה. מחזיר None אם סמל הבדיקה לא מתאים."""
        if len(symbols) != cls.SYMBOLS + 1 or any(not 0 <= s < cls.ALPHABET for s in symbols):
            return None
        *data, check = symbols
        if sum(data) % cls.ALPHABET != check:
            return None
        code = 0
        for s in data:
            code = (code << 3) | s
        return code

    def verify(self, sample_id: int, code, at: float | None = None) -> bool:
        try:
            code = int(code)
        except (TypeError, ValueError):
            return False
        current = self.clock.window(at)
        return any(code == self.code(sample_id, current - back) for back in range(self.ACCEPTED_WINDOWS))
