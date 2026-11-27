# 8. Conclusion

## What we built
Moodle+ is a course website in Hebrew, designed for phones first. The main feature is attendance: the classroom computer plays a code that most people can't hear and that changes every few seconds. The students' phones decode it and check in, and the lecturer sees a live list and exports a CSV. Around it there are a course chat with anonymous messages, polls, recordings with local transcription and an AI summary, and homework grading with AI suggestions and a copy check.

## Results
- All five features in the brief work in the app, plus admin screens, sign-up requests, a gradebook with weights, and appeals.
- 224 automated tests pass. They use a fake clock and fakes for transcription, the AI and Google, so they need no network.
- Real runs worked: Google sign-in, a permanent HTTPS address through Tailscale Funnel, a lesson recording through ffmpeg, Whisper and Gemini, and an AI review of a real submission.

## What worked well
- The 4-second HMAC code, valid for at most 8 seconds, makes forwarding a recording of the signal useless. Only a number leaves the phone.
- Thin routes with all the logic in services made the rules easy to test.
- Manual marks and appeals cover the cases where a phone misses the sound.

## Limits and lessons
- Decoding depends on the speakers, the distance and the noise, so we added the `/debug/audio` page and the manual fallback.
- AI output can be wrong, so it stays a suggestion until the lecturer approves it.
- The Gemini free tier can be overloaded (we saw 503 errors), so the client retries and then falls back to a second model.
- On the free tier Google may use the content, so recordings with sensitive information shouldn't be uploaded.
- We chose polling (every 2.5 seconds in the chat) over sockets, to keep it simple.

## Future work
Sockets instead of polling, hosting on a server with backups, an option for a local AI model, and more languages.
