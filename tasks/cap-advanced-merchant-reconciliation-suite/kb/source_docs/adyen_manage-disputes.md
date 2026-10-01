---
title: "Manage disputes"
description: "After you receive a chargeback you can either accept it, or defend it."
url: "https://docs.adyen.com/risk-management/manage-disputes"
source_url: "https://docs.adyen.com/risk-management/manage-disputes.md"
canonical: "https://docs.adyen.com/risk-management/manage-disputes"
last_modified: "2023-04-14T13:50:00+02:00"
language: "en"
---

# Manage disputes

After you receive a chargeback you can either accept it, or defend it.

You can view, accept or defend disputes in your Customer Area.

If you want to automate the dispute handling process, you can manage disputes through the [Disputes API](https://docs.adyen.com/risk-management/disputes-api) instead.

## Requirements

Before you begin, take into account the following requirements.

| Requirement                                                               | Description                                                                                                                                                                                                                                                                                                                                  |
| ------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Integration type**                                                      | Make sure that you have built an [online payments integration](https://docs.adyen.com/online-payments/build-your-integration/).                                                                                                                                                                                                               |
| **[Customer Area roles](https://docs.adyen.com/account/user-roles/#risk)** | Make sure that you have one of the following roles:- **Merchant admin**
- **Risk Admin**
- **Merchant dispute management**To manage pre-arbitration cases as well as disputes, you need one of the following roles:- **Risk Admin**
- **Pre-arbitration dispute management**                                                                 |
| **[Webhooks](https://docs.adyen.com/development-resources/webhooks)**      | To follow disputes using webhooks, subscribe to the **Standard webhook** and [enable](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#dispute-webhooks-enable) dispute events.                                                                                                                                      |
| **Setup steps**                                                           | Before you begin, we recommend that you:- Understand the general [dispute flow](https://docs.adyen.com/risk-management/understanding-disputes/dispute-process-and-flow/).
- Know the scenarios when Adyen [automatically handles disputes](https://docs.adyen.com/risk-management/manage-disputes#adyen-auto-defense-disputes) on your behalf. |

## View disputes

View a dispute to get more information about it, and decide whether to accept or defend it.

In your [Customer Area](https://ca-live.adyen.com/):

1. Select a [merchant account](https://docs.adyen.com/account/account-structure).
2. Go to **Risk & disputes** > **Disputes**.
3. Select a **Dispute Psp Reference** from the **Chargebacks**, **Requests for Information**, or **Notifications of Fraud** tab.

The dispute details page shows information relating to the dispute.

If the dispute is a chargeback that can be defended, you have the option to accept it or upload defense material using the **Handle chargeback** button. If the dispute is not valid, the Adyen [auto-defense](https://docs.adyen.com/risk-management/manage-disputes#adyen-auto-defense-disputes) process is triggered.

## Accept disputes

Accept the dispute to avoid a lengthy (and possibly costly) dispute process, especially if you agree with the dispute, for example, if the transaction is known to be fraudulent.

You may want to accept the dispute if:

* Your supporting documents do not satisfy the defense document requirements.
* The transaction amount is not high enough to spend resources on compelling evidence.
* The transaction amount does not outweigh the risk of losing the chargeback fee for the second booked chargeback.
* The transaction is known to be fraudulent.
* The shopper has returned the goods, or you have failed to deliver the goods.

You can accept the chargeback in your [Customer Area](https://ca-live.adyen.com/). When you accept the dispute, and the defense period has expired, the final status will be *Lost* and the dispute cycle ends. To indicate that you have accepted, the journal line *DisputeDefensePeriodEnded* will be booked.

## Defend disputes

Defend disputes where you have evidence that the transaction is valid, or the transaction amount is high. If you defend the chargeback, the dispute will move through the entire cycle which will be a lengthy, and possibly costly, process.

A chargeback fee is charged for every booked chargeback. Therefore, we strongly advise you to only defend a chargeback when you have sufficient compelling evidence.

You are allowed to upload defense documents at the following stages:

* **Request for Information** stage.
* **Chargeback** stage.

For the defense material to qualify, you must upload it within the given [time frame](https://docs.adyen.com/risk-management/understanding-disputes/dispute-timeframes/), and it should meet the [requirements](https://docs.adyen.com/risk-management/understanding-disputes/dispute-reason-codes?tab=chargeback_1#defense_requirements) of the reason code, following the [chargeback guidelines](https://docs.adyen.com/risk-management/chargeback-guidelines) for specific schemes.

You will generally defend a dispute when:

* You have enough compelling evidence based on the chargeback reason code.
* The transaction amount is high.

Upload your documents to the dispute details page in a PDF, JPG, or TIFF file. Make sure that your defense documents do not contain sensitive data. Adyen will refuse defense material that contains data such as copies of passports, social security numbers, tax records, unrelated legal documents, Primary Account Numbers ([PAN](https://docs.adyen.com/get-started-with-adyen/adyen-glossary/#card-number-pan)), and [sensitive authentication data](https://docs.adyen.com/get-started-with-adyen/adyen-glossary/#sensitive-authentication-data). After you upload the files, the journal line *InformationSupplied* will be booked, and the status of the dispute will change. If the dispute is in the Request for Information stage, the status changes to *Responded*. If the dispute is in the chargeback stage, the status changes to *Pending*.

Your rebuttal is reviewed by an employee of the bank (and by the card scheme later in the dispute process). You must include valid arguments to prove that you have delivered the service. For more guidance, see [Defense requirements](https://docs.adyen.com/risk-management/understanding-disputes/dispute-reason-codes?tab=chargeback_1#defense_requirements).

If you need further advice or template documents for crafting your rebuttal, contact us via email.

## Adyen auto-defense for disputes

Adyen will automatically defend applicable chargebacks with no action needed on your part. Typically, only disputes on payments made with credit or debit cards can be auto-defended. Disputed payments made with alternative payment methods and disputes that have to be defended at the RFI stage cannot be auto-defended.

Examples of chargebacks that can be auto-defended include:

* Transactions that were refunded before the chargeback was sent. It can sometimes happen that issuers open a dispute on behalf of a cardholder even if you have already refunded the transaction. Adyen cannot influence when issuers open a chargeback.
* Chargebacks with a fraud reason code for which there was a liability shift. This includes, for example, 3D Secure payments but does not include payments made with digital wallets.
* Chargebacks that include technical errors that invalidate them. For example when a chargeback is sent outside the time frame allowed by the schemes.
* Chargebacks not applicable to your MCC code.

## Accept or decline pre-arbitration cases

For some dispute flows, the issuer can open a pre-arbitration case if they decline your defense.

When you are eligible, and the dispute flow supports it, you can accept or decline the pre-arbitration case yourself. This requires additional configuration and approval from Adyen. Reach out to our [Support Team](https://ca-test.adyen.com/ca/ca/contactUs/support.shtml?form=other) or your Adyen contact for more details.

You can (partially) accept the pre-arbitration in your [Customer Area](https://ca-live.adyen.com/).

If you accept the pre-arbitration, the dispute is lost, and you receive a second chargeback.

If you decline the pre-arbitration, the case can be sent to scheme arbitration. We recommend that you only decline if you are confident that the chargeback is not valid, and that the defense materials provided during the first chargeback defense were sufficient.

To decline a pre-arbitration request, you have to provide an explanation why you believe the pre-arbitration request is not valid. If the payment method allows it, you can provide additional documentation when you decline a pre-arbitration request. Make sure that this additional documentation:

* Does not contain defense materials that you should have uploaded during the first chargeback defense stage. New evidence can be disregarded during scheme arbitration.
* Contains information that specifically addresses the issuer or payment method comments included in the pre-arbitration request.

During scheme arbitration, the scheme rules on the chargeback liability based on the information provided throughout chargeback defense timelines. If the scheme rules in favor of the issuer, you can incur a fee of up to USD 600. This fee is added to the second chargeback. The scheme arbitration process can take several months to complete.

## See also

* [Dispute flow](https://docs.adyen.com/risk-management/understanding-disputes/dispute-process-and-flow/)
* [Dispute reason codes and defense requirements](https://docs.adyen.com/risk-management/understanding-disputes/dispute-reason-codes/)
* [Dispute timeframes](https://docs.adyen.com/risk-management/understanding-disputes/dispute-timeframes)
