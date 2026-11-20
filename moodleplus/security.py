"""המשתמש המחובר והרשאות לפי תפקיד."""
from functools import wraps

from flask import abort, g, redirect, request, session, url_for

from .db import get_db
from .errors import NotFound
from .models import User
from .services.users import UserService


def load_current_user() -> None:
    g.user = None
    user_id = session.get("user_id")
    if user_id:
        try:
            g.user = UserService(get_db()).get(user_id)
        except NotFound:
            session.clear()


def current_user() -> User | None:
    return g.get("user")


def login_user(user: User) -> None:
    pending_checkin = session.get("checkin")  # סטודנט שסרק QR לפני שהתחבר
    session.clear()
    session["user_id"] = user.id
    if pending_checkin:
        session["checkin"] = pending_checkin
    session.permanent = True


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            if request.path.startswith("/api/"):
                abort(401)
            return redirect(url_for("auth.login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapper


def role_required(*roles: str):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(*args, **kwargs):
            if current_user().role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator
