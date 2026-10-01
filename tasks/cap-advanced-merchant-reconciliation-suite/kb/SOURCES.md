# KB Sources

Vendored, checked-in copies of public payment/reconciliation documentation.
Benchmark runs never depend on live websites; treat the files in
`source_docs/` as the stable corpus.

- Retrieved: 2026-09-30 (UTC)
- Retrieval method: `curl -L <url>` of the provider's markdown endpoint
  (`.md` URLs; Adyen serves YAML front matter including `source_url` per page).
- License note: docs are copyrighted by Adyen N.V. and Stripe, Inc. They are
  vendored here as unmodified reference copies for an internal benchmark
  fixture; redistribute only within the benchmark repository.

## Adyen (primary reconciliation/reporting corpus)

| File | Source URL |
|---|---|
| `source_docs/adyen_settlement-reconciliation.md` | https://docs.adyen.com/reporting/settlement-reconciliation.md |
| `source_docs/adyen_transaction-level.md` | https://docs.adyen.com/reporting/settlement-reconciliation/transaction-level.md |
| `source_docs/adyen_settlement-details-report.md` | https://docs.adyen.com/reporting/settlement-reconciliation/transaction-level/settlement-details-report.md |
| `source_docs/adyen_batch-level.md` | https://docs.adyen.com/reporting/settlement-reconciliation/batch-level.md |
| `source_docs/adyen_reports-and-the-payments-lifecycle.md` | https://docs.adyen.com/reporting/reports-and-the-payments-lifecycle.md |
| `source_docs/adyen_disputed-transactions.md` | https://docs.adyen.com/reporting/disputed-transactions.md |
| `source_docs/adyen_dispute-notifications.md` | https://docs.adyen.com/risk-management/disputes-api/dispute-notifications.md |
| `source_docs/adyen_invoice-reconciliation.md` | https://docs.adyen.com/reporting/invoice-reconciliation.md |
| `source_docs/adyen_payment-accounting-report.md` | https://docs.adyen.com/reporting/invoice-reconciliation/payment-accounting-report.md |
| `source_docs/adyen_payment-processing-invoice.md` | https://docs.adyen.com/reporting/invoice-reconciliation/payment-processing-invoice.md |
| `source_docs/adyen_closing-your-fiscal-period.md` | https://docs.adyen.com/reporting/closing-your-fiscal-period.md |
| `source_docs/adyen_monthly-and-daily-finance-report.md` | https://docs.adyen.com/reporting/closing-your-fiscal-period/monthly-and-daily-finance-report.md |
| `source_docs/adyen_dispute-process-and-flow.md` | https://docs.adyen.com/risk-management/understanding-disputes/dispute-process-and-flow.md |
| `source_docs/adyen_dispute-timeframes.md` | https://docs.adyen.com/risk-management/understanding-disputes/dispute-timeframes.md |
| `source_docs/adyen_chargeback-guidelines.md` | https://docs.adyen.com/risk-management/chargeback-guidelines.md |
| `source_docs/adyen_manage-disputes.md` | https://docs.adyen.com/risk-management/manage-disputes.md |

## Stripe (secondary provider/balance-transaction corpus)

| File | Source URL |
|---|---|
| `source_docs/stripe_reconciliation.md` | https://docs.stripe.com/payouts/reconciliation.md |
| `source_docs/stripe_payout-reconciliation.md` | https://docs.stripe.com/reports/payout-reconciliation.md |
| `source_docs/stripe_balance.md` | https://docs.stripe.com/reports/report-types/balance.md |
| `source_docs/stripe_balance-transaction-types.md` | https://docs.stripe.com/reports/balance-transaction-types.md |
| `source_docs/stripe_reporting-categories.md` | https://docs.stripe.com/reports/reporting-categories.md |
| `source_docs/stripe_select-a-report.md` | https://docs.stripe.com/reports/select-a-report.md |
| `source_docs/stripe_refunds.md` | https://docs.stripe.com/refunds.md |
| `source_docs/stripe_disputes.md` | https://docs.stripe.com/disputes.md |
| `source_docs/stripe_balances.md` | https://docs.stripe.com/payments/balances.md |
| `source_docs/stripe_payouts.md` | https://docs.stripe.com/payouts.md |
| `source_docs/stripe_payouts-connected-accounts.md` | https://docs.stripe.com/connect/payouts-connected-accounts.md |
