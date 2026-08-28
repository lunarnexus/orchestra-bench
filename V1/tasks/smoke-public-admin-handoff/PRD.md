# Smoke E2E — Public Entrypoint to Admin Confirmation

## Goal
Implement a support intake handoff from public submission to admin triage.

## Product requirements
Complete `support.py` so unauthenticated callers can submit requests and admins can list/resolve them.

## Acceptance criteria
- `submit_request(email, subject, body)` stores a pending request with a stable id and returns the created request dict.
- `admin_list(status=None)` returns requests, optionally filtered by status.
- The returned request dict contains `id`, `email`, `subject`, `body`, `status`, and `admin_note` fields.
- `admin_resolve(request_id, note)` marks a request resolved and stores the note in an `admin_note` field.
- Public submissions must not start as resolved.
- Unknown request ids raise `KeyError`.
