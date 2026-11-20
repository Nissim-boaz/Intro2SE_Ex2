"""תמלול הקלטות. Transcriber הוא ממשק, ו-WhisperTranscriber הוא המימוש המקומי והחינמי."""
import subprocess
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


# מונחים שנאמרים באנגלית בשיעורי תוכנה. Whisper מקבל אותם כרמז, כדי שיכתוב אותם נכון ולא בתעתיק עברי שבור
DEFAULT_TERMS = (
    "UML, class diagram, sequence diagram, use case, object, class, interface, inheritance, "
    "composition, aggregation, association, polymorphism, encapsulation, abstraction, design patterns, "
    "Singleton, Factory, Observer, Strategy, MVC, API, database, SQL, Python, Java, Flask, pytest, Git, GitHub"
)


def transcription_hint(course_name: str = "", terms: str = DEFAULT_TERMS) -> str:
    """משפט פתיחה ש-Whisper ממשיך ממנו. כך הוא מזהה שהשיעור בעברית עם מונחים באנגלית."""
    course = f"שיעור בקורס {course_name}. " if course_name else ""
    return f"{course}השיעור בעברית, ומונחים מקצועיים נאמרים באנגלית: {terms}."


class Transcriber(ABC):
    @abstractmethod
    def transcribe(self, media_path: str, hint: str | None = None) -> list[Segment]:
        """hint: טקסט קצר עם הקשר ומונחים, שעוזר לזהות נכון מילים באנגלית."""


class AudioExtractor:
    """מחלץ אודיו מונו 16kHz עם ffmpeg. Whisper עובד מהר יותר ככה, במיוחד על קבצי וידאו."""

    def __init__(self, ffmpeg: str = "ffmpeg"):
        self.ffmpeg = ffmpeg

    def extract(self, media_path: str, out_dir: str) -> str:
        out = str(Path(out_dir) / "audio.wav")
        cmd = [self.ffmpeg, "-y", "-loglevel", "error", "-i", media_path, "-vn", "-ac", "1", "-ar", "16000", out]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except FileNotFoundError:
            raise RuntimeError("ffmpeg לא מותקן במחשב")
        except subprocess.CalledProcessError as err:
            raise RuntimeError("ffmpeg לא הצליח לקרוא את הקובץ: " + err.stderr.decode(errors="replace")[-300:])
        return out


class WhisperTranscriber(Transcriber):
    def __init__(self, model_size: str = "small", language: str = "he", extractor: AudioExtractor | None = None):
        self.model_size = model_size
        self.language = language
        self.extractor = extractor or AudioExtractor()
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            # int8 על CPU: מהיר מספיק במחשב נייד ולא דורש GPU
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        return self._model

    def transcribe(self, media_path: str, hint: str | None = None) -> list[Segment]:
        with tempfile.TemporaryDirectory() as tmp:
            audio = self._read_wav(self.extractor.extract(media_path, tmp))
        segments, _info = self._load().transcribe(
            audio, language=self.language, vad_filter=True, beam_size=5,
            initial_prompt=hint or transcription_hint(),
        )
        return [Segment(round(s.start, 1), round(s.end, 1), s.text.strip()) for s in segments if s.text.strip()]

    @staticmethod
    def _read_wav(path: str):
        """קורא את ה-wav שיצא מ-ffmpeg למערך numpy.

        מעבירים ל-faster-whisper מערך ולא נתיב, כדי לא להיות תלויים בספריית av
        (הגרסה החדשה שלה לא תואמת ל-faster-whisper).
        """
        import wave

        import numpy as np

        with wave.open(path, "rb") as w:
            frames = w.readframes(w.getnframes())
        return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
