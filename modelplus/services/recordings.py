"""הקלטות שיעור: העלאה, תמלול וסיכום ברקע."""
from __future__ import annotations

import json
import logging
import queue
import sqlite3
import threading
import time
from dataclasses import dataclass

from ..errors import NotFound, ValidationError
from .content import FileStore
from .llm import LessonSummarizer, LLMError
from .transcription import Segment, Transcriber, transcription_hint

log = logging.getLogger(__name__)

MEDIA_EXTENSIONS = (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".mp3", ".m4a", ".wav", ".ogg", ".aac", ".flac")
STATUS_LABELS = {
    "uploaded": "ממתין לתמלול",
    "transcribing": "בתמלול",
    "summarizing": "מסכם",
    "ready": "מוכן",
    "failed": "נכשל",
}


@dataclass
class Recording:
    id: int
    course_id: int
    title: str
    file_path: str
    mime: str
    status: str
    transcript: list[dict]
    summary: str
    key_points: list[str]
    chapters: list[dict]
    error: str
    created_at: str
    published: bool = False
    feedback_status: str = ""          # '' | pending | ready | failed
    feedback: dict | None = None       # {overall, strengths, items} — רק למרצה הקורס
    feedback_error: str = ""
    feedback_job: int = 0
    feedback_at: float = 0.0
    transcript_edited_at: float = 0.0

    @property
    def can_request_feedback(self) -> bool:
        """משוב אחד להקלטה. משוב חדש מותר רק אם המרצה ערך את התמלול אחרי שהמשוב נכתב."""
        if self.processing or not self.transcript or self.feedback_status == "pending":
            return False
        if self.feedback_status == "ready":
            return self.transcript_edited_at > self.feedback_at
        return True  # עוד לא נוצר, נכשל או בוטל

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]

    @property
    def processing(self) -> bool:
        return self.status in ("uploaded", "transcribing", "summarizing")

    @property
    def editable(self) -> bool:
        """עורכים רק אחרי שהעיבוד נגמר, כדי שהסיכום האוטומטי לא ידרוס את התיקונים של המרצה."""
        return not self.processing

    @property
    def is_video(self) -> bool:
        return self.mime.startswith("video/")

    @classmethod
    def from_row(cls, r) -> "Recording":
        return cls(
            r["id"], r["course_id"], r["title"], r["file_path"], r["mime"], r["status"],
            json.loads(r["transcript_json"]), r["summary"], json.loads(r["key_points_json"]),
            json.loads(r["chapters_json"]), r["error"], r["created_at"], bool(r["published"]),
            r["feedback_status"], json.loads(r["feedback_json"]) if r["feedback_json"] else None, r["feedback_error"],
            r["feedback_job"], r["feedback_at"], r["transcript_edited_at"],
        )


def parse_clock(value: str) -> int:
    """'75', '1:15' או '1:02:30' -> שניות."""
    value = (value or "").strip()
    parts = value.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        raise ValidationError(f"הזמן ״{value}״ לא תקין. כתוב אותו כמו 1:15")
    if not 1 <= len(nums) <= 3 or any(n < 0 for n in nums) or any(n > 59 for n in nums[1:]):
        raise ValidationError(f"הזמן ״{value}״ לא תקין. כתוב אותו כמו 1:15")
    seconds = 0
    for n in nums:
        seconds = seconds * 60 + n
    return seconds


class RecordingService:
    def __init__(self, db: sqlite3.Connection, files: FileStore):
        self.db = db
        self.files = files

    def create(self, course_id: int, title: str, filename: str, mime: str, upload) -> Recording:
        if not filename:
            raise ValidationError("בחר קובץ וידאו או אודיו")
        if not filename.lower().endswith(MEDIA_EXTENSIONS):
            raise ValidationError("אפשר להעלות קובץ וידאו או אודיו (למשל mp4 או mp3)")
        rel = self.files.save_stream(f"recordings/{course_id}", filename, upload)
        if not mime.startswith(("video/", "audio/")):
            mime = "video/mp4" if filename.lower().endswith((".mp4", ".mov", ".m4v", ".webm", ".mkv")) else "audio/mpeg"
        cur = self.db.execute(  # published=0: מתחיל כטיוטה שרק המרצה רואה
            "INSERT INTO recordings (course_id, title, file_path, mime, published) VALUES (?, ?, ?, ?, 0)",
            (course_id, title.strip() or filename, rel, mime),
        )
        self.db.commit()
        return self.get(cur.lastrowid)

    def get(self, recording_id: int) -> Recording:
        row = self.db.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)).fetchone()
        if row is None:
            raise NotFound("ההקלטה לא נמצאה")
        return Recording.from_row(row)

    def list(self, course_id: int, include_drafts: bool = True) -> list[Recording]:
        """סטודנטים מקבלים include_drafts=False ורואים רק הקלטות שפורסמו."""
        sql = "SELECT * FROM recordings WHERE course_id = ?"
        if not include_drafts:
            sql += " AND published = 1"
        rows = self.db.execute(sql + " ORDER BY id DESC", (course_id,))
        return [Recording.from_row(r) for r in rows]

    def get_visible(self, recording_id: int, can_manage: bool) -> Recording:
        """טיוטה נראית כאילו לא קיימת עבור מי שלא מנהל את הקורס."""
        rec = self.get(recording_id)
        if not rec.published and not can_manage:
            raise NotFound("ההקלטה לא נמצאה")
        return rec

    # ---------- publishing and editing (lecturer) ----------
    def set_published(self, recording_id: int, published: bool) -> None:
        self.get(recording_id)
        self._set(recording_id, published=1 if published else 0)

    def update_details(self, recording_id: int, title: str, summary: str,
                       key_points: list[str], chapters: list[tuple[str, str]]) -> Recording:
        """chapters: זוגות של (זמן כטקסט, כותרת). זמן נכתב כמו 1:05 או 1:02:30."""
        rec = self.get(recording_id)
        if not rec.editable:
            raise ValidationError("אפשר לערוך אחרי שהתמלול והסיכום מסתיימים")
        title = (title or "").strip()
        if not title:
            raise ValidationError("צריך לתת להקלטה שם")
        cleaned_chapters = []
        for raw_time, raw_title in chapters:
            raw_time, raw_title = (raw_time or "").strip(), (raw_title or "").strip()
            if not raw_time and not raw_title:
                continue  # שורה ריקה שנשארה בטופס
            if not raw_title:
                raise ValidationError(f"לפרק שמתחיל ב-{raw_time} חסרה כותרת")
            cleaned_chapters.append({"start": parse_clock(raw_time), "title": raw_title})
        cleaned_chapters.sort(key=lambda c: c["start"])
        starts = [c["start"] for c in cleaned_chapters]
        if len(set(starts)) != len(starts):
            raise ValidationError("יש שני פרקים שמתחילים באותו זמן")
        self._set(
            recording_id,
            title=title,
            summary=(summary or "").strip(),
            key_points_json=json.dumps([p.strip() for p in key_points if p and p.strip()], ensure_ascii=False),
            chapters_json=json.dumps(cleaned_chapters, ensure_ascii=False),
        )
        return self.get(recording_id)

    # ---------- private feedback for the lecturer ----------
    def request_feedback(self, recording_id: int) -> int:
        """מסמן שהמרצה ביקש משוב ומחזיר מספר בקשה. הכתיבה עצמה רצה ברקע (write_feedback)."""
        rec = self.get(recording_id)
        if rec.processing or not rec.transcript:
            raise ValidationError("אפשר לבקש משוב אחרי שהתמלול מסתיים")
        if rec.feedback_status == "pending":
            return rec.feedback_job  # לחיצה כפולה: לא פותחים בקשה שנייה
        if not rec.can_request_feedback:
            raise ValidationError("כבר יש משוב להקלטה הזו. אחרי שתערוך ותשמור את התמלול אפשר לכתוב משוב חדש")
        job = rec.feedback_job + 1
        self._set(recording_id, feedback_status="pending", feedback_error="", feedback_job=job)
        return job

    def cancel_feedback(self, recording_id: int) -> None:
        """ביטול בזמן הכתיבה. אם כבר היה משוב קודם, חוזרים אליו. התוצאה של הבקשה שבוטלה תיזרק."""
        rec = self.get(recording_id)
        if rec.feedback_status != "pending":
            return
        previous = "ready" if rec.feedback else ""
        self._set(recording_id, feedback_status=previous, feedback_job=rec.feedback_job + 1)

    def pending_feedback_ids(self) -> list[tuple[int, int]]:
        rows = self.db.execute("SELECT id, feedback_job FROM recordings WHERE feedback_status = 'pending' ORDER BY id")
        return [(r["id"], r["feedback_job"]) for r in rows]

    def write_feedback(self, recording_id: int, writer, job: int | None = None) -> Recording:
        """job: מספר הבקשה. אם בינתיים המרצה ביטל (או ביקש שוב), התוצאה הזו כבר לא רלוונטית ונזרקת."""
        rec = self.get(recording_id)
        job = rec.feedback_job if job is None else job
        try:
            fb = writer.write([Segment(**s) for s in rec.transcript])
            fields = dict(
                feedback_status="ready",
                feedback_json=json.dumps(
                    {"overall": fb.overall, "strengths": fb.strengths, "items": fb.items}, ensure_ascii=False
                ),
                feedback_error="",
                feedback_at=time.time(),
            )
        except Exception as err:  # LLMError, רשת: לא נשאיר את המשוב תקוע ב״כותב״
            log.exception("feedback for recording %s failed", recording_id)
            fields = dict(feedback_status="failed", feedback_error=str(err)[:500])
        current = self.get(recording_id)
        if current.feedback_status == "pending" and current.feedback_job == job:
            self._set(recording_id, **fields)
        return self.get(recording_id)

    def update_transcript(self, recording_id: int, texts: list[str]) -> Recording:
        """מחליף רק את הטקסט של כל קטע. הזמנים נשארים כמו שהתמלול קבע, כדי שהקפיצה בנגן תמשיך לעבוד."""
        rec = self.get(recording_id)
        if not rec.editable:
            raise ValidationError("אפשר לערוך אחרי שהתמלול והסיכום מסתיימים")
        if len(texts) != len(rec.transcript):
            raise ValidationError("התמלול השתנה בזמן העריכה. רענן את העמוד ונסה שוב")
        segments = [dict(seg, text=(text or "").strip()) for seg, text in zip(rec.transcript, texts)]
        if segments == rec.transcript:
            return rec  # שמירה בלי שינוי בתמלול לא פותחת משוב חדש
        self._set(recording_id, transcript_json=json.dumps(segments, ensure_ascii=False),
                  transcript_edited_at=time.time())
        return self.get(recording_id)

    def pending_ids(self) -> list[int]:
        rows = self.db.execute(
            "SELECT id FROM recordings WHERE status IN ('uploaded', 'transcribing', 'summarizing') ORDER BY id"
        )
        return [r["id"] for r in rows]

    def delete(self, recording_id: int) -> None:
        rec = self.get(recording_id)
        self.db.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))
        self.db.commit()
        self.files.delete(rec.file_path)

    def retry(self, recording_id: int) -> None:
        rec = self.get(recording_id)
        if rec.status != "failed":
            raise ValidationError("אפשר לנסות שוב רק הקלטה שנכשלה")
        self._set(recording_id, status="uploaded", error="")

    def _set(self, recording_id: int, **fields) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE recordings SET {cols} WHERE id = ?", (*fields.values(), recording_id))
        self.db.commit()

    def process(self, recording_id: int, transcriber: Transcriber, summarizer: LessonSummarizer) -> Recording:
        """התמלול נשמר גם אם הסיכום נכשל, כך שבניסיון חוזר מסכמים בלי לתמלל שוב."""
        rec = self.get(recording_id)
        segments = [Segment(**s) for s in rec.transcript]
        try:
            if not segments:
                self._set(recording_id, status="transcribing")
                course = self.db.execute("SELECT name FROM courses WHERE id = ?", (rec.course_id,)).fetchone()
                hint = transcription_hint(course["name"] if course else "")
                segments = transcriber.transcribe(str(self.files.path(rec.file_path)), hint=hint)
                self._set(recording_id, transcript_json=json.dumps(
                    [{"start": s.start, "end": s.end, "text": s.text} for s in segments], ensure_ascii=False))
            self._set(recording_id, status="summarizing")
            result = summarizer.summarize(segments)
            self._set(
                recording_id,
                status="ready",
                summary=result.summary,
                key_points_json=json.dumps(result.key_points, ensure_ascii=False),
                chapters_json=json.dumps(result.chapters, ensure_ascii=False),
                error="",
            )
        except (LLMError, RuntimeError, OSError) as err:
            log.exception("recording %s failed", recording_id)
            self._set(recording_id, status="failed", error=str(err)[:500])
        except Exception as err:  # לא נשאיר הקלטה תקועה ב״בתמלול״
            log.exception("recording %s failed", recording_id)
            self._set(recording_id, status="failed", error=f"שגיאה לא צפויה: {err}"[:500])
        return self.get(recording_id)


class BackgroundJobRunner:
    """Thread יחיד שמעבד את העבודות לפי הסדר. מודל ה-Whisper נטען פעם אחת ונשאר בזיכרון.

    שני סוגי עבודות: ("process", id) לתמלול וסיכום, ו-("feedback", id) למשוב האישי למרצה.
    """

    def __init__(self, db_path: str, files: FileStore, transcriber: Transcriber, provider_factory):
        self.db_path = db_path
        self.files = files
        self.transcriber = transcriber
        self.provider_factory = provider_factory  # נבנה מחדש לכל עבודה, כדי לקלוט key חדש מ-.env
        self.jobs: "queue.Queue[tuple]" = queue.Queue()
        self.thread = threading.Thread(target=self._run, name="recordings", daemon=True)

    def start(self) -> None:
        from ..db import connect

        conn = connect(self.db_path)
        try:  # מה שנשאר מהרצה קודמת
            service = RecordingService(conn, self.files)
            for rid in service.pending_ids():
                self.jobs.put(("process", rid, None))
            for rid, job in service.pending_feedback_ids():
                self.jobs.put(("feedback", rid, job))
        finally:
            conn.close()
        self.thread.start()

    def enqueue(self, recording_id: int) -> None:
        self.jobs.put(("process", recording_id, None))

    def enqueue_feedback(self, recording_id: int, job: int) -> None:
        self.jobs.put(("feedback", recording_id, job))

    def _run(self) -> None:
        from ..db import connect
        from .llm import LessonFeedbackWriter

        while True:
            kind, rid, job = self.jobs.get()
            conn = connect(self.db_path)
            try:
                service = RecordingService(conn, self.files)
                try:
                    provider = self.provider_factory()
                except LLMError as err:
                    provider = _FailingProvider(str(err))
                if kind == "feedback":
                    service.write_feedback(rid, LessonFeedbackWriter(provider), job)
                else:
                    service.process(rid, self.transcriber, LessonSummarizer(provider))
            except NotFound:
                pass
            finally:
                conn.close()


class _FailingProvider:
    """כשאין GEMINI_API_KEY: כל ניסיון מחזיר את אותה הודעה ברורה."""

    def __init__(self, message: str):
        self.message = message

    def generate_json(self, prompt):
        raise LLMError(self.message)


def start_runner(app) -> None:
    """נקרא מ-create_app. ב-debug reloader רק התהליך הפנימי מריץ את ה-thread."""
    import os

    debug = app.debug or os.environ.get("FLASK_DEBUG") == "1"
    if debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    from .llm import GeminiProvider
    from .transcription import WhisperTranscriber

    cfg = app.config
    runner = BackgroundJobRunner(
        cfg["DATABASE"],
        FileStore(cfg["UPLOAD_DIR"]),
        WhisperTranscriber(cfg["WHISPER_MODEL"]),
        lambda: GeminiProvider(cfg["GEMINI_API_KEY"], cfg["GEMINI_MODEL"], cfg["GEMINI_FALLBACK_MODELS"]),
    )
    runner.start()
    app.extensions["recording_runner"] = runner
