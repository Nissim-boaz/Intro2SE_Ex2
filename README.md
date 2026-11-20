# Moodle+

A course website built for assignment 2 of Introduction to Software Engineering. Every course has a page with content, in-class attendance sampling, lesson recordings with an AI summary and chapters, and a group chat with polls. The interface is in Hebrew (right to left) and designed for phones first.

## What's in the system

There are three roles:

- **Admin** creates users and courses and assigns lecturers and students to courses. Students can be imported from a CSV or XLSX file, including a Moodle participants export as is.
- **Lecturer** edits the course page content, opens attendance samples, uploads recordings and creates polls in the chat.
- **Student** sees their courses, checks in to attendance, writes in the chat (optionally anonymously) and votes in polls.

A user's role applies in every course they are assigned to: a lecturer is a lecturer in all of their courses. Changing a user's role updates the courses they are already in.

Sign-in is with a Google account, and the server verifies the ID token. Anyone not listed in the users table can't get in. For development and demos there is a `MOCK_AUTH` mode with a role and user picker.

The home page and the admin lists (users, courses, course members) have a live search field that filters as you type.

### Attendance

The lecturer enters a lesson number and opens a sample. A new number starts a new lesson, and an existing number adds a sample to that lesson, up to 5 samples per lesson. Each sample stays open for a short time (2 minutes by default).

During a sample, the lecturer's screen shows a QR code that changes every 6 seconds, while the speaker plays a high-frequency signal (17.2 to 19.5 kHz) that most people can't hear. The signal changes too. Both codes are derived with HMAC from the server secret, the sample id and the time window, and are never stored in the database.

The student scans the QR code with the phone camera. The page that opens listens to the microphone for a few seconds, decodes the signal and sends it to the server. If there is no microphone, no permission, or decoding doesn't succeed within 10 seconds, attendance is still recorded with the QR code only and marked as suspicious. The same happens when the IP address is outside the campus ranges. The lecturer approves or rejects suspicious records in the lesson report. A student is never blocked because of the audio alone.

The report is a matrix of students by samples, with an attendance percentage per student, and a CSV export that opens correctly in Excel.

### Chat and polls

One chat per course, opened full screen, in a WhatsApp-like style:

- Reply with a quote, delete your own messages, blue ticks once every member has read a message, and a message info view showing who read it.
- Reactions: a row of the reactions you used most recently, plus a **+** button for any emoji (the phone's emoji keyboard, or a picker on a computer). One reaction per user per message.
- Anonymous messages: the name is hidden from everyone, including the lecturer. Only the admin can see who sent it, to handle harassment. The hiding is done on the server, so the JSON that reaches the browser doesn't contain the sender either.
- Date separators between days, and message search (text and poll questions, never sender names, so search can't reveal who wrote an anonymous message).
- The course lecturer can pin up to 3 messages. A fourth pin replaces the oldest one.
- The lecturer or admin can mute students, so only they can send messages.

The lecturer creates a poll from the chat and chooses with a toggle whether voting is anonymous. In an anonymous poll (the default) everyone sees only the vote counts. In an open poll everyone can also see who voted for each option. Each student votes once and can change their choice. Updates arrive by polling every 2.5 seconds.

### Recordings

The lecturer uploads a video or audio file. In the background, ffmpeg extracts the audio, faster-whisper (the `small` model) transcribes it on the local machine, and Gemini writes a summary, key points and chapters with timestamps. Recordings appear on the course page as cards, and each one has its own page with a player, chapters, summary and the full transcript. Clicking a chapter jumps the player to that point. If the summary fails, the transcript is kept, and a retry runs only the summary again.

A new recording starts as a draft that only lecturers and the admin can see. Before publishing, the lecturer can edit the title, summary, key points, chapters and the transcript text, and can hide a published recording again.

The lecturer who uploaded a recording can ask for private feedback on the lesson (language, content, clarity and pace). Only that lecturer sees it: not other lecturers in the course, not students and not the admin. There is one feedback per recording. A new one can be requested only after the lecturer has edited and saved the transcript. For recordings with no uploading lecturer (uploaded by the admin, uploaded before this feature, or the uploader left the course), the feedback is open to all of the course's lecturers.

## Code structure

```
moodleplus/
  __init__.py        create_app: registers blueprints, the DB and error handling
  schema.sql         all tables (SQLite in WAL mode)
  services/          the logic, with no Flask. Each class has one responsibility
    users.py         UserService, StudentImporter
    courses.py       CourseService, EnrollmentService (course-level permissions)
    content.py       ContentService, FileStore
    tokens.py        TokenClock, QrTokenService, AudioTokenService
    network.py       CampusNetworkPolicy
    attendance.py    AttendanceService, AttendanceReport
    chat.py          ChatService, SenderMask, ReactionService, ReadReceiptService
    polls.py         PollService
    recordings.py    RecordingService, BackgroundJobRunner
    transcription.py Transcriber, WhisperTranscriber, AudioExtractor
    llm.py           LLMProvider, GeminiProvider, LessonSummarizer, LessonFeedbackWriter
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
python seed.py --reset           # demo data: a lecturer, 105 students, a course with content, chat and a poll
python run.py
```

The site runs at `http://localhost:5000`. With `MOCK_AUTH=1`, the sign-in page lets you pick a role and a user. The admin's email comes from `ADMIN_EMAIL`, and the admin is created automatically on the first run.

Important settings in `.env`:

| Variable | What it does |
| --- | --- |
| `SECRET_KEY` | The secret the tokens and the session are derived from. For the demo it must be long and random |
| `MOCK_AUTH` | `1` shows the role picker, `0` leaves only Google |
| `GOOGLE_CLIENT_ID` | From Google Cloud Console |
| `CAMPUS_CIDRS_FILE` | The file with the campus IP ranges. The default is `data/campus_ips.txt` |
| `GEMINI_API_KEY` | A free key from [Google AI Studio](https://aistudio.google.com/apikey) |
| `GEMINI_MODEL` | The default is `gemini-3.8-flash` |
| `WHISPER_MODEL` | The default is `small`. Use `base` for faster transcription |

On the first upload, faster-whisper downloads the model (about 460 MB), and it is cached after that. On a laptop, transcribing a 90-minute lesson takes roughly 20 to 40 minutes.

Note: on the Gemini free tier, Google may use the content to improve its models, so don't upload recordings with sensitive information.

## Running with a tunnel (for phones)

On a phone, the microphone works only over HTTPS. The simplest way is a Cloudflare Quick Tunnel, which is free and needs no account:

```bash
winget install --id Cloudflare.cloudflared     # on Mac: brew install cloudflared
python run.py                                  # in one window
cloudflared tunnel --url http://localhost:5000 # in a second window
```

cloudflared prints an address like `https://something.trycloudflare.com`, which is what you open on the phones. The address changes on every run. For Google sign-in to work behind the tunnel, add the address in Google Cloud Console under Authorized JavaScript origins.

Behind the tunnel, the server sees the phone's public IP address through the `CF-Connecting-IP` header. So `data/campus_ips.txt` must list the campus network's public ranges, not internal addresses like `10.x`. An empty file turns the IP check off.

## Testing in the lecture hall before the demo

1. On the classroom computer, open `/debug/audio`, click "השמע אות בדיקה" (play test signal) and turn the volume up.
2. On a phone, open the same page through the tunnel and tap "התחל להקשיב" (start listening).
3. From the back row, check that the level bars rise and that the decoded code matches the one on the computer. Below 14 dB above the noise, decoding won't work; move a speaker closer or turn it up.

Even if the audio doesn't work in the hall, the demo goes on: attendance is recorded with the QR code only, and the lecturer approves it in the report.

## Tests

```bash
pytest -q
```

The tests need no network and no models. They use a fake clock and fake transcription and LLM implementations, and cover, among other things, the 5-sample limit, QR and audio token expiry, the fallback path, unique votes, one reaction per user, anonymity by role, feedback privacy and permissions.
