"""מהירות מעל רשת איטית (טלפון דרך ה-Funnel): קבצים סטטיים נשמרים בדפדפן, וטקסט נשלח דחוס.

- url_for('static', ...) מוסיף ?v=<זמן השינוי של הקובץ>. כתובת עם v נשמרת בדפדפן לשנה בלי לשאול שוב,
  וכשהקובץ משתנה הכתובת משתנה איתו, כך שהדפדפן טוען את החדש מיד.
- HTML, CSS, JS ו-JSON נשלחים ב-gzip כשהדפדפן תומך. קבצים סטטיים נדחסים פעם אחת ונשמרים בזיכרון.
"""
import gzip
from pathlib import Path

from flask import Flask, request

COMPRESSIBLE = ("text/", "application/javascript", "application/json", "image/svg+xml")
MIN_SIZE = 1024
YEAR = 365 * 24 * 3600


def init_app(app: Flask) -> None:
    static_root = Path(app.static_folder)
    gz_cache: dict[tuple[str, float], bytes] = {}

    @app.url_defaults
    def static_version(endpoint, values):
        if endpoint == "static" and "filename" in values and "v" not in values:
            try:
                values["v"] = int((static_root / values["filename"]).stat().st_mtime)
            except OSError:
                pass

    @app.after_request
    def cache_and_compress(response):
        if request.endpoint == "static" and request.args.get("v") and response.status_code == 200:
            response.headers["Cache-Control"] = f"public, max-age={YEAR}, immutable"
        if not _should_compress(response):
            return response
        key = None
        if request.endpoint == "static":
            path = static_root / (request.view_args or {}).get("filename", "")
            try:
                key = (str(path), path.stat().st_mtime)
            except OSError:
                key = None
        body = gz_cache.get(key) if key else None
        if body is None:
            response.direct_passthrough = False  # a static file arrives as a stream; read it to compress it
            body = gzip.compress(response.get_data(), compresslevel=6)
            if key:
                gz_cache[key] = body
        response.set_data(body)
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Content-Length"] = str(len(body))
        response.vary.add("Accept-Encoding")
        return response


def _should_compress(response) -> bool:
    if response.status_code != 200 or "Content-Encoding" in response.headers:
        return False
    if "gzip" not in request.headers.get("Accept-Encoding", ""):
        return False
    if not (response.mimetype or "").startswith(COMPRESSIBLE):
        return False
    length = response.content_length
    return length is None or length >= MIN_SIZE
