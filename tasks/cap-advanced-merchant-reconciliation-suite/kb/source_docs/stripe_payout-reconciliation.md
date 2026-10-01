# Payout reconciliation report

Reconcile each payout with the batch of transactions it settles.

You can also do [payout reconciliation through the API](https://docs.stripe.com/payouts/reconciliation.md).

The [Payout reconciliation](https://dashboard.stripe.com/reports/reconciliation) report helps you match the payouts you receive in your bank account with the batches of payments and other transactions that they relate to.

The payout reconciliation report is only available for users with [**automatic payouts** enabled](https://dashboard.stripe.com/settings/settlement), or a platform on manual payouts whose Connected Accounts have automatic payouts enabled, and is optimized for users who prefer to reconcile the [transactions](https://support.stripe.com/questions/find-what-transactions-were-included-in-or-impacted-a-payout-amount) included in each payout as a settlement batch. If you use manual payouts (and are not a platform whose Connected Accounts have automatic payouts enabled) or prefer to track and reconcile your Stripe balance like a bank account, see the [Balance](https://docs.stripe.com/reports/balance.md) report instead. To help you decide which report is right for you, see the [guide for selecting reports](https://docs.stripe.com/reports/select-a-report.md#reconciliation).

> You control the timing and amount of instant payouts, so Stripe can’t identify which transactions are included in each payout. You’re responsible for reconciling instant payouts against your transaction history.

To find the transactions included in a payout:

1. Open the [Payout reconciliation report](https://dashboard.stripe.com/reports/reconciliation).
2. Use the [controls](https://docs.stripe.com/reports/options.md) to select a date range that includes the payout’s estimated arrival date. If you aren’t sure of the date, widen the range. See [Payout timing and report availability](https://docs.stripe.com/reports/payout-reconciliation.md#payout-timing-and-report-availability) for details.
3. Find the payout in the **Payout reconciliation** section.
4. Download the **Itemized** CSV to review every payment, refund, dispute, fee, and other balance transaction included in the payout.

The **Balance summary** section shows your starting and ending Stripe balance for the selected date range, along with a high-level summary of your activity during the period.

The **Payout reconciliation** section provides a breakdown of the automatic payouts in the selected date range. The [transactions](https://support.stripe.com/questions/find-what-transactions-were-included-in-or-impacted-a-payout-amount) included in each payout are grouped by [reporting category](https://docs.stripe.com/reports/reporting-categories.md), such as charges, refunds, and fees.

The **Failed payouts** section provides a breakdown of failed automatic payouts, if any. This section is only visible if there are failed automatic payouts in the selected time range.

The **Ending balance reconciliation** section provides a similar breakdown of the transactions that hadn’t been settled as of the report’s end date.

## Download report data

Click **Download** in the upper-right corner of a report section. The **Payout reconciliation** and **Ending balance reconciliation** sections provide these report formats:

- **Summary**: Downloads the totals displayed in the Dashboard.
- **Itemized**: Downloads every transaction included in those totals. For CSV exports, you can include [custom metadata](https://docs.stripe.com/reports/metadata.md) to match Stripe transactions with records in your accounting system.

CSV export is available to all accounts. If the download dialog for your account includes a file format selector, you can select **PDF**, choose **Summary** or **Itemized**, and click **Download**. Itemized PDF exports include up to 5,000 rows. If the dialog doesn’t show **PDF**, use a CSV export.

To download itemized CSV data for one transaction category, hover over the category and click **Download**.

## Activity breakdown

View data such as summary totals and individual transaction details in the Dashboard. Click amounts in the **Payout reconciliation** and **Ending balance reconciliation** sections to audit the underlying transactions. This feature is available only when a Connect platform views reports for its platform account; it isn’t available for reports scoped to connected accounts. Learn more about [activity breakdown](https://docs.stripe.com/reports/activity-breakdown.md).

## Payout timing and report availability

The report groups a payout by the estimated arrival date shown on the [Payouts page](https://dashboard.stripe.com/payouts), not the date your bank posts the deposit. Use the estimated arrival date when selecting the report’s date range. The payout schedule determines when Stripe sends funds to your bank, and weekends, holidays, and bank processing can affect when the funds arrive. Learn more about [payout schedules and timing](https://docs.stripe.com/payouts.md#payout-schedule).

Report data follows a separate processing schedule, so a payout might arrive before its reconciliation data is ready. See [report data availability](https://docs.stripe.com/reports/options.md#data-availability) for processing times and exceptions.

You can request reports for a partial day through the [Reporting API](https://docs.stripe.com/reports/api.md), but reports in the Stripe Dashboard are always for a complete day.

Stripe also issues webhook events twice a day when the data for 00:00 UTC and 12:00 UTC becomes available for reporting. For more details, refer to the [Reporting API](https://docs.stripe.com/reports/api.md) integration pattern.

## Scheduled reports

To learn how to set up a subscription schedule for reports and get notified about new data, see [Scheduled reports](https://docs.stripe.com/reports/options.md#scheduled-reports).

## Available columns

You can customize the columns that appear in the reports when downloading them in the dashboard or through the [Reporting API](https://docs.stripe.com/reports/api.md). The available columns in each type of report are described below.

### Balance Summary

API report type: balance.summary.2

| Column name | Default | Description |
| --- | --- | --- |
| category | ✓ | One of `starting_balance`, `ending_balance`, `activity` or `payouts`. |
| currency | ✓ | Three-letter [ISO code for the currency](https://stripe.com/docs/currencies) in which `net_amount` is defined. |
| description | ✓ | One of `Starting balance (YYYY-MM-DD)` - the balance at the start of the period, `Activity` - the net amount of all transactions that affected your balance except for payouts, `Total payouts` - the amount of payouts to your bank account, or `Ending balance (YYYY-MM-DD)` - the balance left over at the end of the period after subtracting payouts from the `Starting balance` and `Activity`. |
| net_amount | ✓ | Net amount for the transactions associated with `category`. Expressed in major units of the currency (e.g. dollars for USD, yen for JPY). |

### Payouts reconciliation summary

API report type: payout_reconciliation.summary.2

| Column name | Default | Description |
| --- | --- | --- |
| count | ✓ | The number of transactions associated with the `reporting_category`. |
| currency | ✓ | Three-letter [ISO code for the currency](https://stripe.com/docs/currencies) in which `gross`, `fee` and `net` are defined. |
| fee | ✓ | Sum of the fees paid for the transactions associated with the `reporting_category`. Expressed in major units of the currency (e.g. dollars for USD, yen for JPY). |
| gross | ✓ | Sum of the gross amounts of the transactions associated with the `reporting_category`. Expressed in major units of the currency (e.g. dollars for USD, yen for JPY). |
| net | ✓ | Sum of the net amounts for the transactions associated with the `reporting_category`. Expressed in major units of the currency (e.g. dollars for USD, yen for JPY). |
| reporting_category | ✓ | [Reporting Category](https://stripe.com/docs/reporting/reporting-categories) is a new categorization of balance transactions, meant to improve on the current `type` field. |

### Itemized payout reconciliation

API report type: payout_reconciliation.itemized.7

| Column name | Default | Description |
| --- | --- | --- |
| automatic_payout_effective_at | ✓ | The date we expect this [automatic payout](https://stripe.com/docs/payouts#payout-schedule) to arrive in your bank account, in the requested time zone, or UTC if not provided. This is also when the paid-out funds are deducted from your Stripe balance. |
| automatic_payout_effective_at_utc |  | The date we expect this [automatic payout](https://stripe.com/docs/payouts#payout-schedule) to arrive in your bank account, in UTC. This is also when the paid-out funds are deducted from your Stripe balance. |
| automatic_payout_id | ✓ | ID of the automatically created payout associated with this balance transaction (only set if your account is on an [automatic payout schedule](https://stripe.com/docs/payouts#payout-schedule)). |
| available_on | ✓ | The date the balance transaction's net funds will become available in the Stripe balance. Dates in the requested time zone, or UTC if not provided. |
| available_on_utc |  | The date the balance transaction's net funds will become available in the Stripe balance. Dates in UTC. |
| balance_transaction_id | ✓ | Unique identifier for the balance transaction. |
| card_address_city |  | City of the card address associated with this charge, if any |
| card_address_country |  | Country of the card address associated with this charge, if any |
| card_address_line1 |  | First line of the card address associated with this charge, if any |
| card_address_line2 |  | Second line of the card address associated with this charge, if any |
| card_address_postal_code |  | Postal code of the card address associated with this charge, if any |
| card_address_state |  | State of the card address associated with this charge, if any |
| card_brand |  | [Card brand](https://stripe.com/docs/api#card_object-brand), if applicable. |
| card_country |  | Two-letter ISO code representing the country of the card. |
| card_funding |  | Card [funding type](https://stripe.com/docs/api#account_card_object-funding), if applicable. |
| card_network |  | Card network, if applicable. |
| charge_created |  | Creation time of the original charge associated with this balance transaction. Available for charges, refunds and disputes. For charges that were separately authorized and captured, this is the authorization time.  Dates in the requested time zone, or UTC if not provided. |
| charge_created_utc |  | Creation time of the original charge associated with this balance transaction. Available for charges, refunds and disputes. For charges that were separately authorized and captured, this is the authorization time.  Dates in UTC. |
| charge_id |  | Unique identifier for the original charge associated with this balance transaction. Available for charges, refunds and disputes. |
| connected_account_country |  | For Stripe Connect activity related to a connected account, the two-letter ISO code representing the country of the account. |
| connected_account_direct_charge_id |  | For Stripe Connect activity related to a connected account, charge id of the direct charge that happened on connected account. |
| connected_account_id |  | For Stripe Connect activity related to a connected account, the unique ID for the account. |
| connected_account_name |  | For Stripe Connect activity related to a connected account, the name of the account. |
| created | ✓ | Time at which the balance transaction was created. Dates in the requested time zone, or UTC if not provided. |
| created_utc |  | Time at which the balance transaction was created. Dates in UTC. |
| currency | ✓ | Three-letter [ISO code for the currency](https://stripe.com/docs/currencies) in which `gross`, `fee` and `net` are defined. |
| customer_address_city |  | City of the customer address associated with this charge, if any |
| customer_address_country |  | Country of the customer address associated with this charge, if any |
| customer_address_line1 |  | First line of the customer address associated with this charge, if any |
| customer_address_line2 |  | Second line of the customer address associated with this charge, if any |
| customer_address_postal_code |  | Postal code of the customer address associated with this charge, if any |
| customer_address_state |  | State of the customer address associated with this charge, if any |
| customer_description |  | Description provided when creating the customer, often used to store the customer name. |
| customer_email |  | Email address of the customer, if any, associated with this balance transaction. |
| customer_facing_amount |  | For transactions associated with charges, refunds, or disputes, the amount of the original charge, refund, or dispute. If the customer was charged in a different currency than your account's default, this field will reflect the amount as seen by the customer. |
| customer_facing_currency |  | For transactions associated with charges, refunds, or disputes, the three-letter [ISO currency code](https://stripe.com/docs/currencies) for `customer_facing_amount`. |
| customer_id |  | The unique ID of the related customer, if any. |
| customer_name |  | Name of the customer, if any, associated with this balance transaction. |
| customer_shipping_address_city |  | City of the customer shipping address associated with this charge, if any |
| customer_shipping_address_country |  | Country of the customer shipping address associated with this charge, if any |
| customer_shipping_address_line1 |  | First line of the customer shipping address associated with this charge, if any |
| customer_shipping_address_line2 |  | Second line of the customer shipping address associated with this charge, if any |
| customer_shipping_address_postal_code |  | Postal code of the customer shipping address associated with this charge, if any |
| customer_shipping_address_state |  | State of the customer shipping address associated with this charge, if any |
| description | ✓ | An arbitrary string attached to the balance transaction. Often useful for displaying to users. |
| destination_payment_id |  | Destination payment id in the case of Separate Charges & Transfers and destination charges |
| dispute_reason |  | Reason given by cardholder for dispute. Read more about [dispute reasons](https://stripe.com/docs/disputes/categories). |
| fee | ✓ | Fees paid for this transaction. Expressed in major units of the currency (e.g. dollars for USD, yen for JPY). |
| fee_net_of_withheld_tax |  | The Stripe processing fee after removing withheld tax. Calculated as fee minus withheld_tax — represents Stripe's actual processing charge excluding any tax withheld. |
| gross | ✓ | Gross amount of the transaction. Expressed in major units of the currency (e.g. dollars for USD, yen for JPY). |
| invoice_id |  | Unique ID for the invoice associated with this balance transaction. Available for charges, refunds, and disputes made in connection with a Stripe Billing invoice. |
| invoice_number |  | Unique Number for the invoice associated with this balance transaction. Available for charges, refunds, and disputes made in connection with a Stripe Billing invoice. |
| is_link |  | Whether or not the payment was made using Link. |
| is_managed_payments |  | Whether this transaction was processed through Stripe Managed Payments. True when the charge was handled via Stripe Managed Payments, regardless of whether any tax was withheld. |
| net | ✓ | Net amount of the transaction. Expressed in major units of the currency (e.g. dollars for USD, yen for JPY). |
| order_id |  | Unique ID for the order associated with this balance transaction. |
| payment_intent_id |  | The unique ID of the related Payment Intent, if any. |
| payment_metadata[key] |  | Metadata associated with the related PaymentIntent, if any. If no PaymentIntent metadata exists, metadata from any related charge object will be returned. API requests including this column must specify a metadata key in brackets. This column can be specified multiple times to retrieve data from additional metadata keys. |
| payment_method_type |  | The type of payment method used in the related payment. |
| payout_reference_token |  | A unique reference token that displays on the beneficiary's bank statement. |
| payout_statement_descriptor |  | Extra information that displays on the recipient's bank statement. Most banks truncate this information and display it inconsistently. Some banks might not display it at all. |
| refund_metadata[key] |  | Metadata associated with the related refund object, if any. API requests including this column must specify a metadata key in brackets. This column can be specified multiple times to retrieve data from additional metadata keys. |
| regulatory_tag |  | ​​An identifier reflecting the classification of this transaction according to local regulations, if applicable. Accounts with automatic payouts enabled receive a separate payout for each regulatory tag. ​​This column is only populated for Brazilian accounts. |
| reporting_category | ✓ | [Reporting Category](https://stripe.com/docs/reporting/reporting-categories) is a new categorization of balance transactions, meant to improve on the current `type` field. |
| shipping_address_city |  | City of the shipping address associated with this charge, if any |
| shipping_address_country |  | Country of the shipping address associated with this charge, if any |
| shipping_address_line1 |  | First line of the shipping address associated with this charge, if any |
| shipping_address_line2 |  | Second line of the shipping address associated with this charge, if any |
| shipping_address_postal_code |  | Postal code of the shipping address associated with this charge, if any |
| shipping_address_state |  | State of the shipping address associated with this charge, if any |
| source_id |  | The Stripe object to which this transaction is related. |
| statement_descriptor |  | The dynamic statement descriptor or suffix specified when the related charge was created. |
| subscription_id |  | Unique ID for the subscription associated with this balance transaction. Available for charges, refunds, and disputes made in connection with a Stripe Billing subscription. |
| trace_id |  | [Trace ID](https://stripe.com/docs/payouts/trace-id) is a unique identifier generated by bank for the Stripe payouts. Used by banks to locate specific transfers, sometimes referred to as a Reference number. |
| trace_id_status |  | The status of the trace ID. Either `pending`, `unsupported` or `supported`. |
| transfer_metadata[key] |  | Metadata associated with the related transfer object, if any. API requests including this column must specify a metadata key in brackets. This column can be specified multiple times to retrieve data from additional metadata keys. |
| withheld_tax |  | Sales tax, VAT or GST withheld. This amount is already included within the fee column. |

### Failed payouts summary

API report type: failed_payouts.summary.1

| Column name | Default | Description |
| --- | --- | --- |
| count | ✓ | The number of transactions associated with the `reporting_category`. |
| currency | ✓ | Three-letter [ISO code for the currency](https://stripe.com/docs/currencies) in which `gross`, `fee` and `net` are defined. |
| fee | ✓ | Sum of the fees paid for the transactions associated with the `reporting_category`. Expressed in major units of the currency (e.g. dollars for USD, yen for JPY). |
| gross | ✓ | Sum of the gross amounts of the transactions associated with the `reporting_category`. Expressed in major units of the currency (e.g. dollars for USD, yen for JPY). |
| net | ✓ | Sum of the net amounts for the transactions associated with the `reporting_category`. Expressed in major units of the currency (e.g. dollars for USD, yen for JPY). |
| reporting_category | ✓ | [Reporting Category](https://stripe.com/docs/reporting/reporting-categories) is a new categorization of balance transactions, meant to improve on the current `type` field. |

### Itemized failed payouts

API report type: failed_payouts.itemized.2

| Column name | Default | Description |
| --- | --- | --- |
| automatic_payout_effective_at | ✓ | The date we expect this [automatic payout](https://stripe.com/docs/payouts#payout-schedule) to arrive in your bank account, in the requested time zone, or UTC if not provided. This is also when the paid-out funds are deducted from your Stripe balance. |
| automatic_payout_effective_at_utc |  | The date we expect this [automatic payout](https://stripe.com/docs/payouts#payout-schedule) to arrive in your bank account, in UTC. This is also when the paid-out funds are deducted from your Stripe balance. |
| automatic_payout_id | ✓ | ID of the automatically created payout associated with this balance transaction (only set if your account is on an [automatic payout schedule](https://stripe.com/docs/payouts#payout-schedule)). |
| available_on | ✓ | The date the balance transaction's net funds will become available in the Stripe balance. Dates in the requested time zone, or UTC if not provided. |
| available_on_utc |  | The date the balance transaction's net funds will become available in the Stripe balance. Dates in UTC. |
| balance_transaction_id | ✓ | Unique identifier for the balance transaction. |
| card_address_city |  | City of the card address associated with this charge, if any |
| card_address_country |  | Country of the card address associated with this charge, if any |
| card_address_line1 |  | First line of the card address associated with this charge, if any |
| card_address_line2 |  | Second line of the card address associated with this charge, if any |
| card_address_postal_code |  | Postal code of the card address associated with this charge, if any |
| card_address_state |  | State of the card address associated with this charge, if any |
| card_brand |  | [Card brand](https://stripe.com/docs/api#card_object-brand), if applicable. |
| card_country |  | Two-letter ISO code representing the country of the card. |
| card_funding |  | Card [funding type](https://stripe.com/docs/api#account_card_object-funding), if applicable. |
| card_network |  | Card network, if applicable. |
| charge_created |  | Creation time of the original charge associated with this balance transaction. Available for charges, refunds and disputes. For charges that were separately authorized and captured, this is the authorization time.  Dates in the requested time zone, or UTC if not provided. |
| charge_created_utc |  | Creation time of the original charge associated with this balance transaction. Available for charges, refunds and disputes. For charges that were separately authorized and captured, this is the authorization time.  Dates in UTC. |
| charge_id |  | Unique identifier for the original charge associated with this balance transaction. Available for charges, refunds and disputes. |
| connected_account_country |  | For Stripe Connect activity related to a connected account, the two-letter ISO code representing the country of the account. |
| connected_account_direct_charge_id |  | For Stripe Connect activity related to a connected account, charge id of the direct charge that happened on connected account. |
| connected_account_id |  | For Stripe Connect activity related to a connected account, the unique ID for the account. |
| connected_account_name |  | For Stripe Connect activity related to a connected account, the name of the account. |
| created | ✓ | Time at which the balance transaction was created. Dates in the requested time zone, or UTC if not provided. |
| created_utc |  | Time at which the balance transaction was created. Dates in UTC. |
| currency | ✓ | Three-letter [ISO code for the currency](https://stripe.com/docs/currencies) in which `gross`, `fee` and `net` are defined. |
| customer_address_city |  | City of the customer address associated with this charge, if any |
| customer_address_country |  | Country of the customer address associated with this charge, if any |
| customer_address_line1 |  | First line of the customer address associated with this charge, if any |
| customer_address_line2 |  | Second line of the customer address associated with this charge, if any |
| customer_address_postal_code |  | Postal code of the customer address associated with this charge, if any |
| customer_address_state |  | State of the customer address associated with this charge, if any |
| customer_description |  | Description provided when creating the customer, often used to store the customer name. |
| customer_email |  | Email address of the customer, if any, associated with this balance transaction. |
| customer_facing_amount |  | For transactions associated with charges, refunds, or disputes, the amount of the original charge, refund, or dispute. If the customer was charged in a different currency than your account's default, this field will reflect the amount as seen by the customer. |
| customer_facing_currency |  | For transactions associated with charges, refunds, or disputes, the three-letter [ISO currency code](https://stripe.com/docs/currencies) for `customer_facing_amount`. |
| customer_id |  | The unique ID of the related customer, if any. |
| customer_name |  | Name of the customer, if any, associated with this balance transaction. |
| customer_shipping_address_city |  | City of the customer shipping address associated with this charge, if any |
| customer_shipping_address_country |  | Country of the customer shipping address associated with this charge, if any |
| customer_shipping_address_line1 |  | First line of the customer shipping address associated with this charge, if any |
| customer_shipping_address_line2 |  | Second line of the customer shipping address associated with this charge, if any |
| customer_shipping_address_postal_code |  | Postal code of the customer shipping address associated with this charge, if any |
| customer_shipping_address_state |  | State of the customer shipping address associated with this charge, if any |
| description | ✓ | An arbitrary string attached to the balance transaction. Often useful for displaying to users. |
| destination_payment_id |  | Destination payment id in the case of Separate Charges & Transfers and destination charges |
| dispute_reason |  | Reason given by cardholder for dispute. Read more about [dispute reasons](https://stripe.com/docs/disputes/categories). |
| fee | ✓ | Fees paid for this transaction. Expressed in major units of the currency (e.g. dollars for USD, yen for JPY). |
| gross | ✓ | Gross amount of the transaction. Expressed in major units of the currency (e.g. dollars for USD, yen for JPY). |
| invoice_id |  | Unique ID for the invoice associated with this balance transaction. Available for charges, refunds, and disputes made in connection with a Stripe Billing invoice. |
| invoice_number |  | Unique Number for the invoice associated with this balance transaction. Available for charges, refunds, and disputes made in connection with a Stripe Billing invoice. |
| is_link |  | Whether or not the payment was made using Link. |
| net | ✓ | Net amount of the transaction. Expressed in major units of the currency (e.g. dollars for USD, yen for JPY). |
| order_id |  | Unique ID for the order associated with this balance transaction. |
| payment_intent_id |  | The unique ID of the related Payment Intent, if any. |
| payment_metadata[key] |  | Metadata associated with the related PaymentIntent, if any. If no PaymentIntent metadata exists, metadata from any related charge object will be returned. API requests including this column must specify a metadata key in brackets. This column can be specified multiple times to retrieve data from additional metadata keys. |
| payment_method_type |  | The type of payment method used in the related payment. |
| refund_metadata[key] |  | Metadata associated with the related refund object, if any. API requests including this column must specify a metadata key in brackets. This column can be specified multiple times to retrieve data from additional metadata keys. |
| regulatory_tag |  | ​​An identifier reflecting the classification of this transaction according to local regulations, if applicable. Accounts with automatic payouts enabled receive a separate payout for each regulatory tag. ​​This column is only populated for Brazilian accounts. |
| reporting_category | ✓ | [Reporting Category](https://stripe.com/docs/reporting/reporting-categories) is a new categorization of balance transactions, meant to improve on the current `type` field. |
| retried_payout_id | ✓ | The ID of the subsequent payout that retries the transactions from the failed payout. |
| shipping_address_city |  | City of the shipping address associated with this charge, if any |
| shipping_address_country |  | Country of the shipping address associated with this charge, if any |
| shipping_address_line1 |  | First line of the shipping address associated with this charge, if any |
| shipping_address_line2 |  | Second line of the shipping address associated with this charge, if any |
| shipping_address_postal_code |  | Postal code of the shipping address associated with this charge, if any |
| shipping_address_state |  | State of the shipping address associated with this charge, if any |
| source_id |  | The Stripe object to which this transaction is related. |
| statement_descriptor |  | The dynamic statement descriptor or suffix specified when the related charge was created. |
| subscription_id |  | Unique ID for the subscription associated with this balance transaction. Available for charges, refunds, and disputes made in connection with a Stripe Billing subscription. |
| trace_id |  | [Trace ID](https://stripe.com/docs/payouts/trace-id) is a unique identifier generated by bank for the Stripe payouts. Used by banks to locate specific transfers, sometimes referred to as a Reference number. |
| trace_id_status |  | The status of the trace ID. Either `pending`, `unsupported` or `supported`. |
| transfer_metadata[key] |  | Metadata associated with the related transfer object, if any. API requests including this column must specify a metadata key in brackets. This column can be specified multiple times to retrieve data from additional metadata keys. |

### Ending balance reconciliation summary

API report type: ending_balance_reconciliation.summary.1

| Column name | Default | Description |
| --- | --- | --- |
| count | ✓ | The number of transactions associated with the `reporting_category`. |
| currency | ✓ | Three-letter [ISO code for the currency](https://stripe.com/docs/currencies) in which `gross`, `fee` and `net` are defined. |
| fee | ✓ | Sum of the fees paid for the transactions associated with the `reporting_category`. Expressed in major units of the currency (e.g. dollars for USD, yen for JPY). |
| gross | ✓ | Sum of the gross amounts of the transactions associated with the `reporting_category`. Expressed in major units of the currency (e.g. dollars for USD, yen for JPY). |
| net | ✓ | Sum of the net amounts for the transactions associated with the `reporting_category`. Expressed in major units of the currency (e.g. dollars for USD, yen for JPY). |
| reporting_category | ✓ | [Reporting Category](https://stripe.com/docs/reporting/reporting-categories) is a new categorization of balance transactions, meant to improve on the current `type` field. |

### Itemized ending balance reconciliation

API report type: ending_balance_reconciliation.itemized.4

| Column name | Default | Description |
| --- | --- | --- |
| automatic_payout_effective_at | ✓ | The date we expect this [automatic payout](https://stripe.com/docs/payouts#payout-schedule) to arrive in your bank account, in the requested timezone, or UTC if not provided. This is also when the paid-out funds are deducted from your Stripe balance. |
| automatic_payout_effective_at_utc |  | The date we expect this [automatic payout](https://stripe.com/docs/payouts#payout-schedule) to arrive in your bank account, in UTC. This is also when the paid-out funds are deducted from your Stripe balance. |
| automatic_payout_id | ✓ | ID of the automatically created payout associated with this balance transaction (only set if your account is on an [automatic payout schedule](https://stripe.com/docs/payouts#payout-schedule)). |
| available_on | ✓ | The date the balance transaction's net funds will become available in the Stripe balance. Dates in the requested timezone, or UTC if not provided. |
| available_on_utc |  | The date the balance transaction's net funds will become available in the Stripe balance. Dates in UTC. |
| balance_transaction_id | ✓ | Unique identifier for the balance transaction. |
| balance_type |  | The type of balance this transaction belongs to (for example, payments, issuing, corporate_card). |
| card_address_city |  | City of the card address associated with this charge, if any |
| card_address_country |  | Country of the card address associated with this charge, if any |
| card_address_line1 |  | First line of the card address associated with this charge, if any |
| card_address_line2 |  | Second line of the card address associated with this charge, if any |
| card_address_postal_code |  | Postal code of the card address associated with this charge, if any |
| card_address_state |  | State of the card address associated with this charge, if any |
| card_brand |  | [Card brand](https://stripe.com/docs/api#card_object-brand), if applicable. |
| card_country |  | Two-letter ISO code representing the country of the card. |
| card_funding |  | Card [funding type](https://stripe.com/docs/api#account_card_object-funding), if applicable. |
| charge_created |  | Creation time of the original charge associated with this balance transaction. Available for charges, refunds and disputes. For charges that were separately authorized and captured, this is the authorization time.  Dates in the requested timezone, or UTC if not provided. |
| charge_created_utc |  | Creation time of the original charge associated with this balance transaction. Available for charges, refunds and disputes. For charges that were separately authorized and captured, this is the authorization time.  Dates in UTC. |
| charge_id |  | Unique identifier for the original charge associated with this balance transaction. Available for charges, refunds and disputes. |
| connected_account_country |  | For Stripe Connect activity related to a connected account, the two-letter ISO code representing the country of the account. |
| connected_account_direct_charge_id |  | For Stripe Connect activity related to a connected account, charge id of the direct charge that happened on connected account. |
| connected_account_id |  | For Stripe Connect activity related to a connected account, the unique ID for the account. |
| connected_account_name |  | For Stripe Connect activity related to a connected account, the name of the account. |
| created | ✓ | Time at which the balance transaction was created. Dates in the requested timezone, or UTC if not provided. |
| created_utc |  | Time at which the balance transaction was created. Dates in UTC. |
| currency | ✓ | Three-letter [ISO code for the currency](https://stripe.com/docs/currencies) in which `gross`, `fee` and `net` are defined. |
| customer_address_city |  | City of the customer address associated with this charge, if any |
| customer_address_country |  | Country of the customer address associated with this charge, if any |
| customer_address_line1 |  | First line of the customer address associated with this charge, if any |
| customer_address_line2 |  | Second line of the customer address associated with this charge, if any |
| customer_address_postal_code |  | Postal code of the customer address associated with this charge, if any |
| customer_address_state |  | State of the customer address associated with this charge, if any |
| customer_description |  | Description provided when creating the customer, often used to store the customer name. |
| customer_email |  | Email address of the customer, if any, associated with this balance transaction. |
| customer_facing_amount |  | For transactions associated with charges, refunds, or disputes, the amount of the original charge, refund, or dispute. If the customer was charged in a different currency than your account's default, this field will reflect the amount as seen by the customer. |
| customer_facing_currency |  | For transactions associated with charges, refunds, or disputes, the three-letter [ISO currency code](https://stripe.com/docs/currencies) for `customer_facing_amount`. |
| customer_id |  | The unique ID of the related customer, if any. |
| customer_name |  | Name of the customer, if any, associated with this balance transaction. |
| customer_shipping_address_city |  | City of the customer shipping address associated with this charge, if any |
| customer_shipping_address_country |  | Country of the customer shipping address associated with this charge, if any |
| customer_shipping_address_line1 |  | First line of the customer shipping address associated with this charge, if any |
| customer_shipping_address_line2 |  | Second line of the customer shipping address associated with this charge, if any |
| customer_shipping_address_postal_code |  | Postal code of the customer shipping address associated with this charge, if any |
| customer_shipping_address_state |  | State of the customer shipping address associated with this charge, if any |
| description | ✓ | An arbitrary string attached to the balance transaction. Often useful for displaying to users. |
| dispute_reason |  | Reason given by cardholder for dispute. Read more about [dispute reasons](https://stripe.com/docs/disputes/categories). |
| fee | ✓ | Fees paid for this transaction. Expressed in major units of the currency (e.g. dollars for USD, yen for JPY). |
| fee_net_of_withheld_tax |  | The Stripe processing fee after removing withheld tax. Calculated as fee minus withheld_tax — represents Stripe's actual processing charge excluding any tax withheld. |
| gross | ✓ | Gross amount of the transaction. Expressed in major units of the currency (e.g. dollars for USD, yen for JPY). |
| invoice_id |  | Unique ID for the invoice associated with this balance transaction. Available for charges, refunds, and disputes made in connection with a Stripe Billing invoice. |
| invoice_number |  | Unique Number for the invoice associated with this balance transaction. Available for charges, refunds, and disputes made in connection with a Stripe Billing invoice. |
| is_link |  | Whether or not the payment was made using Link. |
| net | ✓ | Net amount of the transaction. Expressed in major units of the currency (e.g. dollars for USD, yen for JPY). |
| payment_intent_id |  | The unique ID of the related Payment Intent, if any. |
| payment_metadata[key] |  | Metadata associated with the related PaymentIntent, if any. If no PaymentIntent metadata exists, metadata from any related charge object will be returned. API requests including this column must specify a metadata key in brackets. This column can be specified multiple times to retrieve data from additional metadata keys. |
| payment_method_type |  | The type of payment method used in the related payment. |
| refund_metadata[key] |  | Metadata associated with the related refund object, if any. API requests including this column must specify a metadata key in brackets. This column can be specified multiple times to retrieve data from additional metadata keys. |
| regulatory_tag |  | ​​An identifier reflecting the classification of this transaction according to local regulations, if applicable. Accounts with automatic payouts enabled receive a separate payout for each regulatory tag. ​​This column is only populated for Brazilian accounts. |
| reporting_category | ✓ | [Reporting Category](https://stripe.com/docs/reporting/reporting-categories) is a new categorization of balance transactions, meant to improve on the current `type` field. |
| shipping_address_city |  | City of the shipping address associated with this charge, if any |
| shipping_address_country |  | Country of the shipping address associated with this charge, if any |
| shipping_address_line1 |  | First line of the shipping address associated with this charge, if any |
| shipping_address_line2 |  | Second line of the shipping address associated with this charge, if any |
| shipping_address_postal_code |  | Postal code of the shipping address associated with this charge, if any |
| shipping_address_state |  | State of the shipping address associated with this charge, if any |
| source_id |  | The Stripe object to which this transaction is related. |
| statement_descriptor |  | The dynamic statement descriptor or suffix specified when the related charge was created. |
| subscription_id |  | Unique ID for the subscription associated with this balance transaction. Available for charges, refunds, and disputes made in connection with a Stripe Billing subscription. |
| trace_id |  | [Trace ID](https://stripe.com/docs/payouts/trace-id) is a unique identifier generated by bank for the Stripe payouts. Used by banks to locate specific transfers, sometimes referred to as a Reference number. |
| trace_id_status |  | The status of the trace ID. Either `pending`, `unsupported` or `supported`. |
| transfer_metadata[key] |  | Metadata associated with the related transfer object, if any. API requests including this column must specify a metadata key in brackets. This column can be specified multiple times to retrieve data from additional metadata keys. |
| withheld_tax |  | Sales tax, VAT or GST withheld. This amount is already included within the fee column. |

### Additional columns

Itemized reports you can download from the Dashboard include the following additional columns:

### Additional columns for itemized reports

- **Product IDs**: The unique identifiers of the products associated with the transaction.
- **Product Names**: The names of the products associated with the transaction.
- **Country**: The country associated with the transaction. For card payments, this is the card’s country of issuance or billing address country. For local payment methods, it’s inferred from the payment method type. For multi-region payment methods like SEPA or PayPal, it defaults to your account country.

## See also

- [Payout schedules FAQ](https://support.stripe.com/questions/payout-schedules-faq)
- [Payouts FAQ](https://support.stripe.com/questions/payouts-faq)
