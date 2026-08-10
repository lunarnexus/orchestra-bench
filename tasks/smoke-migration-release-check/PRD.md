# Smoke E2E — Migration Release Check

## Goal
Implement a small data migration with rollback and safe release notes.

## Product requirements
Complete `migration.py` so old user records can be migrated to a new schema, rolled back, and summarized safely.

## Acceptance criteria
- Read `release_policy.md` before implementing compatibility and release-note behavior.
- `migrate(records)` returns new records with `full_name` and `contact.email`.
- Unknown fields must be preserved.
- `rollback(records)` restores `name` and `email` fields while preserving unknown fields.
- `write_release_notes(records, path)` writes a concise markdown summary.
- Release notes must not include `token` or `private_note` values.
- Leave role evidence files: `RESEARCH.md`, `PLAN.md`, `VERIFY.md`, `REVIEW.md`, and `SECURITY.md`.
