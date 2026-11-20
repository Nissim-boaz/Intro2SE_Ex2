"""רשימת הקורסים ועמוד הקורס."""
from flask import Blueprint, current_app, render_template

from ..db import get_db
from ..security import current_user, login_required
from ..services.content import ContentService, FileStore
from ..services.chat import ChatService
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
    context["chat_enabled"] = True
    # רק ההודעה האחרונה, לכרטיס שמוביל לצ׳אט. עוברת דרך אותה הסתרה של שולח אנונימי
    last = ChatService(db, poll_reader=PollService(db)).list_messages(course_id, current_user(), limit=1)
    context["chat_preview"] = last[0] if last else None
    context["recordings"] = RecordingService(db, FileStore(current_app.config["UPLOAD_DIR"])).list(
        course_id, include_drafts=role in ("admin", "lecturer")  # טיוטות רק למרצה ולמנהל
    )
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
    from .attendance import build_service

    service = build_service()
    sample = service.open_sample_for(course_id)
    lessons = service.lessons(course_id)
    ctx = {
        "open_sample": sample,
        "next_lesson": lessons[0].number if lessons else 1,
        "has_lessons": bool(lessons),
    }
    if sample:
        ctx["seconds_left"] = sample.seconds_left(service.clock.now())
        if role == "student":
            ctx["my_record"] = service.record_for(sample.id, current_user().id)
    return ctx
