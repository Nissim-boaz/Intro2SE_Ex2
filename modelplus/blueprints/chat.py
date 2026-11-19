"""API של הצ׳אט. הדפדפן עושה polling כל 2.5 שניות."""
import time

from flask import Blueprint, jsonify, request

from ..db import get_db
from ..errors import ValidationError
from ..security import current_user, login_required
from ..services.chat import ChatService, ReactionService
from ..services.courses import EnrollmentService
from ..services.polls import PollService

bp = Blueprint("chat", __name__, url_prefix="/api")

# חפיפה קטנה בין בקשות, כדי שלא נפספס הודעה שנכתבה בדיוק בזמן הבקשה. הדפדפן מסנן כפילויות לפי id.
OVERLAP_SECONDS = 1.0


def _chat() -> ChatService:
    db = get_db()
    return ChatService(db, poll_reader=PollService(db))


def _require_member_of_message(message_id: int):
    row = _chat().get_row(message_id)
    EnrollmentService(get_db()).require_member(row["course_id"], current_user())
    return row


@bp.get("/courses/<int:course_id>/chat")
@login_required
def messages(course_id: int):
    EnrollmentService(get_db()).require_member(course_id, current_user())
    since = request.args.get("since", type=float)
    now = time.time()
    items = _chat().list_messages(course_id, current_user(), since=since)
    return jsonify(ok=True, now=now - OVERLAP_SECONDS, messages=items)


@bp.post("/courses/<int:course_id>/chat")
@login_required
def send(course_id: int):
    EnrollmentService(get_db()).require_member(course_id, current_user())
    body = request.get_json(silent=True) or {}
    reply_to = body.get("reply_to")
    try:
        reply_to = int(reply_to) if reply_to else None
    except (TypeError, ValueError):
        raise ValidationError("ההודעה שמגיבים אליה לא נמצאה")
    message_id = _chat().send(
        course_id, current_user(), body.get("body", ""), reply_to_id=reply_to, anonymous=bool(body.get("anonymous"))
    )
    return jsonify(ok=True, id=message_id)


@bp.post("/messages/<int:message_id>/reactions")
@login_required
def react(message_id: int):
    _require_member_of_message(message_id)
    emoji = (request.get_json(silent=True) or {}).get("emoji", "")
    mine = ReactionService(get_db()).toggle(message_id, current_user(), emoji)
    return jsonify(ok=True, mine=mine)


@bp.get("/messages/<int:message_id>/reactions")
@login_required
def who_reacted(message_id: int):
    _require_member_of_message(message_id)
    return jsonify(ok=True, reactions=ReactionService(get_db()).who(message_id))
