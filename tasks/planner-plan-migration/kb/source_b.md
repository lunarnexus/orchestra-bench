# Operations Constraints
Migration must be reversible for 24 hours. Backfill must be chunked. Deploy order must avoid downtime: add columns, dual-write, backfill, switch reads, then remove legacy later.
Verification requires row counts, sampled round-trip records, and export compatibility.
