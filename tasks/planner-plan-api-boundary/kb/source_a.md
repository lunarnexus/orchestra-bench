# Current API
- Existing public route: `GET /v1/orders/{id}` returns `{id,total_cents,status}`.
- Internal module boundary: handlers call `OrderService.get_public_order(order_id)`.
- Compatibility rule: `/v1` response shape must not change.
- Errors: missing orders return HTTP 404 with `{error:"not_found"}`.
