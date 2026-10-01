---
title: "Transaction-level reconciliation"
description: "Learn to reconcile the transactions in a batch."
url: "https://docs.adyen.com/reporting/settlement-reconciliation/transaction-level"
source_url: "https://docs.adyen.com/reporting/settlement-reconciliation/transaction-level.md"
canonical: "https://docs.adyen.com/reporting/settlement-reconciliation/transaction-level"
last_modified: "2021-07-02T16:59:00+02:00"
language: "en"
---

# Transaction-level reconciliation

Learn to reconcile the transactions in a batch.

##### Credit card installment payments in Brazil

If you accept [credit card installment payments](https://docs.adyen.com/payment-methods/cards/credit-card-installments) in Brazil, you need to additionally [follow these instructions](https://docs.adyen.com/reporting/settlement-reconciliation/transaction-level/reconcile-installment-payments).

This guide shows how to reconcile the costs of transactions and the payout amounts in a single payout batch on a transaction level.

To do this, you need:

* The [Settlement details report](https://docs.adyen.com/reporting/settlement-reconciliation/transaction-level/settlement-details-report) to see settled transactions and transaction costs.
* The [External settlement detail report](https://docs.adyen.com/reporting/settlement-reconciliation/transaction-level/external-settlement-detail-report) if you have an agreement with external acquirers to process transactions.

Follow these steps to add up the credits to your account and subtract the debits from your account to verify the total payout amount. Because the Settlement details report is generated for [merchant accounts](https://docs.adyen.com/account/account-structure#merchant-accounts), we recommend doing reconciliation on the merchant account level.

## Step 1 (Optional): Merge your External settlement report with your Settlement details report

The External settlement detail report includes the same fields as the Settlement details report that you need for reconciliation.

Because the acquiring is outside of Adyen, the information used to generate this report is provided by external acquirers. You can get reports directly from them instead. If you do so, you need to skip this step and reconcile those transactions separately.

1. Generate the Settlement details report for your merchant account.
2. Generate the External settlement detail report. This report can only be generated for your [company account](https://docs.adyen.com/account/account-structure#company-account).
3. In the External settlement detail report, find the lines with the merchant account name in the **Merchant Account** column that corresponds to the merchant account for which you generated the Settlement details report.
4. Add those lines to your Settlement details report.

## Step 2: Find transactions

Each line in the report is an entry. Each transaction can have more than one entry.

Use the following columns to identify a transaction:

* **Psp Reference**: A unique identifier assigned by Adyen.
* **Merchant Reference**: An identifier assigned by you. You can use this identifier to match the transaction record in your system(s).

## Step 3: Find the payment amounts and your transaction costs

The following columns show the gross amount a customer paid through Adyen:

* **Gross Credit**

Different payment methods have different transaction costs. The following columns show different costs:

* **Commission**
* **Markup**
* **Scheme Fees**
* **Interchange Fees**

The following column shows the amount credited to your account after deducting transaction costs:

* **Net Credit**

In the following example with select columns from the Settlement details report, we explain a transaction with the **Psp Reference**: `8515748691833060`:

* The customer paid the **Gross Credit** amount of EUR 525.
* The costs for this transaction are shown in the columns **Markup**, **Scheme Fees**, and **Interchange**. The total is EUR 4.43.
* After subtracting the transaction costs, Adyen credits your account with the **Net Credit** amount of EUR 520.57.

| Merchant Account        | Psp Reference    | Merchant Reference | Creation Date    | Type    | Gross Currency | Gross Debit (GC) | Gross Credit (GC) | Net Currency | Net Debit (NC) | Net Credit (NC) | Commission (NC) | Markup (NC) | Scheme Fees (NC) | Interchange (NC) |
| ----------------------- | ---------------- | ------------------ | ---------------- | ------- | -------------- | ---------------- | ----------------- | ------------ | -------------- | --------------- | --------------- | ----------- | ---------------- | ---------------- |
| YOUR\_MERCHANT\_ACCOUNT | 8515748691833060 | R591959192         | 30/08/2018 11:53 | Settled | EUR            |                  | 525               | EUR          |                | 520.57          |                 | 1.58        | 1.27             | 1.58             |

## Step 4: Find debits from your account

The following columns in the report show debits like refunds, chargebacks, and fees from your account:

* **Gross Debit**: The gross debit amount.
* **Net Debit**: The gross debit minus the additional costs that some debits incur.

In the following example with select columns from the Settlement details report, we explain a transaction with the **Psp Reference**: `8515814273533250`.

* The **Type** of debit is a chargeback. Learn about the [journal types](https://docs.adyen.com/reporting/settlement-reconciliation/transaction-level/settlement-details-report#journal-types).
* The **Modification Reference** column shows the reference for this modification.
* The **Gross Debit** amount is EUR 120, and the chargeback has an additional **Markup** cost of EUR 7.5.
* After adding the transaction cost, the **Net Debit** from your account is EUR 127.5.

| Merchant Account        | Psp Reference    | Merchant Reference | Creation Date    | Type       | Modification Reference | Gross Currency | Gross Debit (GC) | Gross Credit (GC) | Net Currency | Net Debit (NC) | Net Credit (NC) | Commission (NC) | Markup (NC) | Scheme Fees (NC) | Interchange (NC) |
| ----------------------- | ---------------- | ------------------ | ---------------- | ---------- | ---------------------- | -------------- | ---------------- | ----------------- | ------------ | -------------- | --------------- | --------------- | ----------- | ---------------- | ---------------- |
| YOUR\_MERCHANT\_ACCOUNT | 8515814273533250 | R370200838         | 31/07/2018 09:49 | Chargeback | 0000000009903188       | EUR            | 120              |                   | EUR          | 127.5          |                 |                 | 7.5         |                  |                  |

## Step 5: Find the payout amount of the batch

When you add up the net credits and subtract the net debits, the amount should equal the payout amount of the batch. To see the amount paid out to your account from Adyen, filter the **Type** column on **MerchantPayout**. This shows the payout entry.

The modification reference, batch number, and your merchant account are in the **Modification Reference** column.

The **Net Debit** column shows the payout amount.

In the following example with select columns from the Settlement details report, we explain a transaction with the **Batch Number**: `229`.

* The **Modification Reference** is `TX22236510273XT`. You can use this as a reference to the payout in your accounting system.
* The **Net Debit** column shows the batch payout amount of EUR 11103.07.

| Merchant Account        | Creation Date    | TimeZone | Type           | Modification Reference                            | Net Currency | Net Debit (NC) | Net Credit (NC) | Batch Number |
| ----------------------- | ---------------- | -------- | -------------- | ------------------------------------------------- | ------------ | -------------- | --------------- | ------------ |
| YOUR\_MERCHANT\_ACCOUNT | 03/09/2018 21:48 | CET      | MerchantPayout | TX22236510273XT batch 229 YOUR\_MERCHANT\_ACCOUNT | EUR          | 11103.07       |                 | 229          |

## Step 6 (Optional): Work out common discrepancies and exceptions

### Weekend sales in batches

The payouts for all weekend sales are included in a batch the following week. Therefore, if you have sales on Friday, Saturday, and Sunday, the amount from all of those transactions are paid out once in a single batch the following week.

### Payments not yet settled

A payment may not be settled because:

* Adyen has received the funds captured and will settle them with your next MerchantPayout.
* Adyen has not yet received the funds. Some foreign cards or particular payment methods have longer settlement times.
* Capture of funds has failed, for example, because of a technical error.
* A payment or partial payment was not canceled when the order was canceled.

To account for these payments:

1. Review your open balances in the [Monthly or daily finance report](https://docs.adyen.com/reporting/closing-your-fiscal-period/monthly-and-daily-finance-report).
2. Compare total Settled amount in the Aggregate settlement details report, selecting a duration since the day of sale and summing by the **Creation date** column) against your own sales report to identify discrepancies or unsettled payments.
3. Use the Received payment details and Interactive payment accounting reports to match items in the former not yet booked to `Settled` since the day of sale.
4. Review the status and log for each payment in the Adyen Customer Area.

## See also

* [Batch-level reconciliation](https://docs.adyen.com/reporting/settlement-reconciliation/)
