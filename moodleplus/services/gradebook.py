"""ציוני הקורס: מבחנים ובחנים, משקל לכל ציון, והציון המשוקלל.

סטודנט רואה רק ציונים שפורסמו, והציון המשוקלל שלו מחושב רק מהם (״עד כה״).
ציון חסר לא נספר. מי שצריך לקבל 0 מקבל אותו מהמרצה במפורש.
"""
from __future__ import annotations

import csv
import io
import sqlite3
import time
from dataclasses import dataclass
from datetime import date
from typing import Callable

from ..errors import NotFound, ValidationError
from ..models import User
from .assignments import HEBREW_MONTHS
from .users import StudentImporter, UserService

KINDS = {"exam": "מבחן", "quiz": "בוחן", "assignment": "מטלה"}
GRADE_KEYS = ("grade", "score", "mark", "ציון", "ציון סופי")
TOTAL_WEIGHT = 100


def parse_grade(value) -> float | None:
    """'87', '87.5' או '87,5' -> מספר בין 0 ל-100. ריק -> None."""
    text = str(value if value is not None else "").strip().replace(",", ".")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        raise ValidationError(f"״{text}״ הוא לא ציון. כתוב מספר בין 0 ל-100")
    if not 0 <= number <= 100:  # גם nan נופל כאן
        raise ValidationError(f"הציון {text} לא בין 0 ל-100")
    return round(number, 2)


def parse_weight(value) -> float:
    try:
        return parse_grade(value) or 0.0
    except ValidationError:
        raise ValidationError(f"המשקל ״{value}״ צריך להיות מספר בין 0 ל-100")


def fmt_grade(value: float | None) -> str:
    """87.0 -> '87', 87.5 -> '87.5', None -> '–'."""
    return "–" if value is None else f"{round(value, 2):g}"


@dataclass(frozen=True)
class Exam:
    id: int
    course_id: int
    title: str
    kind: str       # exam | quiz
    held_on: str    # 'YYYY-MM-DD' או ריק
    weight: float
    published: bool

    @property
    def kind_label(self) -> str:
        return KINDS[self.kind]

    @property
    def date_label(self) -> str:
        if not self.held_on:
            return ""
        d = date.fromisoformat(self.held_on)
        return f"{d.day} ב{HEBREW_MONTHS[d.month - 1]} {d.year}"

    @classmethod
    def from_row(cls, r) -> "Exam":
        return cls(r["id"], r["course_id"], r["title"], r["kind"], r["held_on"], r["weight"], bool(r["published"]))


@dataclass(frozen=True)
class ExamGrade:
    id: int
    exam_id: int
    student_id: int
    student_name: str
    grade: float
    published: bool
    appeal_status: str       # '' | pending | accepted | rejected
    appeal_text: str
    appeal_reply: str
    original_grade: float | None

    @property
    def can_appeal(self) -> bool:
        return self.published and not self.appeal_status

    @classmethod
    def from_row(cls, r) -> "ExamGrade":
        return cls(r["id"], r["exam_id"], r["student_id"], r["student_name"], r["grade"], bool(r["published"]),
                   r["appeal_status"], r["appeal_text"], r["appeal_reply"], r["original_grade"])


@dataclass(frozen=True)
class ImportReport:
    updated: int
    unknown: int   # מיילים שלא שייכים לסטודנט בקורס
    invalid: int   # שורות בלי מייל או עם ציון לא תקין


_GRADE_SQL = (
    "SELECT g.*, u.name AS student_name, e.published FROM exam_grades g "
    "JOIN exams e ON e.id = g.exam_id JOIN users u ON u.id = g.student_id "
    "JOIN enrollments n ON n.user_id = g.student_id AND n.course_id = e.course_id AND n.role = 'student'"
)


class ExamService:
    """מבחנים ובחנים: הגדרה, הזנת ציונים (ידנית או מקובץ), פרסום וערעורים."""

    def __init__(self, db: sqlite3.Connection, clock: Callable[[], float] = time.time):
        self.db = db
        self.clock = clock

    # ---------- exams ----------
    def list(self, course_id: int) -> list[Exam]:
        rows = self.db.execute(
            "SELECT * FROM exams WHERE course_id = ? ORDER BY held_on = '', held_on, id", (course_id,))
        return [Exam.from_row(r) for r in rows]

    def get(self, exam_id: int) -> Exam:
        row = self.db.execute("SELECT * FROM exams WHERE id = ?", (exam_id,)).fetchone()
        if row is None:
            raise NotFound("המבחן לא נמצא")
        return Exam.from_row(row)

    def create(self, course_id: int, title: str, kind: str, held_on: str = "", weight="") -> Exam:
        title, kind, held_on = self._clean(title, kind, held_on)
        number = parse_weight(weight)
        left = TOTAL_WEIGHT - Gradebook(self.db).total_weight(course_id)
        if number > left + 1e-9:
            raise ValidationError(f"נשארו {fmt_grade(max(left, 0))}% לחלק. אפשר לשנות משקלים בטבלת הציונים")
        cur = self.db.execute("INSERT INTO exams (course_id, title, kind, held_on, weight) VALUES (?, ?, ?, ?, ?)",
                              (course_id, title, kind, held_on, number))
        self.db.commit()
        return self.get(cur.lastrowid)

    def update(self, exam_id: int, title: str, kind: str, held_on: str = "") -> Exam:
        self.get(exam_id)
        self.db.execute("UPDATE exams SET title = ?, kind = ?, held_on = ? WHERE id = ?",
                        (*self._clean(title, kind, held_on), exam_id))
        self.db.commit()
        return self.get(exam_id)

    def delete(self, exam_id: int) -> None:
        self.get(exam_id)
        self.db.execute("DELETE FROM exams WHERE id = ?", (exam_id,))
        self.db.commit()

    def set_published(self, exam_id: int, published: bool) -> int:
        """פרסום הציונים לכולם בבת אחת. מחזיר כמה סטודנטים רואים ציון."""
        self.get(exam_id)
        self.db.execute("UPDATE exams SET published = ? WHERE id = ?", (int(published), exam_id))
        self.db.commit()
        return len(self.grades(exam_id))

    @staticmethod
    def _clean(title: str, kind: str, held_on: str) -> tuple[str, str, str]:
        title = (title or "").strip()[:200]
        if not title:
            raise ValidationError("צריך לתת שם למבחן")
        if kind not in ("exam", "quiz"):
            raise ValidationError("בחר אם זה מבחן או בוחן")
        held_on = (held_on or "").strip()
        if held_on:
            try:
                held_on = date.fromisoformat(held_on).isoformat()
            except ValueError:
                raise ValidationError("התאריך לא תקין")
        return title, kind, held_on

    # ---------- grades ----------
    def grades(self, exam_id: int) -> dict[int, ExamGrade]:
        return {r["student_id"]: ExamGrade.from_row(r)
                for r in self.db.execute(_GRADE_SQL + " WHERE g.exam_id = ?", (exam_id,))}

    def get_grade(self, grade_id: int) -> ExamGrade:
        row = self.db.execute(_GRADE_SQL + " WHERE g.id = ?", (grade_id,)).fetchone()
        if row is None:
            raise NotFound("הציון לא נמצא")
        return ExamGrade.from_row(row)

    def roster(self, exam_id: int) -> list[tuple[User, ExamGrade | None]]:
        grades = self.grades(exam_id)
        return [(u, grades.get(u.id)) for u in Gradebook(self.db).students(self.get(exam_id).course_id)]

    def save_grades(self, exam_id: int, changes: dict[int, str]) -> int:
        """שומר רק את מה שהשתנה. קודם בודק הכול, כך ששגיאה אחת לא שומרת חצי כיתה. ערך ריק מוחק את הציון."""
        exam = self.get(exam_id)
        enrolled = {u.id: u for u in Gradebook(self.db).students(exam.course_id)}
        parsed: dict[int, float | None] = {}
        for student_id, value in changes.items():
            if student_id not in enrolled:
                raise ValidationError("אפשר לתת ציון רק לסטודנטים של הקורס")
            try:
                parsed[student_id] = parse_grade(value)
            except ValidationError as err:
                raise ValidationError(f"{enrolled[student_id].name}: {err.message}")
        for student_id, number in parsed.items():
            if number is None:
                self.db.execute("DELETE FROM exam_grades WHERE exam_id = ? AND student_id = ?", (exam_id, student_id))
            else:
                self.db.execute(
                    "INSERT INTO exam_grades (exam_id, student_id, grade) VALUES (?, ?, ?) "
                    "ON CONFLICT (exam_id, student_id) DO UPDATE SET grade = excluded.grade",
                    (exam_id, student_id, number))
        self.db.commit()
        return len(parsed)

    def import_file(self, exam_id: int, filename: str, data: bytes) -> ImportReport:
        """CSV או XLSX עם עמודת מייל ועמודת ציון (גם ״Grade/100.00״ מ-Moodle)."""
        exam = self.get(exam_id)
        reader = StudentImporter(UserService(self.db))
        try:
            rows = reader.read_rows(filename, data)
        except ValidationError:
            raise
        except Exception:  # קובץ פגום, או קובץ אחר ששינו לו את הסיומת
            raise ValidationError("לא הצלחתי לקרוא את הקובץ. שמור אותו מחדש כ-CSV או XLSX")
        key = next((k for k in (rows[0] if rows else {})
                    if k in GRADE_KEYS or k.startswith(("grade/", "grade (", "ציון/", "ציון ("))), None)
        if key is None:
            raise ValidationError("לא מצאתי בקובץ עמודת ציון. קרא לעמודה ״ציון״ או grade")
        by_email = {u.email.lower(): u.id for u in Gradebook(self.db).students(exam.course_id)}
        changes: dict[int, str] = {}
        unknown = invalid = 0
        for row in rows:
            _, email = reader._extract(row)
            value = row.get(key)
            if value is None or not str(value).strip() or str(value).strip() == "-":
                continue  # ריק (או ״-״ של Moodle): אין ציון, לא נוגעים במה שכבר נשמר
            if not email:
                invalid += 1
                continue
            if email not in by_email:
                unknown += 1
                continue
            try:
                changes[by_email[email]] = fmt_grade(parse_grade(value))
            except ValidationError:
                invalid += 1
        return ImportReport(self.save_grades(exam_id, changes), unknown, invalid)

    def counts(self, course_id: int) -> dict[int, dict]:
        """לעמוד הקורס של המרצה: כמה ציונים הוזנו וכמה ערעורים פתוחים, לכל מבחן."""
        result = {e.id: {"graded": 0, "appeals": 0} for e in self.list(course_id)}
        for r in self.db.execute(_GRADE_SQL + " WHERE e.course_id = ?", (course_id,)):
            result[r["exam_id"]]["graded"] += 1
            result[r["exam_id"]]["appeals"] += r["appeal_status"] == "pending"
        return result

    # ---------- appeals ----------
    def pending_appeals(self, exam_id: int) -> list[ExamGrade]:
        rows = self.db.execute(_GRADE_SQL + " WHERE g.exam_id = ? AND g.appeal_status = 'pending' ORDER BY g.appeal_at",
                               (exam_id,))
        return [ExamGrade.from_row(r) for r in rows]

    def appeal(self, grade_id: int, student: User, text: str) -> ExamGrade:
        """ערעור אחד לכל ציון, רק אחרי שהציון פורסם."""
        g = self.get_grade(grade_id)
        if g.student_id != student.id:
            raise ValidationError("אפשר לערער רק על הציון שלך")
        if not g.published:
            raise ValidationError("אפשר לערער רק אחרי שהציון פורסם")
        if g.appeal_status:
            raise ValidationError("כבר הגשת ערעור על הציון הזה")
        text = (text or "").strip()
        if not text:
            raise ValidationError("כתוב על מה אתה מערער ולמה")
        self.db.execute("UPDATE exam_grades SET appeal_status = 'pending', appeal_text = ?, appeal_at = ? WHERE id = ?",
                        (text[:4000], self.clock(), grade_id))
        self.db.commit()
        return self.get_grade(grade_id)

    def resolve_appeal(self, grade_id: int, accept: bool, reply: str, new_grade: str = "") -> ExamGrade:
        """קבלה מחייבת ציון חדש (הקודם נשמר להשוואה). דחייה משאירה את הציון. תשובה לא חובה."""
        g = self.get_grade(grade_id)
        if g.appeal_status != "pending":
            raise ValidationError("אין ערעור פתוח על הציון הזה")
        reply = (reply or "").strip()[:2000]
        if accept:
            number = parse_grade(new_grade)
            if number is None:
                raise ValidationError("כדי לקבל את הערעור צריך לכתוב ציון חדש")
            self.db.execute("UPDATE exam_grades SET appeal_status = 'accepted', appeal_reply = ?, "
                            "original_grade = grade, grade = ? WHERE id = ?", (reply, number, grade_id))
        else:
            self.db.execute("UPDATE exam_grades SET appeal_status = 'rejected', appeal_reply = ? WHERE id = ?",
                            (reply, grade_id))
        self.db.commit()
        return self.get_grade(grade_id)


# ---------- the whole course ----------
@dataclass(frozen=True)
class Component:
    """רכיב אחד בציון הסופי: מטלה, מבחן או בוחן."""
    key: str        # 'a12' למטלה, 'e3' למבחן או בוחן
    id: int
    kind: str       # assignment | exam | quiz
    title: str
    weight: float
    published: bool

    @property
    def kind_label(self) -> str:
        return KINDS[self.kind]


@dataclass(frozen=True)
class Cell:
    component: Component
    grade: float | None
    exam_grade: ExamGrade | None = None


@dataclass(frozen=True)
class GradeRow:
    student: User | None
    cells: list[Cell]

    @property
    def covered(self) -> float:
        """כמה אחוזים מהציון הסופי כבר יש להם ציון."""
        return sum(c.component.weight for c in self.cells if c.grade is not None)

    @property
    def weighted(self) -> float | None:
        if not self.covered:
            return None
        total = sum(c.component.weight * c.grade for c in self.cells if c.grade is not None)
        return round(total / self.covered, 1)


class Gradebook:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def students(self, course_id: int) -> list[User]:
        return [User.from_row(r) for r in self.db.execute(
            "SELECT u.* FROM users u JOIN enrollments e ON e.user_id = u.id "
            "WHERE e.course_id = ? AND e.role = 'student' ORDER BY u.name", (course_id,))]

    def components(self, course_id: int) -> list[Component]:
        result = [Component(f"a{r['id']}", r["id"], "assignment", r["title"], r["weight"], bool(r["grades_published"]))
                  for r in self.db.execute("SELECT * FROM assignments WHERE course_id = ? ORDER BY due_at, id",
                                           (course_id,))]
        result += [Component(f"e{e.id}", e.id, e.kind, e.title, e.weight, e.published)
                   for e in ExamService(self.db).list(course_id)]
        return result

    def total_weight(self, course_id: int) -> float:
        return sum(c.weight for c in self.components(course_id))

    def set_weights(self, course_id: int, weights: dict[str, str]) -> float:
        """משקל לכל רכיב באחוזים, עד 100 ביחד. רכיב שלא נשלח נשאר כמו שהיה."""
        components = self.components(course_id)
        new = {c.key: parse_weight(weights[c.key]) if c.key in weights else c.weight for c in components}
        total = sum(new.values())
        if total > TOTAL_WEIGHT + 1e-9:
            raise ValidationError(f"המשקלים מגיעים ל-{fmt_grade(total)}%. אפשר לחלק עד 100%")
        for c in components:
            table = "assignments" if c.kind == "assignment" else "exams"
            self.db.execute(f"UPDATE {table} SET weight = ? WHERE id = ?", (new[c.key], c.id))
        self.db.commit()
        return total

    def _assignment_grades(self, course_id: int) -> dict[tuple[int, int], float]:
        """(מטלה, סטודנט) -> ציון, כולל 0 שהמרצה רשם למי שלא הגיש."""
        grades = {(r[0], r[1]): 0.0 for r in self.db.execute(
            "SELECT z.assignment_id, z.student_id FROM assignment_zeros z "
            "JOIN assignments a ON a.id = z.assignment_id WHERE a.course_id = ?", (course_id,))}
        grades.update({(r[0], r[1]): float(r[2]) for r in self.db.execute(
            "SELECT s.assignment_id, s.student_id, s.grade FROM submissions s "
            "JOIN assignments a ON a.id = s.assignment_id WHERE a.course_id = ? AND s.grade IS NOT NULL",
            (course_id,))})
        return grades

    def for_student(self, course_id: int, student_id: int) -> GradeRow:
        """מה שהסטודנט רואה: רק ציונים שפורסמו. ציון שלא פורסם לא נכנס גם לחישוב המשוקלל."""
        assignments = self._assignment_grades(course_id)
        exams = {r["exam_id"]: ExamGrade.from_row(r) for r in self.db.execute(
            _GRADE_SQL + " WHERE e.course_id = ? AND g.student_id = ? AND e.published = 1", (course_id, student_id))}
        cells = []
        for c in self.components(course_id):
            if c.kind == "assignment":
                cells.append(Cell(c, assignments.get((c.id, student_id)) if c.published else None))
            else:
                g = exams.get(c.id)
                cells.append(Cell(c, g.grade if g else None, g))
        return GradeRow(None, cells)

    def table(self, course_id: int) -> tuple[list[Component], list[GradeRow]]:
        """למרצה: כל הסטודנטים מול כל הרכיבים, כולל ציונים שעוד לא פורסמו."""
        components = self.components(course_id)
        grades: dict[tuple[str, int], float] = {
            (f"a{a}", s): g for (a, s), g in self._assignment_grades(course_id).items()}
        grades.update({(f"e{r['exam_id']}", r["student_id"]): r["grade"]
                       for r in self.db.execute(_GRADE_SQL + " WHERE e.course_id = ?", (course_id,))})
        rows = [GradeRow(u, [Cell(c, grades.get((c.key, u.id))) for c in components])
                for u in self.students(course_id)]
        return components, rows

    def to_csv(self, course_id: int) -> bytes:
        components, rows = self.table(course_id)
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["שם", "מייל"] + [f"{c.title} ({fmt_grade(c.weight)}%)" for c in components]
                   + ["ציון משוקלל", "אחוז מהציון הסופי"])
        for row in rows:
            w.writerow([row.student.name, row.student.email]
                       + ["" if c.grade is None else fmt_grade(c.grade) for c in row.cells]
                       + ["" if row.weighted is None else fmt_grade(row.weighted), f"{fmt_grade(row.covered)}%"])
        return out.getvalue().encode("utf-8-sig")
