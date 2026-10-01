# Reporting categories and types

Understand the categories on BalanceTransaction objects and their distinctions.

Learn more about the `reporting_category` field on `BalanceTransaction` objects, and how it differs from `type` and other categorizations.

## The reporting category field 

The `BalanceTransaction` object’s `reporting_category` field improves the `type` field by providing a more useful grouping for most finance and reporting purposes. The following sections describe the  advantages of the `reporting-category` field.

##### A More detailed breakdown of type=adjustment

The `reporting_category` attribute separates balance transactions with `type=adjustment` into several different categories, including disputes, dispute reversals, and failed refunds. Additionally, it cateogrizes several types of fees and *Connect* (Connect is Stripe's solution for multi-party businesses, such as marketplace or software platforms, to route payments between sellers, customers, and other recipients) platform fee refunds with `reporting_category=fee`.

#### A separate category for partial-capture reversals

If you’re [separately authorizing and capturing](https://docs.stripe.com/payments/place-a-hold-on-a-payment-method.md) payments, and you capture an amount less than the initial authorization, you see two balance transactions: one for the full amount of the authorization, and another reversing the uncaptured portion. (Summing the two balance transactions yields the captured portion of the charge.)

The balance transaction reversing the uncaptured portion has `type=refund`, just as if you had refunded a portion of a sale at some later time. To allow separate handling of these objects (perhaps counting them against the initial sale amount, rather than as a separate refund) we label these with the distinct reporting category `partial_capture_reversal`.

#### Consolidate multiple types into common categories

Using the `type` field, balance transactions arising from card-based charges are represented with `type=charge`, while those made with [other payment methods](https://docs.stripe.com/payments/payment-methods/overview.md) are represented with `type=payment`. Similarly, refunds and failures for cards versus alternative payment methods have the distinct types `refund` and `payment_refund`.

The `reporting_category` attribute simplifies these (and other) groups of types, as follows:

| Balance transaction types | Reporting category |
| --- | --- |
| `charge`, `payment` | `charge` |
| `refund`, `payment_refund` | `refund` |
| `payout_cancel`, `payout_failure` | `payout_reversal` |
| `transfer`, `recipient_transfer` | `transfer` |
| `transfer_cancel`, `transfer_failure`, `recipient_transfer_cancel`, `recipient_transfer_failure` | `transfer_reversal` |

##### More descriptive category names

We renamed several balance transaction types for greater clarity:

| Balance transaction type | Reporting category |
| --- | --- |
| `application_fee` | `platform_earning` |
| `application_fee_refund` | `platform_earning_refund` |
| `stripe_fee` | `fee` |
| `reserve_transaction` | `connect_reserved_funds` |
| `reserved_funds` | `risk_reserved_funds` |

## Reporting categories reference 

This reference covers the following groups of reporting categories:
