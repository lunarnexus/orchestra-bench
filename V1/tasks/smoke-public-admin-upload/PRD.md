# Smoke E2E — Public Admin Upload

## Goal
Implement a safe public upload handoff for admin approval.

## Product requirements
Complete `uploads.py` so public users can submit allowed files, admins can list pending uploads, and admins can approve them.

## Acceptance criteria
- Read `storage_policy.md` before implementing file validation.
- `submit_upload(user_id, filename, content)` returns an upload dict with `id`, `user_id`, `filename`, `status`, and `path`.
- Allowed extensions are `.txt` and `.md` only.
- Path traversal and absolute paths are rejected with `ValueError`.
- Stored paths must remain under `STORAGE_ROOT`.
- `admin_list(status=None)` lists all uploads or filters by status.
- `admin_approve(upload_id)` marks the upload `approved` and raises `KeyError` for unknown ids.
- Leave role evidence files: `RESEARCH.md`, `PLAN.md`, `VERIFY.md`, `REVIEW.md`, and `SECURITY.md`.
