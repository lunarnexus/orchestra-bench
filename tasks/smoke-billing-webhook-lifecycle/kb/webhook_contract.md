# Webhook Contract

Webhook signatures use lowercase hex HMAC-SHA256.

Canonical payload JSON must be generated with sorted keys and compact separators:
`json.dumps(payload, sort_keys=True, separators=(',', ':'))`.

Payload must include `type: invoice.created` and an `invoice` object. Never include the signing secret.
