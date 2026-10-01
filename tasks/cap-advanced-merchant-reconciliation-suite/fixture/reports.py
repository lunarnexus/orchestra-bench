"""Policy-compliant reports and CSV export (stub).

See Reporting Rules and Security and Exports in the kb/ corpus.
"""


def daily_report(date: str) -> dict:
    """TODO: per-date totals; exclude training/test merchants from
    executive totals but keep them in the audit view. Escape untrusted
    text (merchant names, notes).
    """
    raise NotImplementedError("TODO: implement GET /reports/daily")


def merchant_report(merchant_id: str) -> dict:
    """TODO: per-merchant report including audit events and exceptions."""
    raise NotImplementedError("TODO: implement GET /reports/merchant/{merchant_id}")


def exceptions_report() -> dict:
    """TODO: exception summary with counts by category and state."""
    raise NotImplementedError("TODO: implement GET /reports/exceptions")


def export_csv(run_id: str) -> str:
    """TODO: deterministic, safe CSV for one reconciliation run; export
    path must stay inside the export directory (no traversal).
    """
    raise NotImplementedError("TODO: implement GET /exports/reconciliation.csv")
