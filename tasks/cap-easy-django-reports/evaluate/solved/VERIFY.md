# VERIFY

- command: `pytest -q tests/test_reports.py`
- result: passed for `manage.py` and `tests/test_reports.py`, covering the browser-routable `GET /` homepage, sales/refund ingest, grouped summary pagination, CSV export, and report-run history.
- command: evaluator functional checks against `manage.py`
- result: passed for `functional_browser_homepage`, `functional_persistence_file_backed`, SQLite persistence across reloads, `GET /reports/summary`, `GET /reports/history`, validation, permissions, csv/json export, and pagination.
