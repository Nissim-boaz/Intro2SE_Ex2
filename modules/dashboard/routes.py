import csv
import io
from datetime import datetime, timezone
from flask import Blueprint, render_template, jsonify, request, make_response, redirect, url_for, current_app
from database.db import get_db
from modules.auth.service import lecturer_required
from modules.sessions.service import SessionsService
from modules.students.service import StudentsService
from config import Config

def _get_cfg(key, default=None):
    try:
        if current_app:
            return current_app.config.get(key, getattr(Config, key, default))
    except RuntimeError:
        pass
    return getattr(Config, key, default)

dashboard_bp = Blueprint("dashboard", __name__)

@dashboard_bp.route("/lecturer", methods=["GET"])
@lecturer_required
def lecturer_dashboard():
    active_session = SessionsService.get_active_session()
    latest_closed = None
    summary_data = None

    if not active_session:
        latest_closed = SessionsService.get_latest_closed_session()
        if latest_closed:
            summary_data = get_session_summary_data(latest_closed["id"])

    return render_template(
        "lecturer/dashboard.html",
        active_session=active_session,
        latest_closed=latest_closed,
        summary_data=summary_data,
        default_duration=Config.DEFAULT_SESSION_DURATION_MINUTES
    )

@dashboard_bp.route("/lecturer/summary/<session_id>", methods=["GET"])
@lecturer_required
def session_summary_view(session_id):
    session_obj = SessionsService.get_session_by_id(session_id)
    if not session_obj:
        return "סשן לא נמצא", 404
    summary = get_session_summary_data(session_id)
    return render_template("lecturer/summary.html", session_obj=session_obj, summary=summary)

def get_session_summary_data(session_id: str) -> dict:
    db = get_db()
    attendees = db.execute(
        "SELECT * FROM attendance WHERE session_id = ? ORDER BY timestamp ASC",
        (session_id,)
    ).fetchall()
    attendees_list = [dict(r) for r in attendees]

    attended_emails = {a["email"].lower() for a in attendees_list}
    csv_path = _get_cfg("CLASS_CSV_PATH", Config.CLASS_CSV_PATH)
    absent_students = StudentsService.get_absent_students(csv_path, attended_emails)

    present_count = sum(1 for a in attendees_list if a["status"] == "present")
    suspicious_count = sum(1 for a in attendees_list if a["status"] == "suspicious")
    absent_count = len(absent_students)
    total_class = present_count + suspicious_count + absent_count

    rejected_rows = db.execute(
        "SELECT * FROM rejected_attempts WHERE session_id = ? ORDER BY timestamp DESC",
        (session_id,)
    ).fetchall()

    return {
        "attendees": attendees_list,
        "absent_students": absent_students,
        "present_count": present_count,
        "suspicious_count": suspicious_count,
        "absent_count": absent_count,
        "total_class": total_class,
        "rejected_attempts": [dict(r) for r in rejected_rows]
    }

@dashboard_bp.route("/api/dashboard/stats", methods=["GET"])
@lecturer_required
def get_dashboard_stats():
    active = SessionsService.get_active_session()
    if not active:
        return jsonify({"active": False, "message": "אין סשן פעיל"}), 200

    db = get_db()
    attendees_rows = db.execute(
        "SELECT * FROM attendance WHERE session_id = ? ORDER BY timestamp DESC",
        (active["id"],)
    ).fetchall()
    attendees = [dict(r) for r in attendees_rows]

    rejected_rows = db.execute(
        "SELECT * FROM rejected_attempts WHERE session_id = ? ORDER BY timestamp DESC",
        (active["id"],)
    ).fetchall()
    rejected = [dict(r) for r in rejected_rows]

    present_count = sum(1 for a in attendees if a["status"] == "present")
    suspicious_count = sum(1 for a in attendees if a["status"] == "suspicious")

    # Build timeline for Chart.js
    # Group attendance by minute
    timeline_map = {}
    # Sort attendees ascending by time for timeline
    for a in sorted(attendees, key=lambda x: x["timestamp"]):
        # minute string: HH:MM
        try:
            dt = datetime.fromisoformat(a["timestamp"])
            minute_str = dt.strftime("%H:%M")
        except Exception:
            minute_str = a["timestamp"][:16]
        timeline_map[minute_str] = timeline_map.get(minute_str, 0) + 1

    timeline_labels = list(timeline_map.keys())
    timeline_values = []
    cumulative = 0
    for label in timeline_labels:
        cumulative += timeline_map[label]
        timeline_values.append(cumulative)

    # Time remaining calculation
    now = datetime.now(timezone.utc)
    try:
        end_dt = datetime.fromisoformat(active["end_time"])
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        remaining_seconds = max(0, int((end_dt - now).total_seconds()))
    except Exception:
        remaining_seconds = 0

    return jsonify({
        "active": True,
        "session": active,
        "remaining_seconds": remaining_seconds,
        "total_attendees": len(attendees),
        "present_count": present_count,
        "suspicious_count": suspicious_count,
        "attendees": attendees,
        "rejected_attempts": rejected,
        "chart": {
            "labels": timeline_labels,
            "values": timeline_values
        }
    })

@dashboard_bp.route("/api/attendance/<int:attendance_id>/approve", methods=["POST"])
@lecturer_required
def approve_attendance(attendance_id):
    """F10: Lecturer manually approves suspicious attendance."""
    now_iso = datetime.now(timezone.utc).isoformat()
    db = get_db()
    with db:
        cursor = db.execute("""
            UPDATE attendance
            SET status = 'present', approved_at = ?
            WHERE id = ? AND status = 'suspicious'
        """, (now_iso, attendance_id))
        if cursor.rowcount == 0:
            return jsonify({"error": "רשומת נוכחות לא נמצאה או שכבר אושרה"}), 404

    updated = db.execute("SELECT * FROM attendance WHERE id = ?", (attendance_id,)).fetchone()
    return jsonify({"success": True, "attendance": dict(updated)})

@dashboard_bp.route("/dashboard/export/<session_id>", methods=["GET"])
@lecturer_required
def export_csv(session_id):
    """
    Exports attendance report for session to CSV with UTF-8 BOM.
    Contains: present, suspicious, and absent students.
    """
    session_obj = SessionsService.get_session_by_id(session_id)
    if not session_obj:
        return "סשן לא נמצא", 404

    summary = get_session_summary_data(session_id)

    output = io.StringIO()
    # Write UTF-8 BOM so Excel in Hebrew renders characters properly
    output.write("\ufeff")
    writer = csv.writer(output)

    # Header
    writer.writerow(["שם סטודנט", "אימייל", "סטטוס נוכחות", "שעת רישום", "כתובת IP", "אושר ידנית ע״י מרצה", "User-Agent"])

    # Attendees
    for a in summary["attendees"]:
        status_heb = "נוכח" if a["status"] == "present" else "חשוד (מחוץ לקמפוס)"
        approved_text = a["approved_at"] if a.get("approved_at") else ("לא נדרש" if a["status"] == "present" else "טרם אושר")
        writer.writerow([
            a["student_name"],
            a["email"],
            status_heb,
            a["timestamp"],
            a["ip_address"],
            approved_text,
            a["user_agent"] or ""
        ])

    # Absent students
    for s in summary["absent_students"]:
        writer.writerow([
            s["name"],
            s["email"],
            "לא הגיע",
            "-",
            "-",
            "-",
            "-"
        ])

    csv_data = output.getvalue()
    response = make_response(csv_data)
    filename = f"attendance_{session_id}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    return response
