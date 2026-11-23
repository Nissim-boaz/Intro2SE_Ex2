"""עיצוב אישי לצ׳אט: רקע (צבע, דוגמה או תמונה משלך) וצבע ההודעות שלך.

כל משתמש בוחר לעצמו, לצ׳אט אחד או לכל הצ׳אטים שלו. בחירה לצ׳אט מסוים גוברת על הבחירה הכללית.
שאר חברי הקורס לא רואים את הבחירות של אחרים.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..errors import ValidationError
from ..models import User
from .content import FileStore

ALL_CHATS = 0  # course_id של הבחירה הכללית
WALLPAPERS = {
    "doodles": "ברירת המחדל",
    "plain": "בלי רקע",
    "sand": "חול",
    "mint": "מנטה",
    "sky": "שמיים",
    "lavender": "לבנדר",
    "rose": "ורד",
    "slate": "צפחה",
    "image": "תמונה משלך",
}
BUBBLES = {
    "brand": "כחול",
    "sky": "תכלת",
    "navy": "כחול כהה",
    "green": "ירוק בהיר",
    "olive": "ירוק זית",
    "teal": "טורקיז",
    "purple": "סגול",
    "lilac": "לילך",
    "pink": "ורוד",
    "red": "אדום",
    "orange": "כתום",
    "peach": "אפרסק",
    "brown": "חום",
    "graphite": "גרפיט",
}
DEFAULT_WALLPAPER = "doodles"
DEFAULT_BUBBLE = "brand"
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")
MAX_IMAGE = 8 * 1024 * 1024


@dataclass(frozen=True)
class ChatTheme:
    wallpaper: str
    bubble: str
    image_path: str     # רק כש-wallpaper הוא image
    image_version: int  # מתחלף כשמעלים תמונה חדשה, כדי שהדפדפן לא יציג את הישנה מהמטמון
    custom_here: bool   # יש בחירה מיוחדת לצ׳אט הזה (ולא רק הכללית)


class ChatThemeService:
    def __init__(self, db: sqlite3.Connection, files: FileStore):
        self.db = db
        self.files = files

    def _row(self, user_id: int, course_id: int):
        return self.db.execute("SELECT * FROM chat_themes WHERE user_id = ? AND course_id = ?",
                               (user_id, course_id)).fetchone()

    def get(self, user: User, course_id: int) -> ChatTheme:
        here, everywhere = self._row(user.id, course_id), self._row(user.id, ALL_CHATS)

        def pick(field):
            for row in (here, everywhere):
                if row and row[field]:
                    return row
            return None

        wall_row, bubble_row = pick("wallpaper"), pick("bubble")
        wallpaper = wall_row["wallpaper"] if wall_row else DEFAULT_WALLPAPER
        image = wall_row["image_path"] if wall_row and wallpaper == "image" else ""
        if wallpaper == "image" and not image:
            wallpaper = DEFAULT_WALLPAPER
        return ChatTheme(wallpaper, bubble_row["bubble"] if bubble_row else DEFAULT_BUBBLE, image,
                         wall_row["version"] if wall_row else 0,
                         bool(here and (here["wallpaper"] or here["bubble"])))

    def save(self, user: User, course_id: int, everywhere: bool, wallpaper: str | None = None,
             bubble: str | None = None, image_name: str = "", image=None) -> ChatTheme:
        """שומר רק את מה שנשלח. ״בכל הצ׳אטים״ גם מוחק את אותה בחירה מכל צ׳אט שהיה לו עיצוב משלו."""
        if wallpaper is not None and wallpaper not in WALLPAPERS:
            raise ValidationError("הרקע לא מוכר")
        if bubble is not None and bubble not in BUBBLES:
            raise ValidationError("הצבע לא מוכר")
        if wallpaper == "image" and not image_name:
            raise ValidationError("בחר תמונה לרקע")
        target = ALL_CHATS if everywhere else course_id
        image_path = ""
        if wallpaper == "image":
            if not image_name.lower().endswith(IMAGE_EXT):
                raise ValidationError("הרקע צריך להיות תמונה (JPG, PNG, WEBP או GIF)")
            image_path = self.files.save_stream(f"wallpapers/{user.id}", image_name, image)
            if self.files.path(image_path).stat().st_size > MAX_IMAGE:
                self.files.delete(image_path)
                raise ValidationError("התמונה גדולה מדי. אפשר עד 8MB")
        self.db.execute("INSERT OR IGNORE INTO chat_themes (user_id, course_id) VALUES (?, ?)", (user.id, target))
        if wallpaper is not None:
            old = self._row(user.id, target)["image_path"]
            self.db.execute("UPDATE chat_themes SET wallpaper = ?, image_path = ?, version = version + 1 "
                            "WHERE user_id = ? AND course_id = ?", (wallpaper, image_path, user.id, target))
            self._forget_image(user.id, old)
        if bubble is not None:
            self.db.execute("UPDATE chat_themes SET bubble = ? WHERE user_id = ? AND course_id = ?",
                            (bubble, user.id, target))
        if everywhere:
            for field, value in (("wallpaper", wallpaper), ("bubble", bubble)):
                if value is None:
                    continue
                olds = [r[0] for r in self.db.execute(
                    "SELECT image_path FROM chat_themes WHERE user_id = ? AND course_id != 0", (user.id,))] \
                    if field == "wallpaper" else []
                extra = ", image_path = ''" if field == "wallpaper" else ""
                self.db.execute(f"UPDATE chat_themes SET {field} = ''{extra} WHERE user_id = ? AND course_id != 0",
                                (user.id,))
                for old in olds:
                    self._forget_image(user.id, old)
        self.db.commit()
        return self.get(user, course_id)

    def reset(self, user: User, course_id: int, everywhere: bool) -> ChatTheme:
        """חזרה לברירת המחדל: בצ׳אט הזה (ואז הוא חוזר לבחירה הכללית), או בכל הצ׳אטים."""
        rows = self.db.execute(
            "SELECT image_path FROM chat_themes WHERE user_id = ?" + ("" if everywhere else " AND course_id = ?"),
            (user.id,) if everywhere else (user.id, course_id)).fetchall()
        self.db.execute("DELETE FROM chat_themes WHERE user_id = ?" + ("" if everywhere else " AND course_id = ?"),
                        (user.id,) if everywhere else (user.id, course_id))
        for (old,) in rows:
            self._forget_image(user.id, old)
        self.db.commit()
        return self.get(user, course_id)

    def image_file(self, user: User, course_id: int) -> Path | None:
        theme = self.get(user, course_id)
        return self.files.path(theme.image_path) if theme.image_path else None

    def _forget_image(self, user_id: int, rel: str) -> None:
        """מוחק קובץ תמונה ישן, אלא אם עדיין משתמשים בו."""
        if not rel:
            return
        used = self.db.execute("SELECT 1 FROM chat_themes WHERE user_id = ? AND image_path = ?", (user_id, rel)).fetchone()
        if not used:
            self.files.delete(rel)
