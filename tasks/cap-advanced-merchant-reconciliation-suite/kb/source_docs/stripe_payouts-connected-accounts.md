# Payouts to connected accounts

Manage payouts for your platform's connected accounts.

> This page is for developers building platforms with Stripe Connect. If you’re a business or individual receiving payouts through a platform, contact that platform directly for help with your payout settings and status.

By default, any [charge](https://docs.stripe.com/connect/charges.md) you make on behalf of a connected account accumulates in the connected account’s [balance](https://docs.stripe.com/connect/account-balances.md) and is paid out on a daily rolling basis. Depending on the configuration of your connected accounts, your platform can manage their payouts as follows:

- Schedule [the frequency of automatic payouts](https://docs.stripe.com/connect/manage-payout-schedule.md)
- Perform [manual payouts](https://docs.stripe.com/connect/manual-payouts.md)
- Settle funds [instantly](https://docs.stripe.com/connect/instant-payouts.md)
- When using [destination charges](https://docs.stripe.com/connect/destination-charges.md) or [separate charges and transfers](https://docs.stripe.com/connect/separate-charges-and-transfers.md), retain funds in your platform balance

## Payout management configurations

For connected accounts with access to the full Stripe Dashboard or Express Dashboard, the account holder manages their external *payout* (A payout is the transfer of funds to an external account, usually a bank account, in the form of a deposit) accounts (bank accounts and debit cards). For accounts with access to the Express Dashboard, the platform can schedule automatic payouts and perform manual payouts. To schedule automatic payouts or perform manual payouts for an account that has access to the full Stripe Dashboard, the platform must configure [Platform controls](https://docs.stripe.com/connect/platform-controls-for-stripe-dashboard-accounts.md) for the account.

For connected accounts without access to a Stripe-hosted Dashboard, the platform manages their external payout accounts and can schedule automatic payouts or perform manual payouts.

## Supported settlement currencies 

To see which currencies you can use to settle funds in a particular country, select that country from the following dropdown.

> For a list of supported presentment currencies, see the [currencies](https://docs.stripe.com/currencies.md#presentment-currencies) documentation.
[See table on original page](https://docs.stripe.com/connect/payouts-connected-accounts)
Platforms can also enable their connected accounts to settle funds and pay out to banks in certain non-primary currencies, or pay out to non-domestic bank accounts in the local currency. In some cases, Stripe charges a fee. For more information, see [multi-currency settlement for Connect marketplaces and platforms](https://docs.stripe.com/connect/multi-currency-settlement.md).

## Payout status 

The [Payout object’s](https://docs.stripe.com/api/payouts/object.md) `status` field reflects where funds are in the payout lifecycle:

- **`pending`**: The payout has been created and is waiting to be submitted to the bank. Funds haven’t left Stripe yet.
- **`in_transit`**: Funds have been submitted to the bank and are on their way to the external account.
- **`paid`**: The payout has arrived at the external account. For standard payouts, this typically occurs 1-2 business days after submission.
- **`failed`**: The payout couldn’t be completed. The Payout object’s `failure_code` property indicates the reason. When a payout fails, the external account involved is disabled and can’t receive payouts until the platform updates the connected account’s external account details.
- **`canceled`**: The payout was canceled before funds were submitted to the bank.

For most payouts, the full lifecycle takes several days. [Instant payouts](https://docs.stripe.com/connect/instant-payouts.md) typically reach the account within 30 minutes.

If a connected account holder isn’t seeing expected funds, they need to contact the platform they work with—the platform controls payout settings and schedules for their connected accounts.

### Track payouts with webhooks 

You can track all payout activity on connected accounts by creating an [event destination](https://docs.stripe.com/event-destinations.md) and listening for these events:

- `payout.created`: Sent when a payout is created (status: `pending`).
- `payout.updated`: Sent when payout details change, such as the estimated arrival date.
- `payout.paid`: Sent when the payout reaches the external account (status: `paid`).
- `payout.failed`: Sent when a payout fails (status: `failed`). Stripe also sends an `account.external_account.updated` event because the failed external account is disabled.

> #### Accounts v2 API
> 
> Regardless of the Accounts API version that you use, payouts trigger only the v1 events described here. They don’t have equivalent v2 events.

## Next steps

- [Manage payout schedules](https://docs.stripe.com/connect/manage-payout-schedule.md)
- [Create manual payouts](https://docs.stripe.com/connect/manual-payouts.md)
- [Enable instant payouts](https://docs.stripe.com/connect/instant-payouts.md)
- [Manage external accounts for connected accounts](https://docs.stripe.com/connect/payouts-bank-accounts.md)
