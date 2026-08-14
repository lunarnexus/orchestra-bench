# PLAN

Plan the implementation steps for `app.js`, keep the files small, and use the provided tests for each API behavior.

1. Implement `GET /` as the browser-routable Inventory homepage in `app.js`, with product create/list controls plus stock, low-stock, and ledger route references.
2. Implement `POST /products`, `GET /products`, and `GET /products/{product_id}` with file-backed persistence in `app.js`.
3. Implement `PATCH /products/{product_id}`, `DELETE /products/{product_id}`, and `POST /products/{product_id}/adjustments` with validation and status codes.
4. Implement `GET /reports/low-stock` and `GET /products/{product_id}/ledger` with newest-first results and pagination, then run `node --test tests/api.test.js` and record verification results for app.js and tests/api.test.js.
