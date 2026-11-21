"""נתוני דמו: python seed.py --reset

יוצר אדמין, מרצה, את כל הסטודנטים מ-data/students.csv, קורס עם תכנים,
שיעור קודם עם נוכחות, מטלות עם הגשות, הודעות בצ׳אט וסקר.
"""
import argparse
import random
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # לפני ה-import של Config, כדי שיקרא את הערכים מ-.env

from moodleplus.config import Config  # noqa: E402
from moodleplus.db import connect, init_schema
from moodleplus.services.assignments import AssignmentService
from moodleplus.services.chat import ChatService, ReactionService
from moodleplus.services.content import ContentService, FileStore
from moodleplus.services.courses import CourseService, EnrollmentService
from moodleplus.services.polls import PollService
from moodleplus.services.users import StudentImporter, UserService

ROOT = Path(__file__).resolve().parent


def seed(db_path: str, reset: bool) -> None:
    if reset:
        for suffix in ("", "-wal", "-shm"):
            Path(db_path + suffix).unlink(missing_ok=True)
    db = connect(db_path)
    init_schema(db)
    users = UserService(db)
    if users.find_by_email("lecturer@example.com"):
        print("נתוני הדמו כבר קיימים. הרץ עם --reset כדי להתחיל מחדש.")
        return

    admin = users.ensure(Config.ADMIN_EMAIL, "מנהל המערכת", "admin")
    lecturer = users.create("lecturer@example.com", "ד״ר נועה לוי", "lecturer")
    demo_student = users.create("student@example.com", "סטודנט לדוגמה", "student")
    imported = StudentImporter(users).import_file("students.csv", (ROOT / "data" / "students.csv").read_bytes())
    students = [demo_student] + imported.users

    courses = CourseService(db)
    oop = courses.create(
        "מבוא להנדסת תוכנה",
        "7036010",
        "עיצוב מונחה עצמים, UML, תבניות עיצוב ובדיקות. סמסטר א׳.",
    )
    other = courses.create("מבני נתונים", "7027910", "רשימות, עצים, ערימות וגרפים.")
    enroll = EnrollmentService(db)
    enroll.enroll_many(oop.id, [lecturer] + students)
    enroll.enroll_many(other.id, [lecturer] + students[:30])

    content = ContentService(db, FileStore(Config.UPLOAD_DIR))
    content.add(oop.id, "text", title="ברוכים הבאים",
                body="שיעורים בימי ראשון 10:00 עד 13:00 בבניין 3.\nשעות קבלה: יום שני 12:00, בתיאום מראש במייל.")
    content.add(oop.id, "link", title="סילבוס הקורס", url="https://www.ariel.ac.il", body="נושאים, ציון ומועדים")
    content.add(oop.id, "file", title="מצגת שיעור 1: מבוא ל-UML", file_name="lesson1_uml.txt",
                file_data="מצגת לדוגמה. כאן תהיה המצגת האמיתית.".encode("utf-8"))

    _seed_attendance(db, oop.id, lecturer, students)
    _seed_chat(db, oop.id, lecturer, students)
    _seed_assignments(db, oop.id, students)
    print(f"נוצרו: אדמין ({admin.email}), מרצה, {len(students)} סטודנטים ו-2 קורסים.")
    print("להתחברות בדמו: MOCK_AUTH=1 ואז בחר תפקיד ומשתמש בעמוד ההתחברות.")


def _seed_attendance(db, course_id, lecturer, students) -> None:
    """שיעור 1 שכבר עבר: שתי דגימות, רוב הכיתה נוכחת וכמה רשומות חשודות."""
    rnd = random.Random(7)
    start = time.time() - 7 * 24 * 3600
    lesson_id = db.execute("INSERT INTO lessons (course_id, number) VALUES (?, 1)", (course_id,)).lastrowid
    for seq in (1, 2):
        opened = start + seq * 1800
        sample_id = db.execute(
            "INSERT INTO attendance_samples (lesson_id, seq, opened_at, closes_at, opened_by) VALUES (?, ?, ?, ?, ?)",
            (lesson_id, seq, opened, opened + 120, lecturer.id),
        ).lastrowid
        for st in students:
            roll = rnd.random()
            if roll < 0.12:
                continue  # לא הגיע
            status, method, reasons = ("ok", "qr_audio", "")
            if roll > 0.95:
                status, method, reasons = ("suspicious", "qr_only", "no_audio")
            db.execute(
                "INSERT INTO attendance_records (sample_id, student_id, at, ip, method, status, reasons) "
                "VALUES (?, ?, ?, '10.0.0.1', ?, ?, ?)",
                (sample_id, st.id, opened + rnd.uniform(5, 100), method, status, reasons),
            )
    db.commit()


def _seed_assignments(db, course_id, students) -> None:
    """מטלה שהמועד שלה עבר (עם הגשות, חלקן בדוקות) ומטלה פתוחה."""
    import io
    from datetime import datetime, timedelta

    from werkzeug.datastructures import FileStorage

    def pdf(name):
        return FileStorage(io.BytesIO(b"%PDF-1.4 demo"), name)

    def local(dt):
        return dt.strftime("%Y-%m-%dT%H:%M")

    now = datetime.now()
    clock = [time.time()]
    service = AssignmentService(db, FileStore(Config.UPLOAD_DIR), clock=lambda: clock[0])
    first = service.create(
        course_id, "מטלה 1: דרישות ו-Use Cases",
        "כתבו מסמך דרישות קצר ודיאגרמת Use Case למערכת קורסים.\nהגשה בזוגות, קובץ PDF אחד.",
        local((now - timedelta(days=6)).replace(hour=23, minute=59)),
    )
    second = service.create(
        course_id, "מטלה 2: עיצוב ומימוש מערכת קורסים",
        "עיצוב ומימוש של מערכת קורסים.\nצרפו דיאגרמת מחלקות ודיאגרמת רצף, וקישור לקוד ב-GitHub.",
        local((now + timedelta(days=4)).replace(hour=23, minute=59)),
        "assignment2.pdf", pdf("assignment2.pdf"),
    )
    rng = random.Random(7)
    for i, student in enumerate(students[:70]):
        late = i % 9 == 0
        clock[0] = first.due_at + (3600 if late else -86400 * rng.uniform(.2, 3))
        sub = service.submit(first.id, student, f"hw1_{i + 1}.pdf", pdf(f"hw1_{i + 1}.pdf"))
        if i < 45:
            service.grade(sub.id, str(rng.randint(72, 100)), "עבודה טובה. כדאי לפרט יותר את התרחישים החלופיים." if i % 4 == 0 else "")
    for i, student in enumerate(students[1:25]):
        clock[0] = time.time() - 3600 * rng.uniform(1, 40)
        service.submit(second.id, student, f"hw2_{i + 1}.pdf", pdf(f"hw2_{i + 1}.pdf"))


def _seed_chat(db, course_id, lecturer, students) -> None:
    chat = ChatService(db)
    reactions = ReactionService(db)
    a, b, c = students[1], students[2], students[3]
    q1 = chat.send(course_id, a, "מישהו הבין מה ההבדל בין aggregation ל-composition?")
    r1 = chat.send(course_id, b, "ב-composition החלק לא קיים בלי השלם. אם מוחקים את הבית, החדרים נמחקים איתו", reply_to_id=q1)
    reactions.toggle(r1, a, "🙏")
    reactions.toggle(r1, c, "👍")
    reactions.toggle(r1, lecturer, "👍")
    chat.send(course_id, c, "אפשר לקבל הארכה למטלה 2?", anonymous=True)
    ann = chat.send(course_id, lecturer, "תזכורת: ביום ראשון יש דגימת נוכחות בתחילת השיעור. תביאו טלפון 📱")
    for st in students[4:12]:
        reactions.toggle(ann, st, "👍")
    reactions.toggle(ann, students[12], "😂")

    polls = PollService(db)
    message_id = polls.create(course_id, lecturer, "על מה לחזור בשיעור הבא?",
                              ["Class diagram", "Sequence diagram", "Design Patterns", "בדיקות עם pytest"])
    poll_id = db.execute("SELECT poll_id FROM messages WHERE id = ?", (message_id,)).fetchone()[0]
    options = [o["id"] for o in polls.results(poll_id, lecturer)["options"]]
    rnd = random.Random(3)
    for st in students[1:40]:
        polls.vote(poll_id, st, rnd.choices(options, weights=[2, 5, 4, 1])[0])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="יצירת נתוני דמו ל-Moodle+")
    parser.add_argument("--reset", action="store_true", help="מחק את ה-DB הקיים לפני היצירה")
    seed(Config.DATABASE, parser.parse_args().reset)
