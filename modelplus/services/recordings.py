"""הקלטות שיעור: העלאה, תמלול וסיכום ברקע."""
from __future__ import annotations

import json
import logging
import queue
import sqlite3
import threading
from dataclasses import dataclass

from ..errors import NotFound, ValidationError
from .content import FileStore
from .llm import LessonSummarizer, LLMError
from .transcription import Segment, Transcriber

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

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]

    @property
    def processing(self) -> bool:
        return self.status in ("uploaded", "transcribing", "summarizing")

    @property
    def is_video(self) -> bool:
        return self.mime.startswith("video/")

    @classmethod
    def from_row(cls, r) -> "Recording":
        return cls(
            r["id"], r["course_id"], r["title"], r["file_path"], r["mime"], r["status"],
            json.loads(r["transcript_json"]), r["summary"], json.loads(r["key_points_json"]),
            json.loads(r["chapters_json"]), r["error"], r["created_at"],
        )


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
        cur = self.db.execute(
            "INSERT INTO recordings (course_id, title, file_path, mime) VALUES (?, ?, ?, ?)",
            (course_id, title.strip() or filename, rel, mime),
        )
        self.db.commit()
        return self.get(cur.lastrowid)

    def get(self, recording_id: int) -> Recording:
        row = self.db.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)).fetchone()
        if row is None:
            raise NotFound("ההקלטה לא נמצאה")
        return Recording.from_row(row)

    def list(self, course_id: int) -> list[Recording]:
        rows = self.db.execute("SELECT * FROM recordings WHERE course_id = ? ORDER BY id DESC", (course_id,))
        return [Recording.from_row(r) for r in rows]

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
                segments = transcriber.transcribe(str(self.files.path(rec.file_path)))
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
    """Thread יחיד שמעבד הקלטות לפי הסדר. מודל ה-Whisper נטען פעם אחת ונשאר בזיכרון."""

    def __init__(self, db_path: str, files: FileStore, transcriber: Transcriber, summarizer_factory):
        self.db_path = db_path
        self.files = files
        self.transcriber = transcriber
        self.summarizer_factory = summarizer_factory  # נבנה מחדש לכל עבודה, כדי לקלוט key חדש מ-.env
        self.jobs: "queue.Queue[int]" = queue.Queue()
        self.thread = threading.Thread(target=self._run, name="recordings", daemon=True)

    def start(self) -> None:
        from ..db import connect

        conn = connect(self.db_path)
        try:
            for rid in RecordingService(conn, self.files).pending_ids():  # מה שנשאר מהרצה קודמת
                self.jobs.put(rid)
        finally:
            conn.close()
        self.thread.start()

    def enqueue(self, recording_id: int) -> None:
        self.jobs.put(recording_id)

    def _run(self) -> None:
        from ..db import connect

        while True:
            rid = self.jobs.get()
            conn = connect(self.db_path)
            try:
                service = RecordingService(conn, self.files)
                try:
                    summarizer = self.summarizer_factory()
                except LLMError as err:
                    summarizer = _FailingSummarizer(str(err))
                service.process(rid, self.transcriber, summarizer)
            except NotFound:
                pass
            finally:
                conn.close()


class _FailingSummarizer:
    def __init__(self, message: str):
        self.message = message

    def summarize(self, segments):
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
        lambda: LessonSummarizer(GeminiProvider(cfg["GEMINI_API_KEY"], cfg["GEMINI_MODEL"])),
    )
    runner.start()
    app.extensions["recording_runner"] = runner
