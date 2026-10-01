"""Import ledger and per-network settlement batches (stub).

Imports are idempotent by (batch_id, record_id); duplicate attempts must
not double-count totals. Invalid records are rejected with clear errors.
"""


def import_ledger(payload: dict) -> dict:
    """TODO: validate and upsert ledger entries from payload.

    Expected payload shape: {"batch_id": str, "records": [ledger record]}.
    Ledger records carry record_id, transaction_id, merchant_id,
    merchant_name, merchant_tier (standard|premium|training|test),
    original_transaction_id (null except refunds), amount, currency,
    posted_on (YYYY-MM-DD).
    See kb/policy_handbook.md#policy-import-idempotency and
    kb/policy_handbook.md#policy-tier-tolerances.
    """
    raise NotImplementedError("TODO: implement POST /imports/ledger")


def import_settlements(network: str, payload: dict) -> dict:
    """TODO: validate and upsert settlement records for
    network 'network_a'|'network_b'|'network_c' (reject unknown networks).

    Settlement records carry record_id, transaction_id,
    original_transaction_id (non-null only for reversals), amount,
    currency, settled_on (YYYY-MM-DD). Settlement records carry no
    merchant or tier fields.
    See kb/settlement_formats.md#settlement-match-keys and
    kb/settlement_formats.md#settlement-late-windows.
    """
    raise NotImplementedError("TODO: implement POST /imports/settlements/{network}")
