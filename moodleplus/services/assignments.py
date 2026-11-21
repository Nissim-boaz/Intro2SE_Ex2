"""מטלות: המרצה מפרסם מטלה, הסטודנט מגיש קובץ, והמרצה נותן ציון והערה שרק הסטודנט רואה."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from ..errors import NotFound, ValidationError
from .content import FileStore
from ..models import User

MAX_GRADE = 100
HEBREW_MONTHS = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
                 "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def parse_due(value: str) -> float:
    """'2026-11-25T23:59' משדה datetime-local (שעון מקומי) -> חותמת זמן."""
    try:
        return datetime.fromisoformat((value or "").strip()).timestamp()
    except ValueError:
        raise ValidationError("צריך לבחור תאריך ושעה להגשה")


def when_he(ts: float, now: float | None = None) -> str:
    """חותמת זמן -> 'היום, 14:05', 'מחר, 23:59' או '25 בנובמבר, 23:59'. השנה מופיעה רק כשהיא לא השנה הנוכחית."""
    dt = datetime.fromtimestamp(ts)
    today = datetime.fromtimestamp(now if now is not None else time.time()).date()
    days = (dt.date() - today).days
    named = {0: "היום", -1: "אתמול", 1: "מחר"}
    if days in named:
        return f"{named[days]}, {dt:%H:%M}"
    date = f"{dt.day} ב{HEBREW_MONTHS[dt.month - 1]}" + (f" {dt.year}" if dt.year != today.year else "")
    return f"{date}, {dt:%H:%M}"


def left_he(seconds: float) -> str:
    """כמה זמן נשאר עד ההגשה, בעברית שנשמעת טבעי."""
    if seconds <= 0:
        return "המועד עבר"
    hours = seconds / 3600
    if hours < 1:
        return "פחות משעה"
    if hours < 24:
        n = int(hours)
        return {1: "עוד שעה", 2: "עוד שעתיים"}.get(n, f"עוד {n} שעות")
    n = int(hours // 24)
    return {1: "עוד יום", 2: "עוד יומיים"}.get(n, f"עוד {n} ימים")


@dataclass(frozen=True)
class Assignment:
    id: int
    course_id: int
    title: str
    description: str
    due_at: float
    file_path: str
    file_name: str
    created_at: str

    @property
    def due_input(self) -> str:
        """הערך לשדה datetime-local בטופס העריכה."""
        return datetime.fromtimestamp(self.due_at).strftime("%Y-%m-%dT%H:%M")

    @classmethod
    def from_row(cls, r) -> "Assignment":
        return cls(r["id"], r["course_id"], r["title"], r["description"], r["due_at"],
                   r["file_path"], r["file_name"], r["created_at"])


@dataclass(frozen=True)
class Submission:
    id: int
    assignment_id: int
    student_id: int
    file_path: str
    file_name: str
    submitted_at: float
    grade: int | None
    feedback: str
    late: bool

    @property
    def graded(self) -> bool:
        return self.grade is not None

    @classmethod
    def from_row(cls, r) -> "Submission":
        return cls(r["id"], r["assignment_id"], r["student_id"], r["file_path"], r["file_name"],
                   r["submitted_at"], r["grade"], r["feedback"], bool(r["late"]))


# late מחושב מול מועד ההגשה הנוכחי, כך שהארכה שהמרצה נותן מתקנת גם הגשות שכבר נשלחו
_SUBMISSION_SQL = (
    "SELECT s.*, s.submitted_at > a.due_at AS late FROM submissions s "
    "JOIN assignments a ON a.id = s.assignment_id"
)


class AssignmentService:
    def __init__(self, db: sqlite3.Connection, files: FileStore, clock: Callable[[], float] = time.time):
        self.db = db
        self.files = files
        self.clock = clock

    # ---------- assignments (lecturer) ----------
    def list(self, course_id: int) -> list[Assignment]:
        rows = self.db.execute("SELECT * FROM assignments WHERE course_id = ? ORDER BY due_at, id", (course_id,))
        return [Assignment.from_row(r) for r in rows]

    def get(self, assignment_id: int) -> Assignment:
        row = self.db.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if row is None:
            raise NotFound("המטלה לא נמצאה")
        return Assignment.from_row(row)

    def create(self, course_id: int, title: str, description: str, due: str,
               file_name: str = "", upload=None) -> Assignment:
        title = self._title(title)
        due_at = parse_due(due)
        rel = self.files.save_stream(f"assignments/{course_id}", file_name, upload) if file_name else ""
        cur = self.db.execute(
            "INSERT INTO assignments (course_id, title, description, due_at, file_path, file_name) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (course_id, title, description.strip(), due_at, rel, file_name if rel else ""),
        )
        self.db.commit()
        return self.get(cur.lastrowid)

    def update(self, assignment_id: int, title: str, description: str, due: str,
               file_name: str = "", upload=None, remove_file: bool = False) -> Assignment:
        current = self.get(assignment_id)
        title = self._title(title)
        due_at = parse_due(due)
        path, name = current.file_path, current.file_name
        if file_name or remove_file:  # קובץ חדש מחליף את הישן, ו״הסר״ מוחק אותו
            self.files.delete(path)
            path, name = "", ""
        if file_name:
            path = self.files.save_stream(f"assignments/{current.course_id}", file_name, upload)
            name = file_name
        self.db.execute(
            "UPDATE assignments SET title = ?, description = ?, due_at = ?, file_path = ?, file_name = ? WHERE id = ?",
            (title, description.strip(), due_at, path, name, assignment_id),
        )
        self.db.commit()
        return self.get(assignment_id)

    def delete(self, assignment_id: int) -> None:
        current = self.get(assignment_id)
        for (rel,) in self.db.execute("SELECT file_path FROM submissions WHERE assignment_id = ?", (assignment_id,)):
            self.files.delete(rel)
        self.files.delete(current.file_path)
        self.db.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))
        self.db.commit()

    @staticmethod
    def _title(title: str) -> str:
        title = (title or "").strip()
        if not title:
            raise ValidationError("צריך לתת למטלה שם")
        return title

    # ---------- submissions (student) ----------
    def submit(self, assignment_id: int, student: User, file_name: str, upload) -> Submission:
        """הגשה אחת לסטודנט. הגשה חוזרת מחליפה את הקובץ, עד שהמרצה בודק. אחרי המועד מותר, ומסומן כאיחור."""
        assignment = self.get(assignment_id)
        if not file_name:
            raise ValidationError("בחר קובץ להגשה")
        previous = self.submission_of(assignment_id, student.id)
        if previous and previous.graded:
            raise ValidationError("המטלה כבר נבדקה, אז אי אפשר להגיש אותה מחדש")
        rel = self.files.save_stream(f"submissions/{assignment.id}", file_name, upload)
        if previous:
            self.files.delete(previous.file_path)
            self.db.execute(
                "UPDATE submissions SET file_path = ?, file_name = ?, submitted_at = ? WHERE id = ?",
                (rel, file_name, self.clock(), previous.id),
            )
        else:
            self.db.execute(
                "INSERT INTO submissions (assignment_id, student_id, file_path, file_name, submitted_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (assignment_id, student.id, rel, file_name, self.clock()),
            )
        self.db.commit()
        return self.submission_of(assignment_id, student.id)

    def submission_of(self, assignment_id: int, student_id: int) -> Submission | None:
        row = self.db.execute(
            _SUBMISSION_SQL + " WHERE s.assignment_id = ? AND s.student_id = ?", (assignment_id, student_id)
        ).fetchone()
        return Submission.from_row(row) if row else None

    def get_submission(self, submission_id: int) -> Submission:
        row = self.db.execute(_SUBMISSION_SQL + " WHERE s.id = ?", (submission_id,)).fetchone()
        if row is None:
            raise NotFound("ההגשה לא נמצאה")
        return Submission.from_row(row)

    def my_submissions(self, course_id: int, student_id: int) -> dict[int, Submission]:
        """לעמוד הקורס של סטודנט: מה הוא כבר הגיש, לפי מטלה."""
        rows = self.db.execute(_SUBMISSION_SQL + " WHERE a.course_id = ? AND s.student_id = ?", (course_id, student_id))
        return {r["assignment_id"]: Submission.from_row(r) for r in rows}

    # ---------- grading (lecturer) ----------
    def roster(self, assignment_id: int) -> list[tuple[User, Submission | None]]:
        """כל הסטודנטים בקורס, עם ההגשה של כל אחד (או None). מי שהגיש ולא נבדק מופיע ראשון."""
        assignment = self.get(assignment_id)
        students = [User.from_row(r) for r in self.db.execute(
            "SELECT u.* FROM users u JOIN enrollments e ON e.user_id = u.id "
            "WHERE e.course_id = ? AND e.role = 'student' ORDER BY u.name", (assignment.course_id,))]
        subs = {r["student_id"]: Submission.from_row(r) for r in self.db.execute(
            _SUBMISSION_SQL + " WHERE s.assignment_id = ?", (assignment_id,))}
        rows = [(u, subs.get(u.id)) for u in students]
        rows.sort(key=lambda p: 0 if p[1] and not p[1].graded else 1 if p[1] else 2)
        return rows

    def counts(self, course_id: int) -> dict[int, dict]:
        """לעמוד הקורס של המרצה: כמה הגישו וכמה מחכים לבדיקה, לכל מטלה."""
        rows = self.db.execute(
            "SELECT a.id, COUNT(s.id) AS submitted, SUM(s.id IS NOT NULL AND s.grade IS NULL) AS ungraded "
            "FROM assignments a LEFT JOIN submissions s ON s.assignment_id = a.id "
            "AND s.student_id IN (SELECT user_id FROM enrollments WHERE course_id = a.course_id AND role = 'student') "
            "WHERE a.course_id = ? GROUP BY a.id", (course_id,))
        return {r["id"]: {"submitted": r["submitted"], "ungraded": r["ungraded"] or 0} for r in rows}

    def grade(self, submission_id: int, grade: str, feedback: str) -> Submission:
        """ציון 0 עד 100 והערה. ציון ריק מבטל את הבדיקה, והסטודנט יכול שוב להגיש מחדש."""
        self.get_submission(submission_id)
        value = (grade or "").strip()
        if value:
            try:
                number = int(value)
            except ValueError:
                raise ValidationError("הציון צריך להיות מספר שלם")
            if not 0 <= number <= MAX_GRADE:
                raise ValidationError(f"הציון צריך להיות בין 0 ל-{MAX_GRADE}")
        else:
            number = None
        self.db.execute(
            "UPDATE submissions SET grade = ?, feedback = ?, graded_at = ? WHERE id = ?",
            (number, (feedback or "").strip(), self.clock() if number is not None else 0, submission_id),
        )
        self.db.commit()
        return self.get_submission(submission_id)
