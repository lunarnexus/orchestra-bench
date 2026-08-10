# Billing SDK 3.2 Release Notes
- `create_invoice(customer_id, lines)` now rejects negative quantities with `ValueError`.
- Deprecated `send_invoice_email`; use `notifications.send_invoice` instead.
- Webhook signatures now require canonical JSON with sorted keys.
- No database migration is required.
