---
title: "Dispute webhooks"
description: "Learn about dispute events that trigger a webhook message."
url: "https://docs.adyen.com/risk-management/disputes-api/dispute-notifications"
source_url: "https://docs.adyen.com/risk-management/disputes-api/dispute-notifications.md"
canonical: "https://docs.adyen.com/risk-management/disputes-api/dispute-notifications"
last_modified: "2020-10-30T11:38:00+01:00"
language: "en"
---

# Dispute webhooks

Learn about dispute events that trigger a webhook message.

Adyen sends you a webhook message when a payment is disputed. You can use these webhook messages to alert staff of (pending) chargebacks, so that they can take appropriate action.

A dispute webhook message contains:

* `eventCode`: Indicates an event type in the dispute process.
* `pspReference`: The PSP reference of the dispute. All events related to a dispute have the same PSP reference.
* `originalReference`: The PSP reference of the disputed payment.

Most webhook messages also contain a dispute status in the `additionalData` object. The `disputeStatus` field gives more information about the [status of the dispute](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#dispute-events) at the time of the event. For example, if the dispute was won, lost, has expired or is pending.

The `disputeStatus` is not returned in webhook messages for disputed payments processed in Brazil.

## Requirements

Before you begin, take into account the following requirements and limitations.

| Requirement                                                               | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Integration type**                                                      | Make sure that you have built an [online payments integration](https://docs.adyen.com/online-payments/build-your-integration/).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| **[Customer Area roles](https://docs.adyen.com/account/user-roles/#risk)** | To manage webhooks in the Customer Area, make sure that you have one of the following roles:- **Merchant admin**
- **Merchant technical integrator**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **[Webhooks](https://docs.adyen.com/development-resources/webhooks)**      | Follow the steps on this page to subscribe to the **Standard webhook** and [enable](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#dispute-webhooks-enable) dispute events. For some dispute event types, [additional configuration](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#dispute-webhooks-enable) is required.                                                                                                                                                                                                                                                                                                                         |
| **Limitations**                                                           | The `disputeStatus` is not returned in webhook messages for disputed payments processed in Brazil.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **Setup steps**                                                           | You can manage disputes using the [Disputes API](https://docs.adyen.com/risk-management/disputes-api/) or the [Customer Area](https://docs.adyen.com/risk-management/manage-disputes/). For either flow, we recommend that you:- Understand the general [dispute flow](https://docs.adyen.com/risk-management/understanding-disputes/dispute-process-and-flow/).
- Review the [chargeback guidelines](https://docs.adyen.com/risk-management/chargeback-guidelines) for specific card schemes and other payment methods that you use.
- Know the scenarios when Adyen [automatically handles disputes](https://docs.adyen.com/risk-management/manage-disputes#adyen-auto-defense-disputes) on your behalf. |

## Dispute events

The following tables show an overview of the dispute event types, what they mean, and where applicable, the possible values for the dispute status:

| Webhook `eventCode`                                                                                                                                    | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | Possible `disputeStatus` values                                                                                                                   |
| ------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| **[NOTIFICATION\_OF\_FRAUD](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#notification_of_fraud)**                          | The alert passed on by issuers to schemes and subsequently to processors. Visa calls them TC40 and Mastercard calls them System to Avoid Fraud Effectively (SAFE). These are informational webhooks offered at no charge by Adyen, letting you take action, such as blocking a shopper or issuing a refund before a chargeback is incurred.                                                                                                                                                                                                                                  | Not applicable                                                                                                                                    |
| **[REQUEST\_FOR\_INFORMATION](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#request_for_information)**                      | Information requested for this payment.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | * Unresponded
* Responded
* Expired                                                                                                               |
| **[NOTIFICATION\_OF\_CHARGEBACK](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#notification_of_chargeback)**                | Adyen has received a notification from the scheme that a chargeback is incoming on a payment. This webhook informs you of that event. This is your starting point for the defense, and marks the start of the defense period. Use the [Disputes API](https://docs.adyen.com/risk-management/disputes-api) or the Customer Area to evaluate the chargeback. You can now start your defense, you do not have to wait for the **CHARGEBACK** webhook.                                                                                                                            | - Undefended
- Pending                                                                                                                            |
| **[INFORMATION\_SUPPLIED](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#information_supplied)**                             | You have successfully uploaded your dispute defense documents, or Adyen has auto-defended the dispute.                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | * Responded
* Pending                                                                                                                             |
| **[CHARGEBACK](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#chargeback)**                                                  | A payment was charged back.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | - Undefended
- Pending
- Lost
- Accepted                                                                                                          |
| **[SECOND\_CHARGEBACK](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#second_chargeback)**                                   | The issuing bank declines the material submitted during defense of the original chargeback.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | * Lost                                                                                                                                            |
| **[CHARGEBACK\_REVERSED](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#chargeback_reversed)**                               | A chargeback has been defended towards the issuing bank, and the disputed amount was transferred back to your account. The dispute status will be `Pending` while the issuing bank reviews the material. This stage is not final and a "second" chargeback can be presented by the issuing bank, resulting in losing the chargeback case. Only for the [Visa allocation](https://docs.adyen.com/risk-management/chargeback-guidelines/visa-chargebacks/#visa-allocation-flow) flow, the final status can be `Won` if the issuing bank accepts the defense in pre-arbitration. | - Pending
- Won ([Visa allocation flow only](https://docs.adyen.com/risk-management/chargeback-guidelines/visa-chargebacks/#visa-allocation-flow)) |
| **[PREARBITRATION\_WON](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#prearbitration_won)**                                 | The pre-arbitration case that was initiated has been accepted by the cardholder's bank. This event code is only used for disputes that can include pre-arbitration, such as the [Visa allocation](https://docs.adyen.com/risk-management/chargeback-guidelines/visa-chargebacks#pre-arbitration-allocation) flow or the [UnionPay](https://docs.adyen.com/risk-management/chargeback-guidelines/unionpay-chargebacks#pre-arbitration-allocation) flow.                                                                                                                         | * Won                                                                                                                                             |
| **[PREARBITRATION\_LOST](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#prearbitration_lost)**                               | The pre-arbitration case that was initiated has been declined by the cardholder's bank. This event code is only used for disputes that can include pre-arbitration, such as the [Visa allocation](https://docs.adyen.com/risk-management/chargeback-guidelines/visa-chargebacks#pre-arbitration-allocation) flow or the [UnionPay](https://docs.adyen.com/risk-management/chargeback-guidelines/unionpay-chargebacks#pre-arbitration-allocation) flow.                                                                                                                         | - Lost                                                                                                                                            |
| **[PREARBITRATION\_OPEN](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#prearbitration-open)**                               | The issuer has declined your defense and has opened a pre-arbitration case. When you are eligible, and the dispute flow supports it, you can accept or decline the pre-arbitration case yourself. This requires additional configuration and approval from Adyen. Reach out to our [Support Team](https://ca-test.adyen.com/ca/ca/contactUs/support.shtml?form=other) or your Adyen contact for more details.                                                                                                                                                                | * Undefended                                                                                                                                      |
| **[PREARBITRATION\_ACCEPTED](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#prearbitration-accepted)**                       | You (partially) accept the pre-arbitration case that was opened by the issuer.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | - Pending                                                                                                                                         |
| **[PREARBITRATION\_DECLINED](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#prearbitration-declined)**                       | You decline the pre-arbitration case that was opened by the issuer.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | * Pending                                                                                                                                         |
| **[PREARBITRATION\_ISSUER\_WITHDRAWN](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#prearbitration-withdrawn)**             | The pre-arbitration case was withdrawn by the issuer.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | - Pending
- Won                                                                                                                                   |
| **[SCHEME\_ARBITRATION](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#scheme-arbitration)**                                 | The issuer escalates the pre-arbitration case that you declined.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | * Pending                                                                                                                                         |
| **[SCHEME\_ARBITRATION\_WON](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#scheme-arbitration-won)**                        | The scheme has ruled in your favor.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | - Won                                                                                                                                             |
| **[SCHEME\_ARBITRATION\_LOST](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#scheme-arbitration-lost)**                      | The scheme has ruled in favor of the issuer.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | * Lost                                                                                                                                            |
| **[DISPUTE\_DEFENSE\_PERIOD\_ENDED](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#defense_ended)**                          | You have not defended the dispute within the timeframe, or the defense period ended because you accepted liability for the chargeback and will not defend the dispute.                                                                                                                                                                                                                                                                                                                                                                                                       | - Undefended
- Lost
- Accepted                                                                                                                    |
| **[ISSUER\_RESPONSE\_TIMEFRAME\_EXPIRED](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#issuer_response_timeframe_expired)** | The issuer either accepted your defense of the dispute, or did not respond in time.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | * Won                                                                                                                                             |
| **[ISSUER\_COMMENTS](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications#issuer_comments)**                                       | Includes any free-text [issuer comments](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications/issuer-comments) that include relevant information about the dispute process, such as why the issuer decided to initiate or continue the dispute. You can receive issuer comments for chargebacks and pre-arbitration cases.                                                                                                                                                                                                                               | Not applicable                                                                                                                                    |

## Enable webhooks

Make sure that you set up a [Standard webhook](https://docs.adyen.com/development-resources/webhooks/webhook-types#standard-webhooks), and that you select all [dispute events](https://docs.adyen.com/development-resources/webhooks/webhook-types#dispute-events). For details on how to configure and manage webhooks, refer to [Webhooks](https://docs.adyen.com/development-resources/webhooks).

A dispute webhook message can contain two PSP references:

* `pspReference`: The PSP reference of the dispute. All events related to a dispute have the same PSP reference.
* `originalReference`: The PSP reference of the disputed payment.

To return the PSP reference of the payment in the `originalReference` field, and the PSP reference of the dispute in the `pspReference` for the event types **CHARGEBACK\_REVERSED**, **SECOND\_CHARGEBACK**, **PREARBITRATION\_WON** and **PREARBITRATION\_LOST**, follow these steps:

1. Log in to your [Customer Area](https://ca-test.adyen.com/)
2. Go to **Developers** > **Webhooks**.
3. Next to **Standard webhook** select the edit webhook icon **.
4. Under **Additional Settings** > **Risk** select the edit icon **.
5. Enable **Include the originalReference for CHARGEBACK\_REVERSED events**, and then select **Apply**.
6. Select **Save changes**.

## NOTIFICATION\_OF\_FRAUD

For possible values for the `reason` and `nofReasonCode`  fields, refer to [Dispute reason codes](https://docs.adyen.com/risk-management/understanding-disputes/dispute-reason-codes?tab=notification_of_fraud_3).

```json
{
   "live":"true",
   "notificationItems":[
      {
         "NotificationRequestItem":{
            "additionalData":{
               "modificationMerchantReferences":"",
               "nofReasonCode":"6",
               "paymentMethodVariant":"mcsuperpremiumcredit",
               "nofSchemeCode":"mc",
            },
            "amount":{
               "currency":"USD",
               "value":10089
            },
            "eventCode":"NOTIFICATION_OF_FRAUD",
            "eventDate":"2020-07-19T04:01:13+02:00",
            "merchantAccountCode":"YOUR_MERCHANT_ACCOUNT",
            "merchantReference":"YOUR_REFERENCE",
            "originalReference":"9913333333333333",
            "paymentMethod":"mc",
            "pspReference":"9915555555555555",
            "reason":"Card Not Present Fraud",
            "success":"true"
         }
      }
   ]
}
```

## REQUEST\_FOR\_INFORMATION

For possible values for the `reason` and `rfiReasonCode`  fields, refer to [Dispute reason codes](https://docs.adyen.com/risk-management/understanding-disputes/dispute-reason-codes?tab=request_for_information_2).

```json
{
   "live":"true",
   "notificationItems":[
      {
         "NotificationRequestItem":{
            "additionalData":{
                "rfiSchemeCode":"visa",
                "modificationMerchantReferences":"",
                "rfiReasonCode":"28",
                "defensePeriodEndsAt":"2021-05-06T22:09:50+02:00",
                "disputeStatus" : "Unresponded"
            },
             "amount":{
               "currency":"USD",
               "value":1000
            },
            "eventCode":"REQUEST_FOR_INFORMATION",
            "eventDate":"2021-04-18T22:09:50+01:00",
            "merchantAccountCode":"YOUR_MERCHANT_ACCOUNT",
            "merchantReference":"YOUR_REFERENCE",
            "originalReference":"9913333333333333",
            "paymentMethod":"visa",
            "pspReference":"9915555555555555",
            "reason":"Request for copy bearing signature",
            "success":"true"
         }
      }
   ]
}
```

## NOTIFICATION\_OF\_CHARGEBACK

For a list of all values for `reason` and `chargebackReasonCode`  fields, refer to [Dispute reason codes](https://docs.adyen.com/risk-management/understanding-disputes/dispute-reason-codes?tab=chargeback_1).

```json
{
   "live":"true",
   "notificationItems":[
      {
         "NotificationRequestItem":{
            "additionalData":{
               "chargebackReasonCode":"10.4",
               "modificationMerchantReferences":"",
               "chargebackSchemeCode":"visa",
               "defensePeriodEndsAt":"2021-05-24T16:05:30+03:00",
               "autoDefended":"false",
               "defendable":"true",
               "disputeStatus":"Undefended"
            },
            "amount":{
               "currency":"EUR",
               "value":1000
            },
            "eventCode":"NOTIFICATION_OF_CHARGEBACK",
            "eventDate":"2021-05-06T16:05:30+03:00",
            "merchantAccountCode":"YOUR_MERCHANT_ACCOUNT",
            "merchantReference":"YOUR_REFERENCE",
            "originalReference":"9913333333333333",
            "paymentMethod":"visa",
            "pspReference":"9915555555555555",
            "reason":"Other Fraud-Card Absent Environment",
            "success":"true"
         }
      }
   ]
}
```

## INFORMATION\_SUPPLIED

For a list of all values for `reason` and `chargebackReasonCode`  fields, refer to [Dispute reason codes](https://docs.adyen.com/risk-management/understanding-disputes/dispute-reason-codes?tab=chargeback_1).

```json
{
   "live" : "true",
   "notificationItems" : [
      {
         "NotificationRequestItem" : {
            "additionalData" : {
               "chargebackReasonCode" : "13.3",
               "chargebackSchemeCode" : "visa",
               "disputeStatus" : "Pending"
            },
            "amount" : {
               "currency" : "USD",
               "value" : 10000
            },
            "eventCode" : "INFORMATION_SUPPLIED",
            "eventDate" : "2021-05-17T09:35:14+02:00",
            "merchantAccountCode" : "YOUR_MERCHANT_ACCOUNT",
            "originalReference" : "9914444444444444",
            "merchantReference" : "YOUR_REFERENCE",
            "paymentMethod" : "visa",
            "pspReference" : "9915555555555555",
            "reason" : "Not as Described or Defective Merchandise/Services",
            "success" : "true"
         }
      }
   ]
}
```

## CHARGEBACK

For a list of all values for `reason` and `chargebackReasonCode`  fields, refer to [Dispute reason codes](https://docs.adyen.com/risk-management/understanding-disputes/dispute-reason-codes?tab=chargeback_1).

```json
{
   "live":"true",
   "notificationItems":[
      {
         "NotificationRequestItem":{
            "additionalData":{
               "chargebackReasonCode":"10.4",
               "modificationMerchantReferences":"",
               "chargebackSchemeCode":"visa",
               "defensePeriodEndsAt":"2021-05-24T22:09:50+02:00",
               "defendable" : "true",
               "disputeStatus" : "Undefended"
            },
            "amount":{
               "currency":"EUR",
               "value":1000
            },
            "eventCode":"CHARGEBACK",
            "eventDate":"2021-05-06T22:09:50+02:00",
            "merchantAccountCode":"YOUR_MERCHANT_ACCOUNT",
            "merchantReference":"YOUR_REFERENCE",
            "originalReference":"9913333333333333",
            "paymentMethod":"visa",
            "pspReference":"9915555555555555",
            "reason":"Other Fraud-Card Absent Environment",
            "success":"true"
         }
      }
   ]
} 
```

## SECOND\_CHARGEBACK

For a list of all values for `reason` and `chargebackReasonCode`  fields, refer to [Dispute reason codes](https://docs.adyen.com/risk-management/understanding-disputes/dispute-reason-codes?tab=chargeback_1).

To return the `originalReference` in the **SECOND\_CHARGEBACK** webhook:

1. Log in to your [Customer Area](https://ca-test.adyen.com/)
2. Go to **Developers** > **Webhooks**.
3. Next to **Standard webhook** select the edit webhook icon **.
4. Under **Additional Settings** > **Risk** select the edit icon **.
5. Enable **Include the originalReference for CHARGEBACK\_REVERSED events**, and then select **Apply**.
6. Select **Save changes**.
   ```json
   {
   "live" : "true",
   "notificationItems" : [
     {
        "NotificationRequestItem" : {
           "additionalData" : {
              "chargebackReasonCode" : "13.1",
              "modificationMerchantReferences" : "",
              "chargebackSchemeCode" : "visa",
              "disputeStatus" : "Lost"
           },
           "amount" : {
              "currency" : "GBP",
              "value" : 10000
           },
           "eventCode" : "SECOND_CHARGEBACK",
           "eventDate" : "2020-03-13T11:35:42+01:00",
           "merchantAccountCode" : "YOUR_MERCHANT_ACCOUNT",
           "merchantReference" : "YOUR_REFERENCE",
           "originalReference":"9913333333333333",
           "paymentMethod" : "visa",
           "pspReference" : "9915555555555555",
           "reason" : "Merchandise/Services Not Received",
           "success" : "true"
        }
     }
   ]
   }
   ```

## CHARGEBACK\_REVERSED

To return the `originalReference` in the **CHARGEBACK\_REVERSED** webhook:

1. Log in to your [Customer Area](https://ca-test.adyen.com/)
2. Go to **Developers** > **Webhooks**.
3. Next to **Standard webhook** select the edit webhook icon **.
4. Under **Additional Settings** > **Risk** select the edit icon **.
5. Enable **Include the originalReference for CHARGEBACK\_REVERSED events**, and then select **Apply**.
6. Select **Save changes**.

```json
{
   "live":"true",
   "notificationItems":[
      {
         "NotificationRequestItem":{
            "additionalData" : {
                "disputeStatus" : "Pending"
            },
            "amount":{
               "currency":"EUR",
               "value":1000
            },
            "eventCode":"CHARGEBACK_REVERSED",
            "eventDate":"2020-03-23T13:55:31+01:00",
            "merchantAccountCode":"YOUR_MERCHANT_ACCOUNT",
            "merchantReference":"YOUR_REFERENCE",
            "originalReference":"9913333333333333",
            "paymentMethod":"mc",
            "pspReference":"9915555555555555",
            "reason":"No Cardholder Authorization",
            "success":"true"
         }
      }
   ]
}
```

## PREARBITRATION\_WON

To return the `originalReference` in the **PREARBITRATION\_WON** webhook:

1. Log in to your [Customer Area](https://ca-test.adyen.com/)
2. Go to **Developers** > **Webhooks**.
3. Next to **Standard webhook** select the edit webhook icon **.
4. Under **Additional Settings** > **Risk** select the edit icon **.
5. Enable **Include the originalReference for CHARGEBACK\_REVERSED events**, and then select **Apply**.
6. Select **Save changes**.

```json
{
   "live":"true",
   "notificationItems":[
      {
         "NotificationRequestItem":{
            "additionalData" : {
               "disputeStatus" : "Won"
            },
            "amount":{
               "currency":"EUR",
               "value":1000
            },
            "eventCode":"PREARBITRATION_WON",
            "eventDate":"2020-03-23T13:55:31+01:00",
            "merchantAccountCode":"YOUR_MERCHANT_ACCOUNT",
            "merchantReference":"YOUR_REFERENCE",
            "originalReference":"9913333333333333",
            "paymentMethod":"visa",
            "pspReference":"9915555555555555",
            "reason":"Other Fraud-Card Absent Environment",
            "success":"true"
         }
      }
   ]
}
```

## PREARBITRATION\_LOST

To return the `originalReference` in the **PREARBITRATION\_LOST** webhook:

1. Log in to your [Customer Area](https://ca-test.adyen.com/)
2. Go to **Developers** > **Webhooks**.
3. Next to **Standard webhook** select the edit webhook icon **.
4. Under **Additional Settings** > **Risk** select the edit icon **.
5. Enable **Include the originalReference for CHARGEBACK\_REVERSED events**, and then select **Apply**.
6. Select **Save changes**.

```json
{
   "live":"true",
   "notificationItems":[
      {
         "NotificationRequestItem":{
            "additionalData" : {
              "disputeStatus" : "Lost"
            },
            "amount":{
               "currency":"EUR",
               "value":1000
            },
            "eventCode":"PREARBITRATION_LOST",
            "eventDate":"2020-03-23T13:55:31+01:00",
            "merchantAccountCode":"YOUR_MERCHANT_ACCOUNT",
            "merchantReference":"YOUR_REFERENCE",
            "originalReference":"9913333333333333",
            "paymentMethod":"visa",
            "pspReference":"9915555555555555",
            "reason":"Other Fraud-Card Absent Environment",
            "success":"true"
         }
      }
   ]
}
```

## PREARBITRATION\_OPEN

Applies only when you handle pre-arbitration cases yourself.

```json
{
   "live" : "true",
   "notificationItems" : [
      {
         "NotificationRequestItem" : {
            "additionalData" : {
                "disputeStatus" : "Undefended"
            },
            "amount" : {
               "currency" : "EUR",
               "value" : 1000
            },
            "eventCode" : "PREARBITRATION_OPEN",
            "eventDate" : "2025-10-01T12:40:39+02:00",
            "merchantAccountCode" : "YOUR_MERCHANT_ACCOUNT",
            "merchantReference" : "YOUR_REFERENCE",
            "paymentMethod" : "visa",
            "pspReference" : "NC6HT9CRT65ZGN82",
            "reason" : "Not as Described or Defective Merchandise/Services",
            "success" : "true"
         }
      }
   ]
}
```

## PREARBITRATION\_ACCEPTED

Applies only when you handle pre-arbitration cases yourself.

```json
{
   "live" : "true",
   "notificationItems" : [
      {
         "NotificationRequestItem" : {
            "additionalData" : {
               "captureMerchantReference" : "YOUR_CAPTURE_REFERENCE",
               "capturePspReference" : "KHQC5N7G84BLNK43",
               "disputeStatus" : "Pending"
            },
            "amount" : {
               "currency" : "USD",
               "value" : 1500
            },
            "eventCode" : "PREARBITRATION_ACCEPTED",
            "eventDate" : "2025-10-01T12:46:09+02:00",
            "merchantAccountCode" : "YOUR_MERCHANT_ACCOUNT",
            "merchantReference" : "YOUR_REFERENCE",
            "originalReference" : "JDD6LKT8MBLZNN84",
            "paymentMethod" : "mc",
            "pspReference" : "MKR8T9CRT65ZGN15",
            "reason" : "No Cardholder Authorisation",
            "success" : "true"
         }
      }
   ]
}
```

## PREARBITRATION\_DECLINED

Applies only when you handle pre-arbitration cases yourself.

```json
{
   "live" : "true",
   "notificationItems" : [
      {
         "NotificationRequestItem" : {
            "additionalData" : {
               "captureMerchantReference" : "YOUR_CAPTURE_REFERENCE",
               "capturePspReference" : "QBQQ9DLNRHHKGK38",
               "disputeStatus" : "Pending"
            },
            "amount" : {
               "currency" : "EUR",
               "value" : 1000
            },
            "eventCode" : "PREARBITRATION_DECLINED",
            "eventDate" : "2025-10-01T12:51:33:56+02:00",
            "merchantAccountCode" : "YOUR_MERCHANT_ACCOUNT",
            "merchantReference" : "YOUR_REFERENCE",
            "originalReference" : "M5N7TQ4TG5PFWR50",
            "paymentMethod" : "visa",
            "pspReference" : "WNS7WQ756L2GWR82",
            "reason" : "Misrepresentation",
            "success" : "true"
         }
      }
   ]
}
```

## PREARBITRATION\_ISSUER\_WITHDRAWN

Applies only when you handle pre-arbitration cases yourself. This webhook message is sent when the issuer has withdrawn the pre-arbitration case.

## SCHEME\_ARBITRATION

Applies only when you handle pre-arbitration cases yourself. This webhook message can be sent before you have made a decision to accept or decline, or after you have declined the pre-arbitration case.

## SCHEME\_ARBITRATION\_WON

Applies only when you handle pre-arbitration cases yourself. The payment scheme has ruled that the issuer is liable for the dispute.

## SCHEME\_ARBITRATION\_LOST

Applies only when you handle pre-arbitration cases yourself. The payment scheme has ruled that you are liable for the dispute.

## DISPUTE\_DEFENSE\_PERIOD\_ENDED

See [Dispute timeframes](https://docs.adyen.com/risk-management/understanding-disputes/dispute-timeframes/) for an overview of the defense periods for different schemes.

```json
{
   "live":"true",
   "notificationItems":[
      {
         "NotificationRequestItem":{
           "additionalData":{
               "chargebackReasonCode":"10.4",
               "modificationMerchantReferences":"",
               "chargebackSchemeCode":"visa",
               "disputeStatus" : "Lost"
            },
            "amount":{
               "currency":"EUR",
               "value":1000
            },
            "eventCode":"DISPUTE_DEFENSE_PERIOD_ENDED",
            "eventDate":"2020-11-11T01:30:57+01:00",
            "merchantAccountCode":"YOUR_MERCHANT_ACCOUNT",
            "merchantReference":"YOUR_REFERENCE",
            "originalReference":"9914444444444444",
            "paymentMethod":"visa",
            "pspReference":"9915555555555555",
            "reason":"Other Fraud-Card Absent Environment",
            "success":"true"
         }
      }
   ]
}
```

## ISSUER\_RESPONSE\_TIMEFRAME\_EXPIRED

```json
{
   "live" : "true",
   "notificationItems" : [
      {
         "NotificationRequestItem" : {
            "additionalData" : {
               "chargebackReasonCode" : "13.1",
               "chargebackSchemeCode" : "visa",
               "modificationMerchantReferences" : "",
               "disputeStatus" : "Won"
            },
            "amount" : {
               "currency" : "USD",
               "value" : 10000
            },
            "eventCode" : "ISSUER_RESPONSE_TIMEFRAME_EXPIRED",
            "eventDate" : "2021-05-19T09:35:14+02:00",
            "merchantAccountCode" : "YOUR_MERCHANT_ACCOUNT",
            "originalReference" : "9914444444444444",
            "merchantReference" : "YOUR_REFERENCE",
            "paymentMethod" : "visa",
            "pspReference" : "9915555555555555",
            "reason" : "Merchandise/Services Not Received",
            "success" : "true"
         }
      }
   ]
}
```

## ISSUER\_COMMENTS

For examples of which issuer comments you can receive, see [issuer comments](https://docs.adyen.com/risk-management/disputes-api/dispute-notifications/issuer-comments).

```json
{
   "live" : "true",
   "notificationItems" : [
      {
         "NotificationRequestItem" : {
            "additionalData" : {
                "chargebackReasonCode" : "13.3",
                "chargebackSchemeCode" : "visa",
                "issuerComments.type": "chargeback",
                "issuerComments.disputeAmountChangeReason": "some_text",
                "issuerComments.cancellationMethod": "some_text",
                "issuerComments.orderDetailsNotAsDescribed": "some_text",
                "issuerComments.explanation": "some_text",
                "issuerComments.damagedOrDefectiveOrderInfo": "some_text",
                "issuerComments.howChAttemptReturnAndDispOfMerchandise": "some_text",
                "issuerComments.whatWasNotReceived": "some_text",
                "issuerComments.cancellationDate": "some_text"
            },
            "amount" : {
               "currency" : "EUR",
               "value" : 1000
            },
            "eventCode" : "ISSUER_COMMENTS",
            "eventDate" : "2021-05-17T09:35:14+02:00",
            "merchantAccountCode" : "YOUR_MERCHANT_ACCOUNT",
            "originalReference" : "9914444444444444",
            "merchantReference" : "YOUR_REFERENCE",
            "paymentMethod" : "visa",
            "pspReference" : "9915555555555555",
            "reason" : "Not as Described or Defective Merchandise/Services",
            "success" : "true"
         }
      }
   ]
}
```

## See also

* [Understanding and defending disputes](https://docs.adyen.com/risk-management/understanding-disputes)
* [Webhooks](https://docs.adyen.com/development-resources/webhooks)
