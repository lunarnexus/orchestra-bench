# Capability Task — Research and Record the Webhook Provider Choice

## Goal
Use the provided local docs to compare Nova Notify and SyncPulse, then update the inventory service metadata to record the correct push-webhook provider choice.

## Context
The directory contains:
- `src/inventory_service.py` — the current service to update
- `docs/nova_api.md` — documentation for **Nova Notify** (push webhooks)
- `docs/syncpulse_api.md` — documentation for **SyncPulse** (polling)

## Output format — `research_output.json`
Write a JSON file with this exact schema:

```json
{
  "candidate_apis": [
    {
      "name": "<api name>",
      "mode": "<push|polling>",
      "auth_method": "<bearer_token|api_key|basic_auth>",
      "webhook_registration_endpoint": "<url or null if not supported>"
    }
  ],
  "recommendation": {
    "chosen_api": "<name of api best for push webhooks>",
    "reason": "<one sentence explaining why this API is chosen over the other>"
  },
  "current_service_auth": "<auth method currently used by inventory_service.py>"
}
```

## Implementation artifact
Update `src/inventory_service.py` to add a small `WEBHOOK_INTEGRATION` metadata change that records:
- provider: `Nova Notify`
- mode: `push`
- auth method: `bearer_token`
- webhook registration endpoint: `https://api.novanotify.io/v1/webhooks/register`

## Constraints
- Base findings **only** on the provided documentation files. Do not fabricate external knowledge.
- Nova Notify must be chosen because the docs show push webhooks while SyncPulse only supports polling.
- All field values must match what is documented in the fixture files exactly.
- Write valid JSON only — no extra output required.
- Keep the code change small and local to `src/inventory_service.py`.

## Acceptance criteria for grading
- `research_output.json` exists and matches the schema.
- The JSON includes both APIs with the correct mode, auth method, and webhook endpoint values.
- The recommendation chooses Nova Notify and explains that it supports push webhooks while SyncPulse is polling.
- `current_service_auth` is `bearer_token`.
- `src/inventory_service.py` includes the `WEBHOOK_INTEGRATION` metadata with the Nova Notify choice.
