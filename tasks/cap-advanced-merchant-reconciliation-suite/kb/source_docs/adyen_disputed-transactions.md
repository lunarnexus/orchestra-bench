---
title: "Disputed transactions"
description: "Find details of disputed transactions."
url: "https://docs.adyen.com/reporting/disputed-transactions"
source_url: "https://docs.adyen.com/reporting/disputed-transactions.md"
canonical: "https://docs.adyen.com/reporting/disputed-transactions"
last_modified: "2026-09-30T12:57:17+02:00"
language: "en"
---

# Disputed transactions

Find details of disputed transactions.

##### Time zones

This report is based on the time zone setting of your account.

The Dispute transaction details report includes details of your [disputes](https://docs.adyen.com/risk-management/understanding-disputes) that can help you [manage them](https://docs.adyen.com/risk-management/manage-disputes). The date in the report's file name corresponds with the date on which the included disputes were recorded. For example, the Dispute transaction details report for disputes recorded on 2018-09-01 is `dispute_report_2018_09_01.csv`.

## Sample

[Download a sample Dispute transaction details report](https://docs.adyen.com/reporting/disputed-transactions/SAMPLE_dispute_report_2018_09_01.csv) for examples of the included data.

Based on your account and settings, a report you generate in your account can contain additional data or columns that are not included in the sample report.

## Structure

### Entries

Under the header line, each line in the report is a separate entry.

### Columns

Each column shows specific information about the entries. By default, the report includes [standard columns](https://docs.adyen.com/reporting/disputed-transactions#standard-columns). You can optionally add [additional columns](https://docs.adyen.com/reporting/disputed-transactions#additional-columns).

#### Standard columns

| #  | Column                             | Data type                               | Description                                                                                                                                                                                                                                                                        |
| -- | ---------------------------------- | --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1  | Company Account                    | Unicode Text (80-character)             | Name of your company account as registered in the Adyen payments platform.                                                                                                                                                                                                         |
| 2  | Merchant Account                   | Unicode Text (80-character)             | Name of your merchant account used to process the original payment request.                                                                                                                                                                                                        |
| 3  | Psp Reference                      | Unicode Text (16-character limit)       | Adyen's unique 16 character reference for the payment. This is the PSP reference for the original authorisation request.                                                                                                                                                           |
| 4  | Merchant Reference                 | Unicode Text (80-character)             | Reference number provided when initiating the payment request.                                                                                                                                                                                                                     |
| 5  | Payment Method                     | Unicode Text (30-character)             | Payment method type of the payment which was processed. For example: *visa*, *mc*, *amex*.                                                                                                                                                                                         |
| 6  | Record Date                        | Date field + Time field                 | Timestamp of when the dispute event took place as entered into Adyen's accounting system. Format: `YYYY-MM-DD HH:MM:SS` For example: *2012-07-26 19:58:55*.                                                                                                                        |
| 7  | Record Date TimeZone               | Alpha Text (4-character limit)          | Time zone of the **Record Date**. This is the ISO code for your [time zone setting](https://docs.adyen.com/reporting/time-zone-setting).                                                                                                                                            |
| 8  | Dispute Currency                   | Alpha Text (3-character limit)          | Disputes do not have to be in the original transaction currency, but can be in the currency of the cardholder. Also disputes can be of a lower value than the original transaction. This is the three character ISO code for the dispute amount currency.                          |
| 9  | Dispute Amount                     | Text field Numeric (16-Character limit) | The amount of the disputed payment. For example, 100.00.                                                                                                                                                                                                                           |
| 10 | Record Type                        | Unicode Text (50-character)             | Dispute accounting record type, for example:- RequestForInformation
- NotificationOfChargeback
- Chargeback
- SecondChargeback
- InformationSupplied
- ChargebackReversed
- NotificationOfFraud
- AcquirerPreArbitrationUploaded
- PreArbitrationWon
- PreArbitrationLost          |
| 11 | Dispute PSP Reference              | Unicode Text (16-character limit)       | Adyen's unique 16 character reference for the dispute.                                                                                                                                                                                                                             |
| 12 | Dispute Reason                     | Unicode Text (256-character)            | Dispute reason (free format) provided by the bank or payment method.                                                                                                                                                                                                               |
| 13 | RFI Scheme Code                    | Unicode Text (30-character)             | Payment method scheme/institution which issued the code in the following column. For example: *visa*, *mc*, *amex*.                                                                                                                                                                |
| 14 | RFI Reason Code                    | Unicode Text (30-character)             | Request for Information reason code as provided by the bank or payment method. The mapping is defined by the scheme/institution. This is blank if no RFI was issued.                                                                                                               |
| 15 | CB Scheme Code                     | Unicode Text (30-character)             | Payment method scheme/institution which issued the code in the following column. For example: *visa*, *mc*, *amex*.                                                                                                                                                                |
| 16 | CB Reason Code                     | Unicode Text (30-character)             | Chargeback reason code as provided by the bank or payment method. The mapping is defined by the scheme/institution. This may be blank if there is not formal coding for reasons (for example some direct debits), in which case the **Dispute Reason** column should be consulted. |
| 17 | NoF Scheme Code                    | Unicode Text (30-character)             | Payment method scheme/institution which issued the Notification of Fraud (NoF) code in the **NoF Reason Code** column. For example: *visa*, *mc*, *amex*.                                                                                                                          |
| 18 | NoF Reason Code                    | Unicode Text (30-character)             | Notification of Fraud reason code as provided by the bank or payment method. The mapping is defined by the scheme/institution.                                                                                                                                                     |
| 19 | Payment Date                       | Date field + Time field                 | Date of the original payment (authorisation).                                                                                                                                                                                                                                      |
| 20 | Payment Date TimeZone              | Alpha Text (4-character limit)          | Time zone of the **Payment Date**. This is the ISO code for your [time zone setting](https://docs.adyen.com/reporting/time-zone-setting).                                                                                                                                           |
| 21 | Payment Currency                   | Alpha Text (3-character limit)          | Three character ISO code for the currency which was used for processing the payment. This may differ from the dispute currency in rare cases.                                                                                                                                      |
| 22 | Payment Amount                     | Fixed point number                      | Authorisation amount of the original payment.                                                                                                                                                                                                                                      |
| 23 | Dispute Date                       | Date field + Time field                 | Date the dispute was first entered into the system. This can be the same date as the RFI.                                                                                                                                                                                          |
| 24 | Dispute Date TimeZone              | Alpha Text (4-character limit)          | Time zone of the **Dispute Date**. This is the ISO code for your [time zone setting](https://docs.adyen.com/reporting/time-zone-setting).                                                                                                                                           |
| 25 | Dispute ARN                        | Unicode Text (50-character)             | Acquirer Reference Number, a unique number that tags a dispute when it goes from your bank account (The Acquiring Bank).                                                                                                                                                           |
| 26 | User Name                          | Unicode Text (80-character)             | User (interactive or webservice user) who performed the action resulting in the accounting record. If the record was created by an automated internal process the value `system` is used.                                                                                          |
| 27 | Risk Scoring                       | Integer                                 | Total risk scoring value of the original payment.                                                                                                                                                                                                                                  |
| 28 | Shopper Interaction                | Alpha Text (30-character limit)         | Transaction type. Possible values: *Ecommerce*, *ContAuth*, *POS*, *Moto*.                                                                                                                                                                                                         |
| 29 | Shopper Name                       | Unicode Text (80-character)             | Name of the cardholder as provided during the original transaction (if available).                                                                                                                                                                                                 |
| 30 | Shopper Email                      | Unicode Text (256-character)            | Email address of the shopper/consumer as provided during the original transaction (if available).                                                                                                                                                                                  |
| 31 | Shopper Reference                  | Unicode Text (256-character)            | Supplied customer ID/reference as supplied in the original transaction.                                                                                                                                                                                                            |
| 32 | Shopper PAN                        | Alphanumeric text (80-character)        | Account number of the shopper/consumer. In case of card payments, the last four digits of the card number.                                                                                                                                                                         |
| 33 | IBAN                               | Alphanumeric text (80-character)        | Shopper's bank account IBAN number.                                                                                                                                                                                                                                                |
| 34 | BIC                                | Alphanumeric text (80-character)        | Shopper's bank account BIC number.                                                                                                                                                                                                                                                 |
| 35 | Shopper IP                         | Unicode Text (50-character)             | IP address (IPV4 or IPV6) of the shopper/consumer as provided during the original transaction (if available)                                                                                                                                                                       |
| 36 | Shopper Country                    | Alpha Text (2-character limit)          | ISO country code of the shopper (if available).                                                                                                                                                                                                                                    |
| 37 | Issuer Country                     | Alpha Text (2-character limit)          | ISO country code of the issuer (if available).                                                                                                                                                                                                                                     |
| 38 | Issuer ID                          | Alphanumeric text (30-character limit)  | Unique identifier of the issuer. In case of card payments this will be the issuer BIN (first 6 digits of the card number).                                                                                                                                                         |
| 39 | 3D Directory Response              | Alpha Text (1-character limit)          | Payments which were processed using 3D Secure (Secure Code / Verified by Visa), the directory response. Possible values: *Y*, *N*, *U*, *E*.                                                                                                                                       |
| 40 | 3D Authentication Response         | Alpha Text (1-character limit)          | Payments which were processed using 3D Secure (Secure Code / Verified by Visa) and had directory response 'Y', the authentication response. Possible values: *Y*, *N*, *U*, *A*, *E*.                                                                                              |
| 41 | CVC2 Response                      | Text field Numeric (1-character limit)  | Result passed back by the issuer after verifying the CVC2 (or CVV2/CID in case of Visa/Amex).                                                                                                                                                                                      |
| 42 | AVS Response                       | Text field Numeric (2-character limit)  | Result of the AVS check, if performed.                                                                                                                                                                                                                                             |
| 43 | Auto Defense Dispute Auto Defended | Alpha Text (4-character limit)          | Set to `true`, if chargeback was auto-defended by Adyen. Empty if it was not.                                                                                                                                                                                                      |
| 44 | Dispute End Date                   | Date field + Time field                 | Date and time of day when dispute defense period ended.                                                                                                                                                                                                                            |
| 45 | Dispute End Date TimeZone          | Alpha Text (4-character limit)          | Time zone of the **Dispute End Date**. This is the ISO code for your [time zone setting](https://docs.adyen.com/reporting/time-zone-setting).                                                                                                                                       |
| 46 | Reserved 4                         | String                                  | Reserved for future enhancements.                                                                                                                                                                                                                                                  |
| 47 | Reserved 5                         | String                                  | Reserved for future enhancements.                                                                                                                                                                                                                                                  |

#### Additional columns

You can [configure report columns](https://docs.adyen.com/reporting/disputed-transactions#configure-report-columns) to add these to your report:

| Column                | Data type | Description                                                                                                                                                                     |
| --------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Acquirer              | String    | Name of the Acquirer that processed the original payment.                                                                                                                       |
| Acquirer Account      | String    | The Acquirer account that was used for the transaction.                                                                                                                         |
| Issuer Region Program | String    | The issuer region in which the transaction was made.                                                                                                                            |
| Liability Shift       | Boolean   | Indicates if there was a liability shift for the transaction.                                                                                                                   |
| Metadata              | String    | Contents from the [metadata](https://docs.adyen.com/api-explorer/Checkout/latest/post/payments#request-metadata) object related to the payment, in the form of key value pairs. |
| Data Ed               | String    | Contents from the `Data Ed` object related to the dispute.                                                                                                                      |
| RDR                   | Boolean   | Indicates Rapid Dispute Resolution (RDR) chargebacks (Visa only).                                                                                                               |
| Second Chargeback     | Boolean   | Indicator that marks if a second chargeback is present.                                                                                                                         |
| Shopper Phone Number  | String    | Phone number of the shopper or consumer as provided during the original transaction (if available).                                                                             |
| Shopper Statement     | String    | The shopper statement (descriptor) posted in the payment request.                                                                                                               |
| Status                | String    | The most recent chargeback status.                                                                                                                                              |

## Configure report columns

If you want to add additional columns or change the order of columns in a report, you can do so in the [Customer Area](https://ca-test.adyen.com/). If you have an automated system that uses the report's data, configuring the report columns can affect your automated system.

To configure report columns, you need to have one of the following [user roles](https://docs.adyen.com/account/user-roles):

* Merchant admin
* Merchant report role
* Merchant financial
* Merchant POS Report role

To configure report columns:

1. Log in to your [Customer Area](https://ca-test.adyen.com/).
2. Go to **Settings** > **Report columns**.\
   This opens a page with all the reports that you can configure.
3. Find the report that you want to configure and select **Configure**.
4. Select checkboxes to indicate which columns you want to include in the report.
5. Drag the columns into the order you want them to appear in.
6. Select **Save configuration**.

## See also

* [Understanding disputes](https://docs.adyen.com/risk-management/understanding-disputes)
* [Manage disputes](https://docs.adyen.com/risk-management/manage-disputes)
