"""נוכחות: פתיחת דגימה, מסך המרצה עם הצליל והרשימה החיה, רישום הסטודנט בקול, ודוחות."""
from flask import Blueprint, Response, current_app, flash, jsonify, redirect, render_template, request, url_for

from ..db import get_db
from ..errors import ValidationError
from ..security import current_user, login_required
from ..services.attendance import AttendanceReport, AttendanceService
from ..services.courses import CourseService, EnrollmentService
from ..services.tokens import AudioTokenService, TokenClock
from ..services.users import UserService

bp = Blueprint("attendance", __name__)


def build_service(db=None) -> AttendanceService:
    cfg = current_app.config
    clock = current_app.extensions.get("token_clock") or TokenClock(cfg["TOKEN_WINDOW_SECONDS"])
    return AttendanceService(db or get_db(), AudioTokenService(cfg["SECRET_KEY"], clock), clock)


def section_context(course_id: int, role: str) -> dict:
    """מה שהחלק של הנוכחות בעמוד הקורס צריך, גם בטעינה הראשונה וגם בעדכון החי של הסטודנט."""
    service = build_service()
    sample = service.open_sample_for(course_id)
    lessons = service.lessons(course_id)
    ctx = {
        "open_sample": sample,
        "next_lesson": lessons[0].number if lessons else 1,
        "has_lessons": bool(lessons),
    }
    if sample:
        ctx["seconds_left"] = sample.seconds_left(service.clock.now())
        if role == "student":
            ctx["my_record"] = service.record_for(sample.id, current_user().id)
            ctx["attempts_left"] = service.attempts_left(sample.id, current_user().id)
    return ctx


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
    """המסך של המרצה שואל כאן כל שנייה: הקוד הקולי הנוכחי, הטיימר ומי כבר נרשם."""
    service, sample = _manage_sample(sample_id)
    now = service.clock.now()
    is_open = sample.is_open(now)
    attendees = service.attendees(sample_id)
    data = {
        "ok": True,
        "open": is_open,
        "seconds_left": sample.seconds_left(now),
        "count": len(attendees),
        "enrolled": len(EnrollmentService(get_db()).members(sample.course_id, "student")),
        "attendees": [{"id": a.student_id, "name": a.name, "manual": a.method == "manual"} for a in attendees],
    }
    if is_open:
        code = service.audio.code(sample_id)
        data.update(
            window=service.clock.window(now),
            audio_symbols=AudioTokenService.symbols(code),
            window_ms=service.clock.window_seconds * 1000,
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
    return render_template(
        "attendance/report.html",
        course=CourseService(db).get(lesson.course_id),
        lesson=lesson,
        lessons=service.lessons(lesson.course_id),
        samples=samples,
        rows=rows,
        open_sample=service.open_sample_for(lesson.course_id),
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


@bp.post("/attendance/samples/<int:sample_id>/students/<int:student_id>/mark")
@login_required
def mark_manual(sample_id: int, student_id: int):
    """סימון ידני בדוח: סטודנט שהיה בכיתה אבל הטלפון שלו לא קלט את הצליל."""
    service, sample = _manage_sample(sample_id)
    if EnrollmentService(get_db()).role_in(sample.course_id, UserService(get_db()).get(student_id)) != "student":
        raise ValidationError("אפשר לסמן רק סטודנטים של הקורס")
    service.mark_manual(sample_id, student_id, current_user())
    return redirect(url_for("attendance.lesson_report", lesson_id=sample.lesson_id, _anchor=f"st-{student_id}"))


@bp.post("/attendance/records/<int:record_id>/delete")
@login_required
def remove_record(record_id: int):
    service = build_service()
    record = service.get_record(record_id)
    service, sample = _manage_sample(record.sample_id)
    service.remove_record(record_id)
    return redirect(url_for("attendance.lesson_report", lesson_id=sample.lesson_id, _anchor=f"st-{record.student_id}"))


# ---------- student ----------
@bp.get("/api/courses/<int:course_id>/attendance/panel")
@login_required
def student_panel(course_id: int):
    """החלק של הסטודנט בעמוד הקורס. הדף שואל כאן כל כמה שניות, כך שהכפתור מופיע ברגע שהמרצה פותח דגימה."""
    EnrollmentService(get_db()).require_student(course_id, current_user())
    return render_template("attendance/_student.html", a=section_context(course_id, "student"), course_id=course_id)


@bp.post("/api/attend/<int:sample_id>")
@login_required
def check_in(sample_id: int):
    service = build_service()
    sample = service.get_sample(sample_id)
    EnrollmentService(get_db()).require_student(sample.course_id, current_user())
    body = request.get_json(silent=True) or {}
    service.check_in(sample_id, current_user(), body.get("audio_code"))
    return jsonify(ok=True)
