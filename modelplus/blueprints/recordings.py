"""הקלטות: העלאה (מרצה), צפייה עם סיכום ופרקים (חברי הקורס)."""
from flask import Blueprint, current_app, flash, jsonify, redirect, request, send_file, url_for

from ..db import get_db
from ..security import current_user, login_required
from ..services.content import FileStore
from ..services.courses import EnrollmentService
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
    flash("ההקלטה הועלתה. התמלול והסיכום ייקחו כמה דקות", "success")
    return _back(course_id)


@bp.get("/recordings/<int:recording_id>/media")
@login_required
def media(recording_id: int):
    service = _service()
    rec = service.get(recording_id)
    EnrollmentService(get_db()).require_member(rec.course_id, current_user())
    # conditional=True מאפשר Range requests, כדי שהנגן יוכל לקפוץ לפרק
    return send_file(service.files.path(rec.file_path), mimetype=rec.mime, conditional=True)


@bp.get("/api/recordings/<int:recording_id>/status")
@login_required
def status(recording_id: int):
    rec = _service().get(recording_id)
    EnrollmentService(get_db()).require_member(rec.course_id, current_user())
    return jsonify(ok=True, status=rec.status, label=rec.status_label)


@bp.post("/recordings/<int:recording_id>/retry")
@login_required
def retry(recording_id: int):
    service = _service()
    rec = service.get(recording_id)
    EnrollmentService(get_db()).require_manager(rec.course_id, current_user())
    service.retry(recording_id)
    _enqueue(recording_id)
    return _back(rec.course_id)


@bp.post("/recordings/<int:recording_id>/delete")
@login_required
def delete(recording_id: int):
    service = _service()
    rec = service.get(recording_id)
    EnrollmentService(get_db()).require_manager(rec.course_id, current_user())
    service.delete(recording_id)
    flash("ההקלטה נמחקה", "success")
    return _back(rec.course_id)
