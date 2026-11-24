"""עמודים ציבוריים: מדיניות פרטיות ותנאי שימוש. פתוחים לכולם, גם בלי התחברות (Google דורש אותם)."""
from flask import Blueprint, current_app, render_template

bp = Blueprint("pages", __name__)


def _contact() -> str:
    return current_app.config["ADMIN_EMAIL"]


@bp.get("/privacy")
def privacy():
    return render_template("pages/privacy.html", contact_email=_contact())


@bp.get("/terms")
def terms():
    return render_template("pages/terms.html", contact_email=_contact())
