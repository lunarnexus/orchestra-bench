# PLAN

1. Update `manage.py` to configure Django with SQLite from `REPORTS_DB`, define the `Event` and `ReportRun` models, call `ensure_schema`, and serve `GET /` as the browser-routable Reports homepage alongside `POST /events`, `GET /reports/summary`, and `GET /reports/history`.
2. Keep coverage focused in `tests/test_reports.py` so `pytest -q tests/test_reports.py` verifies the homepage, ingest, grouped aggregates, CSV export, pagination, permissions, validation, and history behavior.
3. Use Django ORM aggregation for date/category summary rows, then paginate the grouped results and persist each summary run through the `ReportRun` model.
