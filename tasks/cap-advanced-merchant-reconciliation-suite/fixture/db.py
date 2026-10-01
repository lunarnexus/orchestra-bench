"""SQLite persistence for Merchant Reconciliation Desk (stub).

DB path comes from RECON_DB, defaulting to recon.sqlite3.
"""
import os

DEFAULT_DB_PATH = "recon.sqlite3"


def get_db_path() -> str:
    """Return the SQLite path from RECON_DB (default: recon.sqlite3)."""
    return os.environ.get("RECON_DB", DEFAULT_DB_PATH)


def get_conn():
    """TODO: open a sqlite3 connection to get_db_path()."""
    raise NotImplementedError("TODO: open sqlite connection for get_db_path()")


def init_schema() -> None:
    """TODO: idempotently create tables (ledger_entries, settlements,
    reconciliation_runs, reconciliation_items, exceptions, audit_events).
    See PRD 'Reconciliation' and the kb/ corpus for required fields.
    """
    raise NotImplementedError("TODO: create schema on startup")
