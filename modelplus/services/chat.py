"""צ׳אט הקורס: הודעות, תגובה עם ציטוט, אנונימיות ו-reactions."""
import sqlite3
import time

from ..errors import NotFound, ValidationError
from ..models import User

ANONYMOUS_NAME = "אנונימי"
REACTIONS = ("👍", "❤️", "😂", "👎", "😢", "🙏")
MAX_LENGTH = 2000


def touch_message(db: sqlite3.Connection, message_id: int) -> None:
    """מסמן שההודעה השתנתה, כדי שה-polling של כולם יקבל אותה שוב."""
    db.execute("UPDATE messages SET updated_at = ? WHERE id = ?", (time.time(), message_id))


class SenderMask:
    """מחליט מה צופה מסוים רואה כשולח. רק אדמין רואה מי שלח הודעה אנונימית."""

    @staticmethod
    def name_for(viewer: User, sender_id: int, sender_name: str, anonymous: bool) -> str:
        if not anonymous:
            return sender_name
        if viewer.is_admin:
            return f"{ANONYMOUS_NAME} ({sender_name})"
        return ANONYMOUS_NAME

    @staticmethod
    def reveals_identity(viewer: User, anonymous: bool) -> bool:
        return viewer.is_admin or not anonymous


class ChatService:
    def __init__(self, db: sqlite3.Connection, poll_reader=None):
        self.db = db
        self.poll_reader = poll_reader  # PollService, כדי לצרף סקרים להודעות

    def get_row(self, message_id: int):
        row = self.db.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        if row is None:
            raise NotFound("ההודעה לא נמצאה")
        return row

    def send(self, course_id: int, sender: User, body: str, reply_to_id: int | None = None,
             anonymous: bool = False, poll_id: int | None = None) -> int:
        body = (body or "").strip()
        if not body and poll_id is None:
            raise ValidationError("אי אפשר לשלוח הודעה ריקה")
        if len(body) > MAX_LENGTH:
            raise ValidationError(f"ההודעה ארוכה מדי. אפשר עד {MAX_LENGTH} תווים")
        if reply_to_id is not None:
            parent = self.get_row(reply_to_id)
            if parent["course_id"] != course_id:
                raise ValidationError("אפשר להגיב רק להודעה מהקורס הזה")
        now = time.time()
        cur = self.db.execute(
            "INSERT INTO messages (course_id, sender_id, body, reply_to_id, is_anonymous, poll_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (course_id, sender.id, body, reply_to_id, 1 if anonymous else 0, poll_id, now, now),
        )
        self.db.commit()
        return cur.lastrowid

    def list_messages(self, course_id: int, viewer: User, since: float | None = None, limit: int = 300) -> list[dict]:
        """הודעות כפי שהצופה רשאי לראות אותן. זהות השולח לא יוצאת מכאן אם אסור."""
        sql = (
            "SELECT m.*, u.name AS sender_name, u.role AS sender_role FROM messages m "
            "JOIN users u ON u.id = m.sender_id WHERE m.course_id = ?"
        )
        args: list = [course_id]
        if since:
            sql += " AND m.updated_at > ?"
            args.append(since)
        sql += " ORDER BY m.id DESC LIMIT ?"
        args.append(limit)
        rows = list(reversed(self.db.execute(sql, args).fetchall()))
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        reactions = self._reactions_for(ids, viewer)
        replies = self._reply_previews([r["reply_to_id"] for r in rows if r["reply_to_id"]], viewer)
        return [self._view(r, viewer, reactions.get(r["id"]), replies.get(r["reply_to_id"])) for r in rows]

    # ---------- helpers ----------
    def _view(self, r, viewer: User, reactions, reply) -> dict:
        anonymous = bool(r["is_anonymous"])
        reveal = SenderMask.reveals_identity(viewer, anonymous)
        view = {
            "id": r["id"],
            "body": r["body"],
            "created_at": r["created_at"],
            "mine": r["sender_id"] == viewer.id,
            "anonymous": anonymous,
            "sender_name": SenderMask.name_for(viewer, r["sender_id"], r["sender_name"], anonymous),
            "sender_is_lecturer": reveal and r["sender_role"] == "lecturer",
            "reply_to": reply,
            "reactions": reactions or {"summary": [], "mine": None},
            "poll": None,
        }
        if reveal:
            view["sender_id"] = r["sender_id"]
        if r["poll_id"] and self.poll_reader:
            view["poll"] = self.poll_reader.results(r["poll_id"], viewer)
        return view

    def _reply_previews(self, ids: list[int], viewer: User) -> dict:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = self.db.execute(
            f"SELECT m.id, m.body, m.sender_id, m.is_anonymous, m.poll_id, u.name AS sender_name "
            f"FROM messages m JOIN users u ON u.id = m.sender_id WHERE m.id IN ({marks})",
            ids,
        )
        out = {}
        for r in rows:
            body = r["body"] or ("סקר" if r["poll_id"] else "")
            out[r["id"]] = {
                "id": r["id"],
                "sender_name": SenderMask.name_for(viewer, r["sender_id"], r["sender_name"], bool(r["is_anonymous"])),
                "body": body[:140],
            }
        return out

    def _reactions_for(self, ids: list[int], viewer: User) -> dict:
        marks = ",".join("?" * len(ids))
        rows = self.db.execute(
            f"SELECT message_id, user_id, emoji FROM message_reactions WHERE message_id IN ({marks})", ids
        )
        out: dict[int, dict] = {}
        for r in rows:
            entry = out.setdefault(r["message_id"], {"counts": {}, "mine": None})
            entry["counts"][r["emoji"]] = entry["counts"].get(r["emoji"], 0) + 1
            if r["user_id"] == viewer.id:
                entry["mine"] = r["emoji"]
        return {
            mid: {"summary": [[e, e_count] for e in REACTIONS if (e_count := v["counts"].get(e))], "mine": v["mine"]}
            for mid, v in out.items()
        }


class ReactionService:
    """reaction אחד לכל משתמש בכל הודעה: הוספה, החלפה או הסרה."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def toggle(self, message_id: int, user: User, emoji: str) -> str | None:
        if emoji not in REACTIONS:
            raise ValidationError("אפשר להגיב רק עם אחד מששת האימוג׳ים")
        current = self.db.execute(
            "SELECT emoji FROM message_reactions WHERE message_id = ? AND user_id = ?", (message_id, user.id)
        ).fetchone()
        if current and current["emoji"] == emoji:
            self.db.execute("DELETE FROM message_reactions WHERE message_id = ? AND user_id = ?", (message_id, user.id))
            result = None
        else:
            self.db.execute(
                "INSERT INTO message_reactions (message_id, user_id, emoji) VALUES (?, ?, ?) "
                "ON CONFLICT (message_id, user_id) DO UPDATE SET emoji = excluded.emoji",
                (message_id, user.id, emoji),
            )
            result = emoji
        touch_message(self.db, message_id)
        self.db.commit()
        return result

    def who(self, message_id: int) -> list[dict]:
        rows = self.db.execute(
            "SELECT u.name, r.emoji FROM message_reactions r JOIN users u ON u.id = r.user_id "
            "WHERE r.message_id = ? ORDER BY u.name",
            (message_id,),
        )
        return [{"name": r["name"], "emoji": r["emoji"]} for r in rows]
