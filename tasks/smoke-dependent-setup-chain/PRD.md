# Smoke E2E — Dependent Setup Chain

## Goal
Complete a small order workflow: product setup, customer setup, cart action, and checkout.

## Product requirements
Implement `checkout()` in `shop.py` so callers can create products, create customers, add cart items, and check out.

## Acceptance criteria
- `checkout` requires an existing customer with a non-empty cart.
- It fails clearly for missing customers, unknown products, and empty carts.
- It returns an order dict containing `order_id`, `customer_id`, `items`, and `total`.
- It clears the customer cart after success.
- Existing setup helpers keep working.
