from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from bench.tasks import TaskDefinition, TaskLoadError, discover_tasks, load_task, list_suites


def _write_task(task_dir: Path, *, task_yaml: str, prd: str = "Requirements go here.\n", prompt: str = "Dispatch the work.\n", fixture: bool = True, kb_dir: bool = False, kb_md: bool = False, evaluate: bool = True) -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "task.yaml").write_text(task_yaml)
    (task_dir / "PRD.md").write_text(prd)
    (task_dir / "Prompt.md").write_text(prompt)
    if fixture:
        (task_dir / "fixture").mkdir()
    if kb_dir:
        (task_dir / "kb").mkdir()
        (task_dir / "kb" / "kb.md").write_text("kb\n")
    if kb_md:
        (task_dir / "kb.md").write_text("kb markdown\n")
    if evaluate:
        (task_dir / "evaluate").mkdir()


def test_discover_tasks_uses_configurable_root(tmp_path: Path) -> None:
    tasks_root = tmp_path / "tasks"
    _write_task(
        tasks_root / "alpha",
        task_yaml="""task_id: alpha\ndescription: Alpha task\nfamily: builder\nbatch: smoke\nscoring_type: pass_fail\ntimeout_minutes: 7\nevaluator: evaluate/run.sh\n""",
    )
    (tasks_root / "ignored").mkdir(parents=True)

    assert discover_tasks(tasks_root) == [tasks_root / "alpha"]


def test_load_task_parses_paths_and_defaults(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "alpha"
    _write_task(
        task_dir,
        task_yaml="""task_id: alpha\ndescription: Alpha task\nfamily: builder\nbatch: smoke\nscoring_type: numeric\ntimeout_minutes: 12\nevaluator: evaluate/run.sh\n""",
        kb_dir=True,
    )

    task = load_task(task_dir, tmp_path / "tasks")

    assert isinstance(task, TaskDefinition)
    assert task.task_id == "alpha"
    assert task.description == "Alpha task"
    assert task.family == "builder"
    assert task.batch == "smoke"
    assert task.scoring_type == "numeric"
    assert task.timeout_minutes == 12
    assert task.evaluator == "evaluate/run.sh"
    assert task.split == "dev"
    assert task.task_dir == task_dir
    assert task.task_yaml_path == task_dir / "task.yaml"
    assert task.prd_path == task_dir / "PRD.md"
    assert task.prompt_path == task_dir / "Prompt.md"
    assert task.fixture_path == task_dir / "fixture"
    assert task.kb_dir_path == task_dir / "kb"
    assert task.kb_md_path is None
    assert task.evaluate_path == task_dir / "evaluate"


def test_load_task_supports_kb_md_file(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "beta"
    _write_task(
        task_dir,
        task_yaml="""task_id: beta\ndescription: Beta task\nfamily: researcher\nbatch: role-focused\nscoring_type: pass_fail\ntimeout_minutes: 8\nevaluator: evaluate/run.sh\n""",
        kb_md=True,
    )

    task = load_task("beta", tmp_path / "tasks")

    assert task.kb_dir_path is None
    assert task.kb_md_path == task_dir / "kb.md"


def test_list_suites_returns_unique_batches(tmp_path: Path) -> None:
    tasks_root = tmp_path / "tasks"
    _write_task(
        tasks_root / "alpha",
        task_yaml="""task_id: alpha\ndescription: Alpha\nfamily: builder\nbatch: smoke\nscoring_type: pass_fail\ntimeout_minutes: 7\nevaluator: evaluate/run.sh\n""",
    )
    _write_task(
        tasks_root / "beta",
        task_yaml="""task_id: beta\ndescription: Beta\nfamily: reviewer\nbatch: smoke\nscoring_type: pass_fail\ntimeout_minutes: 8\nevaluator: evaluate/run.sh\n""",
    )
    _write_task(
        tasks_root / "gamma",
        task_yaml="""task_id: gamma\ndescription: Gamma\nfamily: appsec\nbatch: role-focused\nscoring_type: pass_fail\ntimeout_minutes: 8\nevaluator: evaluate/run.sh\n""",
    )

    assert list_suites(tasks_root) == ["smoke", "role-focused"]


def test_load_task_rejects_invalid_task_id(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "broken"
    _write_task(
        task_dir,
        task_yaml="""task_id: ../escape
description: Broken task
family: builder
batch: smoke
scoring_type: pass_fail
timeout_minutes: 7
evaluator: evaluate/run.sh
""",
    )

    with pytest.raises(TaskLoadError, match="invalid task_id"):
        load_task(task_dir, tmp_path / "tasks")


def test_load_task_rejects_missing_task_yaml(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "missing"
    task_dir.mkdir(parents=True)
    (task_dir / "PRD.md").write_text("req\n")
    (task_dir / "Prompt.md").write_text("dispatch\n")
    (task_dir / "evaluate").mkdir()

    with pytest.raises(TaskLoadError, match="task.yaml not found"):
        load_task(task_dir, tmp_path / "tasks")


def test_load_task_rejects_malformed_task_yaml(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "broken"
    task_dir.mkdir(parents=True)
    (task_dir / "task.yaml").write_text("task_id: [\n")
    (task_dir / "PRD.md").write_text("req\n")
    (task_dir / "Prompt.md").write_text("dispatch\n")
    (task_dir / "evaluate").mkdir()

    with pytest.raises(TaskLoadError, match="malformed task.yaml"):
        load_task(task_dir, tmp_path / "tasks")


def test_load_task_rejects_missing_required_task_id(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "broken"
    _write_task(
        task_dir,
        task_yaml="""description: Broken task\nfamily: builder\nbatch: smoke\nscoring_type: pass_fail\ntimeout_minutes: 7\nevaluator: evaluate/run.sh\n""",
    )
    (task_dir / "task.yaml").write_text("description: Broken task\n")

    with pytest.raises(TaskLoadError, match="task.yaml missing required field 'task_id'"):
        load_task(task_dir, tmp_path / "tasks")


def test_load_task_rejects_evaluate_file(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "broken"
    _write_task(
        task_dir,
        task_yaml="""task_id: broken\ndescription: Broken task\nfamily: builder\nbatch: smoke\nscoring_type: pass_fail\ntimeout_minutes: 7\nevaluator: evaluate/run.sh\n""",
        evaluate=False,
    )
    (task_dir / "evaluate").write_text("not a directory\n")

    with pytest.raises(TaskLoadError, match="missing evaluate directory"):
        load_task(task_dir, tmp_path / "tasks")


def test_default_tasks_root_prefers_repo_tasks_over_v1_reference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    root_task = repo_root / "tasks" / "smoke-dependent-setup-chain"
    legacy_task = repo_root / "V1" / "tasks" / "legacy-task"
    _write_task(
        root_task,
        task_yaml="""task_id: smoke-dependent-setup-chain
description: Smoke task
family: builder
batch: smoke
scoring_type: pass_fail
timeout_minutes: 7
evaluator: evaluate/run.sh
""",
    )
    _write_task(
        legacy_task,
        task_yaml="""task_id: legacy-task
description: Legacy task
family: builder
batch: role-focused
scoring_type: pass_fail
timeout_minutes: 8
evaluator: evaluate/run.sh
""",
    )
    monkeypatch.setattr("bench.tasks._REPO_ROOT", repo_root)

    tasks = discover_tasks()

    assert tasks == [root_task]
    task = load_task(tasks[0])
    assert task.task_id == "smoke-dependent-setup-chain"
    assert task.evaluate_path == root_task / "evaluate"
    assert list_suites() == ["smoke"]


def test_smoke_task_declares_orchestra_scoring_metadata() -> None:
    task_yaml_path = Path(__file__).resolve().parents[2] / "tasks" / "smoke-dependent-setup-chain" / "task.yaml"
    data = yaml.safe_load(task_yaml_path.read_text(encoding="utf-8"))

    assert data["expected_orchestra"] is True
    assert data["required_roles"] == ["builder", "verifier"]


@pytest.mark.parametrize(
    "task_id, timeout_minutes, requires_kb",
    [
        ("smoke-public-admin-handoff", 12, False),
        ("smoke-interactive-progress", 12, False),
        ("smoke-billing-webhook-lifecycle", 15, True),
        ("smoke-public-admin-upload", 15, True),
        ("smoke-migration-release-check", 15, True),
    ],
)
def test_smoke_orchestration_tasks_have_v2_metadata(task_id: str, timeout_minutes: int, requires_kb: bool) -> None:
    task_yaml_path = Path(__file__).resolve().parents[2] / "tasks" / task_id / "task.yaml"
    data = yaml.safe_load(task_yaml_path.read_text(encoding="utf-8"))

    assert data["family"] == "orchestrator"
    assert data["batch"] == "smoke"
    assert data["expected_orchestra"] is True
    assert data["required_roles"] == ["builder", "verifier"]
    assert data["scoring_type"] == "pass_fail"
    assert data["timeout_minutes"] == timeout_minutes
    assert data["evaluator"] == "evaluate/run.sh"
    if requires_kb:
        task_dir = task_yaml_path.parent
        assert (task_dir / "kb").exists() or (task_dir / "kb.md").exists()
