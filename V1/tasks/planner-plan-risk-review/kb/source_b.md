# Incident Notes
Prior payment incident involved duplicate webhook retries and missing idempotency keys. Monitoring exists for refund count and refund total, but no alert currently checks refund/capture ratio.
Support needs a rollback runbook before 25% rollout.
