"""צ׳אט הקורס: הודעות, תגובה עם ציטוט, אנונימיות ו-reactions."""
import sqlite3
import time

from ..errors import Forbidden, NotFound, ValidationError
from ..models import User

ANONYMOUS_NAME = "אנונימי"
DELETED_TEXT = "ההודעה נמחקה"
LOCKED_TEXT = "הצ׳אט מושתק. כרגע רק המרצה יכול לשלוח הודעות"
# ברירת המחדל לשורת התגובות, לפני שלמשתמש יש היסטוריה. אפשר להגיב גם בכל אימוג׳י אחר
REACTIONS = ("👍", "❤️", "😂", "👎", "😢", "🙏")


def is_single_emoji(value: str) -> bool:
    """אימוג׳י אחד בלבד: גם מורכב (גוון עור, דגל, משפחה עם ZWJ, מקש 1️⃣), אבל לא טקסט רגיל."""
    import unicodedata

    if not value or len(value) > 16 or any(ch.isspace() for ch in value):
        return False
    keycap = "⃣" in value
    has_symbol = False
    for ch in value:
        cat = unicodedata.category(ch)
        if cat == "So":
            has_symbol = True
        elif cat in ("Sk", "Mn", "Me", "Cf"):   # גוון עור, FE0F, מקש, ZWJ
            continue
        elif keycap and ch in "0123456789#*":
            has_symbol = True
        else:
            return False                         # אותיות, ספרות, פיסוק
    # לכל היותר אימוג׳י "בסיסי" אחד, חוץ מצירופי ZWJ ודגלים (שני Regional Indicators)
    base = [ch for ch in value if unicodedata.category(ch) == "So"]
    regional = all(0x1F1E6 <= ord(ch) <= 0x1F1FF for ch in base) and len(base) == 2
    if len(base) > 1 and "‍" not in value and not regional:
        return False
    return has_symbol
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
        if sender.role == "student" and self.is_locked(course_id):
            raise Forbidden(LOCKED_TEXT)
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

    def list_messages(self, course_id: int, viewer: User, since: float | None = None, limit: int = 300,
                      from_id: int | None = None) -> list[dict]:
        """הודעות כפי שהצופה רשאי לראות אותן. זהות השולח לא יוצאת מכאן אם אסור.

        ברירת המחדל: ההודעות האחרונות. since: רק מה שהשתנה (polling).
        from_id: כל ההודעות מהודעה מסוימת והלאה, כדי לקפוץ לתוצאת חיפוש ישנה.
        """
        sql = (
            "SELECT m.*, u.name AS sender_name, u.role AS sender_role FROM messages m "
            "JOIN users u ON u.id = m.sender_id WHERE m.course_id = ?"
        )
        args: list = [course_id]
        if since:
            sql += " AND m.updated_at > ?"
            args.append(since)
        if from_id is not None:
            sql += " AND m.id >= ? ORDER BY m.id ASC LIMIT ?"
            args += [from_id, limit]
            rows = self.db.execute(sql, args).fetchall()
        else:
            sql += " ORDER BY m.id DESC LIMIT ?"
            args.append(limit)
            rows = list(reversed(self.db.execute(sql, args).fetchall()))
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        reactions = self._reactions_for(ids, viewer)
        replies = self._reply_previews([r["reply_to_id"] for r in rows if r["reply_to_id"]], viewer)
        return [self._view(r, viewer, reactions.get(r["id"]), replies.get(r["reply_to_id"])) for r in rows]

    # ---------- pinned messages (course lecturer only; the route checks who) ----------
    MAX_PINS = 3

    def set_pinned(self, message_id: int, pinned: bool) -> int | None:
        """נועץ או מבטל נעיצה. כשכבר יש 3 נעוצות, הישנה ביותר יוצאת. מחזיר את מזהה ההודעה שיצאה, אם יצאה."""
        row = self.get_row(message_id)
        if row["deleted"]:
            raise ValidationError("אי אפשר לנעוץ הודעה שנמחקה")
        replaced = None
        if pinned and not row["pinned_at"]:
            current = self.db.execute(
                "SELECT id FROM messages WHERE course_id = ? AND pinned_at > 0 AND deleted = 0 ORDER BY pinned_at",
                (row["course_id"],),
            ).fetchall()
            if len(current) >= self.MAX_PINS:
                replaced = current[0]["id"]
                self.db.execute("UPDATE messages SET pinned_at = 0 WHERE id = ?", (replaced,))
                touch_message(self.db, replaced)
        self.db.execute("UPDATE messages SET pinned_at = ? WHERE id = ?", (time.time() if pinned else 0, message_id))
        touch_message(self.db, message_id)
        self.db.commit()
        return replaced

    def pinned(self, course_id: int, viewer: User) -> list[dict]:
        """הנעוצות מהחדשה לישנה, עם אותה הסתרה של שולח אנונימי כמו בצ׳אט."""
        rows = self.db.execute(
            "SELECT m.id, m.body, m.sender_id, m.is_anonymous, u.name AS sender_name, p.question "
            "FROM messages m JOIN users u ON u.id = m.sender_id LEFT JOIN polls p ON p.id = m.poll_id "
            "WHERE m.course_id = ? AND m.pinned_at > 0 AND m.deleted = 0 ORDER BY m.pinned_at DESC LIMIT ?",
            (course_id, self.MAX_PINS),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "text": ("סקר: " + r["question"]) if r["question"] and not r["body"] else (r["body"] or "")[:200],
                "mine": r["sender_id"] == viewer.id,
                "sender_name": SenderMask.name_for(viewer, r["sender_id"], r["sender_name"], bool(r["is_anonymous"])),
            }
            for r in rows
        ]

    # ---------- search ----------
    def search(self, course_id: int, viewer: User, query: str, limit: int = 50) -> list[dict]:
        """חיפוש בטקסט ההודעות ובשאלות הסקרים, מהחדש לישן.

        מחפשים רק בתוכן ולא בשם השולח, כדי שחיפוש לא יחשוף מי כתב הודעה אנונימית.
        התוצאות עוברות את אותה הסתרה של שולח כמו הצ׳אט עצמו.
        """
        query = (query or "").strip()
        if len(query) < 2:
            return []
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = self.db.execute(
            "SELECT m.id, m.body, m.created_at, m.sender_id, m.is_anonymous, u.name AS sender_name, p.question "
            "FROM messages m JOIN users u ON u.id = m.sender_id LEFT JOIN polls p ON p.id = m.poll_id "
            "WHERE m.course_id = ? AND m.deleted = 0 "
            "AND (m.body LIKE ? ESCAPE '\\' OR p.question LIKE ? ESCAPE '\\') "
            "ORDER BY m.id DESC LIMIT ?",
            (course_id, pattern, pattern, limit),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "text": r["body"] or r["question"] or "",
                "is_poll": bool(r["question"]) and not r["body"],
                "created_at": r["created_at"],
                "mine": r["sender_id"] == viewer.id,
                "sender_name": SenderMask.name_for(viewer, r["sender_id"], r["sender_name"], bool(r["is_anonymous"])),
            }
            for r in rows
        ]

    # ---------- mute: only the lecturer and the admin may post ----------
    def is_locked(self, course_id: int) -> bool:
        row = self.db.execute("SELECT chat_locked FROM courses WHERE id = ?", (course_id,)).fetchone()
        return bool(row and row["chat_locked"])

    def set_locked(self, course_id: int, locked: bool) -> None:
        """ההרשאה (מרצה הקורס או מנהל) נבדקת ב-route. סטודנטים עדיין מגיבים, מצביעים ומוחקים הודעות שלהם."""
        self.db.execute("UPDATE courses SET chat_locked = ? WHERE id = ?", (1 if locked else 0, course_id))
        self.db.commit()

    def delete(self, message_id: int, user: User) -> None:
        """השולח מוחק הודעה שלו. מנהל המערכת יכול למחוק כל הודעה (טיפול בהטרדות).

        ההודעה לא נעלמת אלא מוחלפת ב״ההודעה נמחקה״, כמו בוואטסאפ, כדי שתגובות שציטטו אותה יישארו מובנות.
        """
        row = self.get_row(message_id)
        if row["sender_id"] != user.id and not user.is_admin:
            raise Forbidden("אפשר למחוק רק הודעות שלך")
        if row["deleted"]:
            return
        self.db.execute("UPDATE messages SET deleted = 1, body = '', pinned_at = 0 WHERE id = ?", (message_id,))
        self.db.execute("DELETE FROM message_reactions WHERE message_id = ?", (message_id,))
        touch_message(self.db, message_id)
        self.db.commit()

    # ---------- helpers ----------
    def _view(self, r, viewer: User, reactions, reply) -> dict:
        anonymous = bool(r["is_anonymous"])
        reveal = SenderMask.reveals_identity(viewer, anonymous)
        deleted = bool(r["deleted"])
        view = {
            "id": r["id"],
            "body": "" if deleted else r["body"],
            "deleted": deleted,
            "created_at": r["created_at"],
            "mine": r["sender_id"] == viewer.id,
            "anonymous": anonymous,
            "sender_name": SenderMask.name_for(viewer, r["sender_id"], r["sender_name"], anonymous),
            "sender_is_lecturer": reveal and r["sender_role"] == "lecturer",
            "reply_to": None if deleted else reply,
            "reactions": {"summary": [], "mine": None} if deleted else (reactions or {"summary": [], "mine": None}),
            "poll": None,
            "can_delete": not deleted and (r["sender_id"] == viewer.id or viewer.is_admin),
            "pinned": bool(r["pinned_at"]) and not deleted,
        }
        if reveal:
            view["sender_id"] = r["sender_id"]
        if r["poll_id"] and self.poll_reader and not deleted:
            view["poll"] = self.poll_reader.results(r["poll_id"], viewer)
        return view

    def _reply_previews(self, ids: list[int], viewer: User) -> dict:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = self.db.execute(
            f"SELECT m.id, m.body, m.sender_id, m.is_anonymous, m.poll_id, m.deleted, u.name AS sender_name "
            f"FROM messages m JOIN users u ON u.id = m.sender_id WHERE m.id IN ({marks})",
            ids,
        )
        out = {}
        for r in rows:
            if r["deleted"]:
                body = DELETED_TEXT
            else:
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
        # הנפוץ ביותר ראשון. בתיקו, הקבועים לפי הסדר שלהם, ואחריהם השאר
        order = {e: i for i, e in enumerate(REACTIONS)}

        def rank(item):
            emoji, count = item
            return (-count, order.get(emoji, len(order)), emoji)

        return {
            mid: {"summary": [[e, c] for e, c in sorted(v["counts"].items(), key=rank)], "mine": v["mine"]}
            for mid, v in out.items()
        }


class ReactionService:
    """reaction אחד לכל משתמש בכל הודעה: הוספה, החלפה או הסרה."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def toggle(self, message_id: int, user: User, emoji: str) -> str | None:
        emoji = (emoji or "").strip()
        if not is_single_emoji(emoji):
            raise ValidationError("אפשר להגיב רק עם אימוג׳י אחד")
        msg = self.db.execute("SELECT deleted FROM messages WHERE id = ?", (message_id,)).fetchone()
        if msg is None or msg["deleted"]:
            raise ValidationError("ההודעה נמחקה")
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


class ReadReceiptService:
    """וי כחול: מי קרא איזו הודעה.

    ״קרא״ פירושו שהצ׳אט היה פתוח על המסך של המשתמש אחרי שההודעה הגיעה.
    השולח רואה כמה קראו, ובפרטי ההודעה גם מי ומתי. בקבוצה, וי כחול מופיע רק כשכל חברי הקורס קראו.
    """

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def mark_read(self, course_id: int, user: User, up_to_id: int) -> int:
        """מסמן כנקראו את כל ההודעות בקורס עד up_to_id, חוץ מאלה של המשתמש עצמו."""
        cur = self.db.execute(
            "INSERT OR IGNORE INTO message_reads (message_id, user_id, read_at) "
            "SELECT id, ?, ? FROM messages WHERE course_id = ? AND id <= ? AND sender_id != ? AND deleted = 0",
            (user.id, time.time(), course_id, up_to_id, user.id),
        )
        self.db.commit()
        return cur.rowcount

    def audience(self, course_id: int, sender_id: int) -> int:
        """כמה חברי קורס יכולים לקרוא את ההודעה (כולם חוץ מהשולח)."""
        return self.db.execute(
            "SELECT COUNT(*) FROM enrollments WHERE course_id = ? AND user_id != ?", (course_id, sender_id)
        ).fetchone()[0]

    def receipts_for(self, course_id: int, viewer: User, limit: int = 100) -> dict:
        """לכל אחת מההודעות האחרונות של הצופה: כמה חברי קורס קראו אותה."""
        rows = self.db.execute(
            "SELECT m.id, COUNT(e.user_id) AS readers FROM messages m "
            "LEFT JOIN message_reads r ON r.message_id = m.id "
            "LEFT JOIN enrollments e ON e.user_id = r.user_id AND e.course_id = m.course_id "
            "WHERE m.course_id = ? AND m.sender_id = ? AND m.deleted = 0 "
            "GROUP BY m.id ORDER BY m.id DESC LIMIT ?",
            (course_id, viewer.id, limit),
        )
        return {
            "audience": self.audience(course_id, viewer.id),
            "read": {r["id"]: r["readers"] for r in rows},
        }

    def info(self, message_id: int, viewer: User) -> dict:
        """פרטי ההודעה: רק השולח רואה מי קרא."""
        row = self.db.execute("SELECT course_id, sender_id, deleted FROM messages WHERE id = ?", (message_id,)).fetchone()
        if row is None or row["deleted"]:
            raise NotFound("ההודעה לא נמצאה")
        if row["sender_id"] != viewer.id:
            raise Forbidden("רק מי ששלח את ההודעה רואה מי קרא אותה")
        readers = self.db.execute(
            "SELECT u.name, r.read_at FROM message_reads r JOIN users u ON u.id = r.user_id "
            "JOIN enrollments e ON e.user_id = r.user_id AND e.course_id = ? "
            "WHERE r.message_id = ? ORDER BY r.read_at DESC",
            (row["course_id"], message_id),
        ).fetchall()
        audience = self.audience(row["course_id"], viewer.id)
        return {
            "read_by": [{"name": r["name"], "read_at": r["read_at"]} for r in readers],
            "unread": max(0, audience - len(readers)),
            "audience": audience,
        }
