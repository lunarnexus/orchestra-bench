# Security and Exports — Merchant Reconciliation Desk

Safety rules for exports and HTML output. General context: Adyen report
export/download guidance in `source_docs/adyen_reports-and-the-payments-lifecycle.md`;
Stripe report selection (export formats) in `source_docs/stripe_select-a-report.md`.
Task values are authoritative (`RECONCILIATION_REFERENCE.md#task-addenda`).

<a id="security-safe-export-paths"></a>
## Safe Export Paths

1. `GET /exports/reconciliation.csv?run_id=...` serves exports **only from
   inside the application's export directory**.
2. The `run_id` (or any path-like parameter) is treated as an identifier,
   never as a filesystem path component. Resolving it outside the export
   directory is forbidden.
3. Path-traversal attempts (`..`, absolute paths, encoded variants such as
   `..%2F..%2Fetc%2Fpasswd`) must be rejected with **400 or 404**; the
   response body must never contain the contents of the targeted file.
4. Unknown `run_id` values → 404.
5. Evaluator-only files (e.g. anything under `evaluate/`) must not be
   importable by the app and are never exportable.

<a id="security-csv-determinism"></a>
## Deterministic CSV Export

1. Repeated requests for the same `run_id` must return **byte-identical**
   CSV content (same rows, same order, same formatting).
2. No wall-clock timestamps, run-time ids, random values, or environment-
   dependent content may appear in the CSV body.
3. The header row starts with `transaction_id` (e.g.
   `transaction_id,merchant_id,amount,currency,category,state`); column
   order is fixed.
4. Row order is deterministic — sorted by `transaction_id` (stable tie-
   break on record id).
5. Amounts are rendered with a fixed decimal format (2 decimals);
   unmatched/exception rows carry their category and state.
6. `Content-Type` is `text/csv` (or `text/plain`).

<a id="security-html-escaping"></a>
## HTML Escaping

1. Every HTML page (homepage, merchant reports, exceptions report) must
   escape untrusted text before rendering: merchant names, merchant ids in
   free text, notes/reasons, URLs, and exception details.
2. Escaping covers at minimum `<`, `>`, `&`, `"`, `'` (standard HTML entity
   escaping, e.g. `&lt;script&gt;`).
3. A merchant name containing a script tag (e.g.
   `<script>alert(1)</script>Shop`) must render inert: the response body
   contains the escaped form and never the raw executable tag.
4. Escaping applies to values coming from imported data and from decision
   reasons alike; server-generated labels do not need escaping but must not
   be concatenated with unescaped user data.

<a id="security-admin-token"></a>
## Admin Token Handling

1. Admin routes authenticate via the `X-Admin-Token` header; the expected
   value is read from the `RECON_ADMIN_TOKEN` environment variable (default
   `recon-admin`).
2. Missing or invalid token → **401** with no exception details leaked.
3. The token value must never be echoed into responses, logs, reports, or
   exported files.
4. Read-only report/export routes do not require the admin token; all
   `/admin/*` mutation and listing routes do
   (`policy_handbook.md#policy-admin-auth-audit`).
