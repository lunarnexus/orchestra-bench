# Run Prompt
Read `PRD.md`, inspect the fixture, and finish the browser-routable Django reporting app.
Dispatch and proceed until finished.

Requirements:
- make the provided tests pass
- implement a browser-routable `GET /` HTML reports entrypoint
- implement SQLite-backed sales/refund ingest, grouped summary reports, JSON/CSV export, pagination, permissions, validation, and report-run history
- automatically create required tables on first endpoint use for a fresh `REPORTS_DB`; do not rely only on `reset_database()` or test setup
- treat `start_date > end_date` as an invalid summary request: return `400` and do not create a report-history row
- create `PLAN.md`, `RESEARCH.md`, `VERIFY.md`, `REVIEW.md`, and `APPSEC.md` with substantive, task-specific evidence; do not use keyword lists or filler
- leave the workspace runnable without evaluator-only files

## Operational cleanup requirement

Do not leave `uvicorn`, Django `runserver`, Node/TypeScript servers, Ruby/Sinatra servers, workers, or any other long-running/background process running at the end of the task. If you start a server or worker for testing, use a timeout or background PID and stop it before finalizing.
