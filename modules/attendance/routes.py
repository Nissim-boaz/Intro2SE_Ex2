import time
from flask import Blueprint, render_template, request, make_response, jsonify, redirect, url_for
from modules.sessions.service import SessionsService
from modules.attendance.service import AttendanceService
from config import Config

attendance_bp = Blueprint("attendance", __name__)

COOKIE_NAME = "attend_session_token"

@attendance_bp.route("/attend", methods=["GET"])
def attend_page():
    token = request.args.get("t", "").strip()
    active_session = SessionsService.get_active_session()

    if not active_session:
        return render_template(
            "attendance/error.html",
            error_title="אין סשן פעיל",
            error_message="לא קיים סשן נוכחות פתוח כרגע. אנא המתן לפתיחת סשן על ידי המרצה."
        ), 400

    if not token:
        # Check if already has a valid signed cookie
        cookie_val = request.cookies.get(COOKIE_NAME)
        session_id = AttendanceService.verify_signed_session_token(cookie_val)
        if session_id == active_session["id"]:
            return render_template(
                "attendance/attend.html",
                session_obj=active_session,
                max_age_seconds=Config.COOKIE_MAX_AGE_SECONDS,
                mock_auth=Config.MOCK_AUTH,
                google_client_id=Config.GOOGLE_CLIENT_ID
            )
        return render_template(
            "attendance/error.html",
            error_title="טוקן סריקה חסר",
            error_message="יש לסרוק את קוד ה-QR המוצג על גבי מסך המרצה."
        ), 400

    # Verify QR token for current 6-second window (F2 & F3)
    is_valid = SessionsService.verify_qr_token(active_session["id"], token)
    if not is_valid:
        return render_template(
            "attendance/error.html",
            error_title="קוד QR פג תוקף",
            error_message="קוד ה-QR התחלף או שאינו תקף. אנא סרוק שוב את ה-QR העדכני המוצג בלוח."
        ), 400

    # F4: Issue signed cookie for 5 minutes
    signed_cookie = AttendanceService.create_signed_session_token(active_session["id"])
    response = make_response(render_template(
        "attendance/attend.html",
        session_obj=active_session,
        max_age_seconds=Config.COOKIE_MAX_AGE_SECONDS,
        mock_auth=Config.MOCK_AUTH,
        google_client_id=Config.GOOGLE_CLIENT_ID
    ))

    # Set secure/httponly cookie (secure=False if on plain http for local testing)
    response.set_cookie(
        COOKIE_NAME,
        signed_cookie,
        max_age=Config.COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="Lax",
        secure=request.is_secure
    )
    return response

@attendance_bp.route("/attend/submit", methods=["POST"])
def submit_attendance():
    cookie_val = request.cookies.get(COOKIE_NAME)
    session_id = AttendanceService.verify_signed_session_token(cookie_val)

    if not session_id:
        return jsonify({
            "success": False,
            "error_code": "COOKIE_EXPIRED",
            "message": "פג תוקף הסריקה (עברו יותר מ-5 דקות) או שהסריקה אינה תקפה. יש לסרוק מחדש את קוד ה-QR."
        }), 400

    data = request.get_json(silent=True) or request.form
    google_token = (data.get("google_token") or data.get("credential") or "").strip()

    if not google_token:
        return jsonify({
            "success": False,
            "error_code": "MISSING_TOKEN",
            "message": "טוקן אימות Google לא התקבל"
        }), 400

    try:
        result = AttendanceService.register_attendance(
            session_id=session_id,
            google_token=google_token,
            request=request
        )
        return jsonify(result), 200 if result.get("success") else 400
    except ValueError as e:
        return jsonify({
            "success": False,
            "error_code": "VALIDATION_ERROR",
            "message": str(e)
        }), 400
