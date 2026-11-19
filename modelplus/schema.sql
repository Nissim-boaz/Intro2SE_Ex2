-- Model+ schema (SQLite, WAL)

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name        TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('admin', 'lecturer', 'student')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS courses (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL DEFAULT '',
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS enrollments (
    course_id   INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('lecturer', 'student')),
    PRIMARY KEY (course_id, user_id)
);

CREATE TABLE IF NOT EXISTS content_blocks (
    id          INTEGER PRIMARY KEY,
    course_id   INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('text', 'link', 'file')),
    title       TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL DEFAULT '',
    file_path   TEXT NOT NULL DEFAULT '',
    file_name   TEXT NOT NULL DEFAULT '',
    position    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS lessons (
    id          INTEGER PRIMARY KEY,
    course_id   INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    number      INTEGER NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (course_id, number)
);

CREATE TABLE IF NOT EXISTS attendance_samples (
    id          INTEGER PRIMARY KEY,
    lesson_id   INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL CHECK (seq BETWEEN 1 AND 5),
    opened_at   REAL NOT NULL,
    closes_at   REAL NOT NULL,
    opened_by   INTEGER REFERENCES users(id),
    UNIQUE (lesson_id, seq)
);

CREATE TABLE IF NOT EXISTS attendance_records (
    id          INTEGER PRIMARY KEY,
    sample_id   INTEGER NOT NULL REFERENCES attendance_samples(id) ON DELETE CASCADE,
    student_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    at          REAL NOT NULL,
    ip          TEXT NOT NULL DEFAULT '',
    method      TEXT NOT NULL CHECK (method IN ('qr_audio', 'qr_only')),
    status      TEXT NOT NULL CHECK (status IN ('ok', 'suspicious', 'approved', 'rejected')),
    reasons     TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_record_sample_student
    ON attendance_records (sample_id, student_id);

CREATE TABLE IF NOT EXISTS polls (
    id          INTEGER PRIMARY KEY,
    course_id   INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    question    TEXT NOT NULL,
    anonymous   INTEGER NOT NULL DEFAULT 1,  -- 0: כולם רואים מי הצביע למה
    created_by  INTEGER NOT NULL REFERENCES users(id),
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS poll_options (
    id          INTEGER PRIMARY KEY,
    poll_id     INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    position    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS poll_votes (
    poll_id     INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    option_id   INTEGER NOT NULL REFERENCES poll_options(id) ON DELETE CASCADE,
    PRIMARY KEY (poll_id, user_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY,
    course_id    INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    sender_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body         TEXT NOT NULL DEFAULT '',
    reply_to_id  INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    is_anonymous INTEGER NOT NULL DEFAULT 0,
    poll_id      INTEGER REFERENCES polls(id) ON DELETE CASCADE,
    deleted      INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_messages_course_updated ON messages (course_id, updated_at);

-- מי קרא איזו הודעה ומתי (וי כחול)
CREATE TABLE IF NOT EXISTS message_reads (
    message_id  INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    read_at     REAL NOT NULL,
    PRIMARY KEY (message_id, user_id)
);

CREATE TABLE IF NOT EXISTS message_reactions (
    message_id  INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    emoji       TEXT NOT NULL,
    PRIMARY KEY (message_id, user_id)
);

CREATE TABLE IF NOT EXISTS recordings (
    id              INTEGER PRIMARY KEY,
    course_id       INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    mime            TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'uploaded'
                    CHECK (status IN ('uploaded', 'transcribing', 'summarizing', 'ready', 'failed')),
    transcript_json TEXT NOT NULL DEFAULT '[]',
    summary         TEXT NOT NULL DEFAULT '',
    key_points_json TEXT NOT NULL DEFAULT '[]',
    chapters_json   TEXT NOT NULL DEFAULT '[]',
    error           TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
