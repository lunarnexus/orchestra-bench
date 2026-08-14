# Security Notes

- Treat submission title, body, email, and attachment name as untrusted input.
- The `GET /` homepage should mention `X-Admin-Token` for admin routes and should not encourage pasting secrets into public output.
- Reject attachment names that imply directories, traversal, or absolute paths.
- Safe public rendering can be done by escaping HTML entities instead of allowing raw HTML.
- Audit history is part of the security story: moderation actions should be traceable.
