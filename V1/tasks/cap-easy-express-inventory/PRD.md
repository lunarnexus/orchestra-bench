# Capability Normal — Express-Style Inventory

## Goal
Complete the provided Node workspace so it behaves like a small browser-routable inventory app with durable file-backed persistence.

You are starting from an intentionally incomplete fixture. Deliver a runnable app plus workflow evidence files.

## Product requirements

### Runtime shape
- Keep the API in `app.js` and export `createServer()`.
- Use file-backed persistence with the standard library or another lightweight local approach.
- Read the data file path from `INVENTORY_DB`; default to `inventory-data.json` in the current working directory.
- Initialize required storage automatically when the app is first used.
- Keep the implementation local-only; do not depend on network access.

### Browser entrypoint
Implement `GET /`.

Behavior:
- Return `200` HTML with an `Inventory` title.
- Include usable browser-facing controls or forms for product creation and product listing.
- Include stock adjustment controls that reference `POST /products/{product_id}/adjustments`.
- Include low-stock report and ledger controls or route references for `GET /reports/low-stock` and `GET /products/{product_id}/ledger`.
- The first browser experience must not be a 404 or API-only response.

### Product CRUD
Implement these endpoints:
- `POST /products`
- `GET /products`
- `GET /products/{product_id}`
- `PATCH /products/{product_id}`
- `DELETE /products/{product_id}`

Create request JSON:
```json
{
  "sku": "SKU-100",
  "name": "Stapler",
  "priceCents": 1299,
  "stock": 8,
  "lowStockThreshold": 3
}
```

Behavior:
- `POST /products` returns `201` and persists the product.
- Return product JSON containing:
  - `id`
  - `sku`
  - `name`
  - `priceCents`
  - `stock`
  - `lowStockThreshold`
  - `createdAt`
  - `updatedAt`
- `GET /products` returns `200` with `items` and `total`.
- `GET /products/{product_id}` returns `200` for an existing product and `404` for an unknown product.
- `PATCH /products/{product_id}` returns `200` with the updated product.
- `DELETE /products/{product_id}` returns `204`.
- SKUs must be unique; duplicate SKU creation returns `409`.

### Stock adjustments
Implement `POST /products/{product_id}/adjustments`.

Request JSON:
```json
{
  "delta": -5,
  "reason": "Cycle count correction"
}
```

Behavior:
- Return `200` with the updated product and the new ledger entry.
- Unknown product returns `404`.
- `delta` must be an integer.
- Do not allow stock to become negative; reject that adjustment with `409`.

### Low-stock reporting
Implement `GET /reports/low-stock`.

Behavior:
- Return `200` with `items` and `total`.
- Include every product whose `stock` is less than or equal to `lowStockThreshold`.
- Keep ordering deterministic.

### Ledger history
Implement `GET /products/{product_id}/ledger`.

Behavior:
- Return `200` with paginated ledger entries using `items`, `total`, `page`, and `page_size`.
- Unknown product returns `404`.
- Record at least these actions:
  - product creation
  - product update
  - stock adjustment
- Return newest entries first.
- Each entry should make it clear what happened and include the actor (`api` is fine for this task).

### Validation and status codes
- Invalid create/update/adjustment bodies should return `400`.
- Unknown product ids should return `404`.
- Duplicate SKU creation should return `409`.
- Insufficient stock on an adjustment should return `409`.

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
- Preserve the provided file names unless a strong local reason requires extra modules.

## Done when
- The provided tests pass.
- The API behaviors above work end-to-end.
- The workflow evidence files are present and relevant.

## Operational cleanup requirement

Do not leave `uvicorn`, Django `runserver`, Node/TypeScript servers, Ruby/Sinatra servers, workers, or any other long-running/background process running at the end of the task. If you start a server or worker for testing, use a timeout or background PID and stop it before finalizing.
