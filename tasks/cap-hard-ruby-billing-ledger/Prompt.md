# Run Prompt
Read `PRD.md`, inspect the fixture and KB files, and finish the Ruby billing ledger.

Requirements:
- make the provided Ruby tests pass
- implement a real Sinatra API plus CLI backed by durable SQLite persistence
- add a browser-routable `GET /` HTML entrypoint titled `Billing Ledger` that references or controls `POST /customers`, `POST /invoices`, `POST /payments`, `POST /refunds`, `GET /customers/:id/balance`, `GET /customers/:id/ledger`, `GET /customers/:id/reconciliation`, and `GET /customers/:id/export.csv`
- mention CLI parity on the homepage with `ruby cli.rb reconcile CUSTOMER_ID` and `ruby cli.rb export CUSTOMER_ID OUTPUT_PATH`
- support invoices, payments, refunds/credits, idempotency keys, customer balances, ledger history, reconciliation, and CSV export
- create `PLAN.md`, `RESEARCH.md`, `VERIFY.md`, `REVIEW.md`, and `APPSEC.md` with relevant content
- keep the workspace runnable without evaluator-only files
