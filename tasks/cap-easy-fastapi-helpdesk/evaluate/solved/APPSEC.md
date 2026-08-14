# APPSEC

Threat: A browser user could land on `GET /` and be sent to an empty or misleading page that hides the real helpdesk workflow.
Mitigation: `GET /` returns explicit Helpdesk HTML with the public `/tickets` form and admin route references so the browser entrypoint matches the product contract.

Threat: An unauthenticated caller could attempt to change ticket status or read audit history through admin endpoints.
Mitigation: Admin routes require the `X-Admin-Token` header before changing ticket state or returning audit data.

Threat: User-controlled email, subject, body, status, priority, limit, and offset values could be used for SQL injection or invalid persistence state.
Mitigation: SQLite writes use parameter binding and validation before data reaches the database.

Security review:
- Residual risk: rotate the admin token in real deployments and avoid logging sensitive ticket body content in production audit sinks.
