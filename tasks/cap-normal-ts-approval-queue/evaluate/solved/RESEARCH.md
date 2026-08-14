- source: local `kb/api_notes.md` and `kb/security_notes.md` plus the fixture tests describe the API contract, pagination shape, and security traps.
- decision: keep the app in `src/server.ts` on bare Node HTTP with file-backed JSON persistence so the task stays real TypeScript/Node without adding extra runtime services.
- tradeoff: use escaped public HTML fields and generated upload paths instead of raw HTML or caller-controlled paths; this avoids XSS and traversal while keeping the app simple.

Notes:
- The data file from `APPROVAL_QUEUE_DATA_FILE` provides durable state across restarts.
- `APPROVAL_QUEUE_UPLOAD_DIR` is used for attachments, and `attachment_name` is validated before writing.
- Avoid extra ORM or framework weight; the task focuses on moderation flow, persistence, and security behavior.
