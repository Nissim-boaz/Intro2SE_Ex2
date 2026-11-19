"""אירועי נוכחות (שיעורים), דגימות, רישום סטודנטים ודוח."""
import csv
import io
import sqlite3
from dataclasses import dataclass, field

from ..errors import NotFound, ServiceError, ValidationError
from ..models import User
from .network import CampusNetworkPolicy
from .tokens import AudioTokenService, QrTokenService, TokenClock

MAX_SAMPLES = 5

REASON_LABELS = {
    "no_audio": "בלי אות קולי",
    "audio_mismatch": "האות הקולי לא תאם",
    "off_campus": "מחוץ לרשת הקמפוס",
}


class SampleLimitReached(ServiceError):
    status = 409


class SampleClosed(ServiceError):
    status = 410


class AlreadyCheckedIn(ServiceError):
    status = 409


@dataclass(frozen=True)
class Lesson:
    id: int
    course_id: int
    number: int


@dataclass(frozen=True)
class Sample:
    id: int
    lesson_id: int
    seq: int
    opened_at: float
    closes_at: float
    course_id: int
    lesson_number: int

    def is_open(self, at: float) -> bool:
        return self.opened_at <= at < self.closes_at

    def seconds_left(self, at: float) -> int:
        return max(0, int(round(self.closes_at - at)))


@dataclass(frozen=True)
class Record:
    id: int
    sample_id: int
    student_id: int
    at: float
    ip: str
    method: str
    status: str
    reasons: list[str] = field(default_factory=list)

    @property
    def counts(self) -> bool:
        return self.status in ("ok", "approved")

    @property
    def reason_labels(self) -> list[str]:
        return [REASON_LABELS.get(r, r) for r in self.reasons]

    @classmethod
    def from_row(cls, r) -> "Record":
        reasons = [x for x in r["reasons"].split(",") if x]
        return cls(r["id"], r["sample_id"], r["student_id"], r["at"], r["ip"], r["method"], r["status"], reasons)


class AttendanceService:
    def __init__(self, db: sqlite3.Connection, qr: QrTokenService, audio: AudioTokenService,
                 network: CampusNetworkPolicy, clock: TokenClock):
        self.db = db
        self.qr = qr
        self.audio = audio
        self.network = network
        self.clock = clock

    # ---------- lessons & samples ----------
    def lessons(self, course_id: int) -> list[Lesson]:
        rows = self.db.execute(
            "SELECT id, course_id, number FROM lessons WHERE course_id = ? ORDER BY number DESC", (course_id,)
        )
        return [Lesson(r["id"], r["course_id"], r["number"]) for r in rows]

    def get_lesson(self, lesson_id: int) -> Lesson:
        r = self.db.execute("SELECT id, course_id, number FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
        if r is None:
            raise NotFound("השיעור לא נמצא")
        return Lesson(r["id"], r["course_id"], r["number"])

    def _lesson_for(self, course_id: int, number: int) -> int:
        self.db.execute("INSERT OR IGNORE INTO lessons (course_id, number) VALUES (?, ?)", (course_id, number))
        return self.db.execute(
            "SELECT id FROM lessons WHERE course_id = ? AND number = ?", (course_id, number)
        ).fetchone()["id"]

    _SAMPLE_SQL = (
        "SELECT s.*, l.course_id, l.number AS lesson_number FROM attendance_samples s "
        "JOIN lessons l ON l.id = s.lesson_id "
    )

    @staticmethod
    def _sample(r) -> Sample:
        return Sample(r["id"], r["lesson_id"], r["seq"], r["opened_at"], r["closes_at"], r["course_id"], r["lesson_number"])

    def get_sample(self, sample_id: int) -> Sample:
        r = self.db.execute(self._SAMPLE_SQL + "WHERE s.id = ?", (sample_id,)).fetchone()
        if r is None:
            raise NotFound("הדגימה לא נמצאה")
        return self._sample(r)

    def samples(self, lesson_id: int) -> list[Sample]:
        rows = self.db.execute(self._SAMPLE_SQL + "WHERE s.lesson_id = ? ORDER BY s.seq", (lesson_id,))
        return [self._sample(r) for r in rows]

    def open_sample_for(self, course_id: int) -> Sample | None:
        now = self.clock.now()
        r = self.db.execute(
            self._SAMPLE_SQL + "WHERE l.course_id = ? AND s.opened_at <= ? AND s.closes_at > ? "
            "ORDER BY s.opened_at DESC LIMIT 1",
            (course_id, now, now),
        ).fetchone()
        return self._sample(r) if r else None

    def open_sample(self, course_id: int, lesson_number: int, duration_seconds: int, opened_by: User) -> Sample:
        """פותח דגימה. אם אין עדיין אירוע עם המספר הזה, הוא נוצר עכשיו."""
        if lesson_number < 1:
            raise ValidationError("מספר השיעור צריך להיות 1 ומעלה")
        if not 15 <= duration_seconds <= 15 * 60:
            raise ValidationError("משך הדגימה צריך להיות בין 15 שניות ל-15 דקות")
        if self.open_sample_for(course_id):
            raise ValidationError("כבר יש דגימה פתוחה בקורס. סגור אותה לפני שפותחים חדשה")

        lesson_id = self._lesson_for(course_id, lesson_number)
        count = self.db.execute(
            "SELECT COUNT(*) FROM attendance_samples WHERE lesson_id = ?", (lesson_id,)
        ).fetchone()[0]
        if count >= MAX_SAMPLES:
            self.db.rollback()
            raise SampleLimitReached(f"בשיעור {lesson_number} כבר יש {MAX_SAMPLES} דגימות. אי אפשר לפתוח עוד")
        now = self.clock.now()
        try:
            cur = self.db.execute(
                "INSERT INTO attendance_samples (lesson_id, seq, opened_at, closes_at, opened_by) VALUES (?, ?, ?, ?, ?)",
                (lesson_id, count + 1, now, now + duration_seconds, opened_by.id),
            )
        except sqlite3.IntegrityError:  # שתי פתיחות באותו רגע. ה-UNIQUE וה-CHECK מגנים עלינו
            self.db.rollback()
            raise SampleLimitReached("הדגימה כבר נפתחה. רענן את העמוד")
        self.db.commit()
        return self.get_sample(cur.lastrowid)

    def close_sample(self, sample_id: int) -> None:
        sample = self.get_sample(sample_id)
        now = self.clock.now()
        if sample.closes_at > now:
            self.db.execute("UPDATE attendance_samples SET closes_at = ? WHERE id = ?", (now, sample_id))
            self.db.commit()

    def count(self, sample_id: int) -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM attendance_records WHERE sample_id = ?", (sample_id,)
        ).fetchone()[0]

    # ---------- student check-in ----------
    def scan(self, sample_id: int, qr_token: str) -> Sample:
        """שלב ראשון: הסטודנט סרק את ה-QR. בודקים שהדגימה פתוחה ושהטוקן טרי."""
        sample = self.get_sample(sample_id)
        now = self.clock.now()
        if not sample.is_open(now):
            raise SampleClosed("הדגימה כבר נסגרה")
        if not self.qr.verify(sample_id, qr_token, now):
            raise ValidationError("הקוד פג. סרוק שוב את המסך")
        return sample

    def check_in(self, sample_id: int, student: User, ip: str, audio_code=None) -> Record:
        """שלב שני: רישום. בלי אות קולי תקין או מחוץ לקמפוס הרשומה נשמרת כחשודה."""
        reasons = []
        if audio_code is None:
            reasons.append("no_audio")
        elif not self.audio.verify(sample_id, audio_code, self.clock.now()):
            reasons.append("audio_mismatch")
        if not self.network.is_campus(ip):
            reasons.append("off_campus")
        method = "qr_only" if {"no_audio", "audio_mismatch"} & set(reasons) else "qr_audio"
        status = "suspicious" if reasons else "ok"
        try:
            cur = self.db.execute(
                "INSERT INTO attendance_records (sample_id, student_id, at, ip, method, status, reasons) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sample_id, student.id, self.clock.now(), ip, method, status, ",".join(reasons)),
            )
        except sqlite3.IntegrityError:
            raise AlreadyCheckedIn("כבר נרשמת לדגימה הזו")
        self.db.commit()
        return self.get_record(cur.lastrowid)

    def get_record(self, record_id: int) -> Record:
        r = self.db.execute("SELECT * FROM attendance_records WHERE id = ?", (record_id,)).fetchone()
        if r is None:
            raise NotFound("הרשומה לא נמצאה")
        return Record.from_row(r)

    def record_for(self, sample_id: int, student_id: int) -> Record | None:
        r = self.db.execute(
            "SELECT * FROM attendance_records WHERE sample_id = ? AND student_id = ?", (sample_id, student_id)
        ).fetchone()
        return Record.from_row(r) if r else None

    def set_status(self, record_id: int, status: str) -> Record:
        if status not in ("approved", "rejected"):
            raise ValidationError("סטטוס לא מוכר")
        self.get_record(record_id)
        self.db.execute("UPDATE attendance_records SET status = ? WHERE id = ?", (status, record_id))
        self.db.commit()
        return self.get_record(record_id)

    def records(self, lesson_id: int) -> list[Record]:
        rows = self.db.execute(
            "SELECT r.* FROM attendance_records r JOIN attendance_samples s ON s.id = r.sample_id "
            "WHERE s.lesson_id = ?",
            (lesson_id,),
        )
        return [Record.from_row(r) for r in rows]


@dataclass
class ReportRow:
    student: User
    cells: list[Record | None]
    percent: int


class AttendanceReport:
    """מטריצה של סטודנט מול דגימות בשיעור אחד, ואחוז נוכחות."""

    STATUS_TEXT = {"ok": "נוכח", "approved": "אושר", "suspicious": "ממתין לאישור", "rejected": "נדחה"}

    def __init__(self, attendance: AttendanceService):
        self.attendance = attendance

    def build(self, lesson_id: int, students: list[User]) -> tuple[list[Sample], list[ReportRow]]:
        samples = self.attendance.samples(lesson_id)
        by_key = {(r.sample_id, r.student_id): r for r in self.attendance.records(lesson_id)}
        rows = []
        for st in students:
            cells = [by_key.get((s.id, st.id)) for s in samples]
            present = sum(1 for c in cells if c and c.counts)
            percent = round(100 * present / len(samples)) if samples else 0
            rows.append(ReportRow(st, cells, percent))
        return samples, rows

    def to_csv(self, lesson: Lesson, students: list[User]) -> bytes:
        samples, rows = self.build(lesson.id, students)
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["שם", "מייל"] + [f"דגימה {s.seq}" for s in samples] + ["אחוז נוכחות"])
        for row in rows:
            w.writerow(
                [row.student.name, row.student.email]
                + [self.STATUS_TEXT[c.status] if c else "חסר" for c in row.cells]
                + [f"{row.percent}%"]
            )
        return out.getvalue().encode("utf-8-sig")
