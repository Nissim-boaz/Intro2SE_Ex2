"""שכבת LLM להחלפה קלה בין ספקים, וסיכום שיעור מתוך תמלול."""
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from .transcription import Segment


class LLMError(RuntimeError):
    pass


class LLMProvider(ABC):
    @abstractmethod
    def generate_json(self, prompt: str) -> dict:
        """שולח prompt ומחזיר JSON מפוענח."""


class GeminiProvider(LLMProvider):
    """Google Gemini דרך google-genai. ה-key נקרא מ-.env (GEMINI_API_KEY).

    ב-free tier המודלים לפעמים עמוסים (503) או לא עונים בזמן (504).
    לכן כל מודל מקבל כמה ניסיונות, ואם הוא לא עונה עוברים למודל הבא ברשימה.
    """

    RETRYABLE = (429, 500, 503, 504)

    def __init__(self, api_key: str, model: str, fallbacks: list[str] | None = None,
                 attempts: int = 2, timeout_seconds: int = 180, backoff_seconds: float = 4):
        if not api_key:
            raise LLMError("לא הוגדר GEMINI_API_KEY בקובץ .env, ולכן אין סיכום")
        self.api_key = api_key
        self.models = [model] + [m for m in (fallbacks or []) if m and m != model]
        self.attempts = attempts
        self.timeout_seconds = timeout_seconds
        self.backoff_seconds = backoff_seconds

    def generate_json(self, prompt: str) -> dict:
        import time

        last_error = None
        for model in self.models:
            for attempt in range(self.attempts):
                try:
                    return parse_json(self._call(model, prompt))
                except Exception as err:
                    last_error = err
                    if not self._retryable(err):
                        break  # למשל מודל שלא קיים: אין טעם לנסות שוב, עוברים לבא
                    if attempt + 1 < self.attempts:
                        time.sleep(self.backoff_seconds * (attempt + 1))
        raise LLMError(f"Gemini לא הצליח לסכם כרגע. נסה שוב בעוד כמה דקות ({last_error})")

    def _call(self, model: str, prompt: str) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key,
                              http_options=types.HttpOptions(timeout=self.timeout_seconds * 1000))
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.3),
        )
        return resp.text or ""

    @classmethod
    def _retryable(cls, err: Exception) -> bool:
        if isinstance(err, LLMError):  # JSON לא תקין: אולי בניסיון הבא יצליח
            return True
        code = getattr(err, "code", None)
        return code in cls.RETRYABLE or "timeout" in type(err).__name__.lower() or "timed out" in str(err).lower()


def parse_json(text: str) -> dict:
    """מפענח JSON גם אם המודל עטף אותו ב-```json."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise LLMError("התשובה מהמודל לא הייתה JSON תקין")


@dataclass
class LessonSummary:
    summary: str
    key_points: list[str] = field(default_factory=list)
    chapters: list[dict] = field(default_factory=list)  # [{"start": שניות, "title": str}]


def fmt_time(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class LessonSummarizer:
    PROMPT = """אתה עוזר הוראה בקורס אוניברסיטאי. לפניך תמלול של שיעור, שורה לכל קטע, עם זמן התחלה בשניות.
התמלול נעשה אוטומטית ועלול להכיל שגיאות. מונחים טכניים באנגלית השאר באנגלית.

החזר JSON בלבד, במבנה הזה:
{{
  "summary": "סיכום של 3 עד 5 משפטים בעברית",
  "key_points": ["נקודת מפתח", "..."],
  "chapters": [{{"start": 0, "title": "כותרת קצרה"}}, "..."]
}}

כללים:
- 4 עד 8 נקודות מפתח, כל אחת משפט אחד.
- ראשי פרקים לפי שינוי נושא, בערך פרק לכל 5 עד 15 דקות. הפרק הראשון מתחיל ב-0.
- start הוא מספר שניות שלקוח מהתמלול, בסדר עולה.
- כתוב בעברית טבעית וקצרה.

התמלול:
{transcript}
"""

    def __init__(self, provider: LLMProvider, max_chars: int = 400_000):
        self.provider = provider
        self.max_chars = max_chars

    @staticmethod
    def format_transcript(segments: list[Segment]) -> str:
        return "\n".join(f"[{int(s.start)}] {s.text}" for s in segments)

    def summarize(self, segments: list[Segment]) -> LessonSummary:
        if not segments:
            return LessonSummary("לא זוהה דיבור בהקלטה.")
        transcript = self.format_transcript(segments)[: self.max_chars]
        data = self.provider.generate_json(self.PROMPT.format(transcript=transcript))
        duration = segments[-1].end
        return LessonSummary(
            summary=str(data.get("summary", "")).strip(),
            key_points=[str(p).strip() for p in data.get("key_points", []) if str(p).strip()],
            chapters=self._clean_chapters(data.get("chapters", []), duration),
        )

    @staticmethod
    def _clean_chapters(raw, duration: float) -> list[dict]:
        chapters = []
        for ch in raw if isinstance(raw, list) else []:
            if not isinstance(ch, dict):
                continue
            try:
                start = float(ch.get("start", 0))
            except (TypeError, ValueError):
                continue
            title = str(ch.get("title", "")).strip()
            if title and 0 <= start <= duration:
                chapters.append({"start": int(start), "title": title})
        chapters.sort(key=lambda c: c["start"])
        unique = []
        for ch in chapters:
            if not unique or ch["start"] != unique[-1]["start"]:
                unique.append(ch)
        return unique
