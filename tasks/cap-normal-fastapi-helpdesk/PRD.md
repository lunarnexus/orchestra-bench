# Capability Normal — FastAPI Helpdesk

## Goal
Complete the provided FastAPI workspace so it behaves like a small browser-routable helpdesk app backed by SQLite.

You are starting from an intentionally incomplete fixture. Deliver a runnable app plus workflow evidence files.

## Product requirements

### Runtime shape
- Keep the API in `app.py` and expose `app = FastAPI(...)`.
- Use SQLite persistence via the standard library or another lightweight Python approach.
- Read the database file path from `HELPDESK_DB`; default to `helpdesk.sqlite3` in the current working directory.
- Initialize required tables automatically when the app is first used.
- Implement a browser-routable `GET /` HTML entrypoint for the helpdesk.

### Browser homepage
Implement `GET /`.

Behavior:
- Return HTTP `200` with an HTML response.
- Include a visible `Helpdesk` title.
- Include a public ticket submission form that posts to `/tickets`.
- Include admin controls or links that reference:
  - `GET /admin/tickets`
  - `POST /admin/tickets/{ticket_id}/triage`
  - `GET /admin/tickets/{ticket_id}/audit`
- The first browser experience must be the helpdesk page, not a bare 404 or docs-only landing page.

### Public ticket intake
Implement `POST /tickets`.

Request JSON:
```json
{
  "email": "user@example.com",
  "subject": "Printer broken",
  "body": "3rd floor printer is jammed"
}
```

Behavior:
- Return HTTP `201`.
- Persist the ticket.
- Return a JSON ticket object containing:
  - `id`
  - `email`
  - `subject`
  - `body`
  - `status`
  - `priority`
  - `admin_note`
  - `created_at`
  - `updated_at`
- New tickets must start with `status="open"` and `priority="normal"`.
- Invalid request bodies should fail with FastAPI/Pydantic validation (`422`).

### Admin authentication
All `/admin/*` endpoints must require header:
- `X-Admin-Token: helpdesk-admin`

Behavior:
- Missing or incorrect token returns HTTP `401`.
- Do not require auth on `POST /tickets`.

### Admin triage
Implement `POST /admin/tickets/{ticket_id}/triage`.

Request JSON:
```json
{
  "status": "in_progress",
  "priority": "high",
  "admin_note": "Assigned to ops"
}
```

Behavior:
- Update the existing ticket.
- Return HTTP `200` with the updated ticket.
- Unknown ticket id returns `404`.
- Supported triage statuses: `open`, `in_progress`, `closed`.
- Supported priorities: `low`, `normal`, `high`, `urgent`.

### Admin list with pagination
Implement `GET /admin/tickets`.

Query params:
- `page` (default `1`)
- `page_size` (default `20`)
- optional `status`

Behavior:
- Return HTTP `200`.
- Return a JSON object with `items`, `total`, `page`, and `page_size`.
- Support status filtering.
- Order tickets newest first.

### Audit log
Implement `GET /admin/tickets/{ticket_id}/audit`.

Behavior:
- Return HTTP `200` with paginated audit entries using the same `items`, `total`, `page`, and `page_size` shape.
- Unknown ticket id returns `404`.
- Record at least these actions:
  - ticket creation
  - ticket triage/update
- Audit entries should make it clear who performed the action (`public` vs `admin`).
- Return newest audit entries first.

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
- Preserve the provided API file names unless a strong local reason requires extra modules.

## Done when
- The provided tests pass.
- The browser homepage and API behaviors above work end-to-end.
- The workflow evidence files are present and relevant.
