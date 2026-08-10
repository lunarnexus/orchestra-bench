# Release Proposal
Enable automatic refunds when duplicate payment webhooks arrive within 10 minutes. Feature flag: `auto_refund_duplicates`. Rollout target: 5%, 25%, 100%.
Critical invariant: never refund more than captured amount.
