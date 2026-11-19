"""ניהול משתמשים וייבוא סטודנטים מקובץ."""
import csv
import io
import re
import sqlite3
from dataclasses import dataclass

from ..errors import NotFound, ValidationError
from ..models import ROLES, User

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserService:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def get(self, user_id: int) -> User:
        row = self.db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise NotFound("המשתמש לא נמצא")
        return User.from_row(row)

    def find_by_email(self, email: str) -> User | None:
        row = self.db.execute("SELECT * FROM users WHERE email = ?", (email.strip(),)).fetchone()
        return User.from_row(row) if row else None

    def list(self, role: str | None = None) -> list[User]:
        if role:
            rows = self.db.execute("SELECT * FROM users WHERE role = ? ORDER BY name", (role,))
        else:
            rows = self.db.execute("SELECT * FROM users ORDER BY role, name")
        return [User.from_row(r) for r in rows]

    def create(self, email: str, name: str, role: str) -> User:
        email, name = email.strip().lower(), name.strip()
        if not EMAIL_RE.match(email):
            raise ValidationError("כתובת המייל לא תקינה")
        if not name:
            raise ValidationError("צריך למלא שם")
        if role not in ROLES:
            raise ValidationError("תפקיד לא מוכר")
        if self.find_by_email(email):
            raise ValidationError("כבר יש משתמש עם המייל הזה")
        cur = self.db.execute(
            "INSERT INTO users (email, name, role) VALUES (?, ?, ?)", (email, name, role)
        )
        self.db.commit()
        return self.get(cur.lastrowid)

    def update(self, user_id: int, name: str, role: str) -> User:
        if role not in ROLES:
            raise ValidationError("תפקיד לא מוכר")
        if not name.strip():
            raise ValidationError("צריך למלא שם")
        self.get(user_id)
        self.db.execute("UPDATE users SET name = ?, role = ? WHERE id = ?", (name.strip(), role, user_id))
        self.db.commit()
        return self.get(user_id)

    def delete(self, user_id: int) -> None:
        self.get(user_id)
        self.db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self.db.commit()

    def ensure(self, email: str, name: str, role: str) -> User:
        """מחזיר משתמש קיים או יוצר חדש. משמש לאדמין הראשון ול-seed."""
        return self.find_by_email(email) or self.create(email, name, role)


@dataclass(frozen=True)
class ImportResult:
    created: int
    existing: int
    skipped: list[str]
    users: list[User]


class StudentImporter:
    """קורא CSV או XLSX עם עמודות שם ומייל ויוצר סטודנטים.

    עמודות נתמכות: name/שם, או first name + last name, ו-email/mail/דוא״ל.
    """

    NAME_KEYS = ("name", "full name", "שם", "שם מלא")
    FIRST_KEYS = ("first name", "שם פרטי")
    LAST_KEYS = ("last name", "surname", "שם משפחה")
    EMAIL_KEYS = ("email", "mail", "e-mail", "email address", "דוא״ל", 'דוא"ל', "מייל")

    def __init__(self, users: UserService):
        self.users = users

    def read_rows(self, filename: str, data: bytes) -> list[dict]:
        if filename.lower().endswith(".xlsx"):
            return self._read_xlsx(data)
        if filename.lower().endswith(".csv"):
            return self._read_csv(data)
        raise ValidationError("אפשר להעלות רק קובץ CSV או XLSX")

    def import_file(self, filename: str, data: bytes) -> ImportResult:
        created = existing = 0
        skipped: list[str] = []
        users: list[User] = []
        for i, row in enumerate(self.read_rows(filename, data), start=2):
            name, email = self._extract(row)
            if not email or not EMAIL_RE.match(email):
                skipped.append(f"שורה {i}: אין מייל תקין")
                continue
            user = self.users.find_by_email(email)
            if user:
                existing += 1
            else:
                user = self.users.create(email, name or email.split("@")[0], "student")
                created += 1
            users.append(user)
        return ImportResult(created, existing, skipped, users)

    # --- helpers ---
    @staticmethod
    def _norm(key) -> str:
        return str(key or "").strip().lower().lstrip("﻿")

    def _pick(self, row: dict, keys) -> str:
        for k in keys:
            if row.get(k):
                return str(row[k]).strip()
        return ""

    def _extract(self, row: dict) -> tuple[str, str]:
        email = self._pick(row, self.EMAIL_KEYS).lower()
        name = self._pick(row, self.NAME_KEYS)
        if not name:
            name = " ".join(p for p in (self._pick(row, self.FIRST_KEYS), self._pick(row, self.LAST_KEYS)) if p)
        return name, email

    def _read_csv(self, data: bytes) -> list[dict]:
        text = data.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        return [{self._norm(k): v for k, v in r.items()} for r in reader]

    def _read_xlsx(self, data: bytes) -> list[dict]:
        import openpyxl

        ws = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True).active
        rows = ws.iter_rows(values_only=True)
        header = [self._norm(h) for h in next(rows, [])]
        return [dict(zip(header, r)) for r in rows if any(c not in (None, "") for c in r)]
