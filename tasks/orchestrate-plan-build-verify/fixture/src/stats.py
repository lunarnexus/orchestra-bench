"""Simple statistics module — starter fixture for orchestration tasks."""

from __future__ import annotations


def count(values: list[float]) -> int:
    """Return the number of values in the list."""
    if not values:
        raise ValueError("Cannot compute stats on empty input")
    return len(values)


def total(values: list[float]) -> float:
    """Return the sum of all values, rounded to 2 decimal places."""
    if not values:
        raise ValueError("Cannot compute stats on empty input")
    return round(sum(values), 2)
