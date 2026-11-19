"""אובייקטי נתונים פשוטים שהשירותים מחזירים."""
from dataclasses import dataclass

ROLES = ("admin", "lecturer", "student")
ROLE_LABELS = {"admin": "מנהל מערכת", "lecturer": "מרצה", "student": "סטודנט"}


@dataclass(frozen=True)
class User:
    id: int
    email: str
    name: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_lecturer(self) -> bool:
        return self.role == "lecturer"

    @property
    def role_label(self) -> str:
        return ROLE_LABELS[self.role]

    @classmethod
    def from_row(cls, row) -> "User":
        return cls(row["id"], row["email"], row["name"], row["role"])


@dataclass(frozen=True)
class Course:
    id: int
    code: str
    name: str
    description: str

    @classmethod
    def from_row(cls, row) -> "Course":
        return cls(row["id"], row["code"], row["name"], row["description"])
