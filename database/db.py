import sqlite3
from pathlib import Path
from flask import g, current_app
from config import Config

def get_db(db_path=None):
    if db_path is None:
        if current_app:
            db_path = current_app.config.get("DATABASE_PATH", Config.DATABASE_PATH)
        else:
            db_path = Config.DATABASE_PATH

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # If within Flask application context, store in g
    try:
        if hasattr(g, "db") and g.db is not None:
            return g.db
    except RuntimeError:
        pass

    conn = sqlite3.connect(
        str(path),
        timeout=30.0,
        detect_types=sqlite3.PARSE_DECLTYPES
    )
    conn.row_factory = sqlite3.Row

    # Enable WAL mode for high concurrency
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")

    try:
        if "g" in globals():
            g.db = conn
    except RuntimeError:
        pass

    return conn

def close_db(e=None):
    try:
        db = getattr(g, "db", None)
        if db is not None:
            db.close()
            g.db = None
    except RuntimeError:
        pass

def init_db(db_path=None):
    conn = get_db(db_path)
    with conn:
        # Sessions table (generic for attendance, assignments, voting, etc.)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'attendance',
                status TEXT NOT NULL DEFAULT 'active',
                start_time TEXT NOT NULL,
                end_time TEXT,
                duration_minutes INTEGER NOT NULL DEFAULT 90,
                created_at TEXT NOT NULL,
                closed_at TEXT
            );
        """)

        # Attendance table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                student_name TEXT NOT NULL,
                email TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                user_agent TEXT,
                status TEXT NOT NULL, -- 'present', 'suspicious'
                approved_at TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
        """)

        # Rejected attempts table (F11)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rejected_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                email TEXT NOT NULL,
                student_name TEXT,
                timestamp TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                reason TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
        """)

        # Indexes for query speed & constraints
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_session_email ON attendance(session_id, email);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_attendance_session_status ON attendance(session_id, status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rejected_session ON rejected_attempts(session_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);")

    return conn
