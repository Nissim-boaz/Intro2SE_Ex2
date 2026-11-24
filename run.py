"""הרצה מקומית: python run.py

הפורט: אם PORT מוגדר (בסביבה או ב-.env) משתמשים בו כמו שהוא.
אחרת מתחילים ב-5001 (ב-macOS פורט 5000 תפוס על ידי AirPlay Receiver)
ועוברים לפורט הפנוי הבא אם גם הוא תפוס.
"""
import os
import socket

import sys

from moodleplus import ConfigError, create_app

DEFAULT_PORT = 5001
PORT_ATTEMPTS = 20
HOST = "0.0.0.0"

try:
    app = create_app()
except ConfigError as err:
    print(f"\n * The server did not start:\n{err}\n", file=sys.stderr)
    raise SystemExit(1)


def _port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def choose_port(host: str = HOST) -> int:
    explicit = os.environ.get("PORT")
    if explicit:
        return int(explicit)
    for port in range(DEFAULT_PORT, DEFAULT_PORT + PORT_ATTEMPTS):
        if _port_is_free(host, port):
            return port
    raise SystemExit(
        f"No free port between {DEFAULT_PORT} and {DEFAULT_PORT + PORT_ATTEMPTS - 1}. "
        "Set PORT to a free port and run again."
    )


if __name__ == "__main__":
    port = choose_port()
    # the debug reloader runs this file again in a child process; keep the same port there
    os.environ["PORT"] = str(port)
    print(f" * Open http://localhost:{port}")
    if app.config["PUBLIC_URL"]:
        print(f" * Public address: {app.config['PUBLIC_URL']}")
    if app.config["MOCK_AUTH"]:
        print(
            " * WARNING: MOCK_AUTH=1, sign-in has no authentication. Anyone can pick any user, admin included.\n"
            "   If the Tailscale Funnel is open, that means anyone who has the address. Set MOCK_AUTH=0 for real use.",
            file=sys.stderr,
        )
    app.run(host=HOST, port=port, debug=os.environ.get("FLASK_DEBUG") == "1", threaded=True)
