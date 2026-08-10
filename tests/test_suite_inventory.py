"""Tests for final Slice 11 suite inventory."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

try:
    import yaml  # type: ignore[import]
except ImportError:  # pragma: no cover
    yaml = None


_REPO_ROOT = Path(__file__).resolve().parent.parent
_TASKS_DIR = _REPO_ROOT / "tasks"


def _load_yaml(path: Path) -> dict:
    if yaml is not None:
        return yaml.safe_load(path.read_text()) or {}
    data: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        data[key.strip()] = value.strip().strip('"')
    return data


def _task_meta() -> list[dict]:
    out: list[dict] = []
    for yaml_path in sorted(_TASKS_DIR.glob("*/task.yaml")):
        data = _load_yaml(yaml_path)
        data["dir_name"] = yaml_path.parent.name
        out.append(data)
    return out


class TestFinalSuiteInventory:
    def test_smoke_has_saasbench_pattern_tasks(self):
        smoke = [m for m in _task_meta() if m.get("batch") == "smoke"]
        assert [m["task_id"] for m in smoke] == [
            "smoke-billing-webhook-lifecycle",
            "smoke-dependent-setup-chain",
            "smoke-interactive-progress",
            "smoke-migration-release-check",
            "smoke-public-admin-handoff",
            "smoke-public-admin-upload",
        ]

    def test_workflow_smokes_require_full_role_evidence(self):
        expected = {
            "smoke-billing-webhook-lifecycle",
            "smoke-public-admin-upload",
            "smoke-migration-release-check",
        }
        workflow = {
            str(m.get("task_id")): str(m.get("expected_workflow"))
            for m in _task_meta()
            if m.get("task_id") in expected
        }
        assert set(workflow) == expected
        for roles in workflow.values():
            assert roles == "planner,researcher,builder,verifier,reviewer,appsec"

    def test_role_focused_has_three_tasks_per_role(self):
        by_family: defaultdict[str, list[str]] = defaultdict(list)
        for meta in _task_meta():
            if meta.get("batch") == "role-focused":
                by_family[str(meta.get("family"))].append(str(meta.get("task_id")))

        assert set(by_family) == {"planner", "researcher", "verifier", "reviewer", "builder", "appsec"}
        assert {role: len(ids) for role, ids in by_family.items()} == {
            "planner": 3,
            "researcher": 3,
            "verifier": 3,
            "reviewer": 3,
            "builder": 3,
            "appsec": 3,
        }

    def test_no_transitional_raw_material_batch_remains(self):
        batches = Counter(str(m.get("batch")) for m in _task_meta())
        assert "capability-raw-material" not in batches

    def test_final_public_batches_are_present(self):
        batches = Counter(str(m.get("batch")) for m in _task_meta())
        assert batches["smoke"] == 6
        assert batches["role-focused"] == 18
        assert batches["contract"] >= 1
        assert batches["capability"] >= 1

    def test_readme_documents_final_suites_without_transitional_bucket(self):
        readme = (_REPO_ROOT / "README.md").read_text()
        assert "### smoke — 6 real end-to-end tasks" in readme
        assert "### role-focused — 18 per-role tasks" in readme
        assert "### contract — runtime and anti-fake-success checks" in readme
        assert "### capability — integrated end-to-end tasks" in readme
        assert "capability-raw-material" not in readme
