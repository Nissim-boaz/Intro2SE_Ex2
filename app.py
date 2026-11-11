import os
from flask import Flask, redirect, url_for
from config import Config
from database.db import init_db, close_db
from modules.sessions.routes import sessions_bp
from modules.auth.routes import auth_bp
from modules.attendance.routes import attendance_bp
from modules.dashboard.routes import dashboard_bp

def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)

    if test_config:
        app.config.update(test_config)

    # Database teardown
    app.teardown_appcontext(close_db)

    # Initialize DB schema
    with app.app_context():
        init_db(app.config.get("DATABASE_PATH"))

    # Register Blueprints
    app.register_blueprint(sessions_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(dashboard_bp)

    @app.route("/")
    def index():
        return redirect(url_for("dashboard.lecturer_dashboard"))

    return app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5050))
    print(f"\n==========================================")
    print(f"🚀 שרת הנוכחות עלה בהצלחה!")
    print(f"👉 גש בדפדפן אל: http://localhost:{port}/lecturer")
    print(f"==========================================\n")
    app.run(host="0.0.0.0", port=port, debug=True)
