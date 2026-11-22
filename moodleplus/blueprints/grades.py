"""ציונים: מבחנים ובחנים, משקלים, טבלת הציונים של המרצה, וערעורים של סטודנטים."""
from flask import Blueprint, Response, flash, redirect, render_template, request, url_for

from ..db import get_db
from ..errors import ValidationError
from ..security import current_user, login_required
from ..services.courses import CourseService, EnrollmentService
from ..services.gradebook import TOTAL_WEIGHT, ExamService, Gradebook

bp = Blueprint("grades", __name__)


def section_context(course_id: int, role: str) -> dict:
    """מה שלשונית ״מטלות וציונים״ בעמוד הקורס צריכה. סטודנט מקבל רק את הציונים שלו שפורסמו."""
    db = get_db()
    components = Gradebook(db).components(course_id)
    ctx = {"weights": {c.id: c.weight for c in components if c.kind == "assignment"}}
    if role == "student":
        return ctx | {"mine": Gradebook(db).for_student(course_id, current_user().id)}
    exams = ExamService(db)
    return ctx | {"exams": exams.list(course_id), "exam_counts": exams.counts(course_id),
                  "total_weight": sum(c.weight for c in components)}


def _manage_course(course_id: int):
    EnrollmentService(get_db()).require_manager(course_id, current_user())
    return CourseService(get_db()).get(course_id)


def _manage_exam(exam_id: int):
    service = ExamService(get_db())
    exam = service.get(exam_id)
    EnrollmentService(get_db()).require_manager(exam.course_id, current_user())
    return service, exam


def _exam_page(exam_id: int):
    return redirect(url_for("grades.exam", exam_id=exam_id))


# ---------- lecturer: the whole course ----------
@bp.get("/courses/<int:course_id>/grades")
@login_required
def table(course_id: int):
    course = _manage_course(course_id)
    components, rows = Gradebook(get_db()).table(course_id)
    return render_template("grades/table.html", course=course, components=components, rows=rows,
                           total=sum(c.weight for c in components), total_weight=TOTAL_WEIGHT)


@bp.post("/courses/<int:course_id>/grades/weights")
@login_required
def weights(course_id: int):
    _manage_course(course_id)
    values = {k[2:]: v for k, v in request.form.items() if k.startswith("w_")}
    total = Gradebook(get_db()).set_weights(course_id, values)
    flash(f"המשקלים נשמרו ({total:g}% מתוך 100%)", "success")
    return redirect(url_for("grades.table", course_id=course_id))


@bp.get("/courses/<int:course_id>/grades.csv")
@login_required
def table_csv(course_id: int):
    _manage_course(course_id)
    return Response(Gradebook(get_db()).to_csv(course_id), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=grades_course_{course_id}.csv"})


# ---------- lecturer: one exam ----------
@bp.post("/courses/<int:course_id>/exams")
@login_required
def create(course_id: int):
    _manage_course(course_id)
    form = request.form
    exam = ExamService(get_db()).create(course_id, form.get("title", ""), form.get("kind", ""),
                                        form.get("held_on", ""), form.get("weight", ""))
    flash(f"ה{exam.kind_label} נוסף. עכשיו אפשר להזין ציונים", "success")
    return _exam_page(exam.id)


@bp.get("/exams/<int:exam_id>")
@login_required
def exam(exam_id: int):
    service, item = _manage_exam(exam_id)
    return render_template("grades/exam.html", exam=item, course=CourseService(get_db()).get(item.course_id),
                           roster=service.roster(exam_id), appeals=service.pending_appeals(exam_id))


@bp.post("/exams/<int:exam_id>/edit")
@login_required
def edit(exam_id: int):
    service, _ = _manage_exam(exam_id)
    form = request.form
    service.update(exam_id, form.get("title", ""), form.get("kind", ""), form.get("held_on", ""))
    flash("השינויים נשמרו", "success")
    return _exam_page(exam_id)


@bp.post("/exams/<int:exam_id>/delete")
@login_required
def delete(exam_id: int):
    service, item = _manage_exam(exam_id)
    service.delete(exam_id)
    flash(f"ה{item.kind_label} נמחק", "success")
    return redirect(url_for("courses.show", course_id=item.course_id) + "#assignments")


@bp.post("/exams/<int:exam_id>/grades")
@login_required
def save_grades(exam_id: int):
    """g_<id> הוא מה שהוקלד ו-o_<id> מה שהיה כשהעמוד נטען. נשמר רק מה שהשתנה, כך שטופס ישן
    לא דורס ציון שהתעדכן בינתיים (למשל אחרי ערעור, או על ידי מרצה אחר)."""
    service, _ = _manage_exam(exam_id)
    changes = {}
    for key, value in request.form.items():
        if key.startswith("g_") and key[2:].isdigit() and value.strip() != request.form.get("o_" + key[2:], ""):
            changes[int(key[2:])] = value
    count = service.save_grades(exam_id, changes)
    flash(f"נשמרו {count} שינויים" if count else "לא היה מה לשמור", "success")
    return _exam_page(exam_id)


@bp.post("/exams/<int:exam_id>/import")
@login_required
def import_grades(exam_id: int):
    service, _ = _manage_exam(exam_id)
    file = request.files.get("file")
    if not file or not file.filename:
        raise ValidationError("בחר קובץ להעלאה")
    report = service.import_file(exam_id, file.filename, file.read())
    msg = f"נקלטו {report.updated} ציונים"
    if report.unknown:
        msg += f". {report.unknown} מיילים לא שייכים לסטודנטים בקורס"
    if report.invalid:
        msg += f". {report.invalid} שורות לא תקינות"
    flash(msg, "success" if report.updated else "error")
    return _exam_page(exam_id)


@bp.post("/exams/<int:exam_id>/publish")
@login_required
def publish(exam_id: int):
    service, _ = _manage_exam(exam_id)
    published = request.form.get("published") == "1"
    count = service.set_published(exam_id, published)
    flash(f"הציונים פורסמו. {count} סטודנטים רואים עכשיו את הציון שלהם" if published
          else "הציונים הוסתרו מהסטודנטים", "success")
    return _exam_page(exam_id)


@bp.post("/exam-grades/<int:grade_id>/appeal/resolve")
@login_required
def resolve_appeal(grade_id: int):
    service = ExamService(get_db())
    grade = service.get_grade(grade_id)
    _manage_exam(grade.exam_id)
    accept = request.form.get("decision") == "accept"
    service.resolve_appeal(grade_id, accept, request.form.get("reply", ""), request.form.get("grade", ""))
    flash("הערעור התקבל והציון עודכן" if accept else "הערעור נדחה", "success")
    return _exam_page(grade.exam_id)


# ---------- student ----------
@bp.post("/exam-grades/<int:grade_id>/appeal")
@login_required
def appeal(grade_id: int):
    service = ExamService(get_db())
    course_id = service.get(service.get_grade(grade_id).exam_id).course_id
    EnrollmentService(get_db()).require_student(course_id, current_user())
    service.appeal(grade_id, current_user(), request.form.get("text", ""))
    flash("הערעור נשלח למרצה", "success")
    return redirect(url_for("courses.show", course_id=course_id) + "#assignments")
