---
title: "Invoice reconciliation guide"
description: "Learn how to reconcile your invoices with Adyen"
url: "https://docs.adyen.com/reporting/invoice-reconciliation"
source_url: "https://docs.adyen.com/reporting/invoice-reconciliation.md"
canonical: "https://docs.adyen.com/reporting/invoice-reconciliation"
last_modified: "2022-03-22T12:05:00+01:00"
language: "en"
---

# Invoice reconciliation guide

Learn how to reconcile your invoices with Adyen

Match the costs of your transactions to the items on your [Payment processing invoice from Adyen](https://docs.adyen.com/reporting/invoice-reconciliation/payment-processing-invoice).

To do this, you need:

* The [Payment accounting report](https://docs.adyen.com/reporting/invoice-reconciliation/payment-accounting-report) to see transaction costs associated with different payment statuses. To look at an entire month, generate an [Interactive payment accounting report](https://docs.adyen.com/reporting/invoice-reconciliation/payment-accounting-report/#interactive-payment-accounting-report). When you generate an Interactive payment accounting report, make sure you select the first day of the month until the first day of the next month, select `00:00:00` for both days, and select Central European Time.
* The invoice for the relevant month.

## Step 1: Identify settled transactions

A transaction that has been settled appears in four entries in the report, once with each of the following record types in the **Record Type** column:

* `Received`
* `Authorised`
* `SentForSettle`
* `Settled`

Learn more about the statuses from the [Payments lifecycle](https://docs.adyen.com/account/payments-lifecycle).

## Step 2: Determine processing fees

To see the transaction processing fees charged by Adyen, find entries with the **Record Type**: `Received` and `SentForRefund`.

See Adyen's processing fees in the following columns:

* **Processing Fee Currency**: The currency in which the fee is charged.
* **Processing Fee**: The amount of the fee.

Add the amounts from the **Processing Fee** column together. This is the total of processing fees that have been deducted from your payout.

## Step 3: Match processing fees to your invoice

In your invoice, under the **Specification of amounts already deducted from settlement** section, you can see the total processing fees as **Subtotal** in the **Processing Fees** table.

[![](/images/3/e/b/0/8/3eb08c7d772e4e77cee9699f79bfaba97660a00c-invoice-rec-1.png)](https://docs.adyen.com/media/1af7399e706d94215ab4abfbc97d6e540eb67e652b431e66f16c798c45f4afb6.png)

Look at the **Summary** section of your invoice.

[![](/images/3/a/a/9/0/3aa90becb33410aec0432a1aa8fb92152ae541f9-summary-processing-fees.png)](https://docs.adyen.com/media/e09b665fd4ae85b3a4e8b23940219609eea15b238ad9a48bdb90aa769695563f.png)

If the amount of total processing fees doesn't equal the amount in the **Processing Fees** line, then go to the **Specification of final calculation including discounts** section of the invoice.

[![](https://docs.adyen.com/media/5fe62e0642bd757fb641b8becfcb9724bfc7cc888ba245945f99ee15bce473fc.png)](https://docs.adyen.com/media/5fe62e0642bd757fb641b8becfcb9724bfc7cc888ba245945f99ee15bce473fc.png)

If you need to pay additional fees, you see additional lines in the table. For example, there can be additional lines showing processing fees from transactions settled by other acquirers and fees on transactions refused by [our risk engine](https://docs.adyen.com/risk-management/configure-standard-risk-rules).

## Step 4: Reconcile acquiring and payment method fees

Acquiring and payment method fees are charged only when a transaction reaches the `Settled` status. To see these fees in your report, find the transaction records with the **Record Type**: `Settled`.

See the amounts in the following columns:

* **Markup**: A fee paid for certain card payments or for currency conversion between processing currency and settlement currency. The fee amount depends on the type of card payment or currency conversion rates.
* **Scheme Fees**: A fee paid to the [card scheme](https://docs.adyen.com/get-started-with-adyen/adyen-glossary/#card-networks-or-card-schemes) for each payment transaction made with the card scheme. The fee amount is determined by the corresponding card scheme.
* **Interchange**: A fee paid to the [issuer](https://docs.adyen.com/get-started-with-adyen/adyen-glossary/#issuer-or-issuing-bank) for each payment transaction made via a [card network](https://docs.adyen.com/get-started-with-adyen/adyen-glossary/#card-networks-or-card-schemes). The interchange fee amount is determined by the corresponding card network. A further fee is deducted from the total by Adyen before paying into your merchant account.

Add all these amounts together for the total acquiring and payment method fees. On your invoice, this total and the itemized list of fees are under the section with the calculated amounts.

[![](https://docs.adyen.com/media/04012dd01bc50ae1e0648b605e72bca94cfc203665a919099dc94fb9f9c055f6.png)](https://docs.adyen.com/media/04012dd01bc50ae1e0648b605e72bca94cfc203665a919099dc94fb9f9c055f6.png)

### Payment method fees discrepancy

If the amount in the one of the **Payment Method Fees** lines under the **Specification of final calculation including discounts** section does not equal the amount in the corresponding line under **Specification of amounts already deducted from settlement**, it may be due to a rounding difference. For example:

* The commission markup for a payment method is 0.5%.
* You process 100 transactions, each with an amount of USD 1.00.

The amount in the line under **Specification of amounts already deducted from settlement** is calculated for each transaction: 100 x (USD 1.00 x 0.5%) = USD 0.00.\
The amount in the line under **Specification of final calculation including discounts** is calculated for the aggregated transaction amount (100 x USD 1.00) x 0.5% = USD 0.50.

## Step 5: Determine your amount due

The **Amount due** line under the **Summary** section of your invoice equals the costs calculated at the end of the month minus the already deducted amount. Your **Amount due** will be added or deducted from your next payout and will be an [Invoice deduction entry](https://docs.adyen.com/reporting/settlement-reconciliation/transaction-level/settlement-details-report#invoice-deductions) in the corresponding Settlement details report.

## See also

* [Settlement reconciliation](https://docs.adyen.com/reporting/)
* [Closing your fiscal period](https://docs.adyen.com/reporting/)
