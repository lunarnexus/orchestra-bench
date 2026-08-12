# Run Prompt
Read `PRD.md`, inspect the fixture and KB files, and finish the Python sync workspace.

Requirements:
- make the provided Python tests pass
- implement a real FastAPI API plus `worker.py` background sync worker with durable SQLite jobs
- add a usable browser-routable `GET /` Doc Sync homepage that references `POST /documents`, `POST /sync-jobs`, `GET /sync-jobs/{job_id}`, `GET /admin/sync-jobs`, and `GET /admin/sync-jobs/{job_id}/history`
- support document create/update, job submission, polling, retries, stale-job recovery, conflict handling, audit history, pagination/filtering, and status codes
- mention worker, retry, and conflict behavior from the homepage so the browser entrypoint reflects the real workflow
- create `PLAN.md`, `RESEARCH.md`, `VERIFY.md`, `REVIEW.md`, and `APPSEC.md` with relevant content
- keep the workspace runnable without evaluator-only files
