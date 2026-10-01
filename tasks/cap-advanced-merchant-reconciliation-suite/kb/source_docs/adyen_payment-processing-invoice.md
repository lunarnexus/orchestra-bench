---
title: "Payment processing invoice"
description: "The invoice shows an itemized list of costs for Adyen's payment services."
url: "https://docs.adyen.com/reporting/invoice-reconciliation/payment-processing-invoice"
source_url: "https://docs.adyen.com/reporting/invoice-reconciliation/payment-processing-invoice.md"
canonical: "https://docs.adyen.com/reporting/invoice-reconciliation/payment-processing-invoice"
last_modified: "2022-12-05T16:57:00+01:00"
language: "en"
---

# Payment processing invoice

The invoice shows an itemized list of costs for Adyen's payment services.

##### Time zone

Your invoice is always based on the CET time zone.

Each month, Adyen gives you a Payment processing invoice for your [company account](https://docs.adyen.com/account/account-structure#company-account). This includes the payment processing costs for all of your [merchant accounts](https://docs.adyen.com/account/account-structure#merchant-accounts) that are linked to the same [legal entity](https://docs.adyen.com/account/define-account-structure#legal-entities). If a merchant account is linked to different legal entity than the company account, Adyen gives you a separate invoice for that merchant account.

## Common discrepancies and exceptions

Some costs are in separate invoices, and some costs only appear in the invoice in certain cases:

* If you [order new Adyen payment terminals](https://docs.adyen.com/point-of-sale/managing-terminals/order-terminals#sales-order-steps), the costs do not appear in this invoice. Instead, you get separate invoices for them.

* There can be a difference between the costs in the invoice and the deductions from your settlement batches during the month. Adyen will credit or debit the difference to the next settlement batch for the corresponding merchant account.

* Adyen does not deduct sales tax or value-added tax (VAT) from your settlement batches. If your billed entity is in the following territories, the applicable taxes show up in your invoice:

  * United States: On 1 May 2021, Adyen started charging sales tax for certain services rendered in some US states in which we have nexus to accommodate legislative changes in sales tax policy. These sales tax charges started appearing on relevant invoices on 1 June 2021.
  * France: On 1 May 2021, Adyen started charging VAT on financial services, via the legislative provision under *Option pour la TVA au titre des prestations bancaires et financières (article 260 B du Code Generale des Impots)*. The VAT charges started appearing on relevant invoices on 1 June 2021.

## Get your invoice

You must have either the **Merchant financial** or **Manage key financial tasks** [user role](https://docs.adyen.com/account/user-roles).

To see and download your invoice:

1. Log in to your [Customer Area](https://ca-test.adyen.com/).
2. Go to **Reconciliation** > **Invoices**.

You can see all of your invoices in the page.

## Structure

Your invoice includes the following pages:

* A [summary page](https://docs.adyen.com/reporting/invoice-reconciliation/payment-processing-invoice#summary-page) for the month's transaction fees and commissions.
* A [details page](https://docs.adyen.com/reporting/invoice-reconciliation/payment-processing-invoice#detail-page) with tables for calculated and already deducted amounts.

You can also choose to break down invoice details by merchant account. If so, we include additional pages organized by merchant account.

### Summary page

The summary page shows you an itemized list of costs.

The **Already deducted from settlement** amount shows the total fees and commissions that have been deducted from your [payout batches](https://docs.adyen.com/account/getting-paid#payout-batches-and-reporting). You can find these deductions in the [Interactive payment accounting report](https://docs.adyen.com/reporting/invoice-reconciliation/payment-accounting-report) and [Settlement details report](https://docs.adyen.com/reporting/settlement-reconciliation/transaction-level/settlement-details-report).

The **Amount due** shows the amount you owe that hasn't been deducted from your settlement.

### Details page

The second page shows how we calculate your costs. In the **Specification of final calculation including discounts** section, you can find the **Total** amount of fees.

The table in the **Specification of amounts already deducted from settlement** section contains the costs that have been deducted from settlements. You can see deductions in an invoice deduction line in the [Settlement details report](https://docs.adyen.com/reporting/settlement-reconciliation/transaction-level/settlement-details-report).

## Amount due

The **Amount due** can be positive or negative. The amount deducted from the settlements can be different than the amount due because of the following reasons:

* Tiered pricing: the fees per transaction depend on the total volume processed in the month. During the month, you are charged at the lowest tier. At the end of the month, it can be higher.
* Transactions at the end of the month: commission fees can be charged in the following month.
* Price changes introduced during the month.

Under **Payment instructions**, you can find out how we deduct amount due from the next settlement batch.

## See also

* [Invoice reconciliation](https://docs.adyen.com/reporting/invoice-reconciliation)
* [Payment accounting report](https://docs.adyen.com/reporting/invoice-reconciliation/payment-accounting-report)
