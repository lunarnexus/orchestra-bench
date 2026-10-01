"""Reconciliation engine (stub).

Match ledger and settlement records per the kb/ policy corpus:
- match by transaction_id; refunds/reversals match by original id
- merchant tier controls amount tolerance (policy_handbook.md#policy-tier-tolerances)
- per-network settlement lateness windows (settlement_formats.md#settlement-late-windows;
  network_b's 5-day window differs from network_a/network_c's 2-day default)
"""

EXCEPTION_CATEGORIES = [
    "missing_settlement",
    "unexpected_settlement",
    "amount_mismatch",
    "currency_mismatch",
    "late_settlement",
    "duplicate_transaction_id",
    "refund_reversal_mismatch",
]


def run_reconciliation() -> dict:
    """TODO: create a reconciliation run, classify every ledger/settlement
    pair, persist matched items and exception records, and return a run
    summary (run_id, counts by category).
    """
    raise NotImplementedError("TODO: implement POST /reconcile/run")
