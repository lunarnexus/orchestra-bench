---
title: "Reports and the payments lifecycle"
description: "Learn how Adyen reports show transactions at different stages of the payments lifecycle."
url: "https://docs.adyen.com/reporting/reports-and-the-payments-lifecycle"
source_url: "https://docs.adyen.com/reporting/reports-and-the-payments-lifecycle.md"
canonical: "https://docs.adyen.com/reporting/reports-and-the-payments-lifecycle"
last_modified: "2026-09-30T12:57:16+02:00"
language: "en"
---

# Reports and the payments lifecycle

Learn how Adyen reports show transactions at different stages of the payments lifecycle.

## Payment statuses and corresponding reports

In financial reports, you can find entries from transactions in different stages of the [Payments lifecycle](https://docs.adyen.com/account/payments-lifecycle). The following chart indicates which statuses are recorded in which reports:

![](https://docs.adyen.com/media/f19d1a6cbaf9267024c1fbb57a98bc95fda5cf5dce45e9218cce4315630f0ac3.svg?decoding=auto\&fetchpriority=auto)\
\
\
The [Payment accounting report](https://docs.adyen.com/reporting/invoice-reconciliation/payment-accounting-report) includes payments with the following statuses:

* **Received**: Payment attempt with validated details.
* **Authorised**: Authorised response from acquirer.
* **Settled/Refunded**: Payment attempt with validated details.
* **Error**: Error occurred when communicating. You also receive [webhooks](https://docs.adyen.com/development-resources/webhooks) for payments with this status.
* **Refused**: Refused response from Acquirer or fraud module. You also receive [webhooks](https://docs.adyen.com/development-resources/webhooks) for payments with this status.
* **SentForSettle**: Modification/system: request capture of funds from shopper. You also receive [webhooks](https://docs.adyen.com/development-resources/webhooks) for payments with this status.
* **Cancelled**: Modification: do not allow funds transfer. You also receive [webhooks](https://docs.adyen.com/development-resources/webhooks) for payments with this status.
* **Expired**: Payment was not captured within time limit.
* **SentForRefund**: Modification: transfer funds (refund). You also receive [webhooks](https://docs.adyen.com/development-resources/webhooks) for payments with this status.

The [Settlement details report](https://docs.adyen.com/reporting/settlement-reconciliation/transaction-level/settlement-details-report) includes payments with the following statuses:

* **Settled**: System: funds captured are released to merchant payable.
* **Chargeback**: Payment was reversed by schemes. You also receive [webhooks](https://docs.adyen.com/development-resources/webhooks) for payments with this status.
* **Refunded**: Funds deducted from merchant payable.
* **ChargebackReversed**: Chargeback was reversed by schemes. You also receive [webhooks](https://docs.adyen.com/development-resources/webhooks) for payments with this status.

The [Dispute transaction details report](https://docs.adyen.com/reporting/disputed-transactions) includes payments with the following statuses:

* **Notification of Chargeback**: Notification of a pending chargeback. You also receive [webhooks](https://docs.adyen.com/development-resources/webhooks) for payments with this status.
* **Request for information**: Request for more information about the payment. You also receive [webhooks](https://docs.adyen.com/development-resources/webhooks) for payments with this status.

## See also

* [Payment accounting report](https://docs.adyen.com/reporting/invoice-reconciliation/payment-accounting-report)
* [Settlement details report](https://docs.adyen.com/reporting/settlement-reconciliation/transaction-level/settlement-details-report)
* [Disputed transactions](https://docs.adyen.com/reporting/disputed-transactions)
