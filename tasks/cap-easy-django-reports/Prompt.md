# Run Prompt
Read `PRD.md`, inspect the fixture, and finish the browser-routable Django reporting app.
Dispatch and proceed until finished.

Requirements:
- make the provided tests pass
- implement a browser-routable `GET /` HTML reports entrypoint
- implement SQLite-backed sales/refund ingest, grouped summary reports, JSON/CSV export, pagination, permissions, validation, and report-run history
- create `PLAN.md`, `RESEARCH.md`, `VERIFY.md`, `REVIEW.md`, and `APPSEC.md` with relevant content
- leave the workspace runnable without evaluator-only files

## Operational cleanup requirement

Do not leave `uvicorn`, Django `runserver`, Node/TypeScript servers, Ruby/Sinatra servers, workers, or any other long-running/background process running at the end of the task. If you start a server or worker for testing, use a timeout or background PID and stop it before finalizing.
