# Policy Handbook — Merchant Reconciliation Desk

Core reconciliation policy. General context: Adyen's settlement
reconciliation model (ledger vs. settlement records, transaction-level
matching) in `source_docs/adyen_settlement-reconciliation.md` and
`source_docs/adyen_transaction-level.md`; Stripe's balance-transaction
matching in `source_docs/stripe_reconciliation.md`. Task-specific values are
authoritative; see `RECONCILIATION_REFERENCE.md#task-addenda`.

<a id="policy-tier-tolerances"></a>
## Merchant Tier Amount Tolerances

Settlement amounts are never expected to be bit-identical to ledger amounts:
rounding and fee allocation produce small deltas. Tolerance is set per
merchant tier, applied as an **absolute** difference in the ledger currency.

| Tier | Tolerance |
|---|---|
| `standard` | 0.01 |
| `premium` | 1.00 |
| `training` | 0.01 |
| `test` | 0.01 |

Rules:

1. For a matched pair (ledger `L`, settlement `S`), compute
   `delta = |L.amount - S.amount|`.
2. `delta <= tolerance(L.merchant_tier)` → amounts match; no exception.
3. `delta > tolerance(L.merchant_tier)` → raise `amount_mismatch` with the
   delta recorded on the exception.
4. The tier always comes from the **ledger** record; settlement records carry
   no tier.
5. Unknown or missing tier is treated as `standard`.

Worked examples (standard tier, tolerance 0.01):

- Ledger 50.00, settlement 50.01 → delta 0.01 → **match**.
- Ledger 80.00, settlement 80.20 → delta 0.20 → **amount_mismatch**.

Worked examples (premium tier, tolerance 1.00):

- Ledger 1000.00, settlement 1000.99 → delta 0.99 → **match**.

<a id="policy-refund-reversal-matching"></a>
## Refund / Reversal Matching

Refunds and reversals are matched **by original transaction id, not by their
own transaction id**.

1. A ledger record is a refund/reversal when `original_transaction_id` is
   non-null. Its `transaction_id` is its own id; the original sale has the id
   in `original_transaction_id`.
2. A settlement record is a reversal when its `original_transaction_id` is
   non-null.
3. Matching: a reversal settlement matches the ledger refund whose
   `original_transaction_id` equals the settlement's
   `original_transaction_id` (and whose own ledger transaction id may differ
   from the settlement's transaction id entirely).
4. Amount and currency rules still apply to the matched refund pair
   (tolerance per the original merchant's tier).
5. A reversal settlement whose `original_transaction_id` resolves to **no**
   ledger record (neither as the original sale nor as a refund) raises
   `refund_reversal_mismatch`. The unresolved original id must be preserved
   on the exception (e.g. `original_transaction_id: "TX-9999"`).
6. Refunds never count as unexpected settlements, and original sales are
   never matched against a reversal settlement's own id.

<a id="policy-duplicate-detection"></a>
## Duplicate Transaction Detection

1. If the same `transaction_id` appears on more than one **ledger** record
   within the imported data, raise `duplicate_transaction_id` for that
   transaction id (one exception per duplicated id, listing the duplicate
   record ids).
2. A settlement record matching a duplicated transaction id settles **one**
   ledger row; the duplicate ledger row remains unmatched and is part of the
   duplicate exception, not silently double-settled.
3. Duplicate detection is by transaction id only; differing amounts or
   record ids do not prevent the duplicate classification.
4. Re-importing the same batch must not create new duplicates (see
   [Import Idempotency](#policy-import-idempotency)).

<a id="policy-import-idempotency"></a>
## Import Idempotency

1. Imports (ledger and per-network settlement) are keyed by
   `batch_id` + `record_id`.
2. Re-importing a batch already fully present is a no-op: it returns success
   and must **not** double-count totals, create duplicate rows, or change
   reconciliation results.
3. Re-importing a batch with the same `batch_id` but new `record_id`s adds
   only the new records.
4. Invalid records (missing required fields, malformed amounts/dates) are
   rejected with a clear error; a rejected record never partially persists.

<a id="policy-exception-categories"></a>
## Exception Categories and States

Categories produced by reconciliation (see also
`RECONCILIATION_REFERENCE.md#ref-exception-categories`):

- `missing_settlement` — ledger record with no settlement in any imported
  batch for that network set.
- `unexpected_settlement` — settlement record with no matching ledger record.
- `amount_mismatch` — matched pair beyond tier tolerance.
- `currency_mismatch` — matched pair whose currencies differ.
- `late_settlement` — matched pair settled beyond the network's lateness
  window (see `settlement_formats.md#settlement-late-windows`).
- `duplicate_transaction_id` — see [Duplicate Transaction Detection](#policy-duplicate-detection).
- `refund_reversal_mismatch` — see [Refund / Reversal Matching](#policy-refund-reversal-matching).

Review states:

- `pending` — created by reconciliation, awaiting review.
- `approved` — reviewed and accepted as-is.
- `rejected` — reviewed and rejected.
- `manually_adjusted` — resolved via manual adjustment.

Only `pending` exceptions accept decisions. A decision on a non-pending
exception is a conflict (409). Every decision writes an audit event (see
[Admin Authentication, Decisions, and Audit](#policy-admin-auth-audit)).

<a id="policy-admin-auth-audit"></a>
## Admin Authentication, Decisions, and Audit

1. All `/admin/*` routes require the `X-Admin-Token` header. Missing or
   invalid token → **401**. The expected token comes from the
   `RECON_ADMIN_TOKEN` environment variable (default `recon-admin`); see
   `security_and_exports.md#security-admin-token`.
2. `GET /admin/exceptions` lists unresolved (pending) exceptions with a
   total count.
3. `POST /admin/exceptions/{id}/decision` accepts `decision` in
   `approve`, `reject`, `manual_adjust` and an optional `reason`:
   - `manual_adjust` **requires** a non-empty `reason`; without it the
     request is rejected with **422**.
   - `approve` / `reject` succeed with a reason (reason recorded on the audit
     event when provided).
   - Decision on an exception that is not `pending` → **409**.
   - Decision on an unknown exception id → **404**.
4. Every successful decision writes an **audit event** containing at least:
   exception id, decision, reason, and a monotonically increasing sequence
   or timestamp.
5. Audit history is returned **newest first** (see
   `reporting_rules.md#reporting-audit-order`).
