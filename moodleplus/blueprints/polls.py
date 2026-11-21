"""API של סקרים: יצירה (מרצה) והצבעה (סטודנט)."""
from flask import Blueprint, jsonify, request

from ..db import get_db
from ..errors import ValidationError
from ..security import current_user, login_required
from ..services.courses import EnrollmentService
from ..services.polls import PollService

bp = Blueprint("polls", __name__, url_prefix="/api")


@bp.post("/courses/<int:course_id>/polls")
@login_required
def create(course_id: int):
    EnrollmentService(get_db()).require_manager(course_id, current_user())
    body = request.get_json(silent=True) or {}
    options = body.get("options") or []
    if not isinstance(options, list):
        raise ValidationError("רשימת התשובות לא תקינה")
    message_id = PollService(get_db()).create(
        course_id, current_user(), body.get("question", ""), [str(o) for o in options],
        anonymous=body.get("anonymous", True) is not False,
    )
    return jsonify(ok=True, message_id=message_id)


@bp.post("/polls/<int:poll_id>/vote")
@login_required
def vote(poll_id: int):
    polls = PollService(get_db())
    poll = polls.get(poll_id)
    EnrollmentService(get_db()).require_member(poll["course_id"], current_user())
    try:
        option_id = int((request.get_json(silent=True) or {}).get("option_id"))
    except (TypeError, ValueError):
        raise ValidationError("בחר תשובה")
    polls.vote(poll_id, current_user(), option_id)
    return jsonify(ok=True, poll=polls.results(poll_id, current_user()))
