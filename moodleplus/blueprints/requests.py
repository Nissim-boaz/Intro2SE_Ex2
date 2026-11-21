"""פניות למנהלי המערכת. סטודנטים ומרצים פותחים ועונים, מנהלים עונים ומעדכנים סטטוס."""
import time

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..db import get_db
from ..security import current_user, login_required, role_required
from ..services.requests import KEEP_CLOSED_DAYS, STATUSES, RequestService

bp = Blueprint("requests", __name__)


def _service() -> RequestService:
    return RequestService(get_db())


@bp.app_context_processor
def request_badge():
    """המספר שליד ״פניות״ בתפריט החשבון, בכל עמוד."""
    user = current_user()
    if not user:
        return {}
    return {"requests_badge": _service().badge_for(user)}


@bp.get("/requests")
@login_required
def index():
    if current_user().is_admin:
        return redirect(url_for("requests.inbox"))
    return render_template("requests/index.html", items=_service().mine(current_user()), statuses=STATUSES,
                           keep_days=KEEP_CLOSED_DAYS, now=time.time())


@bp.post("/requests")
@login_required
def create():
    req = _service().create(current_user(), request.form.get("subject", ""), request.form.get("body", ""))
    flash("הפנייה נשלחה למנהלי המערכת", "success")
    return redirect(url_for("requests.show", request_id=req.id))


@bp.get("/admin/requests")
@role_required("admin")
def inbox():
    status = request.args.get("status") or "open"
    service = _service()
    everything = service.all()
    counts = {key: sum(1 for r in everything if r.status == key) for key in STATUSES}
    counts["open"] = counts["new"] + counts["in_progress"]
    return render_template("requests/inbox.html", items=service.all(status), status=status, counts=counts,
                           statuses=STATUSES, keep_days=KEEP_CLOSED_DAYS, now=time.time())


@bp.get("/requests/<int:request_id>")
@login_required
def show(request_id: int):
    service = _service()
    req = service.get_visible(request_id, current_user())
    if req.user_id == current_user().id:
        service.mark_seen(request_id, current_user())
    if current_user().is_admin:
        back_url, back_label = url_for("requests.inbox"), "פניות"
    else:
        back_url, back_label = url_for("requests.index"), "הפניות שלי"
    return render_template("requests/show.html", req=req, thread=service.thread(request_id, current_user()),
                           statuses=STATUSES, keep_days=KEEP_CLOSED_DAYS, now=time.time(),
                           back_url=back_url, back_label=back_label)


@bp.post("/requests/<int:request_id>/reply")
@login_required
def reply(request_id: int):
    _service().reply(request_id, current_user(), request.form.get("body", ""),
                     as_team=request.form.get("as_team") == "1")
    return redirect(url_for("requests.show", request_id=request_id) + "#reply")


@bp.post("/requests/<int:request_id>/status")
@role_required("admin")
def set_status(request_id: int):
    req = _service().set_status(request_id, current_user(), request.form.get("status", ""))
    flash(f"הסטטוס עודכן: {req.status_label}", "success")
    return redirect(url_for("requests.show", request_id=request_id))
