# REVIEW
- finding: `GET /` now gives the app a browser-routable Billing Ledger homepage that points at `/customers`, `/invoices`, `/payments`, `/refunds`, balance, ledger, reconciliation, export, and CLI parity without changing the API contract.
- finding: `/customers`, `/invoices`, `/payments`, `/refunds`, and `/customers/:id/ledger` still share the same SQLite ledger schema, so the response schemas and running balances stay consistent.
- finding: status codes stay explicit: invalid JSON returns `400`, validation issues return `422`, unknown customers return `404`, and idempotent replays return `200` with the original entry.
- risk: if a future change removes the unique `idempotency_key` constraint, reorders ledger items, or lets the homepage drift away from the documented routes, duplicate billing or misleading operator guidance could slip in; keep the tests and CSV export assertions intact.
