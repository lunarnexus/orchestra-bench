# API contract notes

- The browser homepage must serve `GET /` as a usable HTML Doc Sync entrypoint.
- The homepage should reference `POST /documents`, `POST /sync-jobs`, `GET /sync-jobs/{job_id}`, `GET /admin/sync-jobs`, and `GET /admin/sync-jobs/{job_id}/history`.
- Admin header: `X-Admin-Token: sync-admin`
- Pagination responses use `items`, `total`, `page`, `page_size`
- Job status values should at least include `queued`, `running`, `succeeded`, `failed`, `conflict`
- `POST /documents` creates or updates local docs by slug
- `POST /sync-jobs` targets the current document version and must honor idempotency
- `GET /sync-jobs/{job_id}` is the polling endpoint
- `GET /admin/sync-jobs` supports `status`, `slug`, `page`, `page_size`
