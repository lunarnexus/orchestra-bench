# APPSEC
- threat: untrusted JSON input hits billing routes directly, so malformed bodies, missing `idempotency_key`, and bad `amount_cents` values could corrupt ledger state or trigger duplicate charges.
- mitigation: `app.rb` parses JSON once, validates positive integer amounts, returns `400` or `422` on bad input, and uses SQLite parameter binding instead of string interpolation.
- threat: replayed invoice or payment requests could create duplicate charges if the key is only tracked in memory.
- mitigation: persist `idempotency_key` in SQLite with a unique constraint so the replay protection survives reloads, CLI runs, and fresh processes.
- threat: the browser homepage could become a misleading or unsafe sink if it interpolated untrusted data into HTML.
- mitigation: keep `GET /` as static operator guidance for `POST /customers`, `POST /invoices`, `POST /payments`, `POST /refunds`, `GET /customers/:id/balance`, `GET /customers/:id/ledger`, `GET /customers/:id/reconciliation`, `GET /customers/:id/export.csv`, and CLI parity commands, with no user-controlled HTML rendering.
