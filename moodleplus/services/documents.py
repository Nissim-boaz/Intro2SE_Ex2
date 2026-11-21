"""קריאת קבצי הגשה בשביל ה-AI: טקסט כשאפשר, וקובץ שלם (PDF סרוק או תמונה) כש-Gemini צריך לראות אותו בעצמו."""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

TEXT_EXT = {
    ".txt", ".md", ".py", ".java", ".c", ".cpp", ".cc", ".h", ".hpp", ".cs", ".js", ".ts", ".jsx", ".tsx",
    ".html", ".css", ".json", ".sql", ".csv", ".xml", ".yaml", ".yml", ".kt", ".swift", ".go", ".rb", ".php",
    ".m", ".r", ".sh", ".puml", ".plantuml", ".tex",
}
IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
              ".gif": "image/gif"}
MAX_TEXT = 60_000            # תווים לקובץ, כדי שהבקשה ל-Gemini לא תהיה ענקית
MAX_BLOB = 15 * 1024 * 1024  # PDF או תמונה שנשלחים כמו שהם
MIN_PDF_TEXT = 200           # פחות מזה ב-PDF: כנראה סרוק, אז Gemini מקבל את הקובץ עצמו


@dataclass
class Document:
    name: str
    text: str = ""
    blobs: list[tuple[str, bytes]] = field(default_factory=list)  # (mime, bytes)
    error: str = ""

    @property
    def readable(self) -> bool:
        return bool(self.text.strip() or self.blobs)


def read_document(path: Path, name: str) -> Document:
    ext = Path(name).suffix.lower()
    doc = Document(name)
    try:
        data = Path(path).read_bytes()
    except OSError:
        doc.error = "הקובץ לא נמצא"
        return doc
    try:
        if ext == ".pdf":
            doc.text = _pdf_text(data)
            if len(doc.text.strip()) < MIN_PDF_TEXT and len(data) <= MAX_BLOB:
                doc.blobs.append(("application/pdf", data))
        elif ext in (".docx", ".pptx"):
            doc.text = _office_text(data, ext)
        elif ext == ".zip":
            doc.text = _zip_text(data)
        elif ext in IMAGE_MIME:
            if len(data) <= MAX_BLOB:
                doc.blobs.append((IMAGE_MIME[ext], data))
        elif ext in TEXT_EXT or ext == "":
            doc.text = data.decode("utf-8", errors="replace")
        elif ext == ".ipynb":
            doc.text = _notebook_text(data)
        else:
            doc.error = f"ה-AI לא יודע לקרוא קבצי {ext or 'מהסוג הזה'}"
    except Exception:  # קובץ פגום לא מפיל את כל הבדיקה
        doc.error = "לא הצלחתי לקרוא את הקובץ"
    doc.text = doc.text[:MAX_TEXT]
    if not doc.error and not doc.readable:
        doc.error = "הקובץ ריק או שאין בו טקסט"
    return doc


def _pdf_text(data: bytes) -> str:
    try:
        from io import BytesIO

        from pypdf import PdfReader
    except ImportError:
        return ""
    reader = PdfReader(BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages[:60])


def _xml_text(xml: str, paragraph_tag: str) -> str:
    xml = re.sub(rf"</{paragraph_tag}>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def _office_text(data: bytes, ext: str) -> str:
    from io import BytesIO

    with zipfile.ZipFile(BytesIO(data)) as z:
        if ext == ".docx":
            return _xml_text(z.read("word/document.xml").decode("utf-8", "replace"), "w:p")
        slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                        key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
        return "\n\n".join(f"--- שקף {i + 1} ---\n" + _xml_text(z.read(n).decode("utf-8", "replace"), "a:p")
                           for i, n in enumerate(slides))


def _zip_text(data: bytes) -> str:
    from io import BytesIO

    parts, total = [], 0
    with zipfile.ZipFile(BytesIO(data)) as z:
        for info in z.infolist():
            ext = Path(info.filename).suffix.lower()
            if info.is_dir() or "__MACOSX" in info.filename or info.file_size > 2_000_000:
                continue
            if ext in TEXT_EXT:
                body = z.read(info).decode("utf-8", "replace")
            elif ext in (".docx", ".pptx"):
                body = _office_text(z.read(info), ext)
            else:
                continue
            parts.append(f"--- {info.filename} ---\n{body}")
            total += len(body)
            if total > MAX_TEXT:
                break
    return "\n\n".join(parts)


def _notebook_text(data: bytes) -> str:
    import json

    nb = json.loads(data.decode("utf-8", "replace"))
    return "\n\n".join("".join(c.get("source", [])) for c in nb.get("cells", []))


# ---------- similarity between submissions (possible copying) ----------
_WORD = re.compile(r"[\w֐-׿]{2,}")


def shingles(text: str, size: int = 5) -> set[tuple[str, ...]]:
    words = _WORD.findall(text.lower())
    return {tuple(words[i:i + size]) for i in range(len(words) - size + 1)}


def similarity(a: set, b: set) -> float:
    """Jaccard: כמה מהרצפים של 5 מילים משותפים לשתי ההגשות."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
