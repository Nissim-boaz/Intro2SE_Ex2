"""התחברות: Google ID Token, ומצב MOCK_AUTH לפיתוח ולדמו."""
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

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
    # double-submit CSRF של Google Identity Services
    cookie_token = request.cookies.get("g_csrf_token")
    if cookie_token and cookie_token != request.form.get("g_csrf_token"):
        flash("ההתחברות נכשלה. נסה שוב", "error")
        return redirect(url_for("auth.login"))
    try:
        info = verifier.verify(request.form.get("credential", ""))
    except Forbidden as err:
        flash(err.message, "error")
        return redirect(url_for("auth.login"))
    user = UserService(get_db()).find_by_email(info["email"])
    if user is None:
        flash(f"החשבון {info['email']} לא רשום במערכת. פנה למנהל המערכת", "error")
        return redirect(url_for("auth.login"))
    return _finish(user)


@bp.post("/auth/mock")
def mock():
    if not current_app.config["MOCK_AUTH"]:
        return redirect(url_for("auth.login"))
    user = UserService(get_db()).get(int(request.form["user_id"]))
    return _finish(user)


def _finish(user):
    target = session.get("next")
    login_user(user)
    return redirect(_safe_next(target))


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
