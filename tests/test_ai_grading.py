import io
import re
import zipfile

import pytest
from werkzeug.datastructures import FileStorage

from moodleplus.db import connect
from moodleplus.errors import ValidationError
from moodleplus.services.ai_grading import AIGradingService
from moodleplus.services.content import FileStore
from moodleplus.services.courses import CourseService, EnrollmentService
from moodleplus.services.documents import read_document
from moodleplus.services.llm import LLMError, LLMProvider
from moodleplus.services.users import UserService
from tests.conftest import login

DUE = "2026-11-25T23:59"
COPIED = " ".join(f"המחלקה Student{i} מחזיקה רשימה של קורסים ומתודה register שמוסיפה קורס חדש" for i in range(12))


class FakeLLM(LLMProvider):
    """עונה לפי סוג הבקשה: בדיקת הגשה או השוואה לכיתה."""

    def __init__(self, fail_on=None):
        self.prompts = []
        self.files = []
        self.fail_on = fail_on

    def generate_json(self, prompt, files=None):
        self.prompts.append(prompt)
        self.files.append(files or [])
        if "תקצירים של כל ההגשות" in prompt:
            keys = re.findall(r"\[(h\d+)\]", prompt)
            return {"notes": {k: ("בשונה מרוב הכיתה, לא צירפת דיאגרמה" if i == 0 else "") for i, k in enumerate(keys)}}
        if self.fail_on and self.fail_on in prompt:
            raise LLMError("busy")
        grade = 90 if "דיאגרמה" in prompt.split("ההגשה של הסטודנט")[1] else 60
        return {"grade": grade, "reason": "נימוק", "feedback": "עבודה טובה, כדאי להרחיב", "summary": "תקציר",
                "off_topic": "מתכון לעוגה" in prompt,
                "deductions": [] if grade == 90 else [{"points": 25, "reason": "לא צירפת דיאגרמה"},
                                                       {"points": 15, "reason": "חסר ריבוי בקשרים"},
                                                       {"points": 0, "reason": "ignored"}, "broken"]}


def _file(name, text):
    return FileStorage(io.BytesIO(text.encode("utf-8")), name)


@pytest.fixture
def world(db, people, tmp_path):
    files = FileStore(str(tmp_path / "files"))
    ai = AIGradingService(db, files)
    users = UserService(db)
    extra = [users.create(f"x{i}@test.ac.il", f"סטודנט {i}", "student") for i in range(3)]
    EnrollmentService(db).enroll_many(people["course"].id, extra)
    a = ai.assignments.create(people["course"].id, "מטלה 1", "כתבו מחלקות", DUE)
    return ai, a, [people["s1"], people["s2"]] + extra


def test_review_suggests_without_grading_and_compares_the_class(world, people):
    ai, a, students = world
    texts = ["יש דיאגרמה ומחלקות", "רק מחלקות", "דיאגרמה מלאה", "מחלקות בלבד", "מתכון לעוגה"]
    for st, text in zip(students, texts):
        ai.assignments.submit(a.id, st, "hw.txt", _file("hw.txt", text))
    ai.save_settings(a.id, "דיאגרמה שווה 40 נקודות", "sol.txt", _file("sol.txt", "פתרון: מחלקה Course"))
    job = ai.request(a.id)
    llm = FakeLLM()
    ai.run(a.id, job, llm)

    first = llm.prompts[0]
    assert "דיאגרמה שווה 40 נקודות" in first and "פתרון: מחלקה Course" in first and "כתבו מחלקות" in first
    roster = {u.id: s for u, s in ai.assignments.roster(a.id)}
    s1 = roster[students[0].id]
    assert s1.ai_ready and s1.ai_grade == 90 and not s1.graded  # only a suggestion
    assert roster[students[1].id].ai_grade == 60
    assert "לא קשורה" in roster[students[4].id].ai_flag
    notes = [s.ai_class_note for s in roster.values() if s.ai_class_note]
    assert notes == ["בשונה מרוב הכיתה, לא צירפת דיאגרמה"]
    assert not any(st.name in llm.prompts[-1] for st in students)  # no names go to the class pass
    assert ai.assignments.get(a.id).ai_status == "done"


def test_approve_one_and_all_and_feedback_includes_the_class_note(world):
    ai, a, students = world
    for st in students[:4]:
        ai.assignments.submit(a.id, st, "hw.txt", _file("hw.txt", "דיאגרמה"))
    ai.run(a.id, ai.request(a.id), FakeLLM())
    roster = [s for _, s in ai.assignments.roster(a.id) if s]
    noted = next(s for s in roster if s.ai_class_note)
    ai.approve(noted.id)
    got = ai.assignments.get_submission(noted.id)
    assert got.grade == 90 and "עבודה טובה" in got.feedback and "ביחס לכיתה:" in got.feedback
    other = next(s for s in roster if s.id != noted.id)
    ai.assignments.grade(other.id, "55", "המרצה כתב")
    assert ai.approve_all(a.id) == 2  # the lecturer's own grade and the approved one stay
    assert ai.assignments.get_submission(other.id).grade == 55
    assert not ai.assignments.submission_of(a.id, students[0].id).grade_visible  # still unpublished


def test_flags_copied_submissions_for_the_lecturer(world):
    ai, a, students = world
    ai.assignments.submit(a.id, students[0], "a.txt", _file("a.txt", COPIED))
    ai.assignments.submit(a.id, students[1], "b.txt", _file("b.txt", COPIED + " ושורה נוספת"))
    ai.assignments.submit(a.id, students[2], "c.txt", _file("c.txt", " ".join(f"מילה{i}" for i in range(300))))
    ai.run(a.id, ai.request(a.id), FakeLLM())
    roster = {u.id: s for u, s in ai.assignments.roster(a.id)}
    assert students[1].name in roster[students[0].id].ai_flag and "דומה מאוד" in roster[students[0].id].ai_flag
    assert students[0].name in roster[students[1].id].ai_flag
    assert roster[students[2].id].ai_flag == ""


def test_only_new_or_resubmitted_work_is_reviewed_and_cancel_stops(world, db):
    ai, a, students = world
    ai.assignments.submit(a.id, students[0], "a.txt", _file("a.txt", "דיאגרמה"))
    ai.run(a.id, ai.request(a.id), FakeLLM())
    with pytest.raises(ValidationError):
        ai.request(a.id)  # nothing new
    ai.assignments.submit(a.id, students[1], "b.txt", _file("b.txt", "טקסט"))
    assert ai.to_review(a.id) == [ai.assignments.submission_of(a.id, students[1].id).id]
    job = ai.request(a.id)
    ai.cancel(a.id)
    llm = FakeLLM()
    ai.run(a.id, job, llm)
    assert llm.prompts == [] and ai.assignments.get(a.id).ai_status == "cancelled"
    # resubmitting clears the old suggestion
    ai.assignments.submit(a.id, students[0], "a2.txt", _file("a2.txt", "חדש"))
    assert not ai.assignments.submission_of(a.id, students[0].id).ai_ready


def test_a_failed_review_is_kept_per_submission(world):
    ai, a, students = world
    ai.assignments.submit(a.id, students[0], "a.txt", _file("a.txt", "תקלה"))
    ai.assignments.submit(a.id, students[1], "b.txt", _file("b.txt", "דיאגרמה"))
    ai.run(a.id, ai.request(a.id), FakeLLM(fail_on="תקלה"))
    s0 = ai.assignments.submission_of(a.id, students[0].id)
    assert s0.ai_grade is None and s0.ai_error
    a2 = ai.assignments.get(a.id)
    assert a2.ai_status == "done" and "1 הגשות לא נבדקו" in a2.ai_error


def test_reading_documents(tmp_path):
    docx = tmp_path / "w.docx"
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:p><w:t>שלום</w:t></w:p><w:p><w:t>עולם</w:t></w:p></w:document>")
    assert read_document(docx, "w.docx").text.split() == ["שלום", "עולם"]
    code = tmp_path / "src.zip"
    with zipfile.ZipFile(code, "w") as z:
        z.writestr("src/Main.java", "class Main {}")
        z.writestr("img.png", b"\x89PNG")
    doc = read_document(code, "src.zip")
    assert "class Main" in doc.text and "img.png" not in doc.text
    img = tmp_path / "d.png"
    img.write_bytes(b"\x89PNG data")
    assert read_document(img, "d.png").blobs[0][0] == "image/png"
    weird = tmp_path / "x.exe"
    weird.write_bytes(b"MZ")
    assert read_document(weird, "x.exe").error


def test_routes_are_lecturer_only(app, client):
    conn = connect(app.config["DATABASE"])
    users = UserService(conn)
    lect = users.create("l@test.ac.il", "מרצה", "lecturer")
    stud = users.create("s@test.ac.il", "סטודנטית", "student")
    course = CourseService(conn).create("קורס")
    EnrollmentService(conn).enroll_many(course.id, [lect, stud])
    conn.close()
    login(client, lect.id)
    client.post(f"/courses/{course.id}/assignments", data={"title": "מטלה", "due": DUE})
    login(client, stud.id)
    client.post("/assignments/1/submit", data={"file": (io.BytesIO(b"x"), "a.txt")}, content_type="multipart/form-data")
    assert "בדיקה עם AI" not in client.get("/assignments/1").get_data(as_text=True)
    client.post("/assignments/1/ai/run")
    assert client.get("/api/assignments/1/ai-status").status_code == 403
    login(client, lect.id)
    assert "בדיקה עם AI" in client.get("/assignments/1").get_data(as_text=True)
    client.post("/assignments/1/ai/settings", data={"guidelines": "דגש"})
    client.post("/assignments/1/ai/run")
    status = client.get("/api/assignments/1/ai-status").get_json()
    assert status["status"] == "running" and status["total"] == 1


def test_feedback_says_where_points_went_and_fills_the_form(app, client):
    conn = connect(app.config["DATABASE"])
    users = UserService(conn)
    lect = users.create("lf@test.ac.il", "מרצה", "lecturer")
    stud = users.create("sf@test.ac.il", "סטודנטית", "student")
    course = CourseService(conn).create("קורס")
    EnrollmentService(conn).enroll_many(course.id, [lect, stud])
    files = FileStore(app.config["UPLOAD_DIR"])
    ai = AIGradingService(conn, files)
    a = ai.assignments.create(course.id, "מטלה", "", DUE)
    sub = ai.assignments.submit(a.id, stud, "hw.txt", _file("hw.txt", "רק מחלקות"))
    ai.run(a.id, ai.request(a.id), FakeLLM())
    got = ai.assignments.get_submission(sub.id)
    assert got.ai_deductions == ((25.0, "לא צירפת דיאגרמה"), (15.0, "חסר ריבוי בקשרים"))
    text = got.ai_student_feedback
    assert "עבודה טובה" in text and "על מה ירדו נקודות:" in text and "• 25 נקודות: לא צירפת דיאגרמה" in text
    conn.close()

    login(client, lect.id)
    page = client.get(f"/assignments/{a.id}").get_data(as_text=True)
    assert "אשר ושלח לסטודנט" in page and "• 25 נקודות: לא צירפת דיאגרמה" in page and 'value="60"' in page
    client.post(f"/submissions/{sub.id}/grade", data={"grade": "62", "feedback": text + " (המרצה הוסיף)"})
    page = client.get(f"/assignments/{a.id}").get_data(as_text=True)
    assert "השתמש במשוב של ה-AI" in page and "אשר ושלח לסטודנט" not in page
    client.post(f"/assignments/{a.id}/publish-grades", data={"published": "1"})
    login(client, stud.id)
    page = client.get(f"/assignments/{a.id}").get_data(as_text=True)
    assert "לא צירפת דיאגרמה" in page and "(המרצה הוסיף)" in page and ">62<" in page
