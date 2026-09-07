# PLAN

Plan the implementation steps for `app.py`, keep the files small, and use the provided tests for each API behavior.

1. Implement `GET /` as the browser-routable Helpdesk homepage in `app.py`, with a public ticket form and admin route references.
2. Implement public intake with `POST /tickets`, persisted by a SQLite schema and ticket storage in `app.py`.
3. Implement admin auth and triage with `POST /admin/tickets/{ticket_id}/triage`, including status, priority, and assignment updates.
4. Implement audit history with `GET /admin/tickets/{ticket_id}/audit` plus pagination for admin ticket listing, then run `pytest -q tests/test_api.py` and record verification results for app.py and tests/test_api.py.
