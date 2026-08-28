# Worker and upstream notes

- Use SQLite as the durable source of truth for documents, jobs, and history.
- The `GET /` Doc Sync homepage should mention the worker, retry handling, and conflict outcomes so the browser entrypoint matches the asynchronous workflow.
- The worker should claim work, release the write transaction, then call the upstream service.
- The fake upstream used by tests exposes `POST /v1/sync` and may return HTTP `503` on the first attempt for a document/version pair.
- Safe retry means reusing the same job row while increasing `attempts`; do not create duplicate jobs for the same version.
- If a document version changed after the job was queued, mark the job as a conflict instead of syncing stale content.
- Stale running jobs should be reclaimable on a later worker run.
