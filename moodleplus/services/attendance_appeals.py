"""ערעור על נוכחות: סטודנט שסומן חסר בדגימה שנסגרה כותב למרצה, והמרצה מקבל (ונרשם לו סימון ידני) או דוחה."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..errors import NotFound, ValidationError
from ..models import User
from .attendance import AttendanceService, Record, Sample

STATUS_LABELS = {"pending": "ממתין לתשובת המרצה", "accepted": "התקבל", "rejected": "נדחה"}


@dataclass(frozen=True)
class AttendanceAppeal:
    id: int
    sample_id: int
    student_id: int
    student_name: str
    lesson_id: int
    lesson_number: int
    seq: int
    text: str
    status: str
    reply: str
    created_at: float

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]

    @classmethod
    def from_row(cls, r) -> "AttendanceAppeal":
        return cls(r["id"], r["sample_id"], r["student_id"], r["student_name"], r["lesson_id"], r["lesson_number"],
                   r["seq"], r["text"], r["status"], r["reply"], r["created_at"])


@dataclass(frozen=True)
class HistoryCell:
    """דגימה אחת בהיסטוריה של הסטודנט."""
    sample: Sample
    record: Record | None
    appeal: AttendanceAppeal | None
    closed: bool

    @property
    def can_appeal(self) -> bool:
        return self.closed and self.record is None and self.appeal is None


@dataclass(frozen=True)
class HistoryLesson:
    lesson_id: int
    number: int
    cells: list[HistoryCell]

    @property
    def present(self) -> int:
        return sum(1 for c in self.cells if c.record)

    @property
    def percent(self) -> int:
        return round(100 * self.present / len(self.cells)) if self.cells else 0


_SELECT = (
    "SELECT a.*, u.name AS student_name, s.lesson_id, s.seq, l.number AS lesson_number, l.course_id "
    "FROM attendance_appeals a JOIN users u ON u.id = a.student_id "
    "JOIN attendance_samples s ON s.id = a.sample_id JOIN lessons l ON l.id = s.lesson_id"
)


class AttendanceAppealService:
    def __init__(self, db: sqlite3.Connection, attendance: AttendanceService):
        self.db = db
        self.attendance = attendance

    @property
    def clock(self):
        return self.attendance.clock

    # ---------- student ----------
    def history(self, course_id: int, student_id: int) -> list[HistoryLesson]:
        """כל השיעורים בקורס, מהחדש לישן, עם מה שקרה בכל דגימה. דגימה פתוחה לא מוצגת: בה עושים נוכחות רגילה."""
        now = self.clock.now()
        appeals = {a.sample_id: a for a in self._query("WHERE l.course_id = ? AND a.student_id = ?",
                                                       (course_id, student_id))}
        result = []
        for lesson in self.attendance.lessons(course_id):
            cells = []
            for sample in self.attendance.samples(lesson.id):
                if sample.is_open(now):
                    continue
                cells.append(HistoryCell(sample, self.attendance.record_for(sample.id, student_id),
                                         appeals.get(sample.id), True))
            if cells:
                result.append(HistoryLesson(lesson.id, lesson.number, cells))
        return result

    def appeal(self, sample_id: int, student: User, text: str) -> AttendanceAppeal:
        sample = self.attendance.get_sample(sample_id)
        if sample.is_open(self.clock.now()):
            raise ValidationError("הדגימה עוד פתוחה. אפשר לבצע נוכחות רגילה מעמוד הקורס")
        if self.attendance.record_for(sample_id, student.id):
            raise ValidationError("אתה כבר מסומן כנוכח בדגימה הזו")
        if self._query("WHERE a.sample_id = ? AND a.student_id = ?", (sample_id, student.id)):
            raise ValidationError("כבר ערערת על הדגימה הזו")
        text = (text or "").strip()
        if not text:
            raise ValidationError("כתוב למרצה למה אתה מערער, למשל שהטלפון לא קלט את הצליל")
        cur = self.db.execute(
            "INSERT INTO attendance_appeals (sample_id, student_id, text, created_at) VALUES (?, ?, ?, ?)",
            (sample_id, student.id, text[:2000], self.clock.now()))
        self.db.commit()
        return self.get(cur.lastrowid)

    # ---------- lecturer ----------
    def get(self, appeal_id: int) -> AttendanceAppeal:
        found = self._query("WHERE a.id = ?", (appeal_id,))
        if not found:
            raise NotFound("הערעור לא נמצא")
        return found[0]

    def course_of(self, appeal_id: int) -> int:
        return self.db.execute(
            "SELECT l.course_id FROM attendance_appeals a JOIN attendance_samples s ON s.id = a.sample_id "
            "JOIN lessons l ON l.id = s.lesson_id WHERE a.id = ?", (appeal_id,)).fetchone()[0]

    def pending_for_lesson(self, lesson_id: int) -> list[AttendanceAppeal]:
        return self._query("WHERE s.lesson_id = ? AND a.status = 'pending'", (lesson_id,))

    def pending_counts(self, course_id: int) -> dict[int, int]:
        """כמה ערעורים פתוחים יש בכל שיעור בקורס, לפי lesson_id."""
        rows = self.db.execute(
            "SELECT s.lesson_id, COUNT(*) FROM attendance_appeals a JOIN attendance_samples s ON s.id = a.sample_id "
            "JOIN lessons l ON l.id = s.lesson_id WHERE l.course_id = ? AND a.status = 'pending' GROUP BY s.lesson_id",
            (course_id,))
        return {lesson_id: n for lesson_id, n in rows}

    def resolve(self, appeal_id: int, lecturer: User, accept: bool, reply: str) -> AttendanceAppeal:
        """קבלה רושמת לסטודנט נוכחות ידנית בדגימה. דחייה צריכה הסבר, שהסטודנט יראה."""
        appeal = self.get(appeal_id)
        if appeal.status != "pending":
            raise ValidationError("כבר ענית על הערעור הזה")
        reply = (reply or "").strip()
        if not accept and not reply:
            raise ValidationError("כתוב לסטודנט למה הערעור נדחה")
        if accept and not self.attendance.record_for(appeal.sample_id, appeal.student_id):
            self.attendance.mark_manual(appeal.sample_id, appeal.student_id, lecturer)
        self.db.execute(
            "UPDATE attendance_appeals SET status = ?, reply = ?, resolved_by = ?, resolved_at = ? WHERE id = ?",
            ("accepted" if accept else "rejected", reply, lecturer.id, self.clock.now(), appeal_id))
        self.db.commit()
        return self.get(appeal_id)

    def _query(self, where: str, args: tuple) -> list[AttendanceAppeal]:
        rows = self.db.execute(f"{_SELECT} {where} ORDER BY a.created_at", args)
        return [AttendanceAppeal.from_row(r) for r in rows]
