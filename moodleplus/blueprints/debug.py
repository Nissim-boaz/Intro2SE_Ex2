"""עמוד בדיקה לאות הקולי, לבדיקה באולם לפני הדמו."""
from flask import Blueprint, render_template

bp = Blueprint("debug", __name__, url_prefix="/debug")


@bp.get("/audio")
def audio():
    return render_template("debug/audio.html")
