AppSec security review: app.py validates input URL scheme, blocks javascript: and data:, sends private/internal destinations to admin review, and requires admin auth token for decisions.

Validation also checks aliases, escapes original URLs in HTML to avoid XSS, and prevents pending private URLs from redirecting until approved.