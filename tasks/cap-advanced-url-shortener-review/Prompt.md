# Run Prompt
Work in the current directory. Edit the task files here.

Read `PRD.md` and `kb/url_safety.md`, inspect the fixture, and finish ShortLink Desk.
Create a plan and write to PLAN.md, then Dispatch and execute the plan.

Requirements:
- make the FastAPI app runnable with `python3 -m uvicorn app:app --host 127.0.0.1 --port 8123` from this workspace
- do not rely on undeclared Python packages; if the app needs a runtime dependency, list it in `requirements.txt`
- do not leave `uvicorn` or any long-running server process running at the end; if you start it to test, use a timeout/background process and stop it before finalizing
- implement the URL shortener, stats, admin review queue, audit history, URL safety behavior, and SQLite persistence described in the PRD
- keep evaluator-only files out of the app
