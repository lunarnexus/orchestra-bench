# PLAN
- Step 1: add a browser-routable `GET /` homepage in `app.rb` titled `Billing Ledger`, then finish the ledger routes for `POST /customers`, `POST /invoices`, `POST /payments`, `POST /refunds`, `GET /customers/:id/ledger`, and `GET /customers/:id/reconciliation` with SQLite persistence and idempotency keys.
- Step 2: keep `cli.rb` export and reconcile commands aligned with the homepage route references, then run `ruby -Itest test/test_billing_app.rb` and review any failures before final verification.
- Files in scope: `app.rb`, `cli.rb`, and `test/test_billing_app.rb`; verify homepage route coverage, ledger export, balance math, and CSV output.
