# Smoke E2E — Billing Webhook Lifecycle

## Goal
Implement a tiny usage billing flow from event ingestion to invoice webhook.

## Product requirements
Complete `billing.py` so usage events are deduplicated, invoiced, and emitted as signed webhook payloads.

## Acceptance criteria
- Read `webhook_contract.md` before implementing signature behavior.
- `ingest_event(event)` stores only new event ids and returns `True` for new events, `False` for duplicates.
- Events contain `event_id`, `customer_id`, `metric`, `quantity`, and `unit_price_cents`.
- `invoice_customer(customer_id)` returns an invoice dict with `customer_id`, `event_count`, and `total_cents`.
- `build_webhook(invoice, secret)` returns a dict containing `payload` and `signature` keys.
- Signature uses HMAC-SHA256 over canonical JSON payload with the supplied secret.
- The secret must never appear in the payload.
- Leave role evidence files: `RESEARCH.md`, `PLAN.md`, `VERIFY.md`, `REVIEW.md`, and `SECURITY.md`.
