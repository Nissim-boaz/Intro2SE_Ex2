-- Moodle+ schema (SQLite, WAL)

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
    chat_locked INTEGER NOT NULL DEFAULT 0,  -- 1: רק מרצה ומנהל שולחים הודעות בצ׳אט
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
    method      TEXT NOT NULL CHECK (method IN ('audio', 'manual')),  -- audio: הטלפון קלט את הקוד הקולי. manual: המרצה סימן
    marked_by   INTEGER REFERENCES users(id) ON DELETE SET NULL      -- מי סימן ידנית
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_record_sample_student
    ON attendance_records (sample_id, student_id);

-- קודים שגויים ששלח סטודנט בדגימה. אחרי כמה ניסיונות הוא נחסם, כדי שאי אפשר יהיה לנחש את הקוד
CREATE TABLE IF NOT EXISTS attendance_attempts (
    sample_id   INTEGER NOT NULL REFERENCES attendance_samples(id) ON DELETE CASCADE,
    student_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    wrong       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (sample_id, student_id)
);

-- ערעור על נוכחות: סטודנט שסומן חסר בדגימה שנסגרה. ערעור אחד לכל דגימה
CREATE TABLE IF NOT EXISTS attendance_appeals (
    id          INTEGER PRIMARY KEY,
    sample_id   INTEGER NOT NULL REFERENCES attendance_samples(id) ON DELETE CASCADE,
    student_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected')),
    reply       TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL,
    resolved_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    resolved_at REAL NOT NULL DEFAULT 0,
    UNIQUE (sample_id, student_id)
);

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
    pinned_at    REAL NOT NULL DEFAULT 0,        -- 0: לא נעוצה. רק מרצה הקורס נועץ, עד 3 הודעות
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
    published       INTEGER NOT NULL DEFAULT 0,  -- 0: טיוטה שרק המרצה רואה
    -- משוב אישי למרצה על השיעור. רק מרצה הקורס רואה אותו, גם לא מנהל המערכת
    feedback_status TEXT NOT NULL DEFAULT '',    -- '' | pending | ready | failed
    feedback_json   TEXT NOT NULL DEFAULT '',
    feedback_error  TEXT NOT NULL DEFAULT '',
    feedback_job    INTEGER NOT NULL DEFAULT 0,  -- מונה בקשות: תוצאה של בקשה שבוטלה נזרקת
    feedback_at     REAL NOT NULL DEFAULT 0,     -- מתי נכתב המשוב
    transcript_edited_at REAL NOT NULL DEFAULT 0, -- משוב חדש מותר רק אם התמלול נערך אחרי המשוב
    uploaded_by     INTEGER REFERENCES users(id) ON DELETE SET NULL, -- המשוב האישי שייך לו
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- מטלות. due_at היא חותמת זמן (שניות), כדי שהשוואה לזמן ההגשה תהיה פשוטה
CREATE TABLE IF NOT EXISTS assignments (
    id          INTEGER PRIMARY KEY,
    course_id   INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    due_at      REAL NOT NULL,
    file_path   TEXT NOT NULL DEFAULT '',   -- קובץ מצורף מהמרצה (לא חובה)
    file_name   TEXT NOT NULL DEFAULT '',
    grades_published INTEGER NOT NULL DEFAULT 0,  -- 0: המרצה בודק, והסטודנטים עוד לא רואים ציונים
    weight           REAL NOT NULL DEFAULT 0,      -- אחוז מהציון הסופי בקורס
    -- פתרון לסטודנטים (לא חובה). מתפרסם רק אחרי המועד, והפרסום סוגר את ההגשה
    solution_path      TEXT NOT NULL DEFAULT '',
    solution_name      TEXT NOT NULL DEFAULT '',
    solution_published INTEGER NOT NULL DEFAULT 0,
    -- בדיקה עם AI: דגשים ופתרון לדוגמה (לא חובה), ומצב הבדיקה ברקע
    ai_guidelines    TEXT NOT NULL DEFAULT '',
    ai_solution_path TEXT NOT NULL DEFAULT '',
    ai_solution_name TEXT NOT NULL DEFAULT '',
    ai_status        TEXT NOT NULL DEFAULT '',     -- '' | running | done | failed | cancelled
    ai_error         TEXT NOT NULL DEFAULT '',
    ai_job           INTEGER NOT NULL DEFAULT 0,   -- מונה בקשות: תוצאה של בקשה שבוטלה נזרקת
    ai_done          INTEGER NOT NULL DEFAULT 0,
    ai_total         INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- הגשה אחת לכל סטודנט במטלה. הגשה חוזרת מחליפה את הקובץ
CREATE TABLE IF NOT EXISTS submissions (
    id            INTEGER PRIMARY KEY,
    assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    student_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    file_path     TEXT NOT NULL,
    file_name     TEXT NOT NULL,
    submitted_at  REAL NOT NULL,
    grade         INTEGER CHECK (grade IS NULL OR grade BETWEEN 0 AND 100),
    feedback      TEXT NOT NULL DEFAULT '',  -- הערת המרצה. רק הסטודנט והמרצים רואים
    graded_at     REAL NOT NULL DEFAULT 0,
    -- ערעור אחד על הציון: '' | pending | accepted | rejected
    appeal_status  TEXT NOT NULL DEFAULT '',
    appeal_text    TEXT NOT NULL DEFAULT '',
    appeal_reply   TEXT NOT NULL DEFAULT '',
    appeal_at      REAL NOT NULL DEFAULT 0,
    original_grade INTEGER,                   -- הציון לפני שערעור התקבל
    -- הצעת ה-AI. המרצה רואה, ורק אם הוא מאשר הציון והמשוב עוברים לסטודנט
    ai_grade       INTEGER,
    ai_reason      TEXT NOT NULL DEFAULT '',  -- למרצה
    ai_feedback    TEXT NOT NULL DEFAULT '',  -- טיוטת משוב בונה לסטודנט
    ai_deductions  TEXT NOT NULL DEFAULT '',  -- JSON: על מה ירדו נקודות, [{"points": 10, "reason": "..."}]
    ai_class_note  TEXT NOT NULL DEFAULT '',  -- ההגשה ביחס לכיתה, בלי שמות
    ai_summary     TEXT NOT NULL DEFAULT '',
    ai_off_topic   INTEGER NOT NULL DEFAULT 0,
    ai_flag        TEXT NOT NULL DEFAULT '',  -- למרצה בלבד: דמיון חשוד להגשה אחרת, או הגשה לא קשורה
    ai_error       TEXT NOT NULL DEFAULT '',
    ai_at          REAL NOT NULL DEFAULT 0,
    UNIQUE (assignment_id, student_id)
);

-- פניות למנהלי המערכת. פנייה שנסגרה (resolved/rejected) נמחקת 7 ימים אחרי closed_at
CREATE TABLE IF NOT EXISTS requests (
    id               INTEGER PRIMARY KEY,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject          TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'new'
                     CHECK (status IN ('new', 'in_progress', 'resolved', 'rejected')),
    created_at       REAL NOT NULL,
    updated_at       REAL NOT NULL,
    closed_at        REAL NOT NULL DEFAULT 0,
    requester_unseen INTEGER NOT NULL DEFAULT 0   -- 1: יש תשובה או שינוי סטטוס שהפונה עוד לא ראה
);

-- השרשור של פנייה: הודעות, ושינויי סטטוס (status לא ריק, body ריק)
CREATE TABLE IF NOT EXISTS request_messages (
    id          INTEGER PRIMARY KEY,
    request_id  INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    author_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT '',
    as_team     INTEGER NOT NULL DEFAULT 0,  -- 1: הפונה רואה ״מנהל המערכת״ בלי שם. מנהלים אחרים רואים מי כתב
    created_at  REAL NOT NULL
);

-- 0 שהמרצה רשם לסטודנט שלא הגיש. בלי זה ציון חסר פשוט לא נספר
CREATE TABLE IF NOT EXISTS assignment_zeros (
    assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    student_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (assignment_id, student_id)
);

-- מבחנים ובחנים. weight הוא אחוז מהציון הסופי, והציונים גלויים לסטודנטים רק אחרי published
CREATE TABLE IF NOT EXISTS exams (
    id         INTEGER PRIMARY KEY,
    course_id  INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('exam', 'quiz')),
    held_on    TEXT NOT NULL DEFAULT '',
    weight     REAL NOT NULL DEFAULT 0,
    published  INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS exam_grades (
    id             INTEGER PRIMARY KEY,
    exam_id        INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    student_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    grade          REAL NOT NULL CHECK (grade BETWEEN 0 AND 100),
    appeal_status  TEXT NOT NULL DEFAULT '',   -- '' | pending | accepted | rejected
    appeal_text    TEXT NOT NULL DEFAULT '',
    appeal_reply   TEXT NOT NULL DEFAULT '',
    appeal_at      REAL NOT NULL DEFAULT 0,
    original_grade REAL,                       -- הציון לפני שערעור התקבל
    UNIQUE (exam_id, student_id)
);

-- הודעות שמשתמש סימן בכוכב. אישי לגמרי: אף אחד אחר לא רואה
CREATE TABLE IF NOT EXISTS message_stars (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    starred_at REAL NOT NULL,
    PRIMARY KEY (user_id, message_id)
);

-- עיצוב אישי של הצ׳אט. course_id = 0 היא הבחירה לכל הצ׳אטים, וצ׳אט עם בחירה משלו גובר עליה.
-- שדה ריק: אין בחירה כאן, וממשיכים לבחירה הכללית או לברירת המחדל
CREATE TABLE IF NOT EXISTS chat_themes (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id  INTEGER NOT NULL DEFAULT 0,
    wallpaper  TEXT NOT NULL DEFAULT '',
    bubble     TEXT NOT NULL DEFAULT '',
    image_path TEXT NOT NULL DEFAULT '',
    version    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, course_id)
);

-- הגדרות שהאתר זוכר בין הפעלות. למשל admin_email: מי מנהל המערכת הראשי, כדי לדעת מתי ADMIN_EMAIL השתנה
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- בקשות הרשמה שמחכות למנהל מערכת. אישור יוצר משתמש ומוחק את הבקשה, וכך גם דחייה
CREATE TABLE IF NOT EXISTS signup_requests (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    email      TEXT NOT NULL UNIQUE,
    role       TEXT NOT NULL CHECK (role IN ('student', 'lecturer')),
    created_at REAL NOT NULL
);
