# Disputes

Learn about disputes, how they work, and what you can do to prevent them.

A dispute (also known as a chargeback) occurs when a cardholder questions your payment with their *card issuer* (The entity that issued a payment card to a cardholder. This could be a bank, such as with the Visa or Mastercard network, or it could be the card network itself, such as with American Express).

To process a chargeback, the issuer creates a formal dispute on the *card network* (A network that processes the transactions of a particular card brand. It might be an intermediary in front of an issuing bank as with Visa or Mastercard, or a standalone entity as with American Express), which immediately reverses the payment. This pulls the money for the payment—as well as one or more network dispute fees—from Stripe. After that, Stripe debits your balance for the payment amount and dispute fee.

To help you submit the best possible response for each dispute, Stripe guides you through the process in the [Dashboard](https://dashboard.stripe.com/test/disputes), where you can provide the appropriate text and images for the [dispute reason](https://docs.stripe.com/disputes/reason-codes-defense-requirements.md), and your counterargument. If you need help with a dispute, [contact support](https://support.stripe.com/contact).

## Handle disputes 

[Respond to disputes](https://docs.stripe.com/disputes/responding.md): Learn how to challenge or accept a dispute.

[Network categories](https://docs.stripe.com/disputes/categories.md): Learn about reason code categories and broad evidence guidelines.

[Reason codes](https://docs.stripe.com/disputes/reason-codes-defense-requirements.md): Refer to common Visa, Mastercard, and American Express reason codes.

[Disputes API](https://docs.stripe.com/disputes/api.md): Retrieve and update disputes, submit evidence, and handle dispute events.

## Analyze disputes 

[Measure disputes](https://docs.stripe.com/disputes/measuring.md): Learn about the issues that can occur from excessive disputes, and how to avoid them.

[Monitoring programs](https://docs.stripe.com/disputes/monitoring-programs.md): Learn about the monitoring programs operated by the card networks.

## Automate dispute management 

[Prevent disputes with Verifi and Ethoca programs](https://docs.stripe.com/disputes/prevention-preview.md): Automatically prevent disputes and lower your dispute rate.

[Smart Disputes](https://docs.stripe.com/disputes/smart-disputes.md): Use Smart Disputes to automate evidence collection and submission for eligible disputes.
