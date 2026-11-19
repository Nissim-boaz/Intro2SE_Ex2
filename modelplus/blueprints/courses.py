"""רשימת הקורסים ועמוד הקורס."""
from flask import Blueprint, current_app, render_template

from ..db import get_db
from ..security import current_user, login_required
from ..services.content import ContentService, FileStore
from ..services.courses import CourseService, EnrollmentService

bp = Blueprint("courses", __name__)


@bp.get("/")
@login_required
def index():
    db = get_db()
    enrollments = EnrollmentService(db)
    courses = enrollments.courses_for(current_user())
    lecturers = {c.id: enrollments.members(c.id, "lecturer") for c in courses}
    return render_template("courses/index.html", courses=courses, lecturers=lecturers)


@bp.get("/courses/<int:course_id>")
@login_required
def show(course_id: int):
    db = get_db()
    course = CourseService(db).get(course_id)
    enrollments = EnrollmentService(db)
    role = enrollments.require_member(course_id, current_user())
    return render_template(
        "courses/show.html",
        course=course,
        role=role,
        can_manage=role in ("admin", "lecturer"),
        lecturers=enrollments.members(course_id, "lecturer"),
        blocks=ContentService(db, FileStore(current_app.config["UPLOAD_DIR"])).list(course_id),
    )
