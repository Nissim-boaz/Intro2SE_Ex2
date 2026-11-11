from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from modules.auth.service import AuthService
from modules.students.service import StudentsService
from config import Config

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/lecturer/login", methods=["GET", "POST"])
def lecturer_login():
    if session.get("lecturer_authenticated"):
        return redirect(url_for("dashboard.lecturer_dashboard"))

    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        if AuthService.verify_lecturer_password(password):
            session["lecturer_authenticated"] = True
            next_url = request.args.get("next") or url_for("dashboard.lecturer_dashboard")
            return redirect(next_url)
        else:
            error = "סיסמת מרצה שגויה"

    return render_template("lecturer/login.html", error=error)

@auth_bp.route("/lecturer/logout")
def lecturer_logout():
    session.pop("lecturer_authenticated", None)
    return redirect(url_for("auth.lecturer_login"))

@auth_bp.route("/auth/config", methods=["GET"])
def auth_config():
    return jsonify({
        "google_client_id": Config.GOOGLE_CLIENT_ID,
        "mock_auth": Config.MOCK_AUTH
    })

@auth_bp.route("/auth/mock/students", methods=["GET"])
def mock_students():
    """Returns students for simulated Google account chooser in test mode."""
    if not Config.MOCK_AUTH:
        return jsonify({"students": []})
    valid, _, students = StudentsService.validate_csv(Config.CLASS_CSV_PATH)
    return jsonify({"students": students if valid else []})
