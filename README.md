# Moodle+

A course website built for assignment 2 of Introduction to Software Engineering. Every course has a page with content, assignments, in-class attendance sampling, lesson recordings with an AI summary and chapters, and a group chat with polls. The interface is in Hebrew (right to left) and designed for phones first.

## Problem and scope

**Problem.** Today's online teaching tools don't work well in a real classroom. Taking attendance is slow, student comments get lost, polls need a separate tool, nobody summarizes the recordings, and homework review is all manual.

**Goal.** One simple, phone-first web app for a class. It is built around the most important feature: students mark attendance from their phones with no roll call, and the lecturer exports it as a spreadsheet.

**In scope.** Everything described below: attendance with a sound code, with a live list, a report, a CSV export, manual marks and appeals; a course chat with anonymous messages; quick polls; recordings with transcription, an AI summary and chapters; homework submission and grading with AI suggestions and a copy check; roles, Google sign-in, course pages and weighted grades.

**Out of scope.**
- Integration with Moodle, Zoom or university systems. Student lists are imported from CSV or XLSX instead.
- A native phone app. Everything runs in the browser.
- Live sockets. Pages update by polling.
- Hosting on a production server with backups.
- Grading with no lecturer involved. AI output is only a suggestion until the lecturer approves it.

## Demo video

[Demo video (Google Drive)](PASTE-DRIVE-LINK-HERE)

## Project documents

All documents are in [`docs/`](docs/):

1. [Tools report](docs/01_tools_report.md)
2. [Statement of Work](docs/02_SoW.md)
3. [Requirements (SRS)](docs/03_SRS.md)
4. [Use cases](docs/04_use_cases.md)
5. [Main components](docs/05_components.md)
6. [Class and sequence diagrams](docs/06_diagrams.md)
7. [Testing strategy](docs/07_testing_strategy.md)
8. [Conclusion](docs/08_conclusion.md)

## What's in the system

There are three roles. The **admin** manages users and courses and imports students from a CSV or XLSX file (a Moodle participants export works as is). The **lecturer** runs their courses, and the **student** takes part in them. Sign-in is with Google, and only people in the users table can get in. Someone who isn't listed can send a sign-up request, and an admin approves it.

The five features from the brief:

1. **Attendance (the main feature).** The lecturer opens a sample, and the classroom computer plays a high-frequency signal that carries a code that changes every 4 seconds. Students tap "בצע נוכחות" (check in), the phone decodes the code and sends it, and their names appear live on the projected screen. The lecturer can mark a student by hand, a student can appeal a missed sample, and the lesson report exports to a CSV that opens in Excel.
2. **Comments and suggestions.** A WhatsApp-style chat for each course, with replies, reactions and search. A message can be sent anonymously, and then only the admin can see who sent it. Students can also send requests to the admins.
3. **Polls.** The lecturer creates a poll in the chat, anonymous or open, and the results update live.
4. **Recording summaries.** The lecturer uploads a recording. faster-whisper transcribes it on the local machine, and Gemini writes a summary, key points and chapters with timestamps. The lecturer can edit the draft before publishing it.
5. **Homework review.** Gemini reads each submission, suggests a grade and feedback that lists the point deductions, and adds a note relative to the rest of the class. A local text comparison flags submissions that look copied. The lecturer approves every suggestion, and students see nothing until the grades are published.

Beyond the brief there is also a gradebook with exams, quizzes and weighted grades, and appeals on grades.

The full requirements are in the [SRS](docs/03_SRS.md).

## Code structure

```
moodleplus/
  __init__.py        create_app: registers blueprints, the DB and error handling
  schema.sql         all tables (SQLite in WAL mode)
  services/          the logic, with no Flask. Each class has one responsibility
    users.py         UserService, StudentImporter
    courses.py       CourseService, EnrollmentService (course-level permissions)
    content.py       ContentService, FileStore
    assignments.py   AssignmentService
    gradebook.py     ExamService, Gradebook (weights and the weighted grade)
    tokens.py        TokenClock, AudioTokenService
    attendance.py    AttendanceService, AttendanceReport
    attendance_appeals.py AttendanceAppealService
    chat.py          ChatService, SenderMask, ReactionService, ReadReceiptService
    chat_themes.py   ChatThemeService (wallpaper and message colour per user)
    polls.py         PollService
    requests.py      RequestService (requests to the admins)
    signups.py       SignupService (sign-up requests an admin approves)
    recordings.py    RecordingService, BackgroundJobRunner
    transcription.py Transcriber, WhisperTranscriber, AudioExtractor
    llm.py           LLMProvider, GeminiProvider, LessonSummarizer, LessonFeedbackWriter
    ai_grading.py    AIGradingService, SubmissionReviewer, ClassComparer, AIGradingRunner
    documents.py     read_document (submission files as text or as files for Gemini), similarity
  blueprints/        thin routes: read the request, call a service, return a template or JSON
  static/js/         audio_emitter.js (AudioTokenEmitter), audio_listener.js (AudioTokenListener), chat.js and more
tests/               pytest tests for every service
seed.py              demo data
```

Routes don't access the database directly. All the logic and checks live in the services layer, which is the layer to draw the class diagram from.

## Running locally

You need Python 3.12 or later, and ffmpeg for recordings.

```bash
python -m venv venv
venv\Scripts\activate            # on Mac or Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env           # on Mac or Linux: cp
python seed.py --reset           # sample data: a lecturer, the students in data/students.csv, a course with content, assignments, chat and a poll
python run.py
```

The site runs at `http://localhost:5001` (the exact address is printed on start). Port 5000 is skipped because macOS uses it for AirPlay Receiver; if 5001 is taken, the next free port is used. Set `PORT` to force a specific port. With `MOCK_AUTH=1`, the sign-in page lets you pick a role and a user. The main admin's email comes from `ADMIN_EMAIL`, and that admin is created automatically on the first run. Changing `ADMIN_EMAIL` later moves the existing admin to the new address: the same account and data if the address is new, or the old admin's data merged into the account that already has it. No second admin is created.

`data/students.csv` and the Moodle export next to it hold 10 fictional students, so the repository has no real personal data. To use a real class list, import it from the admin screen.

Important settings in `.env`:

| Variable | What it does |
| --- | --- |
| `SECRET_KEY` | The secret the tokens and the session are derived from. It must be long and random |
| `MOCK_AUTH` | `1` shows the role picker with no authentication (development), `0` leaves only Google |
| `GOOGLE_CLIENT_ID` | The OAuth Client ID from Google Cloud Console. With `MOCK_AUTH=0` the server refuses to start without it |
| `ADMIN_EMAIL` | The main admin's Google address. Its email can only be changed here, not in the users screen |
| `PUBLIC_URL` | The permanent address from outside, for example `https://my-pc.tailnet-name.ts.net`. Printed on start |
| `GEMINI_API_KEY` | A free key from [Google AI Studio](https://aistudio.google.com/apikey) |
| `GEMINI_MODEL` | The default is `gemini-3.8-flash` |
| `WHISPER_MODEL` | The default is `small`. Use `base` for faster transcription |

On the first upload, faster-whisper downloads the model (about 460 MB), and it is cached after that.

Note: on the Gemini free tier, Google may use the content to improve its models, so don't upload recordings with sensitive information.

## A permanent HTTPS address (Tailscale Funnel)

On a phone the microphone works only over HTTPS, and Google sign-in needs an address that doesn't change. Tailscale Funnel gives the computer a permanent `https://<machine>.<tailnet>.ts.net` address, free:

1. Install Tailscale for Windows from [tailscale.com/download](https://tailscale.com/download) (or `winget install --id tailscale.tailscale`) and sign in.
2. In the [admin console](https://login.tailscale.com/admin/dns), under DNS, turn on MagicDNS and HTTPS Certificates.
3. Allow Funnel for your machine: in the admin console under Access controls, add the `funnel` attribute to the policy (Tailscale shows a link to do this the first time you run the command below).
4. Start the site, then the Funnel in a second terminal:

```bash
python run.py               # first terminal
tailscale funnel 5001       # second terminal; use the port printed on start
```

Tailscale prints the address. Put it in `.env` as `PUBLIC_URL`. Funnel stays up while that terminal is open; `Ctrl+C` stops it. Behind the Funnel the server gets plain HTTP with an `X-Forwarded-Proto: https` header, which `ProxyFix` reads (`TRUST_PROXY=1`, the default), so Flask knows the visit is secure and marks the session cookie `Secure`.

Warning: with `MOCK_AUTH=1` and the Funnel open, anyone who has the address can sign in as anyone, admin included. The server prints this warning on start.

## Google sign-in

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project.
2. Under APIs & Services, OAuth consent screen: choose External, fill in the app name and your email, and add the privacy policy and terms links (`<PUBLIC_URL>/privacy` and `<PUBLIC_URL>/terms`). Only the basic `email` and `profile` scopes are used, so no review is needed. Publish it (not Testing), or add every user as a test user.
3. Under Credentials, Create credentials, OAuth client ID, type Web application. Under Authorized JavaScript origins add:
   - `http://localhost:5001` (on the computer, open the site through `localhost`, not `127.0.0.1`)
   - your `PUBLIC_URL`, for example `https://my-pc.tailnet-name.ts.net`
   No redirect URIs are needed: the sign-in button sends the ID token straight to the page.
4. Copy the Client ID into `.env` as `GOOGLE_CLIENT_ID`, set `MOCK_AUTH=0`, and set `ADMIN_EMAIL` to your own Google address. Restart the server.

Changes to the origins can take a few minutes to apply on Google's side.

### Development mode

- Real sign-in: `MOCK_AUTH=0`. Sign in with Google as the admin (`ADMIN_EMAIL`).
- Quick switching between users (for showing features): set `MOCK_AUTH=1` and restart the server. The orange strip shows on every page, and the terminal prints a warning.
- Back to real sign-in: `MOCK_AUTH=0` and restart. Anyone who signed in through mock mode is signed out automatically, so nobody keeps an unauthenticated session; people who signed in with Google stay signed in.

## Checking the sound in a room

1. On the classroom computer, open `/debug/audio`, click "השמע אות בדיקה" (play test signal) and turn the volume up.
2. On a phone, open the same page through the `PUBLIC_URL` address and tap "התחל להקשיב" (start listening).
3. From the far end of the room, check that the level bars rise and that the decoded code matches the one on the computer. Below 14 dB above the noise, decoding won't work; move a speaker closer or turn it up.

If a phone can't pick up the signal, the lecturer can still mark that student as present by hand in the lesson report.

## Tests

```bash
pytest -q
```

There are 224 tests, and they need no network and no models. They use a fake clock and fake transcription and LLM implementations, and cover, among other things, the 5-sample limit, audio code expiry and replay, the wrong-code lockout, manual marking, the migration of old attendance records, unique votes, one reaction per user, anonymity by role, feedback privacy, late and graded submissions, publishing grades, weighted grades, appeals, and permissions.
