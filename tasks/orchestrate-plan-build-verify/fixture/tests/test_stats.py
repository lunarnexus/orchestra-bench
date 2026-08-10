"""Tests for stats module — count, sum, mean, median.

Run with:  python3 tests/test_stats.py
Uses only stdlib (no pytest dependency).
"""

import sys
from pathlib import Path

# Ensure src is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from stats import count, total, mean, median  # noqa: E402


def _approx(a, b, tol=1e-9):
    """Check two floats are approximately equal."""
    return abs(a - b) < tol


_passed = 0
_failed = 0


def check(name, condition):
    global _passed, _failed
    if condition:
        _passed += 1
    else:
        _failed += 1
        print(f"  FAIL: {name}")


# ── count ───────────────────────────────────────────────────────

def test_count_basic():
    check("count([1,2,3]) == 3", count([1.0, 2.0, 3.0]) == 3)


def test_count_empty_raises():
    try:
        count([])
        check("count([] raises ValueError", False)
    except ValueError:
        check("count([] raises ValueError", True)


# ── total (sum) ───────────────────────────────────────────────

def test_total_basic():
    check("total([1,2,3]) == 6.0", _approx(total([1.0, 2.0, 3.0]), 6.0))


def test_total_rounding():
    check("total([0.1, 0.2, 0.3]) ~= 0.6", _approx(total([0.1, 0.2, 0.3]), 0.6))


def test_total_empty_raises():
    try:
        total([])
        check("total([] raises ValueError", False)
    except ValueError:
        check("total([] raises ValueError", True)


# ── mean ───────────────────────────────────────────────────────

def test_mean_basic():
    check("mean([2,4,6]) == 4.0", _approx(mean([2.0, 4.0, 6.0]), 4.0))


def test_mean_single_value():
    check("mean([42]) == 42.0", _approx(mean([42.0]), 42.0))


def test_mean_rounding():
    result = mean([1.0, 2.0, 3.0])
    check("mean([1,2,3]) ~= 2.0", _approx(result, 2.0, tol=0.01))


def test_mean_empty_raises():
    try:
        mean([])
        check("mean([] raises ValueError", False)
    except ValueError:
        check("mean([] raises ValueError", True)


# ── median ─────────────────────────────────────────────────────

def test_median_odd_length():
    check("median([3,1,2]) == 2.0", _approx(median([3.0, 1.0, 2.0]), 2.0))


def test_median_even_length():
    result = median([1.0, 2.0, 3.0, 4.0])
    check("median([1,2,3,4]) ~= 2.5", _approx(result, 2.5, tol=0.01))


def test_median_single_value():
    check("median([7]) == 7.0", _approx(median([7.0]), 7.0))


def test_median_unsorted_input():
    result = median([9.0, 3.0, 6.0, 2.0, 5.0])
    check("median([9,3,6,2,5]) == 5.0", _approx(result, 5.0, tol=0.01))


def test_median_empty_raises():
    try:
        median([])
        check("median([] raises ValueError", False)
    except ValueError:
        check("median([] raises ValueError", True)


# ── Main ───────────────────────────────────────────────────────

if __name__ == "__main__":
    # Discover and run all test functions
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        try:
            t()
        except Exception as e:
            _failed += 1
            print(f"  ERROR: {t.__name__}: {e}")

    total_tests = _passed + _failed
    status = "OK" if _failed == 0 else "FAIL"
    print(f"\n{status}: {_passed}/{total_tests} tests passed")
    sys.exit(1 if _failed > 0 else 0)
