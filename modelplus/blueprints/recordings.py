"""הקלטות: העלאה (מרצה), צפייה עם סיכום ופרקים (חברי הקורס)."""
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for

from ..db import get_db
from ..security import current_user, login_required
from ..services.content import FileStore
from ..services.courses import CourseService, EnrollmentService
from ..services.recordings import RecordingService

bp = Blueprint("recordings", __name__)


def _service() -> RecordingService:
    return RecordingService(get_db(), FileStore(current_app.config["UPLOAD_DIR"]))


def _enqueue(recording_id: int) -> None:
    runner = current_app.extensions.get("recording_runner")
    if runner:
        runner.enqueue(recording_id)


def _back(course_id: int):
    return redirect(url_for("courses.show", course_id=course_id) + "#recordings")


@bp.post("/courses/<int:course_id>/recordings")
@login_required
def upload(course_id: int):
    EnrollmentService(get_db()).require_manager(course_id, current_user())
    file = request.files.get("file")
    rec = _service().create(
        course_id, request.form.get("title", ""), file.filename if file else "", file.mimetype if file else "", file
    )
    _enqueue(rec.id)
    flash("ההקלטה הועלתה כטיוטה. אחרי התמלול והסיכום תוכל לעבור עליה ולפרסם לסטודנטים", "success")
    return redirect(url_for("recordings.show", recording_id=rec.id))


def _visible(recording_id: int):
    """ההקלטה אם הצופה רשאי לראות אותה: חבר בקורס, וטיוטה רק למרצה ולמנהל."""
    service = _service()
    rec = service.get(recording_id)
    role = EnrollmentService(get_db()).require_member(rec.course_id, current_user())
    can_manage = role in ("admin", "lecturer")
    return service, service.get_visible(recording_id, can_manage), can_manage


def _managed(recording_id: int):
    service = _service()
    rec = service.get(recording_id)
    EnrollmentService(get_db()).require_manager(rec.course_id, current_user())
    return service, rec


@bp.get("/recordings/<int:recording_id>")
@login_required
def show(recording_id: int):
    """עמוד ההקלטה: נגן, ראשי פרקים, סיכום ותמלול. בעמוד הקורס יש רק כרטיס שמוביל לכאן."""
    _, rec, can_manage = _visible(recording_id)
    return render_template(
        "recordings/show.html",
        rec=rec,
        course=CourseService(get_db()).get(rec.course_id),
        can_manage=can_manage,
        editing=can_manage and request.args.get("edit") == "1" and rec.editable,
    )


@bp.post("/recordings/<int:recording_id>/edit")
@login_required
def edit(recording_id: int):
    service, rec = _managed(recording_id)
    form = request.form
    service.update_details(
        recording_id,
        form.get("title", ""),
        form.get("summary", ""),
        form.getlist("key_point"),
        list(zip(form.getlist("chapter_time"), form.getlist("chapter_title"))),
    )
    if rec.transcript:
        service.update_transcript(recording_id, form.getlist("segment"))
    flash("השינויים נשמרו", "success")
    return redirect(url_for("recordings.show", recording_id=recording_id))


@bp.post("/recordings/<int:recording_id>/publish")
@login_required
def publish(recording_id: int):
    service, rec = _managed(recording_id)
    published = request.form.get("published") == "1"
    service.set_published(recording_id, published)
    flash("ההקלטה פורסמה לסטודנטים" if published else "ההקלטה הוסתרה מהסטודנטים וחזרה להיות טיוטה", "success")
    return redirect(url_for("recordings.show", recording_id=recording_id))


@bp.get("/recordings/<int:recording_id>/media")
@login_required
def media(recording_id: int):
    service, rec, _ = _visible(recording_id)
    # conditional=True מאפשר Range requests, כדי שהנגן יוכל לקפוץ לפרק
    return send_file(service.files.path(rec.file_path), mimetype=rec.mime, conditional=True)


@bp.get("/api/recordings/<int:recording_id>/status")
@login_required
def status(recording_id: int):
    _, rec, _ = _visible(recording_id)
    return jsonify(ok=True, status=rec.status, label=rec.status_label)


@bp.post("/recordings/<int:recording_id>/retry")
@login_required
def retry(recording_id: int):
    service = _service()
    rec = service.get(recording_id)
    EnrollmentService(get_db()).require_manager(rec.course_id, current_user())
    service.retry(recording_id)
    _enqueue(recording_id)
    return redirect(url_for("recordings.show", recording_id=recording_id))


@bp.post("/recordings/<int:recording_id>/delete")
@login_required
def delete(recording_id: int):
    service = _service()
    rec = service.get(recording_id)
    EnrollmentService(get_db()).require_manager(rec.course_id, current_user())
    service.delete(recording_id)
    flash("ההקלטה נמחקה", "success")
    return _back(rec.course_id)
