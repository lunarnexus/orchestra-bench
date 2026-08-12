# RESEARCH

- source: `kb/api_contract.md` is the api contract for `POST /events`, `GET /reports/summary`, `GET /reports/history`, the `X-Report-Token` requirement, and the JSON/CSV response shapes.
- decision: use Django plus `sqlite3` through `django.db.models` and the built-in ORM so filters, grouped aggregation, and persistence stay file-backed without extra services.
- source: `kb/persistence_notes.md` says the evaluator restarts the process, so history and event data must live in SQLite rather than module globals.
- tradeoff: avoid a full migration tree and instead use `schema_editor` deterministically on first use; this keeps the fixture small while still exercising a real Django request stack and Django test client.
- decision: keep all behavior in `manage.py` so the workspace stays compact and the agent can finish the task with no network access or extra modules.
