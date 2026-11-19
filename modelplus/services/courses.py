"""קורסים ושיוך משתמשים לקורסים."""
import sqlite3

from ..errors import Forbidden, NotFound, ValidationError
from ..models import Course, User


class CourseService:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def get(self, course_id: int) -> Course:
        row = self.db.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
        if row is None:
            raise NotFound("הקורס לא נמצא")
        return Course.from_row(row)

    def list(self) -> list[Course]:
        return [Course.from_row(r) for r in self.db.execute("SELECT * FROM courses ORDER BY name")]

    def create(self, name: str, code: str = "", description: str = "") -> Course:
        if not name.strip():
            raise ValidationError("צריך לתת לקורס שם")
        cur = self.db.execute(
            "INSERT INTO courses (name, code, description) VALUES (?, ?, ?)",
            (name.strip(), code.strip(), description.strip()),
        )
        self.db.commit()
        return self.get(cur.lastrowid)

    def update(self, course_id: int, name: str, code: str, description: str) -> Course:
        self.get(course_id)
        if not name.strip():
            raise ValidationError("צריך לתת לקורס שם")
        self.db.execute(
            "UPDATE courses SET name = ?, code = ?, description = ? WHERE id = ?",
            (name.strip(), code.strip(), description.strip(), course_id),
        )
        self.db.commit()
        return self.get(course_id)

    def delete(self, course_id: int) -> None:
        self.get(course_id)
        self.db.execute("DELETE FROM courses WHERE id = ?", (course_id,))
        self.db.commit()


class EnrollmentService:
    """מי שייך לאיזה קורס, ובאיזה תפקיד. כאן נבדקות הרשאות ברמת הקורס."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def enroll(self, course_id: int, user: User) -> None:
        if user.role == "admin":
            raise ValidationError("אין צורך לשייך מנהל מערכת לקורס")
        self.db.execute(
            "INSERT OR REPLACE INTO enrollments (course_id, user_id, role) VALUES (?, ?, ?)",
            (course_id, user.id, user.role),
        )
        self.db.commit()

    def enroll_many(self, course_id: int, users: list[User]) -> int:
        count = 0
        for user in users:
            if user.role != "admin":
                self.db.execute(
                    "INSERT OR IGNORE INTO enrollments (course_id, user_id, role) VALUES (?, ?, ?)",
                    (course_id, user.id, user.role),
                )
                count += 1
        self.db.commit()
        return count

    def unenroll(self, course_id: int, user_id: int) -> None:
        self.db.execute("DELETE FROM enrollments WHERE course_id = ? AND user_id = ?", (course_id, user_id))
        self.db.commit()

    def members(self, course_id: int, role: str | None = None) -> list[User]:
        sql = "SELECT u.* FROM users u JOIN enrollments e ON e.user_id = u.id WHERE e.course_id = ?"
        args: tuple = (course_id,)
        if role:
            sql += " AND e.role = ?"
            args += (role,)
        return [User.from_row(r) for r in self.db.execute(sql + " ORDER BY u.name", args)]

    def courses_for(self, user: User) -> list[Course]:
        if user.is_admin:
            rows = self.db.execute("SELECT * FROM courses ORDER BY name")
        else:
            rows = self.db.execute(
                "SELECT c.* FROM courses c JOIN enrollments e ON e.course_id = c.id "
                "WHERE e.user_id = ? ORDER BY c.name",
                (user.id,),
            )
        return [Course.from_row(r) for r in rows]

    def role_in(self, course_id: int, user: User) -> str | None:
        if user.is_admin:
            return "admin"
        row = self.db.execute(
            "SELECT role FROM enrollments WHERE course_id = ? AND user_id = ?", (course_id, user.id)
        ).fetchone()
        return row["role"] if row else None

    def can_manage(self, course_id: int, user: User) -> bool:
        return self.role_in(course_id, user) in ("admin", "lecturer")

    def require_member(self, course_id: int, user: User) -> str:
        role = self.role_in(course_id, user)
        if role is None:
            raise Forbidden("אין לך גישה לקורס הזה")
        return role

    def require_manager(self, course_id: int, user: User) -> None:
        if not self.can_manage(course_id, user):
            raise Forbidden("רק המרצה של הקורס יכול לעשות את זה")

    def require_student(self, course_id: int, user: User) -> None:
        if self.role_in(course_id, user) != "student":
            raise Forbidden("רק סטודנטים בקורס יכולים לעשות את זה")
