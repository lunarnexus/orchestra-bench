# Capability Hard — TypeScript Approval Queue

## Goal
Complete the provided TypeScript/Node workspace so it behaves like a small moderation queue with durable persistence, attachment handling, public visibility rules, security controls, and audit history.

You are starting from an intentionally incomplete fixture. Deliver a runnable app plus workflow evidence files.

## Product requirements

### Runtime shape
- Keep the app in `src/server.ts`.
- Use real TypeScript running on Node.
- The app must expose a browser-routable HTML `GET /` homepage titled `Approval Queue`.
- Use durable file-backed or SQLite persistence. In-memory-only state is not acceptable.
- Read the data file path from `APPROVAL_QUEUE_DATA_FILE`; default to `approval-queue-data.json` in the current working directory.
- Read the upload directory from `APPROVAL_QUEUE_UPLOAD_DIR`; default to `uploads/` in the current working directory.
- Read the moderation token from `APPROVAL_QUEUE_ADMIN_TOKEN`; default to `queue-admin`.
- Initialize persistence automatically on first run.

### Browser homepage
Implement `GET /` as a usable HTML entrypoint for the moderation workflow.

Behavior:
- Return HTTP `200` with HTML, not JSON.
- Include the page title and visible heading `Approval Queue`.
- Include a usable submission form or equivalent clear browser controls referencing `POST /submissions`.
- Reference the public approved list at `GET /public/submissions`.
- Reference the admin moderation list at `GET /admin/submissions`, moderation action at `POST /admin/submissions/:id/decision`, and audit history at `GET /admin/submissions/:id/history`.
- Mention the admin token header `X-Admin-Token` and note that user content is escaped / sanitized for public rendering.

### Public submission queue
Implement `POST /submissions`.

Request JSON:
```json
{
  "title": "Quarterly launch plan",
  "submitter_email": "author@example.test",
  "body": "Need approval for <script>alert('xss')</script> launch notes",
  "attachment_name": "launch-plan.pdf",
  "attachment_content": "base64-or-plain-text fixture content is acceptable"
}
```

Behavior:
- Return HTTP `201`.
- Persist the submission with status `pending`.
- Return a JSON object containing at least `id`, `title`, `submitter_email`, `status`, `created_at`, `updated_at`, and attachment metadata when provided.
- `title`, `submitter_email`, and `body` are required.
- Support attachments through the request fields above. Saving the provided content as a text file is acceptable.

### Moderation approval and rejection
Implement:
- `GET /admin/submissions`
- `POST /admin/submissions/:id/decision`
- `GET /admin/submissions/:id/history`

Behavior:
- Admin routes require header `X-Admin-Token` matching the configured moderation token.
- Decision request JSON:
  ```json
  {
    "decision": "approved",
    "note": "Looks safe to publish"
  }
  ```
- Also support rejection with `decision = "rejected"`.
- Persist each moderation decision.
- `GET /admin/submissions` must support `status`, `page`, and `page_size` query params.
- `GET /admin/submissions/:id/history` returns audit items newest first.

### Public visibility rules
Implement `GET /public/submissions`.

Behavior:
- Only approved submissions are visible publicly.
- Support `page` and `page_size` query params.
- Public items must expose sanitized/escaped renderable fields for title/body, for example `title_html` and `body_html`.
- Pending and rejected submissions must not appear in public results.

### Attachment and content safety
- Reject path traversal or nested-path attachment names such as `../secret.txt`, `..\\secret.txt`, or `/tmp/secret.txt` with HTTP `422`.
- Store accepted attachments under the configured upload directory using a safe generated relative path.
- Do not leak host filesystem paths in API responses.
- Public rendering must prevent raw `<script>` tags or equivalent HTML injection from appearing unescaped.

### Audit history
- Every submission must record an initial audit entry.
- Every approval/rejection must append another audit entry.
- Audit entries must include at least `id`, `submission_id`, `action`, `detail`, and `created_at`.

### Validation and status handling
- Invalid JSON should return `400`.
- Validation failures should return `422`.
- Unauthorized admin access should return `401`.
- Unknown submissions and unknown routes should return `404` JSON responses.
- Invalid pagination values should return `400`.

## Required workflow evidence
Create these files in the workspace root:
- `PLAN.md`
- `RESEARCH.md`
- `VERIFY.md`
- `REVIEW.md`
- `APPSEC.md`

They are scored for relevant content, not just existence. Missing evidence reduces the score but does not automatically fail an otherwise functional submission.

## Constraints
- Stay within the provided workspace.
- Do not depend on network access.
- Keep the implementation straightforward and testable.
- Preserve the provided file names unless a strong local reason requires small supporting files.

## Done when
- The provided Node tests pass.
- The API behaviors above work end to end.
- Persistence survives a process restart.
- Attachment path traversal and public XSS traps are handled correctly.
- The workflow evidence files are present and relevant.
