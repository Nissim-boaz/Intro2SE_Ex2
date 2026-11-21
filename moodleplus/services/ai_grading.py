"""בדיקת מטלות עם AI.

ה-AI רק מציע: ציון, נימוק למרצה ומשוב בונה לסטודנט. שום דבר לא מגיע לסטודנט עד שהמרצה מאשר ומפרסם.
אחרי שכל ההגשות נבדקו, מעבר אחד על כל הכיתה מוסיף לכל סטודנט הערה ביחס לכיתה (בלי שמות),
ובדיקה מקומית של דמיון טקסט מסמנת למרצה בלבד הגשות שנראות מועתקות.
"""
from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Callable

from ..errors import NotFound, ValidationError
from .assignments import Assignment, AssignmentService
from .content import FileStore
from .documents import Document, read_document, shingles, similarity
from .llm import LLMError, LLMProvider

log = logging.getLogger(__name__)

SIMILAR_AT = 0.5            # חצי מהרצפים של 5 מילים משותפים: כמעט בטוח לא במקרה
MIN_SHINGLES = 60           # הגשה קצרה מדי לא נבדקת לדמיון
MAX_SOLUTION_CHARS = 30_000


@dataclass
class Review:
    grade: int
    reason: str      # למרצה: למה הציון הזה
    feedback: str    # לסטודנט: משוב בונה
    summary: str     # תקציר קצר של מה שהוגש, בשביל ההשוואה לכיתה
    off_topic: bool


class SubmissionReviewer:
    """הגשה אחת -> הצעה לציון, נימוק ומשוב."""

    PROMPT = """אתה עוזר הוראה שבודק מטלה בקורס אוניברסיטאי. כתוב בעברית טבעית וברורה.

המטלה: {title}
ההנחיות שקיבלו הסטודנטים:
{description}

דגשים לבדיקה מהמרצה (אם יש, הם קובעים):
{guidelines}

פתרון לדוגמה מהמרצה (אם יש, השתמש בו כקנה מידה ולא כתשובה היחידה הנכונה):
{solution}

ההגשה של הסטודנט ({file_name}):
{submission}

החזר JSON בלבד במבנה:
{{"grade": מספר שלם 0 עד 100,
  "reason": "2 עד 4 משפטים למרצה: מה טוב, מה חסר, ולמה הציון הזה",
  "feedback": "משוב בונה לסטודנט, בגוף שני, 3 עד 6 משפטים: מה עשה טוב ומה כדאי לשפר בפעם הבאה. מכבד ולא מתנשא, בלי לציין את הציון",
  "summary": "שני משפטים שמתארים מה הסטודנט הגיש ואיזו גישה בחר",
  "off_topic": true אם ההגשה לא קשורה בכלל למטלה, אחרת false}}

אל תמציא דברים שלא מופיעים בהגשה. אם ההגשה ריקה או לא קריאה, תן ציון 0 והסבר."""

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    def review(self, assignment: Assignment, guidelines: str, solution: Document | None,
               submission: Document) -> Review:
        prompt = self.PROMPT.format(
            title=assignment.title,
            description=assignment.description or "(אין הנחיות כתובות)",
            guidelines=guidelines.strip() or "(אין)",
            solution=(solution.text[:MAX_SOLUTION_CHARS] if solution and solution.text
                      else "(מצורף כקובץ)" if solution and solution.blobs else "(אין)"),
            file_name=submission.name,
            submission=submission.text or "(הקובץ מצורף, קרא אותו ממנו)",
        )
        files = list(submission.blobs) + (list(solution.blobs) if solution else [])
        data = self.provider.generate_json(prompt, files=files) if files else self.provider.generate_json(prompt)
        try:
            grade = max(0, min(100, int(round(float(data.get("grade", 0))))))
        except (TypeError, ValueError):
            raise LLMError("ה-AI לא החזיר ציון תקין")
        return Review(grade, str(data.get("reason", "")).strip(), str(data.get("feedback", "")).strip(),
                      str(data.get("summary", "")).strip(), bool(data.get("off_topic")))


class ClassComparer:
    """מעבר אחד על כל הכיתה: לכל סטודנט הערה קצרה ביחס לשאר, בלי שמות ובלי לחשוף עבודות של אחרים."""

    PROMPT = """אלה תקצירים של כל ההגשות במטלה "{title}", כל אחת עם מזהה וציון מוצע.

{items}

לכל הגשה, כתוב לסטודנט משפט אחד או שניים בעברית שממקמים את העבודה ביחס לכיתה, רק אם יש משהו שבאמת בולט:
למשל "בשונה מרוב הכיתה, לא צירפת דיאגרמת רצף" או "הפתרון שלך מקורי יותר מרוב ההגשות".
אל תזכיר שמות, מזהים או עבודות של סטודנטים אחרים, ואל תזכיר ציונים. אם אין משהו בולט, החזר מחרוזת ריקה.

החזר JSON בלבד: {{"notes": {{"מזהה": "הערה או מחרוזת ריקה"}}}}"""

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    def compare(self, title: str, items: list[tuple[str, str, int]]) -> dict[str, str]:
        if len(items) < 3:  # בלי כיתה אין למה להשוות
            return {}
        lines = "\n".join(f"[{key}] ציון {grade}: {summary}" for key, summary, grade in items)
        data = self.provider.generate_json(self.PROMPT.format(title=title, items=lines))
        notes = data.get("notes") or {}
        return {str(k): str(v).strip() for k, v in notes.items() if str(v).strip()}


# ---------- the service ----------
class AIGradingService:
    def __init__(self, db: sqlite3.Connection, files: FileStore, clock: Callable[[], float] = time.time):
        self.db = db
        self.files = files
        self.clock = clock
        self.assignments = AssignmentService(db, files, clock)

    # ----- lecturer settings -----
    def save_settings(self, assignment_id: int, guidelines: str, file_name: str = "", upload=None,
                      remove_solution: bool = False) -> Assignment:
        a = self.assignments.get(assignment_id)
        path, name = a.ai_solution_path, a.ai_solution_name
        if file_name or remove_solution:
            self.files.delete(path)
            path, name = "", ""
        if file_name:
            path, name = self.files.save_stream(f"assignments/{a.course_id}/solutions", file_name, upload), file_name
        self.db.execute("UPDATE assignments SET ai_guidelines = ?, ai_solution_path = ?, ai_solution_name = ? "
                        "WHERE id = ?", ((guidelines or "").strip()[:8000], path, name, assignment_id))
        self.db.commit()
        return self.assignments.get(assignment_id)

    # ----- running -----
    def to_review(self, assignment_id: int) -> list[int]:
        """הגשות של סטודנטים בקורס שעוד לא נבדקו על ידי ה-AI, או שהוגשו מחדש אחרי הבדיקה."""
        rows = self.db.execute(
            "SELECT s.id FROM submissions s JOIN assignments a ON a.id = s.assignment_id "
            "JOIN enrollments e ON e.user_id = s.student_id AND e.course_id = a.course_id AND e.role = 'student' "
            "WHERE s.assignment_id = ? AND (s.ai_at = 0 OR s.ai_at < s.submitted_at) ORDER BY s.id",
            (assignment_id,))
        return [r[0] for r in rows]

    def request(self, assignment_id: int, redo: bool = False) -> int:
        """מתחיל בדיקה ברקע. מחזיר מספר עבודה: תוצאה של בקשה שבוטלה או הוחלפה נזרקת."""
        a = self.assignments.get(assignment_id)
        if a.ai_status == "running":
            return a.ai_job
        if redo:
            self.db.execute("UPDATE submissions SET ai_at = 0 WHERE assignment_id = ?", (assignment_id,))
        total = len(self.to_review(assignment_id))
        if not total:
            raise ValidationError("אין הגשות חדשות לבדיקה")
        self.db.execute("UPDATE assignments SET ai_status = 'running', ai_error = '', ai_job = ai_job + 1, "
                        "ai_done = 0, ai_total = ? WHERE id = ?", (total, assignment_id))
        self.db.commit()
        return self.assignments.get(assignment_id).ai_job

    def cancel(self, assignment_id: int) -> None:
        self.db.execute("UPDATE assignments SET ai_status = 'cancelled', ai_job = ai_job + 1 WHERE id = ? "
                        "AND ai_status = 'running'", (assignment_id,))
        self.db.commit()

    def pending_jobs(self) -> list[tuple[int, int]]:
        return [(r[0], r[1]) for r in self.db.execute("SELECT id, ai_job FROM assignments WHERE ai_status = 'running'")]

    def _current(self, assignment_id: int, job: int) -> bool:
        row = self.db.execute("SELECT ai_status, ai_job FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        return bool(row) and row[0] == "running" and row[1] == job

    def run(self, assignment_id: int, job: int, provider: LLMProvider, delay: float = 0.0) -> None:
        """העבודה עצמה (ב-thread של הרקע): כל הגשה בנפרד, אחר כך השוואה לכיתה ובדיקת דמיון."""
        try:
            a = self.assignments.get(assignment_id)
        except NotFound:
            return
        solution = (read_document(self.files.path(a.ai_solution_path), a.ai_solution_name)
                    if a.ai_solution_path else None)
        reviewer = SubmissionReviewer(provider)
        failures = 0
        for sid in self.to_review(assignment_id):
            if not self._current(assignment_id, job):
                return  # בוטל, או שהתחילה בדיקה חדשה
            sub = self.assignments.get_submission(sid)
            doc = read_document(self.files.path(sub.file_path), sub.file_name)
            try:
                if not doc.readable:
                    raise LLMError(doc.error or "לא הצלחתי לקרוא את הקובץ")
                r = reviewer.review(a, a.ai_guidelines, solution, doc)
                self.db.execute(
                    "UPDATE submissions SET ai_grade = ?, ai_reason = ?, ai_feedback = ?, ai_summary = ?, "
                    "ai_off_topic = ?, ai_error = '', ai_at = ? WHERE id = ?",
                    (r.grade, r.reason, r.feedback, r.summary, int(r.off_topic), self.clock(), sid))
            except LLMError as err:
                failures += 1
                self.db.execute("UPDATE submissions SET ai_grade = NULL, ai_error = ?, ai_at = ? WHERE id = ?",
                                (str(err)[:300], self.clock(), sid))
            self.db.execute("UPDATE assignments SET ai_done = ai_done + 1 WHERE id = ? AND ai_job = ?",
                            (assignment_id, job))
            self.db.commit()
            if delay:
                time.sleep(delay)  # ה-free tier של Gemini מגביל כמה בקשות בדקה
        if not self._current(assignment_id, job):
            return
        self._compare_class(a, provider)
        self._flag_similar(assignment_id)
        reviewed = self.db.execute("SELECT COUNT(*) FROM submissions WHERE assignment_id = ? AND ai_grade IS NOT NULL",
                                   (assignment_id,)).fetchone()[0]
        status, error = ("failed", "ה-AI לא הצליח לבדוק אף הגשה. נסה שוב בעוד כמה דקות") if failures and not reviewed \
            else ("done", f"{failures} הגשות לא נבדקו" if failures else "")
        self.db.execute("UPDATE assignments SET ai_status = ?, ai_error = ? WHERE id = ? AND ai_job = ?",
                        (status, error, assignment_id, job))
        self.db.commit()

    def _compare_class(self, a: Assignment, provider: LLMProvider) -> None:
        rows = self.db.execute("SELECT id, ai_summary, ai_grade FROM submissions WHERE assignment_id = ? "
                               "AND ai_grade IS NOT NULL AND ai_summary != ''", (a.id,)).fetchall()
        keys = {f"h{i + 1}": r[0] for i, r in enumerate(rows)}  # מזהים אנונימיים, בלי מספרים מה-DB
        try:
            notes = ClassComparer(provider).compare(a.title, [(k, r[1], r[2]) for k, r in zip(keys, rows)])
        except LLMError as err:
            log.warning("class comparison failed: %s", err)
            return
        for key, sid in keys.items():
            self.db.execute("UPDATE submissions SET ai_class_note = ? WHERE id = ?", (notes.get(key, ""), sid))

    def _flag_similar(self, assignment_id: int) -> None:
        """דמיון טקסט בין כל זוג הגשות, בלי AI. רצפים שמופיעים גם בהנחיות או בפתרון לא נספרים."""
        a = self.assignments.get(assignment_id)
        common = shingles(a.description)
        if a.ai_solution_path:
            common |= shingles(read_document(self.files.path(a.ai_solution_path), a.ai_solution_name).text)
        subs = self.db.execute(
            "SELECT s.id, s.file_path, s.file_name, s.ai_off_topic, u.name FROM submissions s "
            "JOIN users u ON u.id = s.student_id WHERE s.assignment_id = ?", (assignment_id,)).fetchall()
        prints = {}
        for s in subs:
            grams = shingles(read_document(self.files.path(s["file_path"]), s["file_name"]).text) - common
            if len(grams) >= MIN_SHINGLES:
                prints[s["id"]] = grams
        flags: dict[int, list[str]] = {s["id"]: [] for s in subs}
        names = {s["id"]: s["name"] for s in subs}
        ids = list(prints)
        for i, x in enumerate(ids):
            for y in ids[i + 1:]:
                score = similarity(prints[x], prints[y])
                if score >= SIMILAR_AT:
                    flags[x].append(f"דומה מאוד להגשה של {names[y]} ({round(score * 100)}%)")
                    flags[y].append(f"דומה מאוד להגשה של {names[x]} ({round(score * 100)}%)")
        for s in subs:
            notes = flags[s["id"]] + (["נראה שההגשה לא קשורה למטלה"] if s["ai_off_topic"] else [])
            self.db.execute("UPDATE submissions SET ai_flag = ? WHERE id = ?", ("\n".join(notes), s["id"]))
        self.db.commit()

    # ----- approving -----
    @staticmethod
    def student_feedback(sub) -> str:
        """המשוב שעובר לסטודנט כשהמרצה מאשר: המשוב הבונה, ואחריו ההערה ביחס לכיתה אם יש."""
        parts = [sub.ai_feedback.strip()]
        if sub.ai_class_note.strip():
            parts.append("ביחס לכיתה: " + sub.ai_class_note.strip())
        return "\n\n".join(p for p in parts if p)

    def approve(self, submission_id: int) -> None:
        sub = self.assignments.get_submission(submission_id)
        if sub.ai_grade is None:
            raise ValidationError("אין הצעה של ה-AI להגשה הזו")
        feedback = sub.feedback.strip() or self.student_feedback(sub)
        self.assignments.grade(submission_id, str(sub.ai_grade), feedback)

    def approve_all(self, assignment_id: int) -> int:
        """מאשר את ההצעות לכל ההגשות שעוד אין להן ציון. ציון שהמרצה כבר נתן לא משתנה."""
        ids = [r[0] for r in self.db.execute(
            "SELECT id FROM submissions WHERE assignment_id = ? AND grade IS NULL AND ai_grade IS NOT NULL "
            "AND ai_at >= submitted_at", (assignment_id,))]
        for sid in ids:
            self.approve(sid)
        return len(ids)


# ---------- background thread ----------
class AIGradingRunner:
    """Thread נפרד מזה של ההקלטות, כדי שבדיקת מטלות לא תחכה לתמלול של שעה וחצי."""

    def __init__(self, db_path: str, files: FileStore, provider_factory, delay: float = 4.0):
        self.db_path = db_path
        self.files = files
        self.provider_factory = provider_factory
        self.delay = delay
        self.jobs: "queue.Queue[tuple[int, int]]" = queue.Queue()
        self.thread = threading.Thread(target=self._run, name="ai-grading", daemon=True)

    def start(self) -> None:
        from ..db import connect

        conn = connect(self.db_path)
        try:
            for job in AIGradingService(conn, self.files).pending_jobs():
                self.jobs.put(job)
        finally:
            conn.close()
        self.thread.start()

    def enqueue(self, assignment_id: int, job: int) -> None:
        self.jobs.put((assignment_id, job))

    def _run(self) -> None:
        from ..db import connect

        while True:
            assignment_id, job = self.jobs.get()
            conn = connect(self.db_path)
            try:
                service = AIGradingService(conn, self.files)
                try:
                    provider = self.provider_factory()
                except LLMError as err:
                    conn.execute("UPDATE assignments SET ai_status = 'failed', ai_error = ? WHERE id = ? AND ai_job = ?",
                                 (str(err), assignment_id, job))
                    conn.commit()
                    continue
                service.run(assignment_id, job, provider, self.delay)
            except Exception:  # thread הרקע לא מת בגלל הגשה אחת
                log.exception("AI grading failed")
                conn.execute("UPDATE assignments SET ai_status = 'failed', ai_error = 'משהו השתבש בבדיקה. נסה שוב' "
                             "WHERE id = ? AND ai_job = ?", (assignment_id, job))
                conn.commit()
            finally:
                conn.close()


def start_grading_runner(app) -> None:
    import os

    debug = app.debug or os.environ.get("FLASK_DEBUG") == "1"
    if debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    from .llm import GeminiProvider

    cfg = app.config
    runner = AIGradingRunner(
        cfg["DATABASE"], FileStore(cfg["UPLOAD_DIR"]),
        lambda: GeminiProvider(cfg["GEMINI_API_KEY"], cfg["GEMINI_MODEL"], cfg["GEMINI_FALLBACK_MODELS"]),
        delay=float(cfg.get("AI_GRADING_DELAY", 4.0)),
    )
    runner.start()
    app.extensions["grading_runner"] = runner
