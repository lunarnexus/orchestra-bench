# Reporting Rules — Merchant Reconciliation Desk

Report and audit-view rules. General context: Adyen monthly/daily finance
reports and closing the fiscal period in
`source_docs/adyen_monthly-and-daily-finance-report.md` and
`source_docs/adyen_closing-your-fiscal-period.md`; Stripe report categories
in `source_docs/stripe_reporting-categories.md`. Task values are
authoritative (`RECONCILIATION_REFERENCE.md#task-addenda`).

<a id="reporting-training-test-exclusion"></a>
## Training / Test Merchant Exclusion

1. Merchants whose tier is `training` or `test` are **excluded from
   executive totals** (daily report totals, executive summaries).
2. They are **still included** in audit and exception views: their
   transactions, exceptions, and decisions remain visible in
   `GET /admin/exceptions`, the exceptions report, and per-merchant reports.
3. Exclusion is applied when aggregating totals, never when listing
   records: an excluded merchant's transactions still reconcile, still
   produce exceptions, and still appear in per-merchant reports.
4. The daily report reflects the exclusion directly: the reported total is
   the sum over non-training/test merchants only.

<a id="reporting-daily-totals"></a>
## Daily Report Totals

- `GET /reports/daily?date=YYYY-MM-DD` returns JSON for one business date.
- The response carries the executive total for that date under a top-level
  numeric field (e.g. `total_amount`) — the total of ledger amounts for the
  date **after** the training/test exclusion
  (`reporting_rules.md#reporting-training-test-exclusion`).
- Totals are computed from ledger records (posted on the requested date),
  not from settlement records.
- The date parameter is required; an unknown/empty date is a client error.

<a id="reporting-merchant-reports"></a>
## Merchant Reports

- `GET /reports/merchant/{merchant_id}` returns an **HTML** page for one
  merchant.
- The page must include:
  1. the merchant id and (escaped) merchant name;
  2. the merchant's **exceptions** from reconciliation runs — each with its
     transaction id and category (e.g. `TX-1201` / `amount_mismatch`);
  3. an **audit** section listing the merchant's audit events
     (see [Audit History Ordering](#reporting-audit-order)).
- Unknown merchant ids return a 404.
- All untrusted text (merchant names, notes, exception details) is HTML-
  escaped (`security_and_exports.md#security-html-escaping`).

<a id="reporting-audit-order"></a>
## Audit History Ordering

1. Audit events are stored with a monotonic sequence (or timestamp) and are
   always presented **newest first**.
2. This ordering applies to the audit section of merchant reports, the
   exceptions report, and any audit listing.
3. Ordering is by event sequence/timestamp, not by insertion order of the
   underlying rows, so a later decision on an earlier-created exception must
   appear above earlier events.

<a id="reporting-exception-summary"></a>
## Exception Summary

- `GET /reports/exceptions` returns the exception summary.
- The summary includes **counts by category** and **counts by state**
  (e.g. `amount_mismatch: 1`, `pending: 8`), plus the overall total.
- The summary covers all recorded exceptions, including resolved states;
  training/test merchant exceptions are included (audit views never exclude
  them, see `#reporting-training-test-exclusion`).
- Unresolved (pending) exceptions are the ones listed by
  `GET /admin/exceptions` for review.
