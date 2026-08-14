# Run Prompt

Read `PRD.md` and `kb/url_safety.md`, inspect the fixture, and finish ShortLink Desk.
Dispatch and proceed until finished.

Requirements:
- make the FastAPI app runnable with `uvicorn app:app --host 127.0.0.1 --port 8123`
- do not leave `uvicorn` or any long-running server process running at the end; if you start it to test, use a timeout/background process and stop it before finalizing
- implement the URL shortener, stats, admin review queue, audit history, URL safety behavior, and SQLite persistence described in the PRD
- keep evaluator-only files out of the app
- create relevant `PLAN.md`, `RESEARCH.md`, `VERIFY.md`, `REVIEW.md`, and `APPSEC.md`
