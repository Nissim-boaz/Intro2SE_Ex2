# Moodle+

A course website built for assignment 2 of Introduction to Software Engineering. Every course has a page with content, assignments, in-class attendance sampling, lesson recordings with an AI summary and chapters, and a group chat with polls. The interface is in Hebrew (right to left) and designed for phones first.

## What's in the system

There are three roles:

- **Admin** creates users and courses and assigns lecturers and students to courses. Students can be imported from a CSV or XLSX file, including a Moodle participants export as is.
- **Lecturer** edits the course page content, publishes and grades assignments, opens attendance samples, uploads recordings and creates polls in the chat.
- **Student** sees their courses, submits assignments, checks in to attendance, writes in the chat (optionally anonymously) and votes in polls.

A user's role applies in every course they are assigned to: a lecturer is a lecturer in all of their courses. Changing a user's role updates the courses they are already in.

Sign-in is with a Google account, and the server verifies the ID token. Anyone not listed in the users table can't get in. For development and demos there is a `MOCK_AUTH` mode with a role and user picker.

Students and lecturers can send a request to the admins from the account menu (for example, a missing course or an attendance mistake). Each request is a conversation: the admins reply and set its status (new, in progress, resolved or rejected), and the requester gets a red dot in the menu when there is an update. A resolved or rejected request is deleted 7 days after it was closed.

The home page and the admin lists (users, courses, course members) have a live search field that filters as you type.

The course page has a floating tab bar at the bottom (content, assignments, attendance, recordings, chat), with an unread count on the chat icon.

### Assignments

The lecturer publishes an assignment with instructions, a due date and an optional attached file. Each student submits one file and can replace it until the lecturer grades it. Submitting after the due date is allowed and marked as late; moving the due date updates the late mark on work already sent. The lecturer sees who submitted and who didn't, downloads each submission, and gives a grade (0 to 100) and a note that only that student sees. Grades stay hidden while the lecturer is grading, and one click publishes them to all students at once. After that, a student can appeal a grade once, and the lecturer accepts it with a new grade or rejects it with a reason.

### Attendance

The lecturer enters a lesson number and opens a sample. A new number starts a new lesson, and an existing number adds a sample to that lesson, up to 5 samples per lesson. Each sample stays open for a short time (2 minutes by default).

When the lecturer clicks "התחל" (start) on the sample screen, the computer plays a short audible chime so the class knows a sample has started. Then the speaker plays a high-frequency signal (17.2 to 19.5 kHz) that most people can't hear. The signal carries a code that changes every 4 seconds on the server's clock (not the computer's, which may be set wrong). The code is derived with HMAC from the server secret, the sample id and the time window, and is never stored in the database.

The sample screen is meant to be projected. It shows the time left and the names of the students who checked in, updated live.

On the student's course page, a "בצע נוכחות" (check in) button appears as soon as the sample opens, without refreshing. Tapping it asks for microphone permission (only the first time, since the browser remembers the answer), then the phone listens for up to 10 seconds, decodes the signal and sends the code to the server. Nothing is recorded or uploaded except the decoded number.

The server accepts the current code and the one before it, so a code is valid for at most 8 seconds after it starts playing. That covers decoding on the phone (about 2 seconds) and a slow network, and is too short to record the sound, send it on WhatsApp and play it back. Phone calls and voice messages also cut frequencies this high, so the signal doesn't survive them. A check-in that arrives a few seconds after the sample closes still counts if its code is valid.

There is no check-in without a valid code. A wrong or old code is rejected with a message, and the student can try again while the sample is open. After 5 wrong codes in a sample the student is blocked from it, so the 12-bit code can't be guessed. In the lesson report the lecturer can mark a student as present by hand (for example, a phone that didn't pick up the sound) and can cancel any attendance. Manual marks are labeled in the report and in the CSV. On the course page each student sees their own attendance per lesson, and can appeal a sample they were marked absent in once it closes. The lecturer sees open appeals at the top of the lesson report and accepts them (which marks the student present) or rejects them with a reason.

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
    assignments.py   AssignmentService
    tokens.py        TokenClock, AudioTokenService
    attendance.py    AttendanceService, AttendanceReport
    attendance_appeals.py AttendanceAppealService
    chat.py          ChatService, SenderMask, ReactionService, ReadReceiptService
    polls.py         PollService
    requests.py      RequestService (requests to the admins)
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
python seed.py --reset           # demo data: a lecturer, 105 students, a course with content, assignments, chat and a poll
python run.py
```

The site runs at `http://localhost:5001` (the exact address is printed on start). Port 5000 is skipped because macOS uses it for AirPlay Receiver; if 5001 is taken, the next free port is used. Set `PORT` to force a specific port. With `MOCK_AUTH=1`, the sign-in page lets you pick a role and a user. The admin's email comes from `ADMIN_EMAIL`, and the admin is created automatically on the first run.

Important settings in `.env`:

| Variable | What it does |
| --- | --- |
| `SECRET_KEY` | The secret the tokens and the session are derived from. For the demo it must be long and random |
| `MOCK_AUTH` | `1` shows the role picker, `0` leaves only Google |
| `GOOGLE_CLIENT_ID` | From Google Cloud Console |
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
cloudflared tunnel --url http://localhost:5001 # in a second window (use the port printed on start)
```

cloudflared prints an address like `https://something.trycloudflare.com`, which is what you open on the phones. The address changes on every run. For Google sign-in to work behind the tunnel, add the address in Google Cloud Console under Authorized JavaScript origins.

## Testing in the lecture hall before the demo

1. On the classroom computer, open `/debug/audio`, click "השמע אות בדיקה" (play test signal) and turn the volume up.
2. On a phone, open the same page through the tunnel and tap "התחל להקשיב" (start listening).
3. From the back row, check that the level bars rise and that the decoded code matches the one on the computer. Below 14 dB above the noise, decoding won't work; move a speaker closer or turn it up.

If a phone can't pick up the signal, the lecturer can still mark that student as present by hand in the lesson report.

## Tests

```bash
pytest -q
```

The tests need no network and no models. They use a fake clock and fake transcription and LLM implementations, and cover, among other things, the 5-sample limit, audio code expiry and replay, the wrong-code lockout, manual marking, the migration of old attendance records, unique votes, one reaction per user, anonymity by role, feedback privacy, late and graded submissions, publishing grades, appeals, and permissions.
