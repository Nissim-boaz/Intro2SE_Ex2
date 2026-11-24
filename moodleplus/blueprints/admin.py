"""מסכי האדמין: משתמשים, קורסים ושיוכים."""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..db import get_db
from ..errors import ValidationError
from ..models import ROLE_LABELS
from ..security import current_user, role_required
from ..services.courses import CourseService, EnrollmentService
from ..services.users import StudentImporter, UserService

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _uploaded_file():
    file = request.files.get("file")
    if not file or not file.filename:
        raise ValidationError("בחר קובץ להעלאה")
    return file.filename, file.read()


def _report(result) -> None:
    msg = f"נוספו {result.created} סטודנטים חדשים, {result.existing} כבר היו במערכת"
    if result.skipped:
        msg += f". דילגתי על {len(result.skipped)} שורות בלי מייל תקין"
    flash(msg, "success")


# ---------- users ----------
@bp.get("/")
@role_required("admin")
def users():
    role = request.args.get("role", "")
    return render_template(
        "admin/users.html",
        users=UserService(get_db()).list(),  # הסינון לפי תפקיד קורה בדפדפן, בלי לטעון את העמוד מחדש
        main_admin=UserService(get_db()).main_admin_email(),
        role_filter=role,
        role_labels=ROLE_LABELS,
    )


@bp.post("/users")
@role_required("admin")
def create_user():
    form = request.form
    UserService(get_db()).create(form.get("email", ""), form.get("name", ""), form.get("role", "student"))
    flash("המשתמש נוסף", "success")
    return redirect(url_for("admin.users"))


@bp.post("/users/<int:user_id>")
@role_required("admin")
def update_user(user_id: int):
    role = request.form.get("role", "")
    if user_id == current_user().id and role != current_user().role:
        raise ValidationError("אי אפשר לשנות את התפקיד של עצמך")
    email = request.form.get("email")  # רק טופס העריכה שולח מייל. בחירת תפקיד ברשימה לא נוגעת בו
    UserService(get_db()).update(user_id, request.form.get("name", ""), role, email=email)
    flash("השינויים נשמרו", "success")
    return redirect(url_for("admin.users"))


@bp.post("/users/<int:user_id>/delete")
@role_required("admin")
def delete_user(user_id: int):
    if user_id == current_user().id:
        raise ValidationError("אי אפשר למחוק את המשתמש שלך")
    UserService(get_db()).delete(user_id)
    flash("המשתמש נמחק", "success")
    return redirect(url_for("admin.users"))


@bp.post("/users/import")
@role_required("admin")
def import_users():
    filename, data = _uploaded_file()
    _report(StudentImporter(UserService(get_db())).import_file(filename, data))
    return redirect(url_for("admin.users"))


# ---------- courses ----------
@bp.get("/courses")
@role_required("admin")
def courses():
    db = get_db()
    enrollments = EnrollmentService(db)
    rows = [
        (c, enrollments.members(c.id, "lecturer"), len(enrollments.members(c.id, "student")))
        for c in CourseService(db).list()
    ]
    return render_template("admin/courses.html", rows=rows)


@bp.post("/courses")
@role_required("admin")
def create_course():
    form = request.form
    course = CourseService(get_db()).create(form.get("name", ""), form.get("code", ""), form.get("description", ""))
    flash("הקורס נוצר. עכשיו אפשר לשייך אליו מרצה וסטודנטים", "success")
    return redirect(url_for("admin.course", course_id=course.id))


@bp.get("/courses/<int:course_id>")
@role_required("admin")
def course(course_id: int):
    db = get_db()
    course = CourseService(db).get(course_id)
    enrollments = EnrollmentService(db)
    members = enrollments.members(course_id)
    member_ids = {m.id for m in members}
    candidates = [u for u in UserService(db).list() if u.role != "admin" and u.id not in member_ids]
    return render_template(
        "admin/course.html",
        course=course,
        lecturers=[m for m in members if m.role == "lecturer"],
        students=[m for m in members if m.role == "student"],
        candidates=candidates,
    )


@bp.post("/courses/<int:course_id>/edit")
@role_required("admin")
def update_course(course_id: int):
    form = request.form
    CourseService(get_db()).update(course_id, form.get("name", ""), form.get("code", ""), form.get("description", ""))
    flash("השינויים נשמרו", "success")
    return redirect(url_for("admin.course", course_id=course_id))


@bp.post("/courses/<int:course_id>/delete")
@role_required("admin")
def delete_course(course_id: int):
    CourseService(get_db()).delete(course_id)
    flash("הקורס נמחק", "success")
    return redirect(url_for("admin.courses"))


@bp.post("/courses/<int:course_id>/members")
@role_required("admin")
def add_members(course_id: int):
    db = get_db()
    CourseService(db).get(course_id)
    users = UserService(db)
    picked = [users.get(int(uid)) for uid in request.form.getlist("user_id")]
    if not picked:
        raise ValidationError("בחר לפחות משתמש אחד")
    EnrollmentService(db).enroll_many(course_id, picked)
    flash(f"שויכו {len(picked)} משתמשים לקורס", "success")
    return redirect(url_for("admin.course", course_id=course_id))


@bp.post("/courses/<int:course_id>/members/<int:user_id>/delete")
@role_required("admin")
def remove_member(course_id: int, user_id: int):
    EnrollmentService(get_db()).unenroll(course_id, user_id)
    flash("השיוך הוסר", "success")
    return redirect(url_for("admin.course", course_id=course_id))


@bp.post("/courses/<int:course_id>/import")
@role_required("admin")
def import_to_course(course_id: int):
    db = get_db()
    CourseService(db).get(course_id)
    filename, data = _uploaded_file()
    result = StudentImporter(UserService(db)).import_file(filename, data)
    EnrollmentService(db).enroll_many(course_id, result.users)
    _report(result)
    return redirect(url_for("admin.course", course_id=course_id))
