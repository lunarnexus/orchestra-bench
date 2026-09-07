# API contract notes

- Browser homepage: `GET /` returns `200` HTML with a `Helpdesk` title, a public form that posts to `/tickets`, and admin route references for `/admin/tickets`, `/admin/tickets/{ticket_id}/triage`, and `/admin/tickets/{ticket_id}/audit`
- Admin header: `X-Admin-Token: helpdesk-admin`
- Allowed triage statuses: `open`, `in_progress`, `closed`
- Allowed priorities: `low`, `normal`, `high`, `urgent`
- Pagination responses should use:
  - `items`
  - `total`
  - `page`
  - `page_size`
- `POST /tickets` is public and should return `201`
- Unknown ticket ids on admin detail actions should return `404`
- Missing or incorrect admin token should return `401`
