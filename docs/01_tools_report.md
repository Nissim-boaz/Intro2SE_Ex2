# 1. Technical tools report

What we chose for each part of the system, why, and how we tried it.

| Area | Tool | Why | Alternatives | How we tried it |
|---|---|---|---|---|
| Web framework | Flask 3.1, Python 3.12+ | Small and simple, one process, blueprints keep routes thin | Django, FastAPI | The whole app runs on it; 224 automated tests use the Flask test client |
| Database | SQLite in WAL mode | No setup, one file, enough for a class of about 100 students | PostgreSQL | Used by the running app and by every test (a temporary database per test) |
| Sign-in | Google ID token, checked with `google-auth` | Students already have Google accounts, and we store no passwords | Email and password | A real Google Cloud OAuth client, on `localhost` and on the Tailscale address. Tests cover the token checks with our own test keys |
| HTTPS address | Tailscale Funnel | Phones allow the microphone only over HTTPS; Funnel gives a free, permanent address | ngrok, Cloudflare Tunnel | Running: the site opens from outside on its `ts.net` address, and the session cookie is marked `Secure` there |
| Attendance signal | Web Audio API: tones at 17.2 to 19.5 kHz | Works in any phone browser with nothing to install | QR code (can be photographed and sent), Bluetooth (not available in a browser), GPS (poor indoors) | Server side: `test_tokens.py` and `test_attendance.py`. The `/debug/audio` page shows the level and the decoded code on a phone |
| Attendance code | HMAC of the server secret, the sample id and a 4-second time window (12 bits) | Never stored, can't be worked out without the secret, valid for at most 8 seconds | Random codes kept in the database | `test_tokens.py` |
| Audio extraction | ffmpeg | Reads any video or audio format | moviepy | A real lesson recording went through the full pipeline |
| Transcription | faster-whisper, `small` model, on the local machine | Free, and the audio stays on our computer | Cloud speech services | The same real recording was transcribed. Tests use a fake transcriber |
| Summaries and homework review | Google Gemini (`google-genai`), `gemini-3.8-flash` with `gemini-3.5-flash-lite` as fallback | Free tier; reads text, code, Word, PowerPoint, PDF and images | Other hosted models, a local model | Real calls: the recording above got a summary and chapters, and a real submission got a suggested grade with deductions. We also saw the model return "overloaded" (503), so the client retries and then falls back to the second model |
| File reading | openpyxl (XLSX), pypdf (PDF) | Import student lists and grades; read submissions | pandas | A real Moodle participants export was imported; tests cover CSV, XLSX and PDF |
| Testing | pytest | Simple, with fakes there is no network and no model | unittest | `pytest -q`: 224 tests in 18 files, all pass |
| Front end | Jinja templates, plain JavaScript, CSS | No build step; Hebrew, right to left, phone first | React, Vue | Used on phones and on a computer |
| Writing the code | Claude Code | We described each feature and reviewed what it wrote. For the hard parts we used existing libraries (faster-whisper, google-auth, openpyxl, pypdf) instead of writing our own | Writing everything by hand | The whole app was built this way, and the 224 tests in `tests/` check the code it wrote |

## Notes
- The phone ignores a tone that is less than 14 dB above the room noise. This is a setting in `audio_listener.js`. If a phone can't decode the signal, the lecturer marks the student by hand.
- A code is valid for at most 8 seconds, so a recording of the signal sent to someone outside the class is already too old when it arrives. `test_attendance.py` checks that a replayed code is rejected.
- On the Gemini free tier, Google may use the content to improve its models, so recordings with sensitive information shouldn't be uploaded.
