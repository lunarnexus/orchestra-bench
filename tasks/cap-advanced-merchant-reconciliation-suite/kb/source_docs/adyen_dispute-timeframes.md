---
title: "Dispute timeframes"
description: "Review the different timeframes for handling the dispute process."
url: "https://docs.adyen.com/risk-management/understanding-disputes/dispute-timeframes"
source_url: "https://docs.adyen.com/risk-management/understanding-disputes/dispute-timeframes.md"
canonical: "https://docs.adyen.com/risk-management/understanding-disputes/dispute-timeframes"
last_modified: "2024-04-12T10:27:00+02:00"
language: "en"
---

# Dispute timeframes

Review the different timeframes for handling the dispute process.

Each issuing bank has different timeframes for handling disputes. When a dispute is raised, and the bank initiates a chargeback, you can defend it by providing defense documents within the specified timeline. After that, you can expect a final decision.

## Requirements

Before you begin, take into account the following requirements.

| Requirement                                                               | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Integration type**                                                      | Make sure that you have built an [online payments integration](https://docs.adyen.com/online-payments/build-your-integration/).                                                                                                                                                                                                                                                                                                                                                                                                     |
| **[Customer Area roles](https://docs.adyen.com/account/user-roles/#risk)** | Make sure that you have one of the following roles:- **Merchant admin**
- **Risk admin**
- **Merchant dispute management**                                                                                                                                                                                                                                                                                                                                                                                                         |
| **[Webhooks](https://docs.adyen.com/development-resources/webhooks)**      | To follow disputes using webhooks, subscribe to the **Standard webhook** and [enable](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#dispute-webhooks-enable) dispute events.                                                                                                                                                                                                                                                                                                                            |
| **Setup steps**                                                           | You can manage disputes using the [Disputes API](https://docs.adyen.com/risk-management/disputes-api/) or the [Customer Area](https://docs.adyen.com/risk-management/manage-disputes/). Before you begin, we recommend that you:- Understand the general [dispute flow](https://docs.adyen.com/risk-management/understanding-disputes/dispute-process-and-flow/).
- Know the scenarios when Adyen [automatically handles disputes](https://docs.adyen.com/risk-management/manage-disputes#adyen-auto-defense-disputes) on your behalf. |

## Timeframes

In general, a cardholder has a maximum of 120 calendar days from the transaction date to dispute a transaction. This is the moment that the cardholder expects the product or service to be delivered or fulfilled. In some cases for Visa and Mastercard, the cardholder has a maximum of 540 calendar days from the transaction date to dispute a transaction. For example, when the product or service is not immediately delivered or fulfilled, such as a pre-order or transactions related to travelling.

When a Request for Information (RFI) comes in, or a chargeback is raised, you have a limited timeframe to respond.

The following table shows the timeframe (in calendar days) to exercise and defend a chargeback for various schemes.

| Stage                                                                                                                                                                                                      | Visa Collaboration                                                                                    | Visa Allocation                                                                                       | Mastercard                                                                                                  | American Express                                                                                 | Diners | Discover | CUP | JCB | Affirm | Afterpay/ Clearpay | Klarna [1](https://docs.adyen.com/risk-management/understanding-disputes/dispute-timeframes#klarna) | NYCE | PULSE                                                                                             | Accel & STAR                                                                                                            | TWINT |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ------ | -------- | --- | --- | ------ | ------------------ | -------------------------------------------------------------------------------------------------- | ---- | ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ----- |
| Your response (from RFI date)                                                                                                                                                                              | n/a                                                                                                   | n/a                                                                                                   | n/a                                                                                                         | 14                                                                                               | 18     | 18       | 30  | 18  | n/a    | 13                 | 14 days/ 7 days/ 96 hours                                                                          | n/a  | n/a                                                                                               | n/a                                                                                                                     | n/a   |
| Bank initiates a **Chargeback** (from transaction date)                                                                                                                                                    | 120                                                                                                   | 120                                                                                                   | 120                                                                                                         | 120                                                                                              | 120    | 120      | 180 | 120 | 60     | n/a                | n/a                                                                                                | 120  | 120                                                                                               | 75, 90, or 120 days [**4**](https://docs.adyen.com/risk-management/understanding-disputes/dispute-timeframes#accel-star) | 100   |
| Your response to a **Chargeback** (from NoC date)                                                                                                                                                          | 9 or 18 [**5**](https://docs.adyen.com/risk-management/understanding-disputes/dispute-timeframes#visa) | 9 or 18 [**5**](https://docs.adyen.com/risk-management/understanding-disputes/dispute-timeframes#visa) | 40                                                                                                          | 14                                                                                               | 25     | 25       | 30  | 40  | 15     | n/a                | n/a                                                                                                | 30   | 30                                                                                                | 30                                                                                                                      | 10    |
| Issuer initiates **Pre-Arbitration** (only some flows) When you are [eligible](https://docs.adyen.com/risk-management/understanding-disputes/dispute-process-and-flow), you can accept or decline the case. | 28                                                                                                    | n/a                                                                                                   | 8 to 28 [**6**](https://docs.adyen.com/risk-management/understanding-disputes/dispute-timeframes#mastercard) | n/a                                                                                              | n/a    | n/a      | n/a | n/a | n/a    | n/a                | n/a                                                                                                | n/a  | n/a                                                                                               | 30                                                                                                                      | n/a   |
| Final decision: **ChargebackReversed** or **SecondChargeback** (from defense date)                                                                                                                         | 60                                                                                                    | 45                                                                                                    | 70                                                                                                          | 50 [**2**](https://docs.adyen.com/risk-management/understanding-disputes/dispute-timeframes#amex) | 60     | 80       | 20  | 35  | n/a    | n/a                | n/a                                                                                                | 30   | 30 [**3**](https://docs.adyen.com/risk-management/understanding-disputes/dispute-timeframes#pulse) | 30                                                                                                                      | 45    |

### Notes

[]()1 **Klarna**:\
In the [Klarna disputes flow](https://docs.adyen.com/risk-management/chargeback-guidelines/klarna-chargebacks#klarna-flow), you can **only** respond to the dispute at the [Request for Information](https://docs.adyen.com/risk-management/chargeback-guidelines/klarna-chargebacks#request-for-information) stage.

You need to respond to the [Request for Information (RFI)](https://docs.adyen.com/risk-management/chargeback-guidelines/klarna-chargebacks#request-for-information) within the following timeframes:

* **14 days** for consumer [reason codes](https://docs.adyen.com/risk-management/chargeback-guidelines/klarna-chargebacks#dispute-codes).
* **7 days** for RFIs with [reason code](https://docs.adyen.com/risk-management/chargeback-guidelines/klarna-chargebacks#dispute-codes) `unauthorized_purchase`.
* **96 hours** for RFIs with [reason code](https://docs.adyen.com/risk-management/chargeback-guidelines/klarna-chargebacks#dispute-codes) `high_risk_order`.

If the dispute is lost or if you fail to upload the documents, the **Chargeback** journal is booked, your account is debited, and you receive a [CHARGEBACK](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#chargeback) webhook. You cannot defend this chargeback. This is the final status, and the dispute is lost.

[]()2 **American Express**:\
For an [American Express chargeback](https://docs.adyen.com/risk-management/chargeback-guidelines/american-express-chargebacks), a **ChargebackReversed** status is optional. If you defend a dispute, it stays at the [Information Supplied](https://docs.adyen.com/risk-management/chargeback-guidelines/american-express-chargebacks#information-supplied) stage and the last financial event is a chargeback. A **Chargeback** journal is booked. If American Express rejects your defense, you lose the dispute and this is the final status. Only when you win the chargeback, the status changes to **ChargebackReversed**. The **ChargebackReversed** journal is booked and the disputed amount is transferred to your account.

In exceptional cases, [American Express](https://docs.adyen.com/risk-management/chargeback-guidelines/american-express-chargebacks) can reopen a dispute that was previously closed in your favor. If that happens, the **SecondChargeback** journal is booked, and your account is debited. This is the final status of the dispute.

[]()3 **PULSE**:\
When you lose the pre-arbitration in the [PULSE 4868 dispute flow](https://docs.adyen.com/risk-management/chargeback-guidelines/pulse-chargebacks#4868-dispute-flow), the **PreArbitrationLost** journal is booked within 30 days from the defense date and the final status is **Chargeback**.

[]()4 **Accel & STAR**:\
The timeframe for an issuing bank to initiate a chargeback varies based on the type of reason code:

* **75 days** for [Authorization](https://docs.adyen.com/risk-management/understanding-disputes/dispute-reason-codes?tab=chargeback_0_1#star-authorization-chargebacks) reason codes
* **90 days** for [Processing error](https://docs.adyen.com/risk-management/understanding-disputes/dispute-reason-codes?tab=chargeback_0_1#star-processing-error-chargebacks) reason codes.
* **120 days** for other reason codes.

[]()5 **Visa**:\
From 21 July 2025, the response timeframe for disputes opened on payments processed locally in the United States and Canada is 9 days. For disputes opened before this date in the United States or Canada, and for all other countries and regions, the response timeframe is 18 days.

[]()6 **Mastercard**:\
The time you have to accept or decline a pre-arbitration case depends on the dispute reason code. The timeframe can be shortened if the dispute is escalated to scheme arbitration before you make your decision to accept or decline the pre-arbitration case. When the dispute is sent to scheme arbitration, you can no longer accept or decline the pre-arbitration case yourself. The scheme arbitration process can take several months to complete.

## See also

* [Dispute reason codes and defense requirements](https://docs.adyen.com/risk-management/understanding-disputes/dispute-reason-codes/)
* [Dispute flow](https://docs.adyen.com/risk-management/understanding-disputes/dispute-process-and-flow)
