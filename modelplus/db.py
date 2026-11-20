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
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """עמודות שנוספו אחרי שכבר נוצרו DBs. CREATE TABLE IF NOT EXISTS לא מוסיף עמודות לטבלה קיימת."""
    added = {
        ("messages", "deleted"): "INTEGER NOT NULL DEFAULT 0",
        ("polls", "anonymous"): "INTEGER NOT NULL DEFAULT 1",
        ("courses", "chat_locked"): "INTEGER NOT NULL DEFAULT 0",
        # הקלטות שכבר היו לפני שנוסף שלב הטיוטה נשארות גלויות לסטודנטים.
        # הקלטות חדשות נשמרות כטיוטה כי RecordingService.create מכניס published=0 במפורש
        ("recordings", "published"): "INTEGER NOT NULL DEFAULT 1",
        ("recordings", "feedback_status"): "TEXT NOT NULL DEFAULT ''",
        ("recordings", "feedback_json"): "TEXT NOT NULL DEFAULT ''",
        ("recordings", "feedback_error"): "TEXT NOT NULL DEFAULT ''",
        ("recordings", "feedback_job"): "INTEGER NOT NULL DEFAULT 0",
        ("recordings", "feedback_at"): "REAL NOT NULL DEFAULT 0",
        ("recordings", "transcript_edited_at"): "REAL NOT NULL DEFAULT 0",
    }
    for (table, column), ddl in added.items():
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if cols and column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def _close_db(_exc=None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_app(app: Flask) -> None:
    conn = connect(app.config["DATABASE"])
    try:
        init_schema(conn)
    finally:
        conn.close()
    app.teardown_appcontext(_close_db)
