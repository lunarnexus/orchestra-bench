# Capability Hard — Python Worker Sync

## Goal
Complete the provided Python workspace so it behaves like a Doc Sync document app plus a separate background worker backed by durable SQLite jobs.

You are starting from an intentionally incomplete fixture. Deliver a runnable app plus workflow evidence files.

## Product requirements

### Runtime shape
- Keep the FastAPI app in `app.py` and expose `app = FastAPI(...)`.
- Keep the worker entrypoint in `worker.py`.
- Durable SQLite persistence is required; in-memory-only state is not acceptable.
- Read the database path from `SYNC_DB`; default to `sync-jobs.sqlite3` in the current working directory.
- Read the upstream base URL from `SYNC_UPSTREAM_URL`; default to `http://127.0.0.1:3999`.
- Read the admin token from `SYNC_ADMIN_TOKEN`; default to `sync-admin`.
- Initialize required tables automatically on first use.

### Browser entrypoint
Implement a usable HTML `GET /` entrypoint for the Doc Sync app.

Behavior:
- Return HTTP `200` with HTML, not a bare `404` or docs-only page.
- The page title and primary heading should identify the app as `Doc Sync`.
- Include browser-facing controls or route references for `POST /documents`, `POST /sync-jobs`, `GET /sync-jobs/{job_id}`, `GET /admin/sync-jobs`, and `GET /admin/sync-jobs/{job_id}/history`.
- Mention that the separate worker handles queued jobs, retry behavior, and conflict outcomes so a human can understand the full workflow from the homepage.

### Local documents
Implement `POST /documents` and `GET /documents/{slug}`.

Request JSON:
```json
{
  "slug": "launch-plan",
  "title": "Launch plan",
  "content": "Initial launch draft"
}
```

Behavior:
- Creating a new slug returns HTTP `201`.
- Updating an existing slug returns HTTP `200` and increments its version.
- Persist each document with at least `slug`, `title`, `content`, `version`, `sync_status`, `created_at`, and `updated_at`.
- Unknown slugs return `404`.
- Validation failures return `422`.

### Sync jobs and polling
Implement `POST /sync-jobs` and `GET /sync-jobs/{job_id}`.

Request JSON:
```json
{
  "slug": "launch-plan",
  "idempotency_key": "sync-launch-v1"
}
```

Behavior:
- Queue a sync job for the document's current version.
- New jobs return HTTP `201` with a JSON job payload.
- Repeating the same request with the same `idempotency_key` must return the original job payload with HTTP `200`.
- If an equivalent job for the same document version is already queued, running, or already succeeded, dedupe to the existing job instead of creating another one.
- Unknown document slugs return `404`.

### Background worker and upstream retries
The separate worker process in `worker.py` must process queued jobs.

Behavior:
- The worker should claim queued jobs from SQLite, mark them running, and attempt an HTTP POST to the configured upstream service.
- Upstream request payload should include at least `slug`, `title`, `content`, and `version`.
- Transient upstream failures such as HTTP `503` must be retried safely without creating duplicate jobs.
- Keep an `attempts` counter and an error field or equivalent state.
- Successful sync marks the job succeeded and updates document sync state.

### Conflicts and stale jobs
- If a document changes after a job was queued but before it syncs, that older job must finish as a conflict rather than syncing stale content.
- Handle stale running jobs: if a job is left in `running` long enough, a later worker run must reclaim and finish it.
- Do not hold a SQLite write lock across the upstream HTTP request.

### Audit history and admin listing
Implement:
- `GET /admin/sync-jobs`
- `GET /admin/sync-jobs/{job_id}/history`

Behavior:
- Admin routes require header `X-Admin-Token` matching the configured admin token.
- `GET /admin/sync-jobs` supports `status`, `slug`, `page`, and `page_size`.
- Pagination responses use `items`, `total`, `page`, and `page_size`.
- History returns newest-first audit items with at least `id`, `job_id`, `event`, `detail`, and `created_at`.
- Record at least queued, started, retry, success, conflict, and stale-reclaim events when they occur.

### Validation and status handling
- Unauthorized admin access returns `401`.
- Invalid pagination or unknown status filters return `400`.
- Unknown jobs and documents return `404`.
- Validation failures return `422`.
- Unknown routes should return JSON `404` responses.

## Required workflow evidence
Create these files in the workspace root:
- `PLAN.md`
- `RESEARCH.md`
- `VERIFY.md`
- `REVIEW.md`
- `APPSEC.md`

They are scored for relevant content, not just existence. Missing evidence reduces the score but does not automatically fail an otherwise functional submission.

## Constraints
- Stay within the provided workspace.
- Do not depend on network access beyond the local fake upstream used by tests.
- Keep the implementation straightforward and testable.
- Preserve the provided file names unless a strong local reason requires small supporting files.

## Done when
- The provided tests pass.
- `GET /` provides a browser-routable Doc Sync homepage that references the core document, queue, polling, and admin history workflow.
- Sync jobs survive process restart because state is backed by SQLite.
- Transient upstream failures are retried safely.
- Stale jobs and conflicting document versions are handled correctly.
- The workflow evidence files are present and relevant.

## Operational cleanup requirement

Do not leave `uvicorn`, Django `runserver`, Node/TypeScript servers, Ruby/Sinatra servers, workers, or any other long-running/background process running at the end of the task. If you start a server or worker for testing, use a timeout or background PID and stop it before finalizing.
