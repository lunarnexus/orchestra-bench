"""V2 task inventory must not include the removed role-focused suite."""

from pathlib import Path

import pytest

from bench.tasks import discover_tasks, list_suites

REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS_ROOT = REPO_ROOT / "tasks"


def test_role_focused_suite_is_not_advertised() -> None:
    assert TASKS_ROOT.is_dir(), f"missing tasks root: {TASKS_ROOT}"
    suites = list_suites(TASKS_ROOT)
    assert "role-focused" not in suites
    assert suites == ["smoke", "capability-easy", "capability-normal", "capability-advanced"]


def test_v2_inventory_has_thirteen_tasks() -> None:
    discovered = [path.name for path in discover_tasks(TASKS_ROOT)]
    assert len(discovered) == 13
    assert "cap-advanced-url-shortener-review" in discovered
