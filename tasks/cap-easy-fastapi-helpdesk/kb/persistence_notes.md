# Persistence notes

- Use a real SQLite file, not an in-memory global list.
- Database path comes from `HELPDESK_DB` and should default to `helpdesk.sqlite3`.
- The fixture tests use a temporary database path per test.
- Audit log rows should be written when a ticket is created and when an admin triages a ticket.
- Newest-first ordering keeps admin screens and audit history deterministic.
