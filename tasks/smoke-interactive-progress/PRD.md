# Smoke E2E — Interactive Progression

## Goal
Implement lesson progress behavior for a small learning module.

## Product requirements
Complete `lesson.py` so users can answer steps, receive immediate correctness feedback, and advance progress.

## Acceptance criteria
- `start_session(user_id, lesson_id, answers)` creates a session at step 0 with zero correct answers.
- `submit_answer(session, answer)` returns feedback containing `correct`, `current_step`, `completed`, and `score`.
- Correct answers increment score; incorrect answers do not.
- Each submission advances exactly one step.
- Submitting after completion raises `ValueError`.
