"""Model+: אתר קורסים עם נוכחות, צ׳אט, סקרים והקלטות."""
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

from . import db
from .errors import ServiceError
from .security import current_user, load_current_user


def create_app(config_object=None, **overrides) -> Flask:
    load_dotenv()
    from .config import Config

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object or Config)
    app.config.update(overrides)
    app.permanent_session_lifetime = timedelta(days=30)
    if app.config.get("TRUST_PROXY"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    _ensure_admin(app)
    _register_blueprints(app)
    _register_handlers(app)
    _start_jobs(app)
    return app


def _ensure_admin(app: Flask) -> None:
    from .services.users import UserService

    conn = db.connect(app.config["DATABASE"])
    try:
        UserService(conn).ensure(app.config["ADMIN_EMAIL"], "מנהל המערכת", "admin")
    finally:
        conn.close()


def _register_blueprints(app: Flask) -> None:
    from .blueprints import admin, auth, courses

    for module in (auth, admin, courses):
        app.register_blueprint(module.bp)

    for name in ("content", "attendance", "chat", "polls", "recordings", "debug"):
        try:
            module = __import__(f"modelplus.blueprints.{name}", fromlist=["bp"])
        except ModuleNotFoundError:
            continue
        app.register_blueprint(module.bp)


def _start_jobs(app: Flask) -> None:
    if not app.config.get("START_JOB_RUNNER"):
        return
    try:
        from .services.recordings import start_runner
    except ImportError:
        return
    start_runner(app)


def _wants_json() -> bool:
    return request.path.startswith("/api/") or request.is_json


def _register_handlers(app: Flask) -> None:
    app.before_request(load_current_user)

    @app.context_processor
    def inject_user():
        return {"user": current_user(), "mock_auth": app.config["MOCK_AUTH"]}

    @app.errorhandler(ServiceError)
    def handle_service_error(err: ServiceError):
        if _wants_json():
            return jsonify(ok=False, error=err.message), err.status
        flash(err.message, "error")
        return redirect(request.referrer or "/")

    @app.errorhandler(403)
    def forbidden(_e):
        if _wants_json():
            return jsonify(ok=False, error="אין לך הרשאה לפעולה הזו"), 403
        return render_template("error.html", title="אין גישה",
                               message="אין לך הרשאה לעמוד הזה."), 403

    @app.errorhandler(404)
    def not_found(_e):
        if _wants_json():
            return jsonify(ok=False, error="לא נמצא"), 404
        return render_template("error.html", title="העמוד לא נמצא",
                               message="אולי הקישור ישן, או שהעמוד נמחק."), 404

    @app.errorhandler(401)
    def unauthorized(_e):
        return jsonify(ok=False, error="צריך להתחבר מחדש"), 401
