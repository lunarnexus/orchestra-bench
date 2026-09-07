command: pytest -q tests/test_sync_app.py
result: passed; tests exercised app.py, worker.py, sync_core.py, and tests/test_sync_app.py for the GET / Doc Sync homepage, SQLite persistence, retry behavior, stale reclaim, conflict handling, pagination, and status codes.
command: python worker.py --drain
result: passed during the test flow because the worker drained queued jobs, retried the local fake upstream, and left pollable succeeded or conflict states instead of hanging jobs.
