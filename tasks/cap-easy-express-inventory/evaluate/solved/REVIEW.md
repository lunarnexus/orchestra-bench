# REVIEW

Finding: `app.js` now serves a stable `GET /` Inventory homepage plus consistent product CRUD, adjustment flows, ledger history, and status codes for browser and API clients.
Risk: Ledger and low-stock paths must stay aligned with product writes so reports do not drift from the stored inventory state.

Review summary:
- I checked that `GET /`, `GET /products/{product_id}`, `POST /products/{product_id}/adjustments`, and `GET /products/{product_id}/ledger` agree on the documented routes and response schemas.
- Follow-up: keep delete behavior and ledger ordering stable for clients.
