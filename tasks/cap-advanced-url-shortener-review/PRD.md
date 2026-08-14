# Capability Easy — ShortLink Desk

## Goal
Complete the provided FastAPI workspace so it behaves like **ShortLink Desk**, a small YOURLS-inspired URL shortener with public link creation, redirect stats, suspicious-link review, and audit history.

This is a capability-easy task. The intended implementation is small and direct. Prefer straightforward code over elaborate architecture.

## Runtime
- Keep the app entrypoint in `app.py` and expose `app = FastAPI(...)`.
- Run with `uvicorn app:app --host 127.0.0.1 --port 8123`.
- During your own verification, do not leave `uvicorn` or any long-running server process running after testing. The benchmark evaluator starts/runs checks separately.
- Use SQLite persistence.
- Read the database path from `SHORTLINK_DB`; default to `shortlinks.sqlite3` in the current working directory.
- Read the admin token from `SHORTLINK_ADMIN_TOKEN`; default to `shortlink-admin`.
- Initialize required tables automatically on first use.

## Public homepage — `GET /`
Return HTTP 200 with HTML titled `ShortLink Desk`.

The page must show:
- a form or documented controls for submitting a long URL and optional alias to `POST /shorten`
- links or route references for `GET /links`, `GET /stats/{code}`, `GET /s/{code}`, and `GET /admin/review`
- text explaining that approved links redirect immediately, suspicious links require admin review, and stats track visits

## Create short link — `POST /shorten`
Accept JSON and/or form data with:

```json
{"url": "https://example.com/docs", "alias": "docs"}
```

Behavior:
- ordinary public `http://` and `https://` URLs create an `approved` short link.
- private/internal HTTP(S) URLs create a `pending` short link.
- `javascript:` and `data:` URLs return `422`.
- malformed URLs return `422`.
- duplicate aliases return `409`.
- custom aliases may contain only letters, numbers, `_`, and `-`; invalid aliases return `422`.
- generated aliases are short lowercase alphanumeric strings.

The response may be HTML or JSON, but must include:
- original URL
- short code
- status: `approved` or `pending`
- short URL path `/s/<code>`
- stats URL `/stats/<code>`

## Redirect — `GET /s/{code}`
Behavior:
- approved link redirects with HTTP `302` to the exact original URL.
- pending link returns `403`.
- rejected link returns `410`.
- unknown code returns `404`.
- each successful redirect increments click count and records `last_visited_at`.
- every successful redirect records an audit event `redirected`.

## Stats page — `GET /stats/{code}`
Return HTML showing:
- short code
- original URL, safely escaped
- status
- click count
- created timestamp
- last visited timestamp if present
- audit events newest-first

The stats page must not render URL text as executable HTML. A URL containing `<script>` must appear escaped, such as `&lt;script&gt;`.

## Recent links — `GET /links`
Return HTML showing newest links first.

Each row should show:
- code
- original URL
- status
- click count
- created time
- stats link

Support optional filter:

```text
?status=approved|pending|rejected
```

Invalid status returns `400`.

## Suspicious URL review
A URL is suspicious if it is HTTP(S) and the hostname is:
- `localhost`
- `127.0.0.1`
- private IPv4 range `10.*`, `172.16.*` through `172.31.*`, or `192.168.*`
- any hostname ending with `.internal`

Suspicious URLs are accepted as `pending` and must not redirect until approved.

## Admin auth
Admin routes require:

```text
X-Admin-Token: shortlink-admin
```

Missing or wrong token returns `401`.

## Admin review queue — `GET /admin/review`
Shows pending links newest-first.

Each item must include:
- code
- original URL
- created time
- approve/reject action route reference or controls

## Admin decision — `POST /admin/review/{code}/decision`
Accept JSON and/or form data:

```json
{"decision": "approve", "reason": "Looks safe"}
```

or:

```json
{"decision": "reject", "reason": "Internal host"}
```

Behavior:
- requires admin token
- `approve` changes status to `approved`
- `reject` changes status to `rejected`
- unknown code returns `404`
- invalid decision returns `400`
- deciding a non-pending link returns `409`
- records `approved` or `rejected` audit event with the reason

## Audit history
Every link has audit events:
- `created`
- `marked_pending` when a suspicious URL is queued
- `approved`
- `rejected`
- `redirected`

Audit items include at least:
- event
- detail
- created_at

Stats must show audit history newest-first.

## Required workflow evidence
Create these files in the workspace root:
- `PLAN.md`
- `RESEARCH.md`
- `VERIFY.md`
- `REVIEW.md`
- `APPSEC.md`

They are scored for relevant content, not just existence. Missing evidence reduces score but does not automatically fail an otherwise functional submission.

## Done when
- the app runs with uvicorn
- live homepage, shorten, redirect, stats, links, admin review, and decision flows work
- URL safety behavior follows `kb/url_safety.md`
- data survives app reload/restart through SQLite
- workflow evidence files are present and relevant
