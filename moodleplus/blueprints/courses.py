"""רשימת הקורסים ועמוד הקורס."""
import time

from flask import Blueprint, current_app, render_template

from ..db import get_db
from ..security import current_user, login_required
from ..services.assignments import AssignmentService
from ..services.content import ContentService, FileStore
from ..services.chat import ChatService, ReadReceiptService
from ..services.courses import CourseService, EnrollmentService
from ..services.polls import PollService
from ..services.recordings import RecordingService

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
    context = {}
    context["attendance"] = _attendance_context(course_id, role)
    if role == "student":
        from .attendance import build_appeals

        context["attendance_history"] = build_appeals(db).history(course_id, current_user().id)
    context["chat_enabled"] = True
    # רק ההודעה האחרונה, לכרטיס שמוביל לצ׳אט. עוברת דרך אותה הסתרה של שולח אנונימי
    last = ChatService(db, poll_reader=PollService(db)).list_messages(course_id, current_user(), limit=1)
    context["chat_preview"] = last[0] if last else None
    context["chat_unread"] = ReadReceiptService(db).unread_count(course_id, current_user())
    context["recordings"] = RecordingService(db, FileStore(current_app.config["UPLOAD_DIR"])).list(
        course_id, include_drafts=role in ("admin", "lecturer")  # טיוטות רק למרצה ולמנהל
    )
    assignments = AssignmentService(db, FileStore(current_app.config["UPLOAD_DIR"]))
    context["assignments"] = assignments.list(course_id)
    if role == "student":
        context["my_submissions"] = assignments.my_submissions(course_id, current_user().id)
        context["my_zeros"] = assignments.my_zeros(course_id, current_user().id)
    else:
        context["assignment_counts"] = assignments.counts(course_id)
        context["student_count"] = len(enrollments.members(course_id, "student"))
    context["grades"] = _grades_context(course_id, role)
    context["now"] = time.time()
    return render_template(
        "courses/show.html",
        **context,
        course=course,
        role=role,
        can_manage=role in ("admin", "lecturer"),
        lecturers=enrollments.members(course_id, "lecturer"),
        blocks=ContentService(db, FileStore(current_app.config["UPLOAD_DIR"])).list(course_id),
    )


def _attendance_context(course_id: int, role: str) -> dict:
    from .attendance import section_context

    return section_context(course_id, role)


def _grades_context(course_id: int, role: str) -> dict:
    from .grades import section_context

    return section_context(course_id, role)
