# Run Prompt
Read `PRD.md`, inspect the fixture and KB files, and finish the TypeScript approval queue.
Dispatch and proceed until finished.

Requirements:
- make the provided Node tests pass
- implement a real TypeScript/Node moderation queue with durable persistence
- add a browser-routable `GET /` HTML homepage titled `Approval Queue`
- make the homepage reference or exercise `POST /submissions`, `GET /public/submissions`, `GET /admin/submissions`, `POST /admin/submissions/:id/decision`, and `GET /admin/submissions/:id/history`
- mention `X-Admin-Token` and public sanitization / security notes on the homepage or KB-aligned UX copy
- support public submission, admin approval/rejection, public visibility rules, audit history, pagination/filtering, and attachment handling
- block path traversal and keep public rendering XSS-safe
- create `PLAN.md`, `RESEARCH.md`, `VERIFY.md`, `REVIEW.md`, and `APPSEC.md` with substantive, task-specific evidence; do not use keyword lists or filler
- keep the workspace runnable without evaluator-only files

## Operational cleanup requirement

Do not leave `uvicorn`, Django `runserver`, Node/TypeScript servers, Ruby/Sinatra servers, workers, or any other long-running/background process running at the end of the task. If you start a server or worker for testing, use a timeout or background PID and stop it before finalizing.
