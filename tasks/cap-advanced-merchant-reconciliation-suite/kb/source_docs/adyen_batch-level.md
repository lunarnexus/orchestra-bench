---
title: "Batch-level reconciliation"
description: "Learn to reconcile your payout batches for a specific date range."
url: "https://docs.adyen.com/reporting/settlement-reconciliation/batch-level"
source_url: "https://docs.adyen.com/reporting/settlement-reconciliation/batch-level.md"
canonical: "https://docs.adyen.com/reporting/settlement-reconciliation/batch-level"
last_modified: "2022-01-10T18:28:00+01:00"
language: "en"
---

# Batch-level reconciliation

Learn to reconcile your payout batches for a specific date range.

To reconcile payout batches against your bank statement, you need:

* The [Aggregate Settlement Details Report](https://docs.adyen.com/reporting/settlement-reconciliation/batch-level/aggregate-settlement-details-report) to find settled batches and other account movements for a specified date range.

## Step 1: Find settlement batches

Use the following column to find a batch:

* **Batch Number**: The settlement batch number.

Each batch can have more than one entry in the report if it includes settlements with more than one:

* Creation date: for example, it includes settlement amounts from several days of sales.
* Payment method: for example, it includes settlements from Mastercard and Visa payments.
* Journal type: for example, it includes a settlement from American Express payments and a balance transfer form a previous batch.
* Currency: for example, it includes settlement amounts in EUR and USD.

### Example

The following example shows select columns from the Aggregate settlement details report. The entries are for a settlement batch with the **Batch Number** of **604**.

There are six entries with the **Creation Date** of `2021-03-26`.

* Three of the entries have a **Journal Type**: **Settled**.

  * One entry is for the **Payment Method**: **mc**.
  * One entry is for the **Payment Method**: **visa** with the **Net Currency**: **USD**.
  * One entry is for the **Payment Method**:**visa** with the **Net Currency**: **EUR**.

* Three of the entries have a **Journal Type**: **Balancetransfer**.
  * Each of these entries has a different **Net Currency**.

| Batch Number | Payment Method | Creation Date | Journal Type    | Net Currency | Net Debit (NC) | Net Credit (NC) |
| ------------ | -------------- | ------------- | --------------- | ------------ | -------------- | --------------- |
| 604          | mc             | 2021-03-26    | Settled         | USD          |                | 19.16           |
| 604          | visa           | 2021-03-26    | Settled         | USD          |                | 9.84            |
| 604          | visa           | 2021-03-26    | Settled         | EUR          |                | 1332.45         |
| 604          |                | 2021-03-26    | Balancetransfer | USD          |                | 24352.73        |
| 604          |                | 2021-03-26    | Balancetransfer | SEK          |                | 9.8             |
| 604          |                | 2021-03-26    | Balancetransfer | EUR          |                | 1610643.25      |

## Step 2: Find the total transaction amounts and fees in a batch

Each entry with the **Journal Type** of **Settled** shows the amount settled for a group of transactions. You can see details about the amount in the following columns:

* **Gross Credit**: The total amount for the group of transactions in the entry.
* **Bank/Card Commission**: The bank and/or card commission fees for the group of transactions in the entry.
* **DCC Markup**: The Dynamic Currency Conversion (DCC) markup for the group of transactions in the entry.
* **Num Txs**: The number of transactions included in the entry.
* **Net Credit**: The amount settled to your bank account after deducting bank and/or card commission fees and DCC markup. This is the amount in **Gross Credit** minus the amounts in **Bank/Card Commission** and **DCC Markup**.

### Example

The following example shows select columns from the Aggregate settlement details report. The entries are for a settlement batch with the **Batch Number**: `608`.

The net settlement amount for this batch is EUR 5,847.53. This is the total of the amounts in the **Net Credit** column.\
The total bank or card commission fees for this batch is EUR 114.27. This is the total of the amounts in the **Bank/Card Commission** column.\
The total number of transactions in this batch is 31. This is the total of the numbers in the **Num Txs** column.

| Batch Number | Payment Method | Creation Date | Journal Type | Gross Currency | Gross Debit (GC) | Gross Credit (GC) | Exchange Rate | Net Currency | Net Debit (NC) | Net Credit (NC) | Bank/Card Commission (NC) | DCC Markup (NC) | Num Txs |
| ------------ | -------------- | ------------- | ------------ | -------------- | ---------------- | ----------------- | ------------- | ------------ | -------------- | --------------- | ------------------------- | --------------- | ------- |
| 608          | amex           | 2021-04-01    | Settled      | EUR            |                  | 7                 | 1             | EUR          |                | 6.86            | 0.14                      |                 | 1       |
| 608          | mc             | 2021-04-01    | Settled      | EUR            |                  | 768.75            | 1             | EUR          |                | 752.48          | 16.27                     |                 | 3       |
| 608          | visa           | 2021-04-01    | Settled      | EUR            |                  | 5186.05           | 1             | EUR          |                | 5088.19         | 97.86                     |                 | 27      |

## See also

* [Transaction-level reconciliation](https://docs.adyen.com/reporting/settlement-reconciliation/)
