# Ledger rules

- Treat `balance_cents` as the amount the customer still owes.
- Invoice entries add a positive `delta_cents` and increase the balance.
- Payment and refund/credit entries add a negative `delta_cents` and reduce the balance.
- `running_balance_cents` on a ledger item should reflect the balance immediately after that entry was applied.
- Reconciliation can be computed from ledger totals; it should not require a separate summary table.
- A durable solution should survive process restarts because the evaluator may reload the app and run the CLI in a fresh process.
- `GET /` should be a browser homepage titled `Billing Ledger` that references or exposes `POST /customers`, `POST /invoices`, `POST /payments`, `POST /refunds`, `GET /customers/:id/balance`, `GET /customers/:id/ledger`, `GET /customers/:id/reconciliation`, and `GET /customers/:id/export.csv`.
- The homepage should mention CLI parity with `ruby cli.rb reconcile CUSTOMER_ID` and `ruby cli.rb export CUSTOMER_ID OUTPUT_PATH` so the browser entrypoint and CLI tell the same story.
