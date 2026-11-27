# 3. Software Requirements Specification (SRS)

## 1. Introduction
Moodle+ is a web app for teaching in class. It has three roles: admin, lecturer and student. The interface is in Hebrew, right to left, and designed for phones first.

## 2. Overall description
- A Flask server (Python 3.12+) with SQLite. Pages are rendered on the server, with plain JavaScript in the browser.
- External services: Google sign-in and Google Gemini. ffmpeg and faster-whisper run on the server machine.
- The phone microphone needs HTTPS.

| Role | Can |
|---|---|
| Admin | Manage users, courses and enrollments; import students from CSV or XLSX; approve sign-up requests; answer requests; see who sent an anonymous message; everything a lecturer can do |
| Lecturer (in their courses) | Edit course content; open attendance samples and mark attendance; manage assignments, exams and grades; upload recordings; create polls; pin messages and lock the chat |
| Student (in their courses) | View content; check in; submit assignments; appeal grades and attendance; chat; vote |

## 3. Functional requirements

**Accounts**
- FR-1 Users sign in with Google. The server checks the ID token: signature, audience, expiry and a verified email. Anyone not in the users table is refused.
- FR-2 Someone who isn't listed can send a sign-up request (name, email, student or lecturer), and an admin approves or rejects it.
- FR-3 Users can send requests to the admins and follow their status. Closed requests are deleted after 7 days.

**Attendance (main feature)**
- FR-4 The lecturer opens a sample for a lesson number. A lesson has up to 5 samples, and a sample is open for 2 minutes by default.
- FR-5 The classroom computer plays a short chime, then a 17.2 to 19.5 kHz signal that carries a code. The code changes every 4 seconds on the server's clock.
- FR-6 The check-in button appears on the student's course page without a refresh. The phone listens for up to 10 seconds, decodes the code and sends only the code.
- FR-7 The server accepts the current code and the one before it, so a code is valid for at most 8 seconds. A valid code that arrives up to 4 seconds after the sample closes still counts.
- FR-8 After 5 wrong codes, the student can't check in to that sample.
- FR-9 The projected sample screen shows the time left and the names of the students who checked in, updated live.
- FR-10 The lecturer can mark a student present by hand and can cancel any record. Manual marks are labeled in the report.
- FR-11 A student sees their own attendance and can appeal once for a closed sample they missed. The lecturer accepts (the student is marked present) or rejects, with an optional reply.
- FR-12 The lesson report shows students by samples with a percentage per student, and exports to a CSV that opens correctly in Excel.

**Comments and polls**
- FR-13 Each course has one chat: replies, reactions (one per user per message), deleting your own messages, read receipts and search.
- FR-14 A message can be sent anonymously. The name is hidden from everyone, including the lecturer, and only the admin can see it. The hiding is done on the server.
- FR-15 The lecturer and the admin can pin up to 3 messages and can lock the chat, so only they can write.
- FR-16 The lecturer creates a poll in the chat, anonymous by default or open. Everyone in the course except its creator can vote once and change the vote. Results update every 2.5 seconds.

**Recordings**
- FR-17 The lecturer uploads audio or video. In the background, the server transcribes it and the AI writes a summary, key points and chapters with times.
- FR-18 A new recording is a draft. The lecturer can edit it and then publishes it. Students get a player with chapters, the summary and the transcript.
- FR-19 The lecturer who uploaded a recording can ask for private feedback on the lesson. Nobody else sees it.

**Assignments and grades**
- FR-20 The lecturer publishes an assignment with instructions, a due date and an optional file. A student submits one file and can replace it until grades are published. Late submissions are allowed and marked.
- FR-21 Grades are 0 to 100, with a note for the student. They stay hidden until the lecturer publishes them to everyone at once. A student can appeal each grade once.
- FR-22 The lecturer can add a solution file. It can be published only after the due date, and publishing it closes submission.
- FR-23 AI review: for each submission, a suggested grade, a reason, feedback with the point deductions, and a note relative to the class (no names). A local text comparison flags submissions that look copied, for the lecturer only. The lecturer approves each suggestion or all of them. Students see nothing before grades are published.
- FR-24 Exams and quizzes, with grades entered by hand or imported from CSV or XLSX. Each assignment, exam and quiz can have a weight, up to 100% in total. The student sees a weighted grade so far, and the lecturer sees a class table and can export it.

## 4. Non-functional requirements
- NFR-1 Usability: simple and phone first; checking in is one tap.
- NFR-2 Security: codes are never stored; all permission checks are on the server; the session cookie is `Secure` over HTTPS.
- NFR-3 Privacy: the phone sends only the decoded number, never audio; anonymous senders are removed before the data reaches the browser; the repository holds no real student data.
- NFR-4 Reliability: if a summary fails, the transcript is kept and a retry runs only the summary; the lecturer can always mark attendance by hand.
- NFR-5 Maintainability: routes only call services; all rules live in the services layer, which is tested with fakes.
- NFR-6 Setup: `pip install -r requirements.txt`, settings in `.env`, `python run.py`.

## 5. Data
All tables are in `moodleplus/schema.sql`:
- Users and access: `users`, `signup_requests`, `app_settings`, `requests`, `request_messages`
- Courses: `courses`, `enrollments`, `content_blocks`
- Attendance: `lessons`, `attendance_samples`, `attendance_records`, `attendance_attempts`, `attendance_appeals`
- Chat and polls: `messages`, `message_reactions`, `message_reads`, `message_stars`, `chat_themes`, `polls`, `poll_options`, `poll_votes`
- Recordings: `recordings`
- Assignments and grades: `assignments`, `submissions`, `assignment_zeros`, `exams`, `exam_grades`
