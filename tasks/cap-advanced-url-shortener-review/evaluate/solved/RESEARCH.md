Research source: kb/url_safety.md defines javascript: and data: as invalid, private hosts as pending, and HTML escaping as required.

Decision: normal HTTPS links can be approved, while localhost, 127.0.0.1, RFC1918 private ranges, and .internal names go to review. Tradeoff: keep validation explicit and small for this easy task while preserving escaping against XSS.