# PRD — Merchant Reconciliation Desk

> Status: aligned (Slice 5). Endpoint surface, KB section ids, record
> schemas, merchant tiers, network windows, and evaluator checks are all
> final. Authoritative policy values live in
> `kb/RECONCILIATION_REFERENCE.md#task-addenda`.

## Overview

Build **Merchant Reconciliation Desk**, a FastAPI + SQLite service that:

1. Imports internal ledger entries and per-network settlement batches.
2. Reconciles them according to a large policy/reference corpus in `kb/`.
3. Exposes an exception review workflow with admin auth and audit history.
4. Produces policy-compliant reports and deterministic CSV exports.

The agent must consult named sections of the `kb/` corpus; the PRD points to
section ids, not line numbers.

## Runtime

- Entrypoint: `app.py` with `app = FastAPI(...)`.
- Run: `uvicorn app:app --host 127.0.0.1 --port 8123`
- Persistence: SQLite. DB path from `RECON_DB`, default `recon.sqlite3`.
- Admin token from `RECON_ADMIN_TOKEN`, default `recon-admin`.
- Schema initializes automatically on startup.

## Import workflows

- `POST /imports/ledger` — import internal ledger entries.
- `POST /imports/settlements/{network}` — import network settlement records;
  `network` is `network_a`, `network_b`, or `network_c` (unknown networks are
  rejected with a client error).
- Imports are idempotent by `batch_id` + `record_id`; duplicate attempts must
  not double-count totals (`kb/policy_handbook.md#policy-import-idempotency`).
- Invalid records are rejected with clear errors.

### Import record schemas

`POST /imports/ledger` payload: `{"batch_id": str, "records": [...]}`. Each
ledger record carries: `record_id`, `transaction_id`, `merchant_id`,
`merchant_name`, `merchant_tier` (`standard` | `premium` | `training` |
`test`), `original_transaction_id` (null except refunds/reversals), `amount`,
`currency`, `posted_on` (`YYYY-MM-DD`). The merchant tier always comes from
the ledger record (`kb/policy_handbook.md#policy-tier-tolerances`).

`POST /imports/settlements/{network}` payload: `{"batch_id": str,
"records": [...]}`. Each settlement record carries: `record_id`,
`transaction_id`, `original_transaction_id` (non-null only for reversals),
`amount`, `currency`, `settled_on` (`YYYY-MM-DD`). Settlement records carry
no merchant or tier fields (`kb/settlement_formats.md#settlement-match-keys`).

`fixture/data/` holds sample batches in exactly these shapes (ledger batch
`LEDGER-2026-01`, settlement batches `NETA/NETB/NETC-2026-01`) using the
merchant roster below.

### Merchant roster (sample data)

| Merchant | Tier |
|---|---|
| `M-100` Acme Foods | `standard` |
| `M-200` Northwind Trading | `premium` |
| `M-300` Training Corp | `training` |
| `M-400` Euro Bistro | `standard` |
| `M-500` Harbor Goods | `standard` |
| `M-900` `<script>alert(1)</script>Shop` (unescaped) | `standard` |
| `M-910` Test Merchant 910 | `test` |

## Reconciliation

- `POST /reconcile/run` — run reconciliation.
- Match ledger and settlement records by transaction id / original id per policy.
- Detect: matched, missing settlement, unexpected settlement, amount mismatch
  outside tolerance, currency mismatch, late settlement, duplicate
  transaction id, refund/reversal mismatch.
- Produce a reconciliation run summary and store exception records for
  unresolved mismatches.

### Self-Check: Expected Reconciliation Results (fixture data)

After importing all fixture batches and running reconciliation, the expected
results are:

- **67 matched** (clean ledger–settlement pairs, no exception on the pair)
- **8 exceptions**:
  1. `amount_mismatch` — TX-1201 (80.00 vs 80.20, standard tier)
  2. `currency_mismatch` — TX-4001 (USD ledger vs EUR settlement)
  3. `duplicate_transaction_id` — TX-6001 (two ledger rows)
  4. `late_settlement` — TX-1101 (7 days > 5-day network_b window)
  5. `missing_settlement` — TX-8001
  6. `missing_settlement` — TX-1301
  7. `refund_reversal_mismatch` — SETTLE-RF-2 (original TX-9999 unresolved)
  8. `unexpected_settlement` — TX-7001 (no matching ledger record)

Use these to verify your implementation before finalizing.

## Exception review

- `GET /admin/exceptions` — list unresolved exceptions.
- `POST /admin/exceptions/{id}/decision` — `approve`, `reject`, or
  `manual_adjust`, with reason.
- Requires `X-Admin-Token`; missing/invalid token returns `401`.
- Missing reason for manual override returns `422`.
- Decision on a non-pending exception returns `409`.
- Decision on an unknown exception id returns `404`.
- All decisions write audit events.
- Restarting the app must preserve the decisions themselves, not just their terminal status: approved stays approved and manually adjusted stays manually adjusted. Reports and audit history must continue to reflect those saved decisions.

## Reports

- `GET /reports/daily?date=YYYY-MM-DD`
- `GET /reports/merchant/{merchant_id}`
- `GET /reports/exceptions`
- `GET /exports/reconciliation.csv?run_id=...`

Policy rules (stable section ids; authoritative values in
`kb/RECONCILIATION_REFERENCE.md#task-addenda`):

- Merchant tier amount tolerances — `kb/policy_handbook.md#policy-tier-tolerances`
  (standard 0.01, premium 1.00, training/test 0.01; absolute, ledger currency).
- Refund/reversal matching by original transaction id —
  `kb/policy_handbook.md#policy-refund-reversal-matching`.
- Duplicate transaction id detection —
  `kb/policy_handbook.md#policy-duplicate-detection`.
- Import idempotency (`batch_id` + `record_id`) —
  `kb/policy_handbook.md#policy-import-idempotency`.
- Exception categories and review states —
  `kb/policy_handbook.md#policy-exception-categories`.
- Admin auth, decisions, and audit events —
  `kb/policy_handbook.md#policy-admin-auth-audit`.
- Per-network settlement lateness windows —
  `kb/settlement_formats.md#settlement-late-windows`
  (`network_a` 2 days, `network_b` 5 days, `network_c` 2 days default).
- Settlement match keys — `kb/settlement_formats.md#settlement-match-keys`.
- Currency matching — `kb/settlement_formats.md#settlement-currency-matching`.
- Missing / unexpected settlement classification —
  `kb/settlement_formats.md#settlement-missing-unexpected`.
- Training/test merchants are excluded from executive totals but included in
  audit views — `kb/reporting_rules.md#reporting-training-test-exclusion`.
- Daily report totals — `kb/reporting_rules.md#reporting-daily-totals`.
- Merchant report content (exceptions + audit section) —
  `kb/reporting_rules.md#reporting-merchant-reports`.
- Audit history ordering, newest first —
  `kb/reporting_rules.md#reporting-audit-order`.
- Exception summary counts by category and state —
  `kb/reporting_rules.md#reporting-exception-summary`.
- Safe export paths (inside export directory only) —
  `kb/security_and_exports.md#security-safe-export-paths`.
- Deterministic CSV export —
  `kb/security_and_exports.md#security-csv-determinism`.
- Report/audit views escape untrusted text —
  `kb/security_and_exports.md#security-html-escaping`.
- Admin token configuration — `kb/security_and_exports.md#security-admin-token`.

## Security / safety

- No path traversal for export destinations.
- HTML pages escape merchant names, notes, URLs, and exception details.
- Admin mutation routes require the admin token.
- Evaluator-only files must not be imported by the app.

## Required Rule Index

The full required-rule-to-section-id mapping is maintained in
`kb/RECONCILIATION_REFERENCE.md#required-rule-index` (19 rules). The rules
the PRD marks as required, with their stable section ids:

- Merchant tier amount tolerances — `kb/policy_handbook.md#policy-tier-tolerances`.
- Reversal/refund matching by original transaction id —
  `kb/policy_handbook.md#policy-refund-reversal-matching`.
- Duplicate transaction id detection —
  `kb/policy_handbook.md#policy-duplicate-detection`.
- Idempotent imports — `kb/policy_handbook.md#policy-import-idempotency`.
- Exception categories and states — `kb/policy_handbook.md#policy-exception-categories`.
- Admin auth, decisions, audit — `kb/policy_handbook.md#policy-admin-auth-audit`.
- Per-network settlement lateness windows (Network B differs) —
  `kb/settlement_formats.md#settlement-late-windows`.
- Settlement match keys — `kb/settlement_formats.md#settlement-match-keys`.
- Currency matching — `kb/settlement_formats.md#settlement-currency-matching`.
- Missing / unexpected classification — `kb/settlement_formats.md#settlement-missing-unexpected`.
- Training/test merchant exclusion — `kb/reporting_rules.md#reporting-training-test-exclusion`.
- Daily report totals — `kb/reporting_rules.md#reporting-daily-totals`.
- Merchant report content — `kb/reporting_rules.md#reporting-merchant-reports`.
- Audit history newest-first — `kb/reporting_rules.md#reporting-audit-order`.
- Exception summary — `kb/reporting_rules.md#reporting-exception-summary`.
- Safe export paths — `kb/security_and_exports.md#security-safe-export-paths`.
- Deterministic CSV export — `kb/security_and_exports.md#security-csv-determinism`.
- HTML escaping — `kb/security_and_exports.md#security-html-escaping`.
- Admin token — `kb/security_and_exports.md#security-admin-token`.

## Evaluator Checks (stable)

Evaluator starts the app, exercises live HTTP flows, inspects persistence, and
returns JSON with `details.functionality.checks`. Every check maps to PRD
sections above and at least one `kb/` section:

1. `app_starts_and_homepage_documents_routes` — Runtime + all route sections;
   `kb/RECONCILIATION_REFERENCE.md#ref-toc`.
2. `schema_initializes_and_persists` — Runtime (auto schema init);
   `kb/policy_handbook.md#policy-import-idempotency`.
3. `ledger_import_is_idempotent` — Import workflows;
   `kb/policy_handbook.md#policy-import-idempotency`.
4. `settlement_import_is_idempotent` — Import workflows;
   `kb/policy_handbook.md#policy-import-idempotency`.
5. `happy_path_reconciliation_matches_records` — Reconciliation;
   `kb/settlement_formats.md#settlement-match-keys`.
6. `tier_tolerance_policy_applied` — Reconciliation;
   `kb/policy_handbook.md#policy-tier-tolerances`.
7. `network_b_late_window_policy_applied` — Reconciliation;
   `kb/settlement_formats.md#settlement-late-windows`.
8. `refund_reversal_policy_applied` — Reconciliation;
   `kb/policy_handbook.md#policy-refund-reversal-matching`.
9. `duplicates_and_unexpected_settlements_detected` — Reconciliation;
   `kb/policy_handbook.md#policy-duplicate-detection` and
   `kb/settlement_formats.md#settlement-missing-unexpected`.
10. `exception_queue_and_admin_auth_work` — Exception review;
    `kb/policy_handbook.md#policy-admin-auth-audit` and
    `kb/security_and_exports.md#security-admin-token`.
11. `manual_decision_requires_reason_and_audits` — Exception review;
    `kb/policy_handbook.md#policy-admin-auth-audit`.
12. `audit_history_newest_first` — Reports;
    `kb/reporting_rules.md#reporting-audit-order`.
13. `daily_report_totals_apply_exclusions` — Reports;
    `kb/reporting_rules.md#reporting-daily-totals` and
    `kb/reporting_rules.md#reporting-training-test-exclusion`.
14. `merchant_report_includes_audit_and_exceptions` — Reports;
    `kb/reporting_rules.md#reporting-merchant-reports`.
15. `csv_export_is_deterministic_and_safe` — Reports / Security;
    `kb/security_and_exports.md#security-csv-determinism` and
    `kb/security_and_exports.md#security-safe-export-paths`.
16. `html_escaping_blocks_script_injection` — Security / safety;
    `kb/security_and_exports.md#security-html-escaping`.
17. `data_survives_app_restart` — Runtime (persistence);
    `kb/policy_handbook.md#policy-import-idempotency`.

## Open (deferred to later slices)

- Timeout tuning after calibration (Slice 9).
