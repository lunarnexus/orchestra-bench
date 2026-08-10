# Change Request
Add `GET /v2/orders/{id}` returning `{id,total_cents,status,tracking_url}`.
`tracking_url` is nullable until shipped. Reuse `OrderService`; do not expose internal notes.
Acceptance needs unit tests for v1 unchanged, v2 success, v2 nullable tracking, and 404.
