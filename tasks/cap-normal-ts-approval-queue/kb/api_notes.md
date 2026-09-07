# API Notes

- Implement a browser-routable HTML `GET /` homepage titled `Approval Queue` in addition to the JSON APIs.
- The homepage should reference `POST /submissions`, `GET /public/submissions`, `GET /admin/submissions`, `POST /admin/submissions/:id/decision`, and `GET /admin/submissions/:id/history` so a human can discover the workflow.
- Keep API responses JSON except for the homepage HTML and internal attachment file writes.
- Durable file-backed persistence is acceptable if it is real persistence, not process memory.
- Public responses should present safe rendered fields for user-controlled text.
- Admin listing and public listing both need pagination metadata.
