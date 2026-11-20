"""בלוקי תוכן בעמוד הקורס: טקסט, קישור וקובץ."""
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from werkzeug.utils import secure_filename

from ..errors import NotFound, ValidationError

KINDS = ("text", "link", "file")


@dataclass(frozen=True)
class ContentBlock:
    id: int
    course_id: int
    kind: str
    title: str
    body: str
    url: str
    file_path: str
    file_name: str
    position: int

    @classmethod
    def from_row(cls, r) -> "ContentBlock":
        return cls(r["id"], r["course_id"], r["kind"], r["title"], r["body"], r["url"],
                   r["file_path"], r["file_name"], r["position"])


class FileStore:
    """שומר קבצים שהועלו בתיקייה מקומית ומחזיר נתיב יחסי."""

    def __init__(self, root: str):
        self.root = Path(root)

    def save(self, folder: str, filename: str, data: bytes) -> str:
        safe = secure_filename(filename) or "file"
        rel = Path(folder) / f"{uuid.uuid4().hex[:12]}_{safe}"
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return rel.as_posix()

    def save_stream(self, folder: str, filename: str, stream) -> str:
        safe = secure_filename(filename) or "file"
        rel = Path(folder) / f"{uuid.uuid4().hex[:12]}_{safe}"
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        stream.save(str(target))
        return rel.as_posix()

    def path(self, rel: str) -> Path:
        return self.root / rel

    def delete(self, rel: str) -> None:
        if rel:
            self.path(rel).unlink(missing_ok=True)


class ContentService:
    def __init__(self, db: sqlite3.Connection, files: FileStore):
        self.db = db
        self.files = files

    def list(self, course_id: int) -> list[ContentBlock]:
        rows = self.db.execute(
            "SELECT * FROM content_blocks WHERE course_id = ? ORDER BY position, id", (course_id,)
        )
        return [ContentBlock.from_row(r) for r in rows]

    def get(self, block_id: int) -> ContentBlock:
        row = self.db.execute("SELECT * FROM content_blocks WHERE id = ?", (block_id,)).fetchone()
        if row is None:
            raise NotFound("התוכן לא נמצא")
        return ContentBlock.from_row(row)

    def add(self, course_id: int, kind: str, title: str = "", body: str = "", url: str = "",
            file_name: str = "", file_data: bytes | None = None) -> ContentBlock:
        if kind not in KINDS:
            raise ValidationError("סוג תוכן לא מוכר")
        title, body, url = title.strip(), body.strip(), url.strip()
        file_path = ""
        if kind == "text" and not (title or body):
            raise ValidationError("כתוב כותרת או טקסט")
        if kind == "link":
            self._check_url(url)
        if kind == "file":
            if not file_data:
                raise ValidationError("בחר קובץ להעלאה")
            file_path = self.files.save(f"content/{course_id}", file_name, file_data)
            title = title or file_name
        pos = self.db.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM content_blocks WHERE course_id = ?", (course_id,)
        ).fetchone()[0]
        cur = self.db.execute(
            "INSERT INTO content_blocks (course_id, kind, title, body, url, file_path, file_name, position) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (course_id, kind, title, body, url, file_path, file_name, pos),
        )
        self.db.commit()
        return self.get(cur.lastrowid)

    def update(self, block_id: int, title: str, body: str = "", url: str = "") -> ContentBlock:
        block = self.get(block_id)
        if block.kind == "link":
            self._check_url(url.strip())
        else:
            url = block.url
        self.db.execute(
            "UPDATE content_blocks SET title = ?, body = ?, url = ? WHERE id = ?",
            (title.strip(), body.strip(), url.strip(), block_id),
        )
        self.db.commit()
        return self.get(block_id)

    def delete(self, block_id: int) -> None:
        block = self.get(block_id)
        self.db.execute("DELETE FROM content_blocks WHERE id = ?", (block_id,))
        self.db.commit()
        self.files.delete(block.file_path)

    def move(self, block_id: int, direction: int) -> None:
        """direction: -1 למעלה, +1 למטה. מחליף מקום עם השכן."""
        block = self.get(block_id)
        blocks = self.list(block.course_id)
        idx = next(i for i, b in enumerate(blocks) if b.id == block_id)
        other = idx + direction
        if not 0 <= other < len(blocks):
            return
        blocks[idx], blocks[other] = blocks[other], blocks[idx]
        for pos, b in enumerate(blocks, start=1):
            self.db.execute("UPDATE content_blocks SET position = ? WHERE id = ?", (pos, b.id))
        self.db.commit()

    @staticmethod
    def _check_url(url: str) -> None:
        if not url.startswith(("http://", "https://")):
            raise ValidationError("הקישור צריך להתחיל ב-https://")
