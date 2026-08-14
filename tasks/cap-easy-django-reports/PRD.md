# Capability Normal — Django Reports

## Goal
Complete the provided Django workspace so it behaves like a small browser-routable reporting app backed by SQLite.

You are starting from an intentionally incomplete fixture. Deliver a runnable app plus workflow evidence files.

## Product requirements

### Runtime shape
- Keep the main app entrypoint in `manage.py`.
- Use Django with SQLite persistence.
- Read the database file path from `REPORTS_DB`; default to `reports.sqlite3` in the current working directory.
- Initialize required tables automatically when the app is first used.
- Implement a browser-routable `GET /` HTML entrypoint for the reports app.

### Browser homepage
Implement `GET /`.

Behavior:
- Return HTTP `200` with an HTML response.
- Include a visible `Reports` title.
- Include event ingest controls that reference `POST /events`.
- Include a report token field for `X-Report-Token`.
- Include summary filter/export controls that reference `GET /reports/summary`, including CSV export.
- Include history controls or route references for `GET /reports/history`.
- The first browser experience must be the reports page, not a bare 404 or API-only landing page.

### Event ingest
Implement `POST /events`.

Request JSON:
```json
{
  "event_type": "sale",
  "occurred_on": "2024-05-01",
  "category": "books",
  "amount": 1200
}
```

Behavior:
- Return HTTP `201`.
- Persist the event.
- Return a JSON event object containing at least:
  - `id`
  - `event_type`
  - `occurred_on`
  - `category`
  - `amount`
  - `created_at`
- Supported event types: `sale`, `refund`.
- Invalid payloads must return HTTP `400` with a useful error body.

### Report permissions
All `/reports/*` endpoints must require header:
- `X-Report-Token: reports-admin`

Behavior:
- Missing or incorrect token returns HTTP `401`.
- Do not require auth on `POST /events`.

### Summary reports
Implement `GET /reports/summary`.

Query params:
- optional `start_date`
- optional `end_date`
- optional `category`
- `page` (default `1`)
- `page_size` (default `20`)
- `format` (`json` default, `csv` optional)

Behavior:
- Group events by `occurred_on` date and `category`.
- Return aggregates with:
  - `date`
  - `category`
  - `sales_total`
  - `refund_total`
  - `net_total`
  - `event_count`
- Support filtering by date range and category.
- Support pagination on grouped results.
- Return grouped results newest date first.
- Invalid dates, pagination, or export formats must return HTTP `400`.
- JSON responses must use `{ "items", "total", "page", "page_size" }`.
- CSV responses must include a header row and the same grouped fields.

### Report history
Implement `GET /reports/history`.

Behavior:
- Return HTTP `200` with paginated JSON using the same `items`, `total`, `page`, and `page_size` shape.
- Record successful summary runs in persistent history.
- History entries should make it clear which export format ran, how many grouped rows were returned, and when the report was generated.
- Return newest history entries first.

## Required workflow evidence
Create these files in the workspace root:
- `PLAN.md`
- `RESEARCH.md`
- `VERIFY.md`
- `REVIEW.md`
- `APPSEC.md`

They are scored for relevant content, not just existence. Missing evidence reduces the score but does not automatically fail an otherwise functional submission.

## Constraints
- Stay within the provided workspace.
- Do not depend on network access.
- Keep the implementation straightforward and testable.
- Preserve the provided file names unless a strong local reason requires extra modules.

## Done when
- The provided tests pass.
- The API behaviors above work end-to-end.
- Report data persists in SQLite across process reloads.
- The workflow evidence files are present and relevant.

## Operational cleanup requirement

Do not leave `uvicorn`, Django `runserver`, Node/TypeScript servers, Ruby/Sinatra servers, workers, or any other long-running/background process running at the end of the task. If you start a server or worker for testing, use a timeout or background PID and stop it before finalizing.
