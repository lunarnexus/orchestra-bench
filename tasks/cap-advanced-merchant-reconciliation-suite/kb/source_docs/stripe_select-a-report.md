# How to select a report

Find the right report to fit your financial workflow.

Stripe has a variety of different reports that provide information about your transactions. Start with the task you’re looking to perform and use the table below to identify the best report. You can also view and download many reports through your [organization](https://docs.stripe.com/reports/multiple-accounts.md) to see data across all your accounts.

| Task | Suggested report |
| --- | --- |
| - Download monthly transaction history
- View monthly totals by transaction category
- [Reconcile](https://docs.stripe.com/reports/select-a-report.md#reconciliation) your Stripe balance like a bank account
- Download a list of your payouts | [Balance](https://docs.stripe.com/reports/balance.md) |
| - Break down the individual transactions included in each payout to your bank account
- Download the detail for multiple payouts at a time | [Payout reconciliation](https://docs.stripe.com/reports/payout-reconciliation.md) |
| - View all fees charged by Stripe, networks, and external partners across products and services | [Fees](https://docs.stripe.com/reports/all-fees.md) |

## Reconcile your cash 

The [Balance](https://docs.stripe.com/reports/balance.md) and [Payout reconciliation](https://docs.stripe.com/reports/payout-reconciliation.md) reports both provide downloadable transaction history including custom metadata, and you can use either to reconcile your cash. The reports group transactions in different ways to facilitate different types of reconciliation.

> Stripe doesn’t support third-party [accounting tools](https://docs.stripe.com/stripe-apps/embedded-apps/accounting-integrations.md#xero) reconciliation for Stripe reports.

### Balance report 

The Balance report resembles a bank statement and is optimized for users who treat their Stripe account similar to a bank account in their accounting system. The Balance report helps you to record all activity that occurred in Stripe during a date range. Payouts are recorded as simple transfers between your Stripe account and your bank account, which don’t correspond to any specific payments. Like a bank account, the balance is reconciled at the end of the period to confirm that all transactions have been accounted for.

### Payout reconciliation report 

The Payout reconciliation report is optimized for users on automatic payout plans who model their Stripe balance as a temporary clearing account in their accounting system. This report helps you to reconcile each payout against the transactions included in that batch after it settles.

> You control the timing and amount of instant payouts, so Stripe can’t identify which transactions are included in each payout. You’re responsible for reconciling instant payouts against your transaction history.

### Reconcile between reports 

Most reconciliation workflows don’t require using both reports, but it can be helpful to understand how they fit together.

The following table shows an account on a [two day rolling schedule](https://docs.stripe.com/payouts.md#payout-schedule) with 5 days of activity. The account was opened on the 1st of the month and accepted 10 USD in charges from its customers on its first day. Those funds became available on the 3rd, and the account received its first payout to its bank account because of the 2 day payout schedule.

| Day | Transactions | Payouts | Balance at end of day |
| --- | --- | --- | --- |
| 1st | 10 USD |  | 10 USD |
| 2nd | 20 USD |  | 30 USD |
| 3rd | 30 USD | 10 USD | 50 USD |
| 4th | 50 USD | 20 USD | 80 USD |
| 5th | 70 USD | 30 USD | 120 USD |

Given the above account activity and a [date range](https://docs.stripe.com/reports/options.md#date-range) of **3rd–5th**, the [Balance summary](https://docs.stripe.com/reports/balance.md) would include the following data.

| BALANCE SUMMARY |  |
| --- | --- |
| Starting balance | 30 USD |
| Balance change from activity | 150 USD |
| Total payouts | -60 USD |
| Ending balance | 120 USD |

The [Balance change from activity](https://docs.stripe.com/reports/balance.md) section of the Balance report includes all transactions that occurred from the 3rd through the 5th. The total of these transactions matches the **Balance change from activity** line item in the balance summary of 150 USD.

The [Payout reconciliation](https://docs.stripe.com/reports/payout-reconciliation.md) report includes transactions from the 1st through the 3rd because these transactions were paid out within the selected date range of 3rd–5th. The sum of these transactions matches the **Total Payouts** line item of the balance summary of -60 USD.

The [Ending balance reconciliation](https://docs.stripe.com/reports/payout-reconciliation.md) section at the bottom of the Payout reconciliation report includes transactions from the 4th and 5th because these transactions weren’t paid out within the selected date range of 3rd–5th. The sum of these transactions matches the **Ending balance** line item in the balance summary of 120 USD.

## Include transactions in a given date range 

When you run a report, you select the reporting period using the controls in the Dashboard, or by specifying start and end dates using the API. Each report uses a different type of date to determine which transactions fall within the reporting period.

| Report | Relevant Date | Report Column |
| --- | --- | --- |
| [Balance](https://docs.stripe.com/reports/balance.md) | Date of change in Stripe balance | Balance transaction `created`1 |
| [Payout reconciliation](https://docs.stripe.com/reports/payout-reconciliation.md) | Date automatic payout is available | `automatic_payout_effective_at` |
| [Fees](https://docs.stripe.com/reports/all-fees.md) | Date of change in Stripe balance or date fee was incurred | `balance_transaction_created` or `incurred_at` |

1 Excludes automatic payout transactions, which impact your Stripe balance based on the `available_on` date.
