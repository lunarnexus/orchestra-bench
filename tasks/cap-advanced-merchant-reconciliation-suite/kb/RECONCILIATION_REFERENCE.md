# Reconciliation Reference — Merchant Reconciliation Desk

Compiled reference for the Merchant Reconciliation Desk task. It combines the
vendored provider documentation in `source_docs/` (see `SOURCES.md` for URLs
and retrieval dates) with the task-specific addenda below. The task policy
values in the addenda are **authoritative** for this benchmark; where they
conflict with general provider guidance, the addenda win.

Each rule lives in a named section with a stable anchor id. `PRD.md` and the
evaluator reference these ids, not line numbers.

<a id="ref-toc"></a>
## Table of Contents

### This file
- [Required Rule Index](#required-rule-index)
- [Task-Specific Addenda](#task-addenda)
- [Exception Categories and States](#ref-exception-categories)
- [Source Document Map](#source-docs-map)

### policy_handbook.md
- [Merchant Tier Amount Tolerances](policy_handbook.md#policy-tier-tolerances)
- [Refund / Reversal Matching](policy_handbook.md#policy-refund-reversal-matching)
- [Duplicate Transaction Detection](policy_handbook.md#policy-duplicate-detection)
- [Import Idempotency](policy_handbook.md#policy-import-idempotency)
- [Exception Categories and States](policy_handbook.md#policy-exception-categories)
- [Admin Authentication, Decisions, and Audit](policy_handbook.md#policy-admin-auth-audit)

### settlement_formats.md
- [Per-Network Settlement Lateness Windows](settlement_formats.md#settlement-late-windows)
- [Settlement Match Keys](settlement_formats.md#settlement-match-keys)
- [Currency Matching](settlement_formats.md#settlement-currency-matching)
- [Missing and Unexpected Settlements](settlement_formats.md#settlement-missing-unexpected)

### reporting_rules.md
- [Training / Test Merchant Exclusion](reporting_rules.md#reporting-training-test-exclusion)
- [Daily Report Totals](reporting_rules.md#reporting-daily-totals)
- [Merchant Reports](reporting_rules.md#reporting-merchant-reports)
- [Audit History Ordering](reporting_rules.md#reporting-audit-order)
- [Exception Summary](reporting_rules.md#reporting-exception-summary)

### security_and_exports.md
- [Safe Export Paths](security_and_exports.md#security-safe-export-paths)
- [Deterministic CSV Export](security_and_exports.md#security-csv-determinism)
- [HTML Escaping](security_and_exports.md#security-html-escaping)
- [Admin Token Handling](security_and_exports.md#security-admin-token)

<a id="required-rule-index"></a>
## Required Rule Index

Rules the PRD marks as required, mapped to their stable section ids:

| Rule | Section id |
|---|---|
| Merchant tier amount tolerances | `policy_handbook.md#policy-tier-tolerances` |
| Reversal/refund matching by original transaction id | `policy_handbook.md#policy-refund-reversal-matching` |
| Duplicate transaction id detection | `policy_handbook.md#policy-duplicate-detection` |
| Idempotent imports (batch id + record id) | `policy_handbook.md#policy-import-idempotency` |
| Exception categories and review states | `policy_handbook.md#policy-exception-categories` |
| Admin auth, decisions, audit events | `policy_handbook.md#policy-admin-auth-audit` |
| Per-network settlement lateness windows (Network B differs) | `settlement_formats.md#settlement-late-windows` |
| Settlement match keys | `settlement_formats.md#settlement-match-keys` |
| Currency matching | `settlement_formats.md#settlement-currency-matching` |
| Missing / unexpected settlement classification | `settlement_formats.md#settlement-missing-unexpected` |
| Training/test merchant exclusion from executive totals | `reporting_rules.md#reporting-training-test-exclusion` |
| Daily report totals shape | `reporting_rules.md#reporting-daily-totals` |
| Merchant report content (exceptions + audit) | `reporting_rules.md#reporting-merchant-reports` |
| Audit history newest-first ordering | `reporting_rules.md#reporting-audit-order` |
| Exception summary counts by category and state | `reporting_rules.md#reporting-exception-summary` |
| Safe export paths (inside export directory only) | `security_and_exports.md#security-safe-export-paths` |
| Deterministic, safe CSV export | `security_and_exports.md#security-csv-determinism` |
| HTML escaping of untrusted text | `security_and_exports.md#security-html-escaping` |
| Admin token configuration | `security_and_exports.md#security-admin-token` |

<a id="task-addenda"></a>
## Task-Specific Addenda

Authoritative policy values for this task. The fixture data and evaluator are
built against these numbers.

### Merchant tiers and amount tolerances

| Tier | Amount tolerance (absolute, in the ledger currency) |
|---|---|
| `standard` | 0.01 |
| `premium` | 1.00 |
| `training` | 0.01 |
| `test` | 0.01 |

A ledger/settlement pair matches on amount when
`|ledger_amount - settlement_amount| <= tier tolerance`. Tolerance is applied
per merchant tier taken from the ledger record. See
[policy_handbook.md#policy-tier-tolerances](policy_handbook.md#policy-tier-tolerances).

### Settlement networks and lateness windows

| Network | Lateness window (days after ledger `posted_on`) |
|---|---|
| `network_a` | 2 |
| `network_b` | 5 |
| `network_c` | 2 (default) |

A settlement is late when
`settled_on - posted_on > window`. **Network B's 5-day window is the deliberate
exception** to the 2-day default; code must read the window per network, not
hardcode one value. See
[settlement_formats.md#settlement-late-windows](settlement_formats.md#settlement-late-windows).

### Exception categories

`missing_settlement`, `unexpected_settlement`, `amount_mismatch`,
`currency_mismatch`, `late_settlement`, `duplicate_transaction_id`,
`refund_reversal_mismatch`. See
[Exception Categories and States](#ref-exception-categories).

### Executive reporting exclusions

Merchants with tier `training` or `test` are excluded from executive daily
totals but must still appear in audit/exception views. See
[reporting_rules.md#reporting-training-test-exclusion](reporting_rules.md#reporting-training-test-exclusion).

### Security

Admin mutation routes require the `X-Admin-Token` header (401 when missing or
invalid); token comes from `RECON_ADMIN_TOKEN` (default `recon-admin`). CSV
exports are byte-deterministic and confined to the export directory; all HTML
views escape untrusted text. See `security_and_exports.md`.

<a id="ref-exception-categories"></a>
## Exception Categories and States

Full definitions live in
[policy_handbook.md#policy-exception-categories](policy_handbook.md#policy-exception-categories).
Summary:

- `missing_settlement` — ledger record with no settlement in any imported batch.
- `unexpected_settlement` — settlement with no matching ledger record.
- `amount_mismatch` — matched pair whose amounts differ beyond tier tolerance.
- `currency_mismatch` — matched pair whose currencies differ.
- `late_settlement` — matched pair settled beyond the network's lateness window.
- `duplicate_transaction_id` — the same transaction id appears more than once
  in the ledger (or a settlement maps to multiple ledger rows).
- `refund_reversal_mismatch` — a refund/reversal whose original transaction id
  resolves to no matching original transaction.

Review states: `pending` (newly created), `approved`, `rejected`,
`manually_adjusted`. Only `pending` exceptions accept a decision; every
decision writes an audit event.

<a id="source-docs-map"></a>
## Source Document Map

Vendored copies (unmodified) in `source_docs/`; URLs and retrieval date in
`SOURCES.md`.

- **Adyen (primary reconciliation/reporting corpus)** — 16 documents covering
  settlement reconciliation (transaction-level and batch-level), the reports
  and payments lifecycle, disputed transactions and dispute notifications,
  invoice reconciliation (payment accounting report, payment processing
  invoice), closing the fiscal period, monthly/daily finance reports, and
  dispute process, timeframes, chargeback guidelines, and dispute management.
  Use these for the conceptual model of settlement vs. ledger reconciliation,
  report lifecycle, and dispute handling.
- **Stripe (secondary provider/balance-transaction corpus)** — 11 documents
  covering payout reconciliation, balance and balance-transaction reports,
  reporting categories, report selection, refunds, disputes, balances, and
  payouts (including connected accounts). Use these for balance-transaction
  style matching and payout-side reconciliation concepts.

The task's internal networks (`network_a`, `network_b`, `network_c`) are
abstractions over these provider formats; the task addenda above define the
exact values the implementation must use.
