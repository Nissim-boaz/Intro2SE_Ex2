"""פניות למנהלי המערכת: סטודנט או מרצה פותח פנייה, ומנהל עונה ומעדכן סטטוס.

פנייה שנסגרה (טופלה או נדחתה) נמחקת 7 ימים אחרי הסגירה.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Callable

from ..errors import Forbidden, NotFound, ValidationError
from ..models import User

STATUSES = {
    "new": "חדשה",
    "in_progress": "בטיפול",
    "resolved": "טופלה",
    "rejected": "נדחתה",
}
CLOSED = ("resolved", "rejected")
KEEP_CLOSED_DAYS = 7
TEAM_NAME = "מנהל המערכת"  # מה שהפונה רואה כשמנהל עונה בלי שם
MAX_BODY = 4000


@dataclass(frozen=True)
class SupportRequest:
    id: int
    user_id: int
    user_name: str
    user_role: str
    subject: str
    status: str
    created_at: float
    updated_at: float
    closed_at: float
    requester_unseen: bool

    @property
    def status_label(self) -> str:
        return STATUSES[self.status]

    @property
    def closed(self) -> bool:
        return self.status in CLOSED

    @property
    def deletes_at(self) -> float:
        return self.closed_at + KEEP_CLOSED_DAYS * 86400 if self.closed else 0

    @classmethod
    def from_row(cls, r) -> "SupportRequest":
        return cls(r["id"], r["user_id"], r["user_name"], r["user_role"], r["subject"], r["status"],
                   r["created_at"], r["updated_at"], r["closed_at"], bool(r["requester_unseen"]))


@dataclass(frozen=True)
class RequestEntry:
    """שורה בשרשור: הודעה, או שינוי סטטוס (status לא ריק).

    author_name הוא מה שהצופה רשאי לראות. כשמנהל ענה בלי שם, הפונה מקבל ״מנהל המערכת״,
    ומנהלים רואים את השם האמיתי ואת as_team.
    """
    id: int
    author_name: str
    author_is_admin: bool
    mine: bool
    body: str
    status: str
    created_at: float
    as_team: bool = False

    @property
    def status_label(self) -> str:
        return STATUSES.get(self.status, "")


_SELECT = ("SELECT r.*, u.name AS user_name, u.role AS user_role FROM requests r "
           "JOIN users u ON u.id = r.user_id")


class RequestService:
    def __init__(self, db: sqlite3.Connection, clock: Callable[[], float] = time.time):
        self.db = db
        self.clock = clock

    # ---------- opening and reading ----------
    def create(self, user: User, subject: str, body: str) -> SupportRequest:
        if user.is_admin:
            raise ValidationError("מנהלי מערכת לא פותחים פניות. הן מגיעות אליהם")
        subject = (subject or "").strip()
        if not subject:
            raise ValidationError("כתוב נושא לפנייה")
        body = self._body(body)
        now = self.clock()
        cur = self.db.execute(
            "INSERT INTO requests (user_id, subject, status, created_at, updated_at) VALUES (?, ?, 'new', ?, ?)",
            (user.id, subject[:200], now, now),
        )
        self._add_entry(cur.lastrowid, user.id, body, "", now)
        self.db.commit()
        return self.get(cur.lastrowid)

    def get(self, request_id: int) -> SupportRequest:
        self.purge()
        row = self.db.execute(_SELECT + " WHERE r.id = ?", (request_id,)).fetchone()
        if row is None:
            raise NotFound("הפנייה לא נמצאה. ייתכן שהיא נסגרה לפני יותר מ-7 ימים ונמחקה")
        return SupportRequest.from_row(row)

    def get_visible(self, request_id: int, viewer: User) -> SupportRequest:
        """רק מי שפתח את הפנייה ומנהלי המערכת רואים אותה."""
        req = self.get(request_id)
        if not viewer.is_admin and req.user_id != viewer.id:
            raise Forbidden("זו לא הפנייה שלך")
        return req

    def mine(self, user: User) -> list[SupportRequest]:
        self.purge()
        rows = self.db.execute(_SELECT + " WHERE r.user_id = ? ORDER BY r.updated_at DESC", (user.id,))
        return [SupportRequest.from_row(r) for r in rows]

    def all(self, status: str | None = None) -> list[SupportRequest]:
        """לתיבת הפניות של המנהלים: פתוחות קודם (חדשות לפני בטיפול), ואז סגורות. בתוך כל קבוצה, העדכנית למעלה."""
        self.purge()
        sql, args = _SELECT, ()
        if status == "open":
            sql += " WHERE r.status NOT IN ('resolved', 'rejected')"
        elif status in STATUSES:
            sql += " WHERE r.status = ?"
            args = (status,)
        sql += (" ORDER BY CASE r.status WHEN 'new' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END,"
                " r.updated_at DESC")
        return [SupportRequest.from_row(r) for r in self.db.execute(sql, args)]

    def thread(self, request_id: int, viewer: User) -> list[RequestEntry]:
        rows = self.db.execute(
            "SELECT m.*, u.name AS author_name, u.role AS author_role FROM request_messages m "
            "JOIN users u ON u.id = m.author_id WHERE m.request_id = ? ORDER BY m.id", (request_id,))
        entries = []
        for r in rows:
            as_team = bool(r["as_team"])
            # השם מוחלף כאן, בשרת, כך שהוא לא מגיע לדפדפן של הפונה בשום צורה
            name = TEAM_NAME if as_team and not viewer.is_admin else r["author_name"]
            entries.append(RequestEntry(r["id"], name, r["author_role"] == "admin", r["author_id"] == viewer.id,
                                        r["body"], r["status"], r["created_at"], as_team))
        return entries

    # ---------- replying and status ----------
    def reply(self, request_id: int, author: User, body: str, as_team: bool = False) -> None:
        """as_team (רק למנהל): הפונה יראה ״מנהל המערכת״ במקום השם."""
        req = self.get_visible(request_id, author)
        if req.closed:
            raise ValidationError("הפנייה נסגרה. אם צריך עוד משהו, פתח פנייה חדשה")
        body = self._body(body)
        now = self.clock()
        # תשובה ראשונה של מנהל מעבירה פנייה חדשה לטיפול. שינוי הסטטוס נרשם לפני התשובה, כמו שזה קרה
        if author.is_admin and req.status == "new":
            self._add_entry(request_id, author.id, "", "in_progress", now)
        self._add_entry(request_id, author.id, body, "", now, as_team=as_team and author.is_admin)
        if author.is_admin:
            self.db.execute(
                "UPDATE requests SET updated_at = ?, requester_unseen = 1, "
                "status = CASE status WHEN 'new' THEN 'in_progress' ELSE status END WHERE id = ?",
                (now, request_id))
        else:
            self.db.execute("UPDATE requests SET updated_at = ? WHERE id = ?", (now, request_id))
        self.db.commit()

    def set_status(self, request_id: int, admin: User, status: str) -> SupportRequest:
        if not admin.is_admin:
            raise Forbidden("רק מנהלי מערכת מעדכנים סטטוס של פנייה")
        if status not in STATUSES:
            raise ValidationError("סטטוס לא מוכר")
        req = self.get(request_id)
        if status == req.status:
            return req
        now = self.clock()
        self._add_entry(request_id, admin.id, "", status, now)
        self.db.execute(
            "UPDATE requests SET status = ?, updated_at = ?, closed_at = ?, requester_unseen = 1 WHERE id = ?",
            (status, now, now if status in CLOSED else 0, request_id))
        self.db.commit()
        return self.get(request_id)

    def mark_seen(self, request_id: int, viewer: User) -> None:
        self.db.execute("UPDATE requests SET requester_unseen = 0 WHERE id = ? AND user_id = ?", (request_id, viewer.id))
        self.db.commit()

    # ---------- counters for the menus ----------
    def badge_for(self, user: User) -> int:
        """למנהל: כמה פניות חדשות מחכות. לסטודנט או מרצה: בכמה פניות שלו יש עדכון שעוד לא ראה."""
        if user.is_admin:
            sql, args = "SELECT COUNT(*) FROM requests WHERE status = 'new'", ()
        else:
            sql, args = "SELECT COUNT(*) FROM requests WHERE user_id = ? AND requester_unseen = 1", (user.id,)
        return self.db.execute(sql, args).fetchone()[0]

    def purge(self) -> int:
        """מוחק פניות שנסגרו לפני יותר מ-7 ימים (וההודעות שלהן, ב-CASCADE)."""
        cutoff = self.clock() - KEEP_CLOSED_DAYS * 86400
        cur = self.db.execute("DELETE FROM requests WHERE closed_at > 0 AND closed_at < ?", (cutoff,))
        if cur.rowcount:
            self.db.commit()
        return cur.rowcount

    def _add_entry(self, request_id: int, author_id: int, body: str, status: str, at: float,
                   as_team: bool = False) -> None:
        self.db.execute(
            "INSERT INTO request_messages (request_id, author_id, body, status, as_team, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (request_id, author_id, body, status, int(as_team), at))

    @staticmethod
    def _body(body: str) -> str:
        body = (body or "").strip()
        if not body:
            raise ValidationError("כתוב את תוכן ההודעה")
        if len(body) > MAX_BODY:
            raise ValidationError(f"ההודעה ארוכה מדי (עד {MAX_BODY} תווים)")
        return body
