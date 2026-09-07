# VERIFY
- command: `ruby -Itest test/test_billing_app.rb`
- result: passed after finishing `app.rb`, `cli.rb`, and `test/test_billing_app.rb`; the suite now covers the `GET /` Billing Ledger homepage, sqlite persistence, invoices, payments, refunds, ledger export, reconciliation, and idempotency.
- command: `ruby cli.rb reconcile 1`
- result: prints JSON reconciliation with balance totals, and the homepage documents the same CLI parity commands plus `GET /customers/:id/export.csv`.
- command: `ruby cli.rb export 1 tmp/export.csv`
- result: writes CSV output for the same customer ledger.
