# Idempotency notes

- The grader repeats at least one invoice request with the same `idempotency_key`.
- Returning the original entry with HTTP `200` is acceptable for a replay.
- The repeated request must not create another row or change the customer balance twice.
- Persist the idempotency key alongside ledger entries so the guarantee survives process restarts.
- Plain in-memory hashes are not sufficient because the app will be reloaded in another process.
