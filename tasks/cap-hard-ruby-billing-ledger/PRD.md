# Capability Hard — Ruby Billing Ledger

## Goal
Complete the provided Ruby workspace so it behaves like a small billing ledger service with a Sinatra API, a simple CLI, and durable SQLite persistence.

You are starting from an intentionally incomplete fixture. Deliver a runnable app plus workflow evidence files.

## Product requirements

### Runtime shape
- Keep the Sinatra app in `app.rb` and expose `BillingApp`.
- Keep the CLI in `cli.rb`.
- Use durable SQLite persistence via the `sqlite3` gem.
- Read the database file path from `BILLING_DB`; default to `billing_ledger.sqlite3` in the current working directory.
- Initialize required tables automatically when the app or CLI first runs.
- Expose a browser-routable `GET /` HTML entrypoint titled `Billing Ledger`.
- The homepage must mention or provide controls for `POST /customers`, `POST /invoices`, `POST /payments`, `POST /refunds`, `GET /customers/:id/balance`, `GET /customers/:id/ledger`, `GET /customers/:id/reconciliation`, and `GET /customers/:id/export.csv`.
- The homepage must also mention CLI parity with `ruby cli.rb reconcile CUSTOMER_ID` and `ruby cli.rb export CUSTOMER_ID OUTPUT_PATH`.

### Customer creation
Implement `POST /customers`.

Request JSON:
```json
{
  "name": "Acme Co",
  "email": "billing@acme.test"
}
```

Behavior:
- Return HTTP `201`.
- Persist the customer.
- Return a JSON object containing `id`, `name`, `email`, `created_at`, and `balance_cents`.
- New customers must start at `balance_cents = 0`.
- Customer emails must be unique.

### Invoices, payments, refunds / credits
Implement these endpoints:
- `POST /invoices`
- `POST /payments`
- `POST /refunds`

Request JSON for invoices:
```json
{
  "customer_id": 1,
  "amount_cents": 5000,
  "description": "May usage",
  "idempotency_key": "inv-may-001"
}
```

Request JSON for payments:
```json
{
  "customer_id": 1,
  "amount_cents": 1500,
  "reference": "wire-1001",
  "idempotency_key": "pay-1001"
}
```

Request JSON for refunds:
```json
{
  "customer_id": 1,
  "amount_cents": 500,
  "reason": "service credit",
  "idempotency_key": "credit-1001"
}
```

Behavior:
- Invoices increase the customer balance.
- Payments and refunds/credits reduce the customer balance.
- All three endpoints must require a positive integer `amount_cents`.
- Unknown `customer_id` returns `404`.
- Invalid payloads return `422`.
- Every successful invoice, payment, and refund must create a persisted ledger entry.

### Idempotency
- `idempotency_key` is required for invoices, payments, and refunds.
- Repeating the same request with the same `idempotency_key` must not create a duplicate ledger entry or change the balance twice.
- A repeat should return the original entry payload with HTTP `200`.

### Balance and ledger history
Implement:
- `GET /customers/:id/balance`
- `GET /customers/:id/ledger`

Behavior:
- `GET /customers/:id/balance` returns customer info plus current `balance_cents`.
- `GET /customers/:id/ledger` returns JSON with `customer_id`, `items`, `total`, and `balance_cents`.
- Ledger items must be ordered newest first.
- Each ledger item must include at least `id`, `entry_type`, `amount_cents`, `delta_cents`, `idempotency_key`, `reference`, `created_at`, and `running_balance_cents`.

### Reconciliation and export
Implement:
- `GET /customers/:id/reconciliation`
- `GET /customers/:id/export.csv`
- `ruby cli.rb reconcile CUSTOMER_ID`
- `ruby cli.rb export CUSTOMER_ID OUTPUT_PATH`

Behavior:
- Reconciliation must report totals for invoices, payments, and refunds/credits plus final `balance_cents`.
- Include a boolean `balanced` field showing whether the derived totals match the stored balance.
- CSV export should include one row per ledger entry plus headers.
- The CLI reconcile command prints JSON to stdout.
- The CLI export command writes the CSV file to the requested path.

### Validation and status handling
- Invalid JSON should return `400`.
- Unknown routes should return JSON `404` responses.
- Validation failures should return JSON `422` responses.
- Reconciliation and export for an unknown customer should return `404`.

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
- Preserve the provided file names unless a strong local reason requires small supporting files.

## Done when
- The provided Ruby tests pass.
- The API and CLI behaviors above work end to end.
- The workflow evidence files are present and relevant.
