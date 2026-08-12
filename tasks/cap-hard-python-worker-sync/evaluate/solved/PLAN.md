Plan steps for the Python worker sync task:
1. Inspect app.py, worker.py, sync_core.py, and tests/test_sync_app.py so GET /, POST /documents, POST /sync-jobs, GET /sync-jobs/{job_id}, and GET /admin/sync-jobs share one SQLite-backed Doc Sync workflow.
2. Implement create_sync_job in sync_core.py and FastAPI routes in app.py with pagination, filters, validation, status codes, and SQLite-backed audit rows for queued, started, retry, conflict, reclaimed, and success events.
3. Build worker.py processing around claim_next_job, run_worker, and process_next_job for queued jobs, transient retry handling, stale-job reclaim, and conflict detection when a document version changed before sync.
4. Ensure POST /sync-jobs records idempotency_key reuse correctly in sync_core.py so app.py and worker.py share the same deduplicated SQLite job state.
5. Verify with pytest -q tests/test_sync_app.py and confirm the changed files app.py, worker.py, sync_core.py, and tests/test_sync_app.py cover retries, conflicts, audit history, and persistence.
