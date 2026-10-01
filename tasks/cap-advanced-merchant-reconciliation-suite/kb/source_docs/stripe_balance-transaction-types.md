# Balance transaction types

Learn more about the different types of balance transactions that represent funds moving through your Stripe account.

Balance transactions are our recommended starting point for reporting on your account’s balance activity. We create them for every type of transaction that comes into, or flows out of, your Stripe account’s balance.

You can create reports that make use of balance transactions using the [API](https://docs.stripe.com/api/.md) or [Sigma](https://docs.stripe.com/data/query-transactions.md).

When you first receive a payment in your account, we initially reflect it as a `pending` balance (less any Stripe fees). This balance becomes `available` based on the settlement timing of your transactions, which can vary based on your market, payment method, or transaction type. The [status](https://docs.stripe.com/api.md#balance_transaction_object-status) attribute on balance transactions indicates the state of the balance. To learn more, see [Balances and settlement time](https://docs.stripe.com/payments/balances.md).

To classify transactions for [accounting purposes](https://docs.stripe.com/reports/reporting-categories.md), use the `reporting_category` field instead of the `type` field.

## Balance transaction source 

Balance transactions include a [source](https://docs.stripe.com/api.md#balance_transaction_object-source) field that contains the ID of the related Stripe object.

Use the [API](https://docs.stripe.com/api/.md) to retrieve additional information about the payment activity that caused the creation of the Balance transaction. Using [Sigma](https://docs.stripe.com/data/query-transactions.md), you can also join the `balance_transactions` table with other tables using the `source_id` column.

## Balance transaction types 

You can organize balance transaction types into different groups based on the underlying activity that generated the balance transactions.

If you’re not using the Connect API or Issuing API, your balance transactions belong in the first two groups (“related to charges and payments” or “related to Stripe balance changes”).

### Balance transaction types related to charges and payments

These balance transaction types are related to creating and refunding charges as part of processing payments.

- `charge`
  Created when a [credit card charge](https://docs.stripe.com/docs/payments/charges-api.md) is created successfully.

- `payment`
  Created when a [local payment method](https://docs.stripe.com/docs/payments/payment-methods/overview.md) charge is created successfully.

- `payment_failure_refund`
  [ACH, direct debit](https://docs.stripe.com/docs/payments/payment-methods/overview.md), and other [delayed notification payment methods](https://docs.stripe.com/docs/payments/payment-methods.md#payment-notification) remain in a pending state until they either succeed or fail. You’ll see a pending Balance transaction of type `payment` when the payment is created. Another Balance transaction of type `payment_failure_refund` appears if the pending payment later fails.

- `payment_refund`
  Created when a [local payment method](https://docs.stripe.com/docs/payments/payment-methods/overview.md) refund is initiated.

  Additionally, if your customer’s bank or card issuer is unable to correctly process a refund (e.g., due to a closed bank account or a problem with the card) Stripe returns the funds to your balance. The returned funds are represented as a Balance transaction with the type `payment_refund`.

- `payment_reversal`
  Created when a debit/failure related to a payment is detected from a banking partner. This balance transaction takes funds that were previously credited to the merchant for a payment out of the merchant balance.

- `refund`
  Created when a [credit card charge refund](https://docs.stripe.com/docs/refunds.md) is initiated.

  If you [authorize and capture](https://docs.stripe.com/docs/payments/place-a-hold-on-a-payment-method.md) separately and the capture amount is less than the initial authorization, you see a balance transaction of type `charge` for the full authorization amount and another balance transaction of type `refund` for the uncaptured portion.

- `refund_failure`
  Created when a [credit card charge refund](https://docs.stripe.com/docs/refunds.md) fails, and Stripe returns the funds to your balance.

  This may occur if your customer’s bank or card issuer is unable to correctly process a refund (for example, due to a closed bank account or a problem with the card).

### Balance transaction types related to Stripe balance changes

These balance transaction types are related to changes that affect your Stripe balance such as payouts, fees and top-ups.

- `adjustment`
  Adjustments correspond to additions or deductions from your Stripe balance that are made outside of the normal charge/refund flow. For example, some of the most common reasons for adjustments are:

  - **Refund failures**. If your customer’s bank or card issuer is unable to correctly process a refund (e.g., due to a closed bank account or a problem with the card) Stripe returns the funds to your balance. The returned funds are represented as a Balance transaction with the type `adjustment`, where the description indicates the related refund object.
  - **Disputes**. When a customer [disputes a charge](https://docs.stripe.com/docs/disputes.md), Stripe deducts the disputed amount from your balance. The deduction is represented as a Balance transaction with the type `adjustment`, where the source object is a dispute.
  - **Dispute reversals**. When you [win a dispute](https://docs.stripe.com/docs/disputes.md#responding-to-a-dispute), the disputed amount is returned to your balance. The returned funds are represented as a Balance transaction with the type `adjustment`, where the source object is a dispute.
  - In the past, fees for Stripe software and services (e.g., for Radar, Connect and Billing) were represented as adjustments.
  - In the past, Connect platform fee refunds were represented as adjustments.

  The `description` field on the Balance transaction describes the purpose of each adjustment.

- `advance`
  Incrementing funds as part of an advance operation to change the date that funds settle to your balance. For example, this can occur when you create an [instant payout](https://docs.stripe.com/docs/payouts/instant-payouts-with-advance-funding.md) and the requested payout amount is greater than your available balance. Funds are credited to a new `available_on` date and debited from the original `available_on` date to cover the difference.

- `advance_funding`
  Decrementing funds as part of an advance operation to change the date that funds settle to your balance. For example, this can occur when you create an [instant payout](https://docs.stripe.com/docs/payouts/instant-payouts-with-advance-funding.md) and the requested payout amount is greater than your available balance. Funds are credited to a new `available_on` date and debited from the original `available_on` date to cover the difference.

- `anticipation_repayment`
  Repayments made to service an anticipation loan in Brazil. These repayments go to the financial institution to whom you have sold your receivables.

- `balance_transfer_inbound`
  Funds moving into a balance (e.g. Issuing balance) from another balance (e.g. Stripe balance)

- `balance_transfer_outbound`
  Funds moving from your Stripe balance to a different (e.g. Issuing) balance.

- `climate_order_purchase`
  Funds used to purchase carbon removal units from Frontier Climate.

- `climate_order_refund`
  Funds refunded to your balance when a Climate Order is canceled.

- `contribution`
  Funds contributed via Stripe to a cause (currently Stripe Climate).

- `currency_conversion`
  Created to debit or credit your balance when a currency conversion is initiated.

- `obligation_outbound`
  Obligation for receivable unit received.

- `obligation_reversal_inbound`
  Obligation for receivable unit reversed.

- `payment_network_reserve_hold`
  Funds that a payment network holds in reserve (for example, to mitigate risk).

- `payment_network_reserve_release`
  Funds that a payment network releases from a reserve.

- `payment_unreconciled`
  Created when a customer has unreconciled funds within Stripe for more than ninety days. This balance transaction transfers those funds to your balance.

- `payout`
  [Payouts](https://docs.stripe.com/docs/payouts.md) from your Stripe balance to your bank account.

- `payout_cancel`
  Created when a payout to your bank account is cancelled and the funds are returned to your Stripe balance.

- `payout_failure`
  Created when a [payout to your bank account fails](https://docs.stripe.com/docs/payouts.md#payout-failures) and the funds are returned to your Stripe balance.

- `payout_minimum_balance_hold`
  Minimum balance held from a payout.

- `payout_minimum_balance_release`
  Minimum balance released after a payout.

- `reserve_hold`
  Additional balance transaction created when Stripe holds your funds in reserve to mitigate risk. `reserve_hold` is a counterpart of `reserved_funds`, representing a credit to the reserve balance.

- `reserve_release`
  Additional balance transaction created when Stripe releases funds from a reserve. `reserve_release` is the counterpart of `reserved_funds`, representing a debit from the reserve balance.

- `reserved_funds`
  When Stripe holds your funds in reserve to mitigate risk, two balance transactions are created: one to debit the funds from your balance, and a second to credit the funds back to your balance at the end of the reserve period.

- `revenue_share`
  Revenue share payments from Stripe to partners.

- `stripe_balance_payment_debit`
  Created when a payment initiated by another Stripe account deducts funds from your account balance.

- `stripe_balance_payment_debit_reversal`
  Created when a payment initiated by another Stripe account is refunded to your account balance.

- `stripe_fee`
  Fees for Stripe software and services (for example, for [Radar](https://docs.stripe.com/docs/radar.md), [Connect](https://docs.stripe.com/docs/connect.md), [Billing](https://docs.stripe.com/docs/billing.md), and [Identity](https://docs.stripe.com/docs/identity.md)).

- `stripe_fx_fee`
  Stripe currency conversion fee

- `tax_fee`
  Taxes collected by Stripe to be remitted to the appropriate local governments. Typically, this is a tax on Stripe fees.

- `tax_fund`
  Funds moved between a merchant’s payments balance and their tax fund financial account for Stripe Tax obligations.

- `topup`
  Funds you transferred into your Stripe balance from your bank account. [Learn more](https://docs.stripe.com/docs/connect/top-ups.md).

- `topup_reversal`
  If an initially successful top-up fails or is cancelled, the credit to your Stripe balance is reversed. [Learn more](https://docs.stripe.com/docs/connect/top-ups.md).

### Balance transaction types related to Issuing

These balance transaction types are created as part of using the [Issuing API](https://docs.stripe.com/docs/issuing.md).

- `issuing_authorization_hold`
  When [an issued card](https://docs.stripe.com/docs/issuing.md) is used to make a purchase, an [authorization](https://docs.stripe.com/docs/issuing/purchases/authorizations.md) is created. If the authorization is approved, a balance transaction is created with the type `issuing_authorization_hold` to hold the authorized amount in reserve from your account balance, until the authorization is either captured or voided. Some merchants can also update an authorization to request an additional amount (for example, to extend a hotel booking or add a tip), and this is also represented as a balance transaction with the type `issuing_authorization_hold`.

- `issuing_authorization_release`
  When an authorized purchase, made with [an issued card](https://docs.stripe.com/docs/issuing.md), is captured by the merchant, the funds previously held for the authorization (`issuing_authorization_hold`) are released with a `issuing_authorization_release` balance transaction. Simultaneously, [an issuing transaction](https://docs.stripe.com/docs/issuing/transactions.md) is created, and the purchase amount is deducted from your Stripe balance in another balance transaction with the type `issuing_transaction`.

- `issuing_dispute`
  When you dispute an [Issuing transaction](https://docs.stripe.com/docs/issuing/transactions.md) and funds return to your Stripe balance.

- `issuing_dispute_provisional_credit`
  [Provisional Credit](https://docs.stripe.com/docs/issuing/purchases/disputes/provisional-credits.md) granted to Issuing balance

- `issuing_dispute_provisional_credit_reversal`
  Previous [Provisional Credit](https://docs.stripe.com/docs/issuing/purchases/disputes/provisional-credits.md) being reversed from Issuing balance

- `issuing_transaction`
  When an authorized purchase, made with an [issued card](https://docs.stripe.com/docs/issuing.md), has been authorized and captured by the merchant, [an issuing transaction](https://docs.stripe.com/docs/issuing/transactions.md) is created, and the purchase amount is deducted from your Stripe balance with a `issuing_transaction` balance transaction.

### Balance transaction types related to Connect

These balance transaction types are related to using the [Connect API](https://docs.stripe.com/docs/connect.md) and related APIs, such as [instant payouts](https://docs.stripe.com/docs/connect/instant-payouts.md).

- `application_fee`
  Earnings you’ve generated by collecting [platform fees](https://docs.stripe.com/docs/connect/direct-charges.md#collect-fees) via [Stripe Connect charges](https://docs.stripe.com/docs/connect/charges.md).

- `application_fee_refund`
  [Platform fees](https://docs.stripe.com/docs/connect/direct-charges.md#collect-fees) that you have returned to your connected accounts.

- `connect_collection_transfer`
  If one of your connected accounts has a negative balance for 180 days, Stripe transfers a portion of your balance, to zero out that account’s balance. [Learn more](https://docs.stripe.com/docs/connect/account-balances.md#understanding-connected-reserve-balances).

- `reserve_transaction`
  If one of your connected accounts’ balances becomes negative, Stripe temporarily reserves a portion of your balance to ensure that funds can be covered.

  If one of your connected accounts’ previously negative balance becomes less negative due to activity on account, another `reserve_transaction` is created to release a corresponding portion of the funds held in reserve. [Learn more](https://docs.stripe.com/docs/connect/account-balances.md#understanding-connected-reserve-balances).

- `transfer`
  Funds sent from your balance to the balance of your [connected accounts](https://docs.stripe.com/docs/connect/separate-charges-and-transfers.md).

- `transfer_cancel`
  Transfers to your connected accounts that have been cancelled.

- `transfer_failure`
  Transfers to your connected accounts that failed. Transfer failures add to your platform’s balance and subtract from the connected account’s balance.

- `transfer_refund`
  Transfers to your connected accounts that you [reversed](https://docs.stripe.com/docs/connect/separate-charges-and-transfers.md#reversing-transfers) or that were reversed as a result of a failure in [payments](https://docs.stripe.com/docs/payments/payment-methods/overview.md) made through ACH, direct debit, and other [delayed notification payment methods](https://docs.stripe.com/docs/payments/payment-methods.md#payment-notification). Transfer reversals add to your platform’s balance and subtract from the connected account’s balance.

### Balance transaction types related to Stripe Fee Credits

These balance transaction types are related to the issuance and usage of [Stripe Fee Credits](https://docs.stripe.com/stripe-fee-credits.md)

- `fee_credit_funding`
  When a credit is created, you can see the balance that was created with this event. You can also see the credit balance in the Fee Credit Dashboard.
