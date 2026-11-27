# 7. Testing strategy

## Goal
Show that each class in the services layer (see [components](05_components.md)) follows its rules, and that permissions and privacy hold, with no network, no AI model and no real clock.

## Approach
- **Automated tests with pytest** (`pytest -q`). Each test gets a new temporary SQLite database (`tests/conftest.py`). Most tests call the services directly; route tests use the Flask test client to check permissions and responses.
- **Fakes instead of outside systems:**
  - `FakeClock` (`tests/fakes.py`) moves time forward by hand, so the 4-second windows, the 8-second code life and sample closing are exact.
  - `FakeTranscriber` and `FakeLLM` (in `test_recordings.py` and `test_ai_grading.py`) replace Whisper and Gemini.
  - A fake Google verifier, and tokens signed with our own test keys, replace Google sign-in.
- **Layers:** routes only call services, so testing the services covers the rules. Route tests check that each role sees and does only what it should.
- **Real runs** for what the fakes can't show: Google sign-in, the Tailscale address, and a real recording and a real submission through Whisper and Gemini (see the [tools report](01_tools_report.md)).

## Test map
224 tests in 18 files, all passing.

| Class under test | File | Tests | What it checks |
|---|---|---|---|
| `TokenClock`, `AudioTokenService` | `test_tokens.py` | 6 | symbols round trip, check symbol, a new code every window, valid for at most two windows, tied to the sample and the secret |
| `AttendanceService`, `AttendanceReport` | `test_attendance.py` | 25 | 5-sample limit, one open sample per course, replayed and wrong codes, lockout after 5, closing time, duplicates, manual marks, report percentages, CSV with BOM, old records migrated |
| `AttendanceAppealService` | `test_attendance_appeals.py` | 4 | appeal only after closing and only once, accept marks present, reject without a reason |
| `ChatService`, `SenderMask`, `ReactionService`, `ReadReceiptService` | `test_chat.py` | 40 | anonymity by role (including replies, search and pins), one reaction per user, deleting, read receipts, locking, pins (up to 3), search |
| Stars and chat themes | `test_chat_personal.py` | 6 | stars are personal and keep anonymity, theme scope |
| `PollService` | `test_polls.py` | 13 | one vote per user that can be changed, the creator doesn't vote, anonymous and open polls, only lecturers create |
| `RecordingService`, `BackgroundJobRunner`, `LessonSummarizer`, `GeminiProvider` | `test_recordings.py` | 34 | status flow, a failed summary keeps the transcript, retry, drafts hidden from students, editing, private feedback, Gemini retry and fallback |
| `AssignmentService` | `test_assignments.py` | 11 | late submissions, replacing a file until grades are published, hidden grades, appeals, permissions |
| `ExamService`, `Gradebook` | `test_gradebook.py` | 14 | weights up to 100%, only published grades count, grade import, solution publishing closes submission, zeros, exam appeals |
| `AIGradingService`, `SubmissionReviewer`, `ClassComparer` | `test_ai_grading.py` | 8 | suggestions only, approve one or all, class note, copy flag, only new work is reviewed, deductions in the feedback, reading documents |
| `ContentService` | `test_content.py` | 5 | blocks in order, moving, editing, students can't add |
| `UserService`, `StudentImporter` | `test_users.py` | 11 | CSV and Moodle XLSX import, duplicate and invalid emails, the last admin is protected |
| `GoogleTokenVerifier`, admin email | `test_google_signin.py` | 16 | signature, audience, expiry, verified email, only registered users, `Secure` cookie over HTTPS, the development-mode strip |
| `SignupService` | `test_signups.py` | 4 | validation, approve and reject, the full path to signing in, the bot trap |
| `RequestService` | `test_requests.py` | 9 | who can see a request, status changes, deletion after 7 days, admins can reply without a name |
| `EnrollmentService`, routes | `test_permissions.py` | 13 | course roles, outsiders blocked, admin-only pages, sign-in flow |
| Public pages | `test_pages.py` | 3 | privacy and terms pages are open to everyone |
| Static files (`web_speed.py`) | `test_web_speed.py` | 2 | versioned files with long caching, compressed text |

## Checking the sound in a room
Automated tests cover the code on the server, but not the speaker and the microphone. To check them:
1. On the classroom computer, open `/debug/audio` and play the test signal.
2. On a phone, open the same page and start listening.
3. From the far end of the room, check that the level rises and the decoded code matches the computer.
If a phone still can't decode the signal, the lecturer marks the student by hand.

## Done when
- All pytest tests pass.
- The sound check above decodes the code on the phones.
