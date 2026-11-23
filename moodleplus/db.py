"""חיבור ל-SQLite. חיבור אחד לכל בקשה, במצב WAL."""
import sqlite3
from pathlib import Path

from flask import Flask, current_app, g

SCHEMA = Path(__file__).with_name("schema.sql")


def connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    _migrate(conn)
    legacy_records = _set_aside_legacy_attendance(conn)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    if legacy_records:
        _copy_legacy_attendance(conn)
    # DBs מלפני התיקון: תפקיד בקורס שלא תואם לתפקיד של המשתמש (שונה אחרי השיוך) מתיישר אליו
    conn.execute(
        "UPDATE enrollments SET role = (SELECT role FROM users WHERE users.id = enrollments.user_id) "
        "WHERE role != (SELECT role FROM users WHERE users.id = enrollments.user_id) "
        "AND (SELECT role FROM users WHERE users.id = enrollments.user_id) IN ('lecturer', 'student')"
    )
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """עמודות שנוספו אחרי שכבר נוצרו DBs. CREATE TABLE IF NOT EXISTS לא מוסיף עמודות לטבלה קיימת."""
    added = {
        ("messages", "deleted"): "INTEGER NOT NULL DEFAULT 0",
        ("messages", "pinned_at"): "REAL NOT NULL DEFAULT 0",
        ("polls", "anonymous"): "INTEGER NOT NULL DEFAULT 1",
        ("courses", "chat_locked"): "INTEGER NOT NULL DEFAULT 0",
        # הקלטות שכבר היו לפני שנוסף שלב הטיוטה נשארות גלויות לסטודנטים.
        # הקלטות חדשות נשמרות כטיוטה כי RecordingService.create מכניס published=0 במפורש
        ("recordings", "published"): "INTEGER NOT NULL DEFAULT 1",
        # הקלטות ישנות בלי מעלה: המשוב פתוח לכל מרצי הקורס, כמו שהיה
        ("recordings", "uploaded_by"): "INTEGER REFERENCES users(id) ON DELETE SET NULL",
        ("recordings", "feedback_status"): "TEXT NOT NULL DEFAULT ''",
        ("recordings", "feedback_json"): "TEXT NOT NULL DEFAULT ''",
        ("recordings", "feedback_error"): "TEXT NOT NULL DEFAULT ''",
        ("recordings", "feedback_job"): "INTEGER NOT NULL DEFAULT 0",
        ("recordings", "feedback_at"): "REAL NOT NULL DEFAULT 0",
        ("recordings", "transcript_edited_at"): "REAL NOT NULL DEFAULT 0",
        ("request_messages", "as_team"): "INTEGER NOT NULL DEFAULT 0",
        # מטלות שכבר היו לפני שלב הפרסום נשארות עם ציונים גלויים, כמו שהיו
        ("assignments", "grades_published"): "INTEGER NOT NULL DEFAULT 1",
        ("submissions", "appeal_status"): "TEXT NOT NULL DEFAULT ''",
        ("submissions", "appeal_text"): "TEXT NOT NULL DEFAULT ''",
        ("submissions", "appeal_reply"): "TEXT NOT NULL DEFAULT ''",
        ("submissions", "appeal_at"): "REAL NOT NULL DEFAULT 0",
        ("submissions", "original_grade"): "INTEGER",
        ("assignments", "ai_guidelines"): "TEXT NOT NULL DEFAULT ''",
        ("assignments", "ai_solution_path"): "TEXT NOT NULL DEFAULT ''",
        ("assignments", "ai_solution_name"): "TEXT NOT NULL DEFAULT ''",
        ("assignments", "ai_status"): "TEXT NOT NULL DEFAULT ''",
        ("assignments", "ai_error"): "TEXT NOT NULL DEFAULT ''",
        ("assignments", "ai_job"): "INTEGER NOT NULL DEFAULT 0",
        ("assignments", "ai_done"): "INTEGER NOT NULL DEFAULT 0",
        ("assignments", "ai_total"): "INTEGER NOT NULL DEFAULT 0",
        ("submissions", "ai_grade"): "INTEGER",
        ("submissions", "ai_reason"): "TEXT NOT NULL DEFAULT ''",
        ("submissions", "ai_feedback"): "TEXT NOT NULL DEFAULT ''",
        ("submissions", "ai_class_note"): "TEXT NOT NULL DEFAULT ''",
        ("submissions", "ai_summary"): "TEXT NOT NULL DEFAULT ''",
        ("submissions", "ai_off_topic"): "INTEGER NOT NULL DEFAULT 0",
        ("submissions", "ai_flag"): "TEXT NOT NULL DEFAULT ''",
        ("submissions", "ai_error"): "TEXT NOT NULL DEFAULT ''",
        ("submissions", "ai_at"): "REAL NOT NULL DEFAULT 0",
        ("submissions", "ai_deductions"): "TEXT NOT NULL DEFAULT ''",
        ("assignments", "weight"): "REAL NOT NULL DEFAULT 0",
        ("assignments", "solution_path"): "TEXT NOT NULL DEFAULT ''",
        ("assignments", "solution_name"): "TEXT NOT NULL DEFAULT ''",
        ("assignments", "solution_published"): "INTEGER NOT NULL DEFAULT 0",
    }
    for (table, column), ddl in added.items():
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if cols and column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


_LEGACY_RECORDS = "attendance_records_legacy"


def _set_aside_legacy_attendance(conn: sqlite3.Connection) -> bool:
    """רשומות נוכחות מתקופת ה-QR (עם status ו-reasons) עוברות לטבלה הזמנית, והסכמה יוצרת את הטבלה החדשה.

    ה-CHECK על method השתנה, ו-SQLite לא יודע לשנות CHECK בטבלה קיימת, אז בונים אותה מחדש.
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(attendance_records)")}
    if "reasons" not in cols:
        return False
    conn.execute("DROP INDEX IF EXISTS ux_record_sample_student")  # האינדקס היה עובר עם הטבלה ששינתה שם
    conn.execute(f"ALTER TABLE attendance_records RENAME TO {_LEGACY_RECORDS}")
    return True


def _copy_legacy_attendance(conn: sqlite3.Connection) -> None:
    # רק מה שנספר כנוכחות: עם אות קולי, או חשוד שהמרצה אישר (נחשב עכשיו סימון ידני).
    # חשודים שלא טופלו ונדחים לא עוברים, כי אין יותר מצב כזה
    conn.execute(
        f"INSERT INTO attendance_records (id, sample_id, student_id, at, method) "
        f"SELECT id, sample_id, student_id, at, CASE WHEN method = 'qr_audio' THEN 'audio' ELSE 'manual' END "
        f"FROM {_LEGACY_RECORDS} WHERE status IN ('ok', 'approved')"
    )
    conn.execute(f"DROP TABLE {_LEGACY_RECORDS}")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def _close_db(_exc=None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


LEGACY_DB_NAME = "model" + "plus.db"  # השם הקודם של האתר. מפוצל כדי שחיפוש-החלפה לא ישנה אותו


def move_legacy_db(path: str) -> bool:
    """עד שהאתר נקרא Moodle+, קובץ ה-DB נקרא אחרת. אם יש קובץ ישן ואין חדש, מעבירים אותו כדי שלא יאבדו נתונים."""
    new = Path(path)
    old = new.with_name(LEGACY_DB_NAME)
    if new.exists() or not old.exists():
        return False
    for suffix in ("", "-wal", "-shm"):  # קובצי ה-WAL זזים יחד עם ה-DB
        src = Path(str(old) + suffix)
        if src.exists():
            src.rename(str(new) + suffix)
    return True


def init_app(app: Flask) -> None:
    move_legacy_db(app.config["DATABASE"])
    conn = connect(app.config["DATABASE"])
    try:
        init_schema(conn)
    finally:
        conn.close()
    app.teardown_appcontext(_close_db)
