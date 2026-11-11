import time
import socket
from flask import Blueprint, jsonify, request, session, send_file, url_for, current_app
from modules.sessions.service import SessionsService
from config import Config, BASE_DIR

def _get_cfg(key, default=None):
    try:
        if current_app:
            return current_app.config.get(key, getattr(Config, key, default))
    except RuntimeError:
        pass
    return getattr(Config, key, default)

def get_lan_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None

def get_attend_base_url() -> str:
    from dotenv import dotenv_values
    env_vals = dotenv_values(BASE_DIR / ".env")
    configured = env_vals.get("SERVER_BASE_URL") or os.getenv("SERVER_BASE_URL") or _get_cfg("SERVER_BASE_URL", Config.SERVER_BASE_URL)
    if configured:
        return configured.rstrip("/")

    host = request.host # e.g. "localhost:5050" or "127.0.0.1:5050"
    if "localhost" in host or "127.0.0.1" in host:
        lan_ip = get_lan_ip()
        if lan_ip:
            port = host.split(":")[1] if ":" in host else "5050"
            return f"{request.scheme}://{lan_ip}:{port}"
    return request.host_url.rstrip("/")

sessions_bp = Blueprint("sessions", __name__, url_prefix="/sessions")

def is_lecturer_logged_in():
    return session.get("lecturer_authenticated") is True

@sessions_bp.route("/start", methods=["POST"])
def start_session():
    if not is_lecturer_logged_in():
        return jsonify({"error": "נדרשת התחברות מרצה"}), 401

    data = request.get_json(silent=True) or request.form
    title = data.get("title", "שיעור נוכחות")
    try:
        duration = int(data.get("duration", Config.DEFAULT_SESSION_DURATION_MINUTES))
    except (ValueError, TypeError):
        duration = Config.DEFAULT_SESSION_DURATION_MINUTES

    try:
        new_session = SessionsService.create_session(title=title, duration_minutes=duration)
        return jsonify({"success": True, "session": new_session})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@sessions_bp.route("/<session_id>/close", methods=["POST"])
def close_session(session_id):
    if not is_lecturer_logged_in():
        return jsonify({"error": "נדרשת התחברות מרצה"}), 401

    closed = SessionsService.close_session(session_id)
    if not closed:
        return jsonify({"error": "סשן לא נמצא או שכבר נסגר"}), 404

    return jsonify({"success": True, "session": closed})

@sessions_bp.route("/active/token", methods=["GET"])
def get_active_token():
    active = SessionsService.get_active_session()
    if not active:
        return jsonify({"active": False, "error": "אין סשן פעיל כרגע"}), 404

    now = time.time()
    token = SessionsService.generate_qr_token(active["id"], now)
    seconds_remaining = Config.QR_WINDOW_SECONDS - (int(now) % Config.QR_WINDOW_SECONDS)
    attend_base = get_attend_base_url()
    attend_url = f"{attend_base}/attend?t={token}"

    return jsonify({
        "active": True,
        "session_id": active["id"],
        "token": token,
        "seconds_remaining": seconds_remaining,
        "window_duration": Config.QR_WINDOW_SECONDS,
        "attend_url": attend_url
    })

@sessions_bp.route("/active/qr.png", methods=["GET"])
def get_active_qr_png():
    active = SessionsService.get_active_session()
    if not active:
        return jsonify({"error": "אין סשן פעיל כרגע"}), 404

    now = time.time()
    token = SessionsService.generate_qr_token(active["id"], now)
    # Build complete attend URL with LAN IP or configured base URL so mobile phones can connect
    attend_base = get_attend_base_url()
    attend_url = f"{attend_base}/attend?t={token}"
    img_buf = SessionsService.generate_qr_image_bytes(attend_url)
    return send_file(img_buf, mimetype="image/png", max_age=0)
