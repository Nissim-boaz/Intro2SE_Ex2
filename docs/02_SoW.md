# 2. Statement of Work (SoW)

**Project:** Moodle+, a web-based teaching tool.
**Course:** Introduction to Software Engineering, Ariel University, assignment 2.
**Team:** Bnaya Amitay, Nissim Boaz.

## Purpose
A working, phone-first web app for a class. It makes attendance simple and adds comments, polls, recording summaries and homework review. The problem and the scope are in the [README](../README.md#problem-and-scope).

## Objectives
1. Students mark attendance from their phones with no roll call, and the lecturer exports it as a spreadsheet. This is the main feature.
2. Students comment and make suggestions, during class or later.
3. The lecturer runs quick polls on the current material.
4. The lecturer gets an AI summary of a lesson recording.
5. Students and lecturers get an AI review of homework, including a comparison with the rest of the class.

## Deliverables
| Deliverable | Where |
|---|---|
| Source code and sample data (`seed.py`) | the repository |
| Problem, scope and setup | `README.md` |
| Tools report, SoW, SRS, use cases, components, diagrams, testing strategy, conclusion | `docs/` |
| Automated tests | `tests/` |
| Demo video | link in the README |

## Work plan
1. Define the problem and the scope; create the repository and the README.
2. Research the tools and try each one.
3. Write the SRS, the use cases and the main components.
4. Build the core: users, courses, attendance, with tests.
5. Build the chat, polls, recordings, assignments, grades and AI review.
6. Draw the class and sequence diagrams; write the testing strategy.
7. Record the demo video, write the conclusion and submit.

## Assumptions and constraints
- One classroom computer with speakers. Students use phones with a modern browser.
- The server runs on our own computer and is reached over HTTPS through Tailscale Funnel.
- Free tiers only (Gemini, Tailscale).
- No integration with Moodle, Zoom or university systems.

## Risks
| Risk | What we do about it |
|---|---|
| A phone doesn't pick up the signal | The lecturer marks the student by hand; the student can appeal; `/debug/audio` checks the signal in the room |
| A student tries to check in from outside the class | The code changes every 4 seconds and is valid for at most 8; 5 wrong codes lock the student out of that sample |
| The AI is wrong or unavailable | AI output is only a suggestion; a fallback model; if a summary fails, the transcript is kept |
| Personal data | Anonymous messages are hidden on the server; lesson feedback is private to its lecturer; the repository holds only fictional students |

## Acceptance criteria
- Students check in from their phones, and the lecturer sees the report and exports a CSV.
- The five features above work in the running app.
- All automated tests pass.
