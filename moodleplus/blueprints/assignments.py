"""מטלות: פרסום ועריכה (מרצה), הגשה (סטודנט), ובדיקה עם ציון (מרצה)."""
import time

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for

from ..db import get_db
from ..errors import Forbidden
from ..security import current_user, login_required
from ..services.assignments import AssignmentService
from ..services.content import FileStore
from ..services.courses import CourseService, EnrollmentService

bp = Blueprint("assignments", __name__)

# קבצים שבטוח לפתוח בדפדפן. כל השאר יורדים כקובץ
INLINE = (".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp")


def _service() -> AssignmentService:
    return AssignmentService(get_db(), FileStore(current_app.config["UPLOAD_DIR"]))


def _page(assignment_id: int):
    return redirect(url_for("assignments.show", assignment_id=assignment_id))


def _send(service: AssignmentService, rel: str, name: str):
    return send_file(service.files.path(rel), download_name=name, as_attachment=not name.lower().endswith(INLINE))


@bp.post("/courses/<int:course_id>/assignments")
@login_required
def create(course_id: int):
    EnrollmentService(get_db()).require_manager(course_id, current_user())
    form, upload = request.form, request.files.get("file")
    assignment = _service().create(
        course_id, form.get("title", ""), form.get("description", ""), form.get("due", ""),
        upload.filename if upload else "", upload,
    )
    flash("המטלה פורסמה לסטודנטים", "success")
    return _page(assignment.id)


@bp.get("/assignments/<int:assignment_id>")
@login_required
def show(assignment_id: int):
    service = _service()
    assignment = service.get(assignment_id)
    role = EnrollmentService(get_db()).require_member(assignment.course_id, current_user())
    can_manage = role in ("admin", "lecturer")
    return render_template(
        "assignments/show.html",
        a=assignment,
        course=CourseService(get_db()).get(assignment.course_id),
        can_manage=can_manage,
        is_student=role == "student",
        mine=service.submission_of(assignment_id, current_user().id) if role == "student" else None,
        roster=service.roster(assignment_id) if can_manage else [],
        now=time.time(),
    )


@bp.post("/assignments/<int:assignment_id>/edit")
@login_required
def edit(assignment_id: int):
    service = _service()
    EnrollmentService(get_db()).require_manager(service.get(assignment_id).course_id, current_user())
    form, upload = request.form, request.files.get("file")
    service.update(
        assignment_id, form.get("title", ""), form.get("description", ""), form.get("due", ""),
        upload.filename if upload else "", upload, remove_file=form.get("remove_file") == "1",
    )
    flash("המטלה עודכנה", "success")
    return _page(assignment_id)


@bp.post("/assignments/<int:assignment_id>/delete")
@login_required
def delete(assignment_id: int):
    service = _service()
    course_id = service.get(assignment_id).course_id
    EnrollmentService(get_db()).require_manager(course_id, current_user())
    service.delete(assignment_id)
    flash("המטלה נמחקה", "success")
    return redirect(url_for("courses.show", course_id=course_id) + "#assignments")


@bp.get("/assignments/<int:assignment_id>/file")
@login_required
def attachment(assignment_id: int):
    service = _service()
    assignment = service.get(assignment_id)
    EnrollmentService(get_db()).require_member(assignment.course_id, current_user())
    if not assignment.file_path:
        raise Forbidden("למטלה הזו אין קובץ מצורף")
    return _send(service, assignment.file_path, assignment.file_name)


@bp.post("/assignments/<int:assignment_id>/submit")
@login_required
def submit(assignment_id: int):
    service = _service()
    assignment = service.get(assignment_id)
    EnrollmentService(get_db()).require_student(assignment.course_id, current_user())
    upload = request.files.get("file")
    sub = service.submit(assignment_id, current_user(), upload.filename if upload else "", upload)
    flash("ההגשה נשלחה באיחור. המרצה יראה מתי הגשת" if sub.late else "ההגשה התקבלה", "success")
    return _page(assignment_id)


def _submission_for_viewer(submission_id: int):
    """ההגשה, אם הצופה הוא הסטודנט שהגיש או מרצה/מנהל של הקורס. סטודנט אחר לא רואה אותה."""
    service = _service()
    sub = service.get_submission(submission_id)
    assignment = service.get(sub.assignment_id)
    if sub.student_id != current_user().id:
        EnrollmentService(get_db()).require_manager(assignment.course_id, current_user())
    return service, sub


@bp.get("/submissions/<int:submission_id>/file")
@login_required
def submission_file(submission_id: int):
    service, sub = _submission_for_viewer(submission_id)
    return _send(service, sub.file_path, sub.file_name)


@bp.post("/assignments/<int:assignment_id>/publish-grades")
@login_required
def publish_grades(assignment_id: int):
    service = _service()
    EnrollmentService(get_db()).require_manager(service.get(assignment_id).course_id, current_user())
    published = request.form.get("published") == "1"
    count = service.set_grades_published(assignment_id, published)
    flash(f"הציונים פורסמו. {count} סטודנטים רואים עכשיו את הציון שלהם" if published
          else "הציונים הוסתרו מהסטודנטים", "success")
    return _page(assignment_id)


@bp.post("/submissions/<int:submission_id>/appeal")
@login_required
def appeal(submission_id: int):
    service = _service()
    sub = service.appeal(submission_id, current_user(), request.form.get("text", ""))
    flash("הערעור נשלח למרצה", "success")
    return redirect(url_for("assignments.show", assignment_id=sub.assignment_id) + "#my-submission")


@bp.post("/submissions/<int:submission_id>/appeal/resolve")
@login_required
def resolve_appeal(submission_id: int):
    service = _service()
    sub = service.get_submission(submission_id)
    EnrollmentService(get_db()).require_manager(service.get(sub.assignment_id).course_id, current_user())
    accept = request.form.get("decision") == "accept"
    service.resolve_appeal(submission_id, accept, request.form.get("reply", ""), request.form.get("grade", ""))
    flash("הערעור התקבל והציון עודכן" if accept else "הערעור נדחה", "success")
    return redirect(url_for("assignments.show", assignment_id=sub.assignment_id) + f"#sub-{submission_id}")


@bp.post("/submissions/<int:submission_id>/grade")
@login_required
def grade(submission_id: int):
    service = _service()
    sub = service.get_submission(submission_id)
    EnrollmentService(get_db()).require_manager(service.get(sub.assignment_id).course_id, current_user())
    service.grade(submission_id, request.form.get("grade", ""), request.form.get("feedback", ""))
    flash("הציון נשמר", "success")
    return redirect(url_for("assignments.show", assignment_id=sub.assignment_id) + f"#sub-{submission_id}")
