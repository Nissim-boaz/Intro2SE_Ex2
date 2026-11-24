"""התחברות: Google ID Token, ומצב MOCK_AUTH לפיתוח ולדמו."""
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for

from ..db import get_db
from ..errors import Forbidden
from ..security import current_user, login_user
from ..services.google_auth import GoogleTokenVerifier
from ..services.users import UserService

bp = Blueprint("auth", __name__)


def _safe_next(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return url_for("courses.index")


@bp.get("/login")
def login():
    if current_user():
        return redirect(_safe_next(request.args.get("next")))
    session["next"] = _safe_next(request.args.get("next"))
    users = UserService(get_db()).list() if current_app.config["MOCK_AUTH"] else []
    return render_template(
        "auth/login.html",
        google_client_id=current_app.config["GOOGLE_CLIENT_ID"],
        mock_users=users,
    )


@bp.post("/auth/google")
def google():
    verifier = current_app.extensions.get("google_verifier") or GoogleTokenVerifier(
        current_app.config["GOOGLE_CLIENT_ID"]
    )
    # הדפדפן שולח את ה-credential ב-fetch מאותו אתר (callback של Google Identity Services),
    # ולכן עוגיית ה-session נשמרת ואפשר לחזור לעמוד שממנו הגיעו.
    payload = request.get_json(silent=True) or request.form
    try:
        info = verifier.verify(payload.get("credential", ""))
    except Forbidden as err:
        return _fail(err.message)
    user = UserService(get_db()).find_by_email(info["email"])
    if user is None:
        return _fail(f"החשבון {info['email']} לא רשום במערכת. פנה למנהל המערכת")
    target = _safe_next(session.get("next"))
    login_user(user, via="google")
    if request.is_json:
        return jsonify(ok=True, next=target)
    return redirect(target)


def _fail(message: str):
    if request.is_json:
        return jsonify(ok=False, error=message), 403
    flash(message, "error")
    return redirect(url_for("auth.login"))


@bp.post("/auth/mock")
def mock():
    if not current_app.config["MOCK_AUTH"]:
        return redirect(url_for("auth.login"))
    user = UserService(get_db()).get(int(request.form["user_id"]))
    return _finish(user)


def _finish(user):
    target = session.get("next")
    login_user(user, via="mock")
    return redirect(_safe_next(target))


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
