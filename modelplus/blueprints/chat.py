"""API של הצ׳אט. הדפדפן עושה polling כל 2.5 שניות."""
import time

from flask import Blueprint, jsonify, render_template, request

from ..db import get_db
from ..errors import ValidationError
from ..security import current_user, login_required
from ..services.chat import ChatService, ReactionService, ReadReceiptService
from ..services.courses import CourseService, EnrollmentService
from ..services.polls import PollService

bp = Blueprint("chat", __name__, url_prefix="/api")
# העמוד עצמו (לא API) יושב ב-blueprint נפרד בלי הקידומת /api, ונרשם יחד עם bp
page_bp = Blueprint("chat_page", __name__)

# חפיפה קטנה בין בקשות, כדי שלא נפספס הודעה שנכתבה בדיוק בזמן הבקשה. הדפדפן מסנן כפילויות לפי id.
OVERLAP_SECONDS = 1.0


def _chat() -> ChatService:
    db = get_db()
    return ChatService(db, poll_reader=PollService(db))


def _require_member_of_message(message_id: int):
    row = _chat().get_row(message_id)
    EnrollmentService(get_db()).require_member(row["course_id"], current_user())
    return row


@page_bp.get("/courses/<int:course_id>/chat")
@login_required
def page(course_id: int):
    """הצ׳אט במסך מלא. עמוד הקורס מציג רק כרטיס שמוביל לכאן."""
    db = get_db()
    enrollments = EnrollmentService(db)
    role = enrollments.require_member(course_id, current_user())
    return render_template(
        "chat/page.html",
        course=CourseService(db).get(course_id),
        role=role,
        can_manage=role in ("admin", "lecturer"),
        members=len(enrollments.members(course_id)),
        locked=ChatService(db).is_locked(course_id),
    )


@bp.get("/courses/<int:course_id>/chat")
@login_required
def messages(course_id: int):
    EnrollmentService(get_db()).require_member(course_id, current_user())
    since = request.args.get("since", type=float)
    now = time.time()
    items = _chat().list_messages(course_id, current_user(), since=since)
    # הווים משתנים גם בלי שההודעה עצמה השתנתה, לכן הם נשלחים בכל בקשה
    receipts = ReadReceiptService(get_db()).receipts_for(course_id, current_user())
    locked = _chat().is_locked(course_id)
    return jsonify(ok=True, now=now - OVERLAP_SECONDS, messages=items, receipts=receipts, locked=locked)


@bp.post("/courses/<int:course_id>/chat/lock")
@login_required
def lock(course_id: int):
    """השתקת סטודנטים: רק מרצה הקורס או מנהל המערכת."""
    EnrollmentService(get_db()).require_manager(course_id, current_user())
    locked = bool((request.get_json(silent=True) or {}).get("locked"))
    _chat().set_locked(course_id, locked)
    return jsonify(ok=True, locked=locked)


@bp.post("/courses/<int:course_id>/chat/read")
@login_required
def mark_read(course_id: int):
    EnrollmentService(get_db()).require_member(course_id, current_user())
    try:
        up_to = int((request.get_json(silent=True) or {}).get("up_to", 0))
    except (TypeError, ValueError):
        raise ValidationError("מזהה הודעה לא תקין")
    ReadReceiptService(get_db()).mark_read(course_id, current_user(), up_to)
    return jsonify(ok=True)


@bp.delete("/messages/<int:message_id>")
@login_required
def delete(message_id: int):
    _require_member_of_message(message_id)
    _chat().delete(message_id, current_user())
    return jsonify(ok=True)


@bp.get("/messages/<int:message_id>/info")
@login_required
def info(message_id: int):
    _require_member_of_message(message_id)
    return jsonify(ok=True, **ReadReceiptService(get_db()).info(message_id, current_user()))


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
