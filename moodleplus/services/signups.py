"""בקשות הרשמה: מי שעוד לא במערכת ממלא שם, מייל ותפקיד, ומנהל מערכת מאשר או דוחה.

אחרי אישור נוצר משתמש רגיל עם המייל הזה, והוא נכנס עם Google כמו כולם. מי שהזין מייל של מישהו אחר
לא מרוויח כלום: רק בעל חשבון ה-Google של המייל הזה יכול להתחבר איתו.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from ..errors import NotFound, ValidationError
from ..models import ROLE_LABELS, User
from .users import EMAIL_RE, UserService

SIGNUP_ROLES = ("student", "lecturer")  # מנהל מערכת לא מבקשים: את זה רק מנהל קיים נותן
MAX_PENDING = 500  # הטופס פתוח לכולם, אז יש תקרה לבקשות שמחכות


@dataclass(frozen=True)
class SignupRequest:
    id: int
    name: str
    email: str
    role: str
    created_at: float

    @property
    def role_label(self) -> str:
        return ROLE_LABELS[self.role]


class SignupService:
    def __init__(self, db: sqlite3.Connection, clock=time.time):
        self.db = db
        self.clock = clock
        self.users = UserService(db)

    def submit(self, name: str, email: str, role: str) -> SignupRequest:
        name, email = (name or "").strip(), (email or "").strip().lower()
        if not name:
            raise ValidationError("כתוב את השם המלא שלך")
        if not EMAIL_RE.match(email):
            raise ValidationError("כתובת המייל לא תקינה")
        if role not in SIGNUP_ROLES:
            raise ValidationError("בחר אם אתה סטודנט או מרצה")
        if self.users.find_by_email(email):
            raise ValidationError("כבר יש לך גישה לאתר. אפשר להתחבר עם Google")
        if self.db.execute("SELECT 1 FROM signup_requests WHERE email = ?", (email,)).fetchone():
            raise ValidationError("כבר שלחת בקשה עם המייל הזה. היא מחכה לאישור של מנהל המערכת")
        if self.count() >= MAX_PENDING:
            raise ValidationError("יש כרגע יותר מדי בקשות שמחכות. נסה שוב מאוחר יותר")
        cur = self.db.execute("INSERT INTO signup_requests (name, email, role, created_at) VALUES (?, ?, ?, ?)",
                              (name[:120], email, role, self.clock()))
        self.db.commit()
        return self.get(cur.lastrowid)

    def get(self, request_id: int) -> SignupRequest:
        row = self.db.execute("SELECT * FROM signup_requests WHERE id = ?", (request_id,)).fetchone()
        if row is None:
            raise NotFound("הבקשה לא נמצאה. אולי מנהל אחר כבר טיפל בה")
        return SignupRequest(row["id"], row["name"], row["email"], row["role"], row["created_at"])

    def pending(self) -> list[SignupRequest]:
        rows = self.db.execute("SELECT * FROM signup_requests ORDER BY created_at")
        return [SignupRequest(r["id"], r["name"], r["email"], r["role"], r["created_at"]) for r in rows]

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM signup_requests").fetchone()[0]

    def approve(self, request_id: int, role: str | None = None) -> User:
        """יוצר את המשתמש (המנהל יכול לשנות את התפקיד שהתבקש) ומוחק את הבקשה."""
        req = self.get(request_id)
        role = role or req.role
        if role not in ("student", "lecturer", "admin"):
            raise ValidationError("תפקיד לא מוכר")
        user = self.users.find_by_email(req.email) or self.users.create(req.email, req.name, role)
        self.db.execute("DELETE FROM signup_requests WHERE id = ?", (request_id,))
        self.db.commit()
        return user

    def reject(self, request_id: int) -> None:
        self.get(request_id)
        self.db.execute("DELETE FROM signup_requests WHERE id = ?", (request_id,))
        self.db.commit()
