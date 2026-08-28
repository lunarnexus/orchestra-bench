# URL safety notes

ShortLink Desk intentionally allows ordinary public `http://` and `https://` destinations to redirect immediately.

Reject these as invalid input:
- `javascript:` URLs
- `data:` URLs
- URLs without an HTTP or HTTPS scheme
- malformed URLs without a hostname

Treat these HTTP(S) destinations as suspicious and require admin review before redirecting:
- `localhost`
- `127.0.0.1`
- private IPv4 ranges: `10.*`, `172.16.*` through `172.31.*`, and `192.168.*`
- hostnames ending in `.internal`

Security expectations:
- never render the original URL as raw HTML
- validate custom aliases to contain only letters, numbers, `_`, and `-`
- admin actions require the `X-Admin-Token` header
- pending links must not redirect until approved
