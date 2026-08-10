# Task: Research and Record the Webhook Provider Choice

Use the provided local docs to compare Nova Notify and SyncPulse, then update the inventory service metadata to record the correct push-webhook provider choice.

Read all files carefully before producing your output:
- `src/inventory_service.py` — the current service to update
- `docs/nova_api.md` — documentation for **Nova Notify** (push webhooks)
- `docs/syncpulse_api.md` — documentation for **SyncPulse** (polling)

Steps:
1. Read the existing service to understand its current integration pattern.
2. Read both API docs and identify which supports push webhooks, the webhook registration endpoint, and the authentication method required by each API.
3. Write `research_output.json` in the current directory with your findings (see PRD.md for schema).
4. Update `src/inventory_service.py` with a minimal implementation artifact that records the chosen integration choice.

Constraints:
- Base findings only on the provided documentation files. Do not fabricate external knowledge.
- All field values must match what is documented in the fixture files exactly.
- Keep the code change small and local to `src/inventory_service.py`.
