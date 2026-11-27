# 6. Class diagrams and sequence diagrams

The classes are in `moodleplus/services/`. Each diagram shows the main public methods; small helpers are left out.

## Class diagrams

### Attendance
```mermaid
classDiagram
  class ServiceError
  class SampleLimitReached
  class SampleClosed
  class AlreadyCheckedIn
  class WrongCode
  class TooManyAttempts
  ServiceError <|-- SampleLimitReached
  ServiceError <|-- SampleClosed
  ServiceError <|-- AlreadyCheckedIn
  ServiceError <|-- WrongCode
  ServiceError <|-- TooManyAttempts

  class TokenClock {
    +now() float
    +window(at) int
    +seconds_left(at) float
  }
  class AudioTokenService {
    +max_age_seconds() int
    +code(sample_id, window) int
    +symbols(code) list
    +decode(symbols) int
    +verify(sample_id, code, at) bool
  }
  class Lesson {
    +id
    +course_id
    +number
  }
  class Sample {
    +id
    +lesson_id
    +seq
    +opened_at
    +closes_at
    +is_open(at) bool
    +seconds_left(at) int
  }
  class Record {
    +id
    +sample_id
    +student_id
    +method
    +manual() bool
    +label() str
  }
  class AttendanceService {
    +open_sample(course_id, lesson_number, duration_seconds, opened_by) Sample
    +close_sample(sample_id)
    +check_in(sample_id, student, audio_code) Record
    +mark_manual(sample_id, student_id, by) Record
    +remove_record(record_id)
    +attendees(sample_id) list
    +attempts_left(sample_id, student_id) int
  }
  class AttendanceReport {
    +build(lesson_id, students) tuple
    +to_csv(lesson, students) bytes
  }
  class AttendanceAppealService {
    +history(course_id, student_id) list
    +appeal(sample_id, student, text) AttendanceAppeal
    +resolve(appeal_id, lecturer, accept, reply) AttendanceAppeal
  }
  AudioTokenService --> TokenClock
  AttendanceService --> AudioTokenService : verify the code
  AttendanceService --> TokenClock
  AttendanceService ..> Sample
  AttendanceService ..> Record
  AttendanceService ..> ServiceError : raises
  Lesson "1" o-- "1..5" Sample
  Sample "1" o-- "*" Record
  AttendanceReport --> AttendanceService
  AttendanceAppealService --> AttendanceService : accept marks present
```

### Chat and polls
```mermaid
classDiagram
  class ChatService {
    +send(course_id, sender, body, reply_to_id, anonymous, poll_id) int
    +list_messages(course_id, viewer, since) list
    +delete(message_id, user)
    +set_pinned(message_id, pinned)
    +set_locked(course_id, locked)
    +search(course_id, viewer, query) list
  }
  class SenderMask {
    +name_for(viewer, sender_id, sender_name, anonymous) str
    +reveals_identity(viewer, anonymous) bool
  }
  class ReactionService {
    +toggle(message_id, user, emoji) str
    +who(message_id) list
  }
  class ReadReceiptService {
    +mark_read(course_id, user, up_to_id) int
    +unread_count(course_id, user) int
    +info(message_id, viewer) dict
  }
  class PollService {
    +create(course_id, creator, question, options, anonymous) int
    +vote(poll_id, user, option_id)
    +results(poll_id, viewer) dict
  }
  ChatService --> SenderMask : hides anonymous senders
  ChatService --> PollService : poll results inside messages
  PollService ..> ChatService : a poll is posted as a message
```

### Recordings
```mermaid
classDiagram
  class RecordingService {
    +create(course_id, title, filename, mime, upload, uploaded_by) Recording
    +process(recording_id, transcriber, summarizer) Recording
    +retry(recording_id)
    +set_published(recording_id, published)
    +update_details(recording_id, title, summary, key_points, chapters) Recording
    +update_transcript(recording_id, texts) Recording
    +request_feedback(recording_id) int
    +write_feedback(recording_id, writer, job) Recording
  }
  class BackgroundJobRunner {
    +start()
    +enqueue(recording_id)
    +enqueue_feedback(recording_id, job)
  }
  class Transcriber {
    <<abstract>>
    +transcribe(media_path, hint) list
  }
  class WhisperTranscriber
  class AudioExtractor {
    +extract(media_path, out_dir) str
  }
  class LLMProvider {
    <<abstract>>
    +generate_json(prompt) dict
  }
  class GeminiProvider
  class LessonSummarizer {
    +summarize(segments) LessonSummary
  }
  class LessonFeedbackWriter {
    +write(segments) LessonFeedback
  }
  Transcriber <|-- WhisperTranscriber
  LLMProvider <|-- GeminiProvider
  WhisperTranscriber --> AudioExtractor : ffmpeg
  BackgroundJobRunner --> RecordingService
  BackgroundJobRunner --> Transcriber
  BackgroundJobRunner ..> LessonSummarizer : creates
  BackgroundJobRunner ..> LessonFeedbackWriter : creates
  RecordingService ..> Transcriber
  RecordingService ..> LessonSummarizer
  LessonSummarizer --> LLMProvider
  LessonFeedbackWriter --> LLMProvider
```

### Assignments, grades and AI grading
```mermaid
classDiagram
  class AssignmentService {
    +create(course_id, title, description, due) Assignment
    +submit(assignment_id, student, file_name, upload) Submission
    +grade(submission_id, grade, feedback) Submission
    +set_grades_published(assignment_id, published)
    +appeal(submission_id, student, text) Submission
    +resolve_appeal(submission_id, accept, reply, new_grade) Submission
    +set_solution_published(assignment_id, published)
  }
  class Assignment {
    +id
    +title
    +due_at
    +weight
    +grades_published
    +solution_published
  }
  class Submission {
    +id
    +student_id
    +file_name
    +submitted_at
    +grade
    +appeal_status
    +ai_grade
  }
  class ExamService {
    +create(course_id, title, kind, held_on, weight) Exam
    +save_grades(exam_id, changes) int
    +import_file(exam_id, filename, data) ImportReport
    +set_published(exam_id, published) int
    +appeal(grade_id, student, text) ExamGrade
  }
  class Gradebook {
    +set_weights(course_id, weights) float
    +for_student(course_id, student_id) GradeRow
    +table(course_id) tuple
    +to_csv(course_id) bytes
  }
  class AIGradingService {
    +save_settings(assignment_id, guidelines, file_name, upload)
    +request(assignment_id, redo) int
    +cancel(assignment_id)
    +run(assignment_id, job, provider)
    +approve(submission_id)
    +approve_all(assignment_id) int
  }
  class AIGradingRunner {
    +start()
    +enqueue(assignment_id, job)
  }
  class SubmissionReviewer {
    +review(assignment, guidelines, solution, submission) Review
  }
  class ClassComparer {
    +compare(title, items) dict
  }
  class LLMProvider {
    <<abstract>>
    +generate_json(prompt) dict
  }
  Assignment "1" o-- "*" Submission
  AssignmentService ..> Assignment
  AssignmentService ..> Submission
  AIGradingService --> AssignmentService
  AIGradingService ..> SubmissionReviewer : one per run
  AIGradingService ..> ClassComparer : once per run
  SubmissionReviewer --> LLMProvider
  ClassComparer --> LLMProvider
  AIGradingRunner --> AIGradingService
```
`Gradebook` reads the published assignment and exam grades straight from the database, so it doesn't depend on the other two services.

### Users and courses
```mermaid
classDiagram
  class UserService {
    +create(email, name, role) User
    +find_by_email(email) User
    +update(user_id, name, role, email) User
    +ensure_admin(email) User
  }
  class StudentImporter {
    +read_rows(filename, data) list
    +import_file(filename, data) ImportResult
  }
  class SignupService {
    +submit(name, email, role) SignupRequest
    +approve(request_id, role) User
    +reject(request_id)
  }
  class GoogleTokenVerifier {
    +verify(credential) dict
  }
  class CourseService {
    +create(name, code, description) Course
  }
  class EnrollmentService {
    +enroll(course_id, user)
    +role_in(course_id, user) str
    +require_member(course_id, user) str
    +require_manager(course_id, user)
  }
  class ContentService {
    +add(course_id, kind, title, body, url, file_name, file_data) ContentBlock
    +move(block_id, direction)
  }
  class FileStore {
    +save(folder, filename, data) str
    +path(rel) Path
  }
  StudentImporter --> UserService
  SignupService --> UserService
  ContentService --> FileStore
```

## Sequence diagrams

### Attendance check-in (main feature)
```mermaid
sequenceDiagram
  actor L as Lecturer
  participant PC as Classroom computer
  participant S as Server (AttendanceService, AudioTokenService)
  actor St as Student phone
  L->>S: open_sample(course, lesson number, duration)
  S-->>L: Sample, and the sample screen opens
  L->>PC: press start
  PC->>PC: play the chime
  loop every second
    PC->>S: GET live (code, time left, names)
    S-->>PC: code for the current 4-second window
    PC->>PC: play the code at 17.2 to 19.5 kHz
  end
  loop every 3 seconds
    St->>S: GET attendance panel
    S-->>St: a sample is open, show the check-in button
  end
  St->>St: tap, microphone, listen up to 10 s, decode
  St->>S: POST attend(sample_id, code)
  S->>S: check_in: sample open? already checked in? attempts left?
  S->>S: verify(code) against the current and previous window
  alt valid code
    S->>S: save Record (method audio)
    S-->>St: checked in
    Note over PC,S: the next live poll shows the student's name
  else wrong or old code
    S->>S: count a wrong attempt (locked after 5)
    S-->>St: error, try again
  end
```

### Attendance appeal and report
```mermaid
sequenceDiagram
  actor St as Student
  actor L as Lecturer
  participant S as Server (AttendanceAppealService, AttendanceService)
  St->>S: appeal(sample_id, text), after the sample closed
  S-->>St: waiting for the lecturer
  L->>S: open the lesson report
  S-->>L: students by samples, and open appeals
  alt accept
    L->>S: resolve(appeal, accept)
    S->>S: mark_manual(sample, student)
  else reject
    L->>S: resolve(appeal, reject, optional reply)
  end
  L->>S: export CSV
  S-->>L: CSV that opens in Excel
```

### Recording: upload to summary
```mermaid
sequenceDiagram
  actor L as Lecturer
  participant S as RecordingService
  participant R as BackgroundJobRunner
  participant T as WhisperTranscriber
  participant G as LessonSummarizer (Gemini)
  L->>S: create(file), a draft with status uploaded
  S->>R: enqueue(recording_id)
  R->>S: process(recording_id, transcriber, summarizer)
  S->>T: transcribe (ffmpeg extracts the audio, faster-whisper runs locally)
  T-->>S: segments with times
  S->>G: summarize(segments)
  alt success
    G-->>S: summary, key points, chapters
    S->>S: status ready
  else failure
    S->>S: keep the transcript, status failed
    Note over L,S: a retry runs only the summary
  end
  L->>S: edit, then set_published(true)
  S-->>L: students can see it
```

### AI-assisted grading
```mermaid
sequenceDiagram
  actor L as Lecturer
  participant A as AIGradingService
  participant R as AIGradingRunner
  participant G as Gemini (SubmissionReviewer, ClassComparer)
  participant SV as AssignmentService
  actor St as Student
  L->>A: save_settings(notes, solution), request()
  A->>R: enqueue(assignment, job)
  R->>A: run(assignment, job, provider)
  loop each new or changed submission
    A->>G: review(submission)
    G-->>A: grade, reason, feedback, deductions
  end
  A->>G: compare the whole class (no names)
  G-->>A: a note for each submission
  A->>A: local text comparison, copy flag for the lecturer
  L->>A: approve(submission) or approve_all()
  A->>SV: grade(submission, AI grade, feedback)
  L->>SV: set_grades_published(assignment, true)
  SV-->>St: grade and feedback, only after publishing
```

### Anonymous chat message
```mermaid
sequenceDiagram
  actor St as Student
  participant C as ChatService
  participant M as SenderMask
  actor X as Another user
  St->>C: send(body, anonymous=true)
  C->>C: save sender_id with is_anonymous
  X->>C: list_messages(viewer)
  C->>M: name_for(viewer, sender)
  M-->>C: "anonymous", or the real name only for an admin
  C-->>X: JSON without the sender's identity
```
