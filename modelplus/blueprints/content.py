"""עריכת התכנים בעמוד הקורס (מרצה ואדמין) והורדת קבצים (חברי הקורס)."""
from flask import Blueprint, current_app, redirect, request, send_file, url_for

from ..db import get_db
from ..security import current_user, login_required
from ..services.content import ContentService, FileStore
from ..services.courses import EnrollmentService

bp = Blueprint("content", __name__)


def _service() -> ContentService:
    return ContentService(get_db(), FileStore(current_app.config["UPLOAD_DIR"]))


def _back(course_id: int):
    return redirect(url_for("courses.show", course_id=course_id) + "#content")


@bp.post("/courses/<int:course_id>/content")
@login_required
def add(course_id: int):
    EnrollmentService(get_db()).require_manager(course_id, current_user())
    form = request.form
    upload = request.files.get("file")
    _service().add(
        course_id,
        form.get("kind", "text"),
        title=form.get("title", ""),
        body=form.get("body", ""),
        url=form.get("url", ""),
        file_name=upload.filename if upload else "",
        file_data=upload.read() if upload and upload.filename else None,
    )
    return _back(course_id)


@bp.post("/content/<int:block_id>/edit")
@login_required
def edit(block_id: int):
    service = _service()
    block = service.get(block_id)
    EnrollmentService(get_db()).require_manager(block.course_id, current_user())
    service.update(block_id, request.form.get("title", ""), request.form.get("body", ""), request.form.get("url", ""))
    return _back(block.course_id)


@bp.post("/content/<int:block_id>/delete")
@login_required
def delete(block_id: int):
    service = _service()
    block = service.get(block_id)
    EnrollmentService(get_db()).require_manager(block.course_id, current_user())
    service.delete(block_id)
    return _back(block.course_id)


@bp.post("/content/<int:block_id>/move")
@login_required
def move(block_id: int):
    service = _service()
    block = service.get(block_id)
    EnrollmentService(get_db()).require_manager(block.course_id, current_user())
    service.move(block_id, -1 if request.form.get("dir") == "up" else 1)
    return _back(block.course_id)


@bp.get("/content/<int:block_id>/file")
@login_required
def download(block_id: int):
    service = _service()
    block = service.get(block_id)
    EnrollmentService(get_db()).require_member(block.course_id, current_user())
    # רק סוגים בטוחים נפתחים בדפדפן. כל השאר (למשל HTML) יורדים כקובץ
    inline = block.file_name.lower().endswith((".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp"))
    return send_file(service.files.path(block.file_path), download_name=block.file_name, as_attachment=not inline)
