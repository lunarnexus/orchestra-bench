# APPSEC

- threat: the browser-routable `GET /` homepage must not weaken the reporting trust boundary, so it only references `POST /events`, `GET /reports/summary`, and `GET /reports/history` without bypassing `X-Report-Token` on protected routes.
- threat: unauthenticated access to `GET /reports/summary` or `GET /reports/history` could expose reporting data, so `_require_report_token` requires `X-Report-Token: reports-admin` and fails closed with `401`.
- mitigation: validate event payloads, pagination, and date filters at the boundary before querying SQLite, and use Django ORM / parameterized ORM filters instead of string-built SQL.
- threat: CSV export can become an unreviewed alternate sink for report data, so the same auth, filtering, pagination, and persistence rules apply to csv and json output.
- mitigation: keep secrets out of the workspace and store only report metadata plus event aggregates in SQLite-backed `Event` and `ReportRun` tables.
