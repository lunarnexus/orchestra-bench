# Settlement Formats — Merchant Reconciliation Desk

Per-network settlement batch format and matching/lateness rules. General
context: Adyen settlement details reports (transaction-level settlement rows
against the payment ledger) in `source_docs/adyen_settlement-details-report.md`
and `source_docs/adyen_batch-level.md`; Stripe payout reconciliation in
`source_docs/stripe_payout-reconciliation.md`. Task values are authoritative
(`RECONCILIATION_REFERENCE.md#task-addenda`).

## Settlement record shape

Each imported settlement batch has a `batch_id` and `records`; each record:

- `record_id` — unique within the batch (import idempotency key).
- `transaction_id` — the transaction this settlement settles (for a reversal,
  the reversal's own id, e.g. `SETTLE-RF-1`).
- `amount`, `currency` — settled amount and currency.
- `settled_on` — settlement date (`YYYY-MM-DD`).
- `original_transaction_id` — non-null only for reversals (see
  `policy_handbook.md#policy-refund-reversal-matching`).

<a id="settlement-late-windows"></a>
## Per-Network Settlement Lateness Windows

Lateness is evaluated **per network**, against the ledger record's
`posted_on`. Each network has its own window; the window is the maximum
allowed days between `posted_on` and `settled_on` before the settlement is
classified `late_settlement`.

| Network | Window (days) |
|---|---|
| `network_a` | 2 |
| `network_b` | **5** |
| `network_c` | 2 (default) |

Rules:

1. `age = settled_on - posted_on` (whole days).
2. `age <= window(network)` → settlement is in time.
3. `age > window(network)` → raise `late_settlement`.
4. **Network B is the deliberate exception**: its 5-day window is longer
   than the 2-day default used by the other networks. A settlement that is
   late on `network_a`/`network_c` may be in time on `network_b`.
5. The window is looked up per network at reconciliation time; do not
   hardcode a single global window.

Worked examples (ledger posted 2025-06-01):

- `network_b`, settled 2025-06-06 → age 5 → **in time** on network B
  (would be late on a 2-day network).
- `network_b`, settled 2025-06-08 → age 7 → **late** even on network B.
- `network_a`, settled 2025-06-02 → age 1 → in time.

Lateness is independent of amount matching: a pair can be both
`amount_mismatch` and `late_settlement`.

<a id="settlement-match-keys"></a>
## Settlement Match Keys

1. Normal (non-reversal) records match ledger ↔ settlement on
   `transaction_id`.
2. Reversal records match on `original_transaction_id` per
   `policy_handbook.md#policy-refund-reversal-matching`; their own
   `transaction_id` is never used as the match key.
3. One settlement record settles at most one ledger record.
4. A ledger record is matched when exactly one settlement record from any
   imported batch resolves to it.

<a id="settlement-currency-matching"></a>
## Currency Matching

1. The settlement `currency` must equal the ledger `currency` for a matched
   pair.
2. Mismatch → `currency_mismatch` exception (amounts are not compared for
   tolerance once the currency differs; no FX conversion is performed in
   this task).
3. Example: ledger 75.00 USD vs settlement 75.00 EUR → `currency_mismatch`
   even though the numeric amounts are equal.

<a id="settlement-missing-unexpected"></a>
## Missing and Unexpected Settlements

- `missing_settlement` — a ledger record (non-reversal, and reversals whose
  original matched) with no settlement record in any imported batch.
- `unexpected_settlement` — a settlement record that resolves to no ledger
  record (not a valid reversal either).
- A settlement whose `transaction_id` equals a **duplicated** ledger
  transaction id settles one row; the remaining duplicate ledger row is
  reported via `duplicate_transaction_id`, not `missing_settlement`
  (`policy_handbook.md#policy-duplicate-detection`).
- Reconciliation runs over all imported batches; a record matched in any
  batch is not missing.
