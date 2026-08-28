# REVIEW

- finding: `manage.py` now serves a stable `GET /` Reports homepage that references event ingest, summary export, and history workflows instead of landing on a bare 404.
- finding: `/reports/*` stays behind `_require_report_token` and `X-Report-Token`, while `POST /events` remains public as required by the API contract.
- risk: status codes can drift if pagination, format parsing, or date validation are handled implicitly, so the implementation returns explicit `400` responses for those boundaries.
- finding: grouped summary rows come from the `Event` model and ORM aggregation instead of ad hoc Python-only state, which keeps pagination and response schemas aligned with SQLite persistence.
- risk: report-run history is product behavior, not debug output, so missing persistent `ReportRun` rows would break both auditability and reload behavior.
