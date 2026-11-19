"""נוכחות: פתיחת דגימה, מסך המרצה, רישום הסטודנט ודוחות."""
import segno
from flask import (Blueprint, Response, current_app, flash, jsonify, redirect, render_template, request,
                   session, url_for)

from ..db import get_db
from ..errors import ServiceError, ValidationError
from ..security import current_user, login_required
from ..services.attendance import AttendanceReport, AttendanceService
from ..services.courses import CourseService, EnrollmentService
from ..services.network import CampusNetworkPolicy
from ..services.tokens import AudioTokenService, QrTokenService, TokenClock

bp = Blueprint("attendance", __name__)


def build_service(db=None) -> AttendanceService:
    cfg = current_app.config
    clock = current_app.extensions.get("token_clock") or TokenClock(cfg["TOKEN_WINDOW_SECONDS"])
    secret = cfg["SECRET_KEY"]
    return AttendanceService(
        db or get_db(),
        QrTokenService(secret, clock),
        AudioTokenService(secret, clock),
        CampusNetworkPolicy.from_file(cfg["CAMPUS_CIDRS_FILE"]),
        clock,
    )


def client_ip() -> str:
    # מאחורי cloudflared הכתובת האמיתית מגיעה בכותרת הזו
    if current_app.config.get("TRUST_PROXY") and request.headers.get("CF-Connecting-IP"):
        return request.headers["CF-Connecting-IP"].strip()
    return request.remote_addr or ""


def _manage_sample(sample_id: int):
    service = build_service()
    sample = service.get_sample(sample_id)
    EnrollmentService(get_db()).require_manager(sample.course_id, current_user())
    return service, sample


# ---------- lecturer ----------
@bp.post("/courses/<int:course_id>/attendance/samples")
@login_required
def open_sample(course_id: int):
    EnrollmentService(get_db()).require_manager(course_id, current_user())
    try:
        lesson_number = int(request.form.get("lesson_number", ""))
        minutes = float(request.form.get("minutes", "2") or 2)
    except ValueError:
        raise ValidationError("מספר השיעור והמשך צריכים להיות מספרים")
    sample = build_service().open_sample(course_id, lesson_number, int(minutes * 60), current_user())
    return redirect(url_for("attendance.screen", sample_id=sample.id))


@bp.get("/attendance/samples/<int:sample_id>/screen")
@login_required
def screen(sample_id: int):
    service, sample = _manage_sample(sample_id)
    course = CourseService(get_db()).get(sample.course_id)
    return render_template("attendance/screen.html", sample=sample, course=course)


@bp.get("/api/attendance/samples/<int:sample_id>/live")
@login_required
def live(sample_id: int):
    service, sample = _manage_sample(sample_id)
    now = service.clock.now()
    is_open = sample.is_open(now)
    data = {
        "ok": True,
        "open": is_open,
        "seconds_left": sample.seconds_left(now),
        "count": service.count(sample_id),
        "enrolled": len(EnrollmentService(get_db()).members(sample.course_id, "student")),
    }
    if is_open:
        token = service.qr.token(sample_id)
        url = url_for("attendance.scan", sample_id=sample_id, t=token, _external=True)
        code = service.audio.code(sample_id)
        data.update(
            token=token,
            qr_svg=segno.make(url, error="m").svg_inline(omitsize=True, border=2, dark="#1D1D1F"),
            audio_symbols=AudioTokenService.symbols(code),
            window_ms_left=int(service.clock.seconds_left(now) * 1000),
        )
    return jsonify(data)


@bp.post("/attendance/samples/<int:sample_id>/close")
@login_required
def close(sample_id: int):
    service, sample = _manage_sample(sample_id)
    service.close_sample(sample_id)
    flash(f"דגימה {sample.seq} בשיעור {sample.lesson_number} נסגרה", "success")
    return redirect(url_for("attendance.lesson_report", lesson_id=sample.lesson_id))


@bp.get("/courses/<int:course_id>/attendance")
@login_required
def course_report(course_id: int):
    EnrollmentService(get_db()).require_manager(course_id, current_user())
    lessons = build_service().lessons(course_id)
    if lessons:
        return redirect(url_for("attendance.lesson_report", lesson_id=lessons[0].id))
    flash("עוד לא נפתחו דגימות בקורס הזה", "success")
    return redirect(url_for("courses.show", course_id=course_id) + "#attendance")


@bp.get("/attendance/lessons/<int:lesson_id>")
@login_required
def lesson_report(lesson_id: int):
    service = build_service()
    lesson = service.get_lesson(lesson_id)
    db = get_db()
    EnrollmentService(db).require_manager(lesson.course_id, current_user())
    students = EnrollmentService(db).members(lesson.course_id, "student")
    samples, rows = AttendanceReport(service).build(lesson_id, students)
    open_sample = service.open_sample_for(lesson.course_id)
    return render_template(
        "attendance/report.html",
        course=CourseService(db).get(lesson.course_id),
        lesson=lesson,
        lessons=service.lessons(lesson.course_id),
        samples=samples,
        rows=rows,
        open_sample=open_sample,
        suspicious=sum(1 for r in rows for c in r.cells if c and c.status == "suspicious"),
    )


@bp.get("/attendance/lessons/<int:lesson_id>.csv")
@login_required
def lesson_csv(lesson_id: int):
    service = build_service()
    lesson = service.get_lesson(lesson_id)
    db = get_db()
    EnrollmentService(db).require_manager(lesson.course_id, current_user())
    students = EnrollmentService(db).members(lesson.course_id, "student")
    data = AttendanceReport(service).to_csv(lesson, students)
    return Response(
        data,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=attendance_lesson_{lesson.number}.csv"},
    )


@bp.post("/attendance/records/<int:record_id>/status")
@login_required
def set_status(record_id: int):
    service = build_service()
    record = service.get_record(record_id)
    sample = service.get_sample(record.sample_id)
    EnrollmentService(get_db()).require_manager(sample.course_id, current_user())
    service.set_status(record_id, request.form.get("status", ""))
    return redirect(url_for("attendance.lesson_report", lesson_id=sample.lesson_id))


# ---------- student ----------
@bp.get("/attendance/samples/<int:sample_id>/scanner")
@login_required
def scanner(sample_id: int):
    """כפתור ״סמן נוכחות״ בעמוד הקורס מוביל לכאן: סורק QR בתוך הדפדפן, אם הטלפון תומך."""
    sample = build_service().get_sample(sample_id)
    EnrollmentService(get_db()).require_student(sample.course_id, current_user())
    return render_template("attendance/scanner.html", sample=sample)


@bp.get("/attend/<int:sample_id>")
def scan(sample_id: int):
    """לכאן מוביל ה-QR. בודקים את הטוקן מיד, עוד לפני ההתחברות, ושומרים ב-session."""
    token = request.args.get("t")
    if token:
        service = build_service()
        try:
            service.scan(sample_id, token)
        except ServiceError as err:  # פג תוקף, דגימה סגורה או לא קיימת
            return render_template("attendance/attend.html", sample_id=sample_id, error=err.message)
        session["checkin"] = {"s": sample_id, "at": service.clock.now()}
        return redirect(url_for("attendance.scan", sample_id=sample_id))

    if current_user() is None:
        return redirect(url_for("auth.login", next=url_for("attendance.scan", sample_id=sample_id)))
    service = build_service()
    sample = service.get_sample(sample_id)
    EnrollmentService(get_db()).require_student(sample.course_id, current_user())
    existing = service.record_for(sample_id, current_user().id)
    pending = _pending_checkin(sample_id, service)
    error = None
    if not existing and not pending:
        error = "צריך לסרוק את הקוד שעל המסך בכיתה"
    return render_template("attendance/attend.html", sample_id=sample_id, sample=sample,
                           course=CourseService(get_db()).get(sample.course_id),
                           existing=existing, error=error)


def _pending_checkin(sample_id: int, service: AttendanceService) -> bool:
    pending = session.get("checkin") or {}
    grace = current_app.config["CHECKIN_GRACE_SECONDS"]
    return pending.get("s") == sample_id and service.clock.now() - pending.get("at", 0) <= grace


@bp.post("/api/attend/<int:sample_id>")
@login_required
def check_in(sample_id: int):
    service = build_service()
    sample = service.get_sample(sample_id)
    EnrollmentService(get_db()).require_student(sample.course_id, current_user())
    if not _pending_checkin(sample_id, service):
        raise ValidationError("הקוד פג. סרוק שוב את המסך")
    body = request.get_json(silent=True) or {}
    audio_code = None if body.get("audio_failed") else body.get("audio_code")
    record = service.check_in(sample_id, current_user(), client_ip(), audio_code)
    session.pop("checkin", None)
    return jsonify(ok=True, status=record.status, method=record.method, reasons=record.reason_labels)
