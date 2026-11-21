"""סקרים בצ׳אט: המרצה יוצר, כל סטודנט מצביע פעם אחת ויכול לשנות.

המרצה בוחר ביצירה אם הסקר אנונימי (ברירת המחדל): בסקר אנונימי כולם רואים רק ספירות.
בסקר גלוי כולם רואים גם מי הצביע לכל תשובה, כמו בוואטסאפ.
"""
import sqlite3

from ..errors import NotFound, ValidationError
from ..models import User
from .chat import ChatService, touch_message

MAX_OPTIONS = 6


class PollService:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def create(self, course_id: int, creator: User, question: str, options: list[str], anonymous: bool = True) -> int:
        """יוצר סקר ושולח אותו כהודעה בצ׳אט. מחזיר את מזהה ההודעה."""
        question = (question or "").strip()
        options = [o.strip() for o in options if o and o.strip()]
        if not question:
            raise ValidationError("כתוב שאלה לסקר")
        if len(options) < 2:
            raise ValidationError("צריך לפחות שתי תשובות")
        if len(options) > MAX_OPTIONS:
            raise ValidationError(f"אפשר עד {MAX_OPTIONS} תשובות")
        if len(set(options)) != len(options):
            raise ValidationError("יש שתי תשובות זהות")
        cur = self.db.execute(
            "INSERT INTO polls (course_id, question, anonymous, created_by) VALUES (?, ?, ?, ?)",
            (course_id, question, 1 if anonymous else 0, creator.id),
        )
        poll_id = cur.lastrowid
        self.db.executemany(
            "INSERT INTO poll_options (poll_id, text, position) VALUES (?, ?, ?)",
            [(poll_id, text, i) for i, text in enumerate(options)],
        )
        self.db.commit()
        return ChatService(self.db).send(course_id, creator, "", poll_id=poll_id)

    def get(self, poll_id: int):
        row = self.db.execute("SELECT * FROM polls WHERE id = ?", (poll_id,)).fetchone()
        if row is None:
            raise NotFound("הסקר לא נמצא")
        return row

    def vote(self, poll_id: int, user: User, option_id: int) -> None:
        """הצבעה אחת לכל משתמש. הצבעה חוזרת מחליפה את הקודמת. כל חבר בקורס מצביע, חוץ ממי שיצר את הסקר."""
        if self.get(poll_id)["created_by"] == user.id:
            raise ValidationError("מי שיצר את הסקר לא מצביע בו")
        option = self.db.execute(
            "SELECT id FROM poll_options WHERE id = ? AND poll_id = ?", (option_id, poll_id)
        ).fetchone()
        if option is None:
            raise ValidationError("התשובה לא שייכת לסקר הזה")
        self.db.execute(
            "INSERT INTO poll_votes (poll_id, user_id, option_id) VALUES (?, ?, ?) "
            "ON CONFLICT (poll_id, user_id) DO UPDATE SET option_id = excluded.option_id",
            (poll_id, user.id, option_id),
        )
        self._touch(poll_id)
        self.db.commit()

    def results(self, poll_id: int, viewer: User) -> dict:
        """בסקר אנונימי: רק ספירות, ואף אחד (גם לא המרצה) לא מקבל מי הצביע למה.
        בסקר גלוי: גם שמות המצביעים לכל תשובה."""
        poll = self.get(poll_id)
        anonymous = bool(poll["anonymous"])
        options = self.db.execute(
            "SELECT o.id, o.text, COUNT(v.user_id) AS votes FROM poll_options o "
            "LEFT JOIN poll_votes v ON v.option_id = o.id WHERE o.poll_id = ? "
            "GROUP BY o.id ORDER BY o.position",
            (poll_id,),
        ).fetchall()
        mine = self.db.execute(
            "SELECT option_id FROM poll_votes WHERE poll_id = ? AND user_id = ?", (poll_id, viewer.id)
        ).fetchone()
        result = {
            "id": poll_id,
            "question": poll["question"],
            "anonymous": anonymous,
            "options": [{"id": o["id"], "text": o["text"], "votes": o["votes"]} for o in options],
            "total": sum(o["votes"] for o in options),
            "my_vote": mine["option_id"] if mine else None,
            "can_vote": poll["created_by"] != viewer.id,
        }
        if not anonymous:
            voters: dict[int, list[str]] = {}
            for v in self.db.execute(
                "SELECT v.option_id, u.name FROM poll_votes v JOIN users u ON u.id = v.user_id "
                "WHERE v.poll_id = ? ORDER BY u.name",
                (poll_id,),
            ):
                voters.setdefault(v["option_id"], []).append(v["name"])
            for opt in result["options"]:
                opt["voters"] = voters.get(opt["id"], [])
        return result

    def _touch(self, poll_id: int) -> None:
        row = self.db.execute("SELECT id FROM messages WHERE poll_id = ?", (poll_id,)).fetchone()
        if row:
            touch_message(self.db, row["id"])
