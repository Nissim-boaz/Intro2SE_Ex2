from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, current_app
from modules.auth.service import AuthService
from modules.students.service import StudentsService
from config import Config

def _get_cfg(key, default=None):
    try:
        if current_app:
            return current_app.config.get(key, getattr(Config, key, default))
    except RuntimeError:
        pass
    return getattr(Config, key, default)

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

@auth_bp.route("/auth/google/login")
def google_oauth_login():
    """Redirects student directly to Google's official account selector screen."""
    client_id = _get_cfg("GOOGLE_CLIENT_ID", Config.GOOGLE_CLIENT_ID)
    if not client_id:
        return render_template(
            "attendance/error.html",
            error_title="נדרש מזהה לקוח Google (Client ID)",
            error_message="כדי להתחבר ישירות דרך גוגל, יש להזין GOOGLE_CLIENT_ID ו-GOOGLE_CLIENT_SECRET בקובץ .env (ראה הסבר להלן)."
        ), 400

    redirect_uri = url_for("auth.google_oauth_callback", _external=True)
    google_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={client_id}&"
        f"redirect_uri={redirect_uri}&"
        f"response_type=code&"
        f"scope=openid%20email%20profile&"
        f"prompt=select_account"
    )
    return redirect(google_url)

@auth_bp.route("/auth/google/callback")
def google_oauth_callback():
    """Handles Google OAuth redirect callback."""
    code = request.args.get("code")
    error = request.args.get("error")
    if error:
        return render_template(
            "attendance/error.html",
            error_title="ההתחברות עם Google בוטלה",
            error_message=f"האימות לא הושלם: {error}"
        ), 400

    if not code:
        return render_template(
            "attendance/error.html",
            error_title="שגיאת אימות",
            error_message="קוד אימות לא התקבל מחשבון ה-Google"
        ), 400

    # Verify 5-minute cookie
    cookie_val = request.cookies.get("attend_session_token")
    from modules.attendance.service import AttendanceService
    session_id = AttendanceService.verify_signed_session_token(cookie_val)
    if not session_id:
        return render_template(
            "attendance/error.html",
            error_title="פג תוקף הסריקה (5 דקות)",
            error_message="חלפו יותר מ-5 דקות מרגע סריקת הברקוד. יש לסרוק מחדש את ה-QR מהלוח."
        ), 400

    try:
        redirect_uri = url_for("auth.google_oauth_callback", _external=True)
        id_token = AuthService.exchange_code_for_id_token(code, redirect_uri)
        result = AttendanceService.register_attendance(session_id, id_token, request)
        if result.get("success"):
            return render_template("attendance/success.html", result=result)
        else:
            return render_template(
                "attendance/error.html",
                error_title="רישום הנוכחות נדחה",
                error_message=result.get("message")
            ), 400
    except Exception as e:
        return render_template(
            "attendance/error.html",
            error_title="שגיאה ברישום נוכחות",
            error_message=str(e)
        ), 400

@auth_bp.route("/auth/config", methods=["GET"])
def auth_config():
    return jsonify({
        "google_client_id": _get_cfg("GOOGLE_CLIENT_ID", Config.GOOGLE_CLIENT_ID),
        "mock_auth": _get_cfg("MOCK_AUTH", Config.MOCK_AUTH)
    })

@auth_bp.route("/auth/mock/students", methods=["GET"])
def mock_students():
    """Returns students for simulated Google account chooser in test mode."""
    csv_path = _get_cfg("CLASS_CSV_PATH", Config.CLASS_CSV_PATH)
    valid, _, students = StudentsService.validate_csv(csv_path)
    return jsonify({"students": students if valid else []})
