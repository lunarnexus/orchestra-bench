"""Append-only audit event log (stub).

Every admin exception decision writes an audit event; history is served
newest first.
"""


def record_event(actor: str, action: str, details: dict) -> None:
    """TODO: append an audit event (actor, action, details, timestamp)."""
    raise NotImplementedError("TODO: implement audit event append")


def list_events(limit: int = 50) -> list[dict]:
    """TODO: return audit events, newest first."""
    raise NotImplementedError("TODO: implement audit history query")
