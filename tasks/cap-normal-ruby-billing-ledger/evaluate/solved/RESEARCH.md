# RESEARCH
- source: `PRD.md`, `kb/ledger_rules.md`, and `kb/idempotency_notes.md` define the API contract, ledger math, and replay expectations for invoices, payments, refunds, and export.
- decision: use `sqlite3` directly from Sinatra and avoid extra ORM layers so the app stays small, durable, and easy to reset in `test/test_billing_app.rb`.
- tradeoff: a direct SQLite schema in `app.rb` avoids extra dependencies, but it means route handlers must own validation, idempotency checks, and reconciliation logic explicitly.
- source: the fixture tests and API contract require `ruby -Itest test/test_billing_app.rb`, `POST /invoices`, `GET /customers/:id/ledger`, and `ruby cli.rb reconcile CUSTOMER_ID`.
- decision: persist `idempotency_key` on `ledger_entries` with a unique constraint so duplicate requests stay correct across process restarts.
