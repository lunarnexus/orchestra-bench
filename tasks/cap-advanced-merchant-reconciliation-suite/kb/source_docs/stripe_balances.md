# Balances and settlement time

Learn about balance states, settlement timing, and best practices for balance management.

Your Stripe account can have one or more [balances](https://docs.stripe.com/api/balance.md) that hold funds for different products and currencies. Understanding balance states, settlement time, and potential ways to accelerate settlement can help you manage your funds and avoid negative balances.

## Balance types

The following are available balance types. There are other balance types, such as [Connect balances](https://docs.stripe.com/connect/account-balances.md) and [Issuing balance](https://docs.stripe.com/issuing/funding/balance.md), but you need to onboard to their respective products to access them.

### Payments balance

Your payments balance represents all of your incoming transactions from customer charges. When a customer makes a purchase using a card or *local payment method* (Payment methods used in specific countries or regions, such as bank transfers, vouchers, and digital wallets. Examples include Pix (Brazil, bank transfers), Konbini (Japan, vouchers), and WeChat Pay (China, digital wallet)), the funds pass through the payments balance and eventually settle. When a customer initiates a refund or files a dispute, funds are also deducted from the payments balance. You can also use your payments balance to reconcile all of your transactions and payouts to an external bank account.

### Refunds and disputes balance

You can choose to set aside funds for future refunds or disputes in your refunds and dispute balance. You can fund this balance by making an external top up.

### Reserve balance

Sometimes, Stripe might create a reserve balance on your behalf to ensure that your Stripe account can cover any expected incoming refunds or disputes. The reserve balance holds funds that you can’t pay out or transfer until the reserve hold period is complete.

### Financial account (US and UK only)

Your financial account allows you to store funds on Stripe in USD, GBP, or EUR. You can fund this balance with earnings from your payments balance or external top ups from your bank account. You can use your financial account to send money to others, create a card to spend from, or instantly convert between currencies.

## Balance states

When Stripe processes a payment or a funding transaction, funds move through different balance states before you can use them: pending and available. These two states are generally affected by the [settlement timing](https://docs.stripe.com/payments/balances.md#settlement-time), which can vary by location and sometimes by payment method. Funds in a Balance transition from `pending` to `available` at the corresponding [available_on](https://docs.stripe.com/api/balance_transactions/object.md#balance_transaction_object-available_on) time for each balance transaction.

### Pending

Funds in the pending state represent incoming transactions that haven’t settled into your balance. For example, when a customer makes a card payment, the charge amount (minus Stripe’s fee) appears in your pending balance until settlement. You can’t withdraw or spend these funds until they’re available.

Eligible users have options to immediately access pending funds using [Instant Payouts](https://docs.stripe.com/payouts/instant-payouts.md), or to reduce settlement time using Stripe features. For more details, see [Accelerate settlement timing](https://docs.stripe.com/payments/balances.md#accelerate-settlement-timing).

### Available

After the funds settle, they move to your available balance. You can use these funds for payouts to bank accounts, refunds, transfers, or any other debit transaction.

> For eligible businesses in the US, payment proceeds settle in your [financial account](https://docs.stripe.com/treasury.md). You only need to add your bank account information for external payouts.

## Settlement time

Settlement time is the time between when a payment or a [funding transaction](https://docs.stripe.com/payments/customer-balance/funding-instructions.md) is made and when the funds become available in your Stripe balance.

For example, if a customer makes a 100 USD card payment on Monday in the US, the funds are initially pending. Then the funds are available in your balance on Wednesday, 2 business days later.

Settlement timing varies based on your [country](https://docs.stripe.com/payments/balances.md#settlement-timing-by-country) and the [payment method](https://docs.stripe.com/payments/balances.md#settlement-time-by-payment-method) used.

### Definition of days 

There are two definitions of days that affect settlement and payout timing:

- **Calendar days**: Includes every day, including weekends and holidays.
- **Business days**: Only includes working days, typically Monday through Friday, and excludes public holidays.

For example, a charge created on a Saturday could have two different timings depending on which definition of day you use:

- If you use calendar days, Saturday is day 0.
- If you use business days, the next Monday is day 0.

### Settlement timing by country 

Use the following collapsed table to determine your country’s settlement timing. The initial settlement timing applies to your first payout, and the default settlement timing applies to subsequent payouts.

> In some cases, risk criteria might prevent your account from changing to the default settlement timing.

### Country and settlement timing

| Country | Initial settlement timing | Default settlement timing |
| --- | --- | --- |
| Australia | 2 business days | — |
| Austria | 7 calendar days | 3 business days |
| Belgium | 7 calendar days | 3 business days |
| Bulgaria | 7 calendar days | 3 business days |
| Brazil | - 30 calendar days
- 5 calendar days for international charges
- 2 business days for Boleto and Pix payments | — |
| Canada | 7 calendar days | 3 business days |
| Croatia | 7 calendar days | 3 business days |
| Cyprus | 7 calendar days | 3 business days |
| Czech Republic | 7 calendar days | 3 business days |
| Denmark | 7 calendar days | 3 business days |
| Estonia | 7 calendar days | 3 business days |
| Finland | 7 calendar days | 3 business days |
| France | 7 calendar days | 3 business days |
| Germany | 7 calendar days | 3 business days |
| Gibraltar | 7 calendar days | 3 business days |
| Greece | 7 calendar days | 3 business days |
| Hong Kong | 7 calendar days | — |
| Hungary | 7 calendar days | 3 business days |
| India | - 2 business days for domestic charges
- 5 business days for international charges | — |
| Ireland | 7 calendar days | 3 business days |
| Italy | 7 calendar days | 3 business days |
| Japan | 7 calendar days | 4 business days |
| Latvia | 7 calendar days | 3 business days |
| Liechtenstein | 7 calendar days | 3 business days |
| Lithuania | 7 calendar days | 3 business days |
| Luxembourg | 7 calendar days | 3 business days |
| Malaysia | 7 calendar days | — |
| Malta | 7 calendar days | 3 business days |
| Mexico | 7 calendar days | 3 business days |
| Netherlands | 7 calendar days | 3 business days |
| New Zealand | 4 business days | — |
| Norway | 7 calendar days | 3 business days |
| Poland | 7 calendar days | 3 business days |
| Portugal | 7 calendar days | 3 business days |
| Romania | 7 calendar days | 3 business days |
| Singapore | 7 calendar days | — |
| Slovakia | 7 calendar days | 3 business days |
| Slovenia | 7 calendar days | 3 business days |
| Spain | 7 calendar days | 3 business days |
| Sweden | 7 calendar days | 3 business days |
| Switzerland | 7 calendar days | 3 business days |
| Thailand | 7 business days | — |
| United Arab Emirates | 5 business days | — |
| United Kingdom | 7 calendar days | 3 business days |
| United States | 2 business days | — |

### Settlement time by payment method 

Bank payment methods typically have longer settlement times than card payments because of the underlying banking systems. These payments have a higher risk of returns or reversals, which factors into their longer settlement periods.

| Payment method | Settlement timing |
| --- | --- |
| ACH Debit | 4 business days |
| SEPA Direct Debit | 6 business days |
| Bacs Direct Debit | 4 business days |
| AU BECS Direct Debit | 2 business days |
| NZ BECS Direct Debit | 2 business days |
| PAD Canada | 5 business days |
| [USD Bank Transfers](https://docs.stripe.com/payments/bank-transfers.md) | 5 business days |

To manage your cash flow and cover potential refunds, disputes, and fees that might lead to negative balances, you can set a [minimum balance](https://docs.stripe.com/payouts/minimum-balances-for-automatic-payouts.md) in your Stripe account.

## Accelerate settlement timing

Stripe offers products and payment methods that have reduced settlement time depending on your location and are subject to eligibility criteria.

### 2-day ACH settlement

For eligible US businesses, Stripe offers faster ACH settlement that reduces the settlement time from 4 business days to 2 business days from payment creation. For more details about eligibility and activation, see the [ACH support page](https://support.stripe.com/questions/two-day-settlement-for-ach-direct-debit).

### Instant Payouts

Instant Payouts gives you access to your funds immediately following a successful card charge. To learn about eligibility requirements, fees, and supported countries, see [Instant Payouts](https://docs.stripe.com/payouts/instant-payouts.md).

## Best practices for balance management

- **Set up a minimum balance**: If you use automatic payouts, set up a [minimum balance](https://docs.stripe.com/payouts/minimum-balances-for-automatic-payouts.md) to handle any events that cause your account to go negative because of refunds, fees, and chargebacks. A minimum balance helps you avoid paused payouts and automatic debits to your external accounts.
- **Customize your payout schedule**: As a general practice, setting your payout schedule to manual or monthly automatic payouts gives you better control over managing your funds flows. Your account might have fees debited from your balance on a daily or monthly basis, so this allows you to keep a balance to cover for any occurrence.
