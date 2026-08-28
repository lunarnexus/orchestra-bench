threat: security risk from untrusted input in document fields, slug values, and idempotency keys could break SQL or confuse worker state if app.py built queries dynamically.
mitigation: sync_core.py uses sqlite parameter binding everywhere, validates slug and payload shape at the FastAPI boundary, keeps X-Admin-Token auth protection on /admin/* endpoints, and exposes GET / as a route reference page instead of embedding secrets.
threat: the worker talks to an external sync target and could duplicate side effects after transient failures or stale claims.
mitigation: worker.py retries only the same SQLite job row, records attempts/history, marks changed versions as conflict, validates state transitions, and releases the database transaction before the upstream network call.
