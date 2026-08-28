# Run Prompt
Read `PRD.md`, inspect the fixture and KB files, and finish the Python sync workspace.
Dispatch and proceed until finished.

Requirements:
- make the provided Python tests pass
- implement a real FastAPI API plus `worker.py` background sync worker with durable SQLite jobs
- add a usable browser-routable `GET /` Doc Sync homepage that references `POST /documents`, `POST /sync-jobs`, `GET /sync-jobs/{job_id}`, `GET /admin/sync-jobs`, and `GET /admin/sync-jobs/{job_id}/history`
- support document create/update, job submission, polling, retries, stale-job recovery, conflict handling, audit history, pagination/filtering, and status codes
- mention worker, retry, and conflict behavior from the homepage so the browser entrypoint reflects the real workflow
- create `PLAN.md`, `RESEARCH.md`, `VERIFY.md`, `REVIEW.md`, and `APPSEC.md` with substantive, task-specific evidence; do not use keyword lists or filler
- keep the workspace runnable without evaluator-only files

## Operational cleanup requirement

Do not leave `uvicorn`, Django `runserver`, Node/TypeScript servers, Ruby/Sinatra servers, workers, or any other long-running/background process running at the end of the task. If you start a server or worker for testing, use a timeout or background PID and stop it before finalizing.
