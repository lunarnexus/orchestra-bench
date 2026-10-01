from __future__ import annotations

from pathlib import Path

import yaml

from bench.runtime import (
    RuntimeEnvironment,
    _apply_orchestra_tools_override,
    _container_mounts,
    prepare_visible_tasks_root,
)


def _env(tmp_path: Path) -> RuntimeEnvironment:
    return RuntimeEnvironment(
        tasks_root=tmp_path / "tasks",
        results_root=tmp_path / "results",
        artifacts_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "workspace",
        orchestra_config_src=tmp_path / "config" / "orchestra",
        lmstudio_config_src=tmp_path / "config" / "pi" / "lmstudio.json",
        pi_skills_src=tmp_path / "config" / "skills",
        orchestra_runtime_dir=tmp_path / "home" / ".pi" / "agent" / "orchestra",
        lmstudio_runtime_file=tmp_path / "home" / ".pi" / "agent" / "lmstudio.json",
        run_id="run-1",
    )


def _write_task(task_dir: Path, *, with_evaluate: bool = True) -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "task.yaml").write_text(
        "task_id: alpha\n"
        "description: isolation contract\n"
        "family: smoke\n"
        "batch: smoke\n"
        "timeout_minutes: 5\n"
        "evaluator: evaluate/run.sh\n"
        "split: dev\n"
    )
    (task_dir / "PRD.md").write_text("prd\n")
    (task_dir / "Prompt.md").write_text("prompt\n")
    (task_dir / "fixture").mkdir(exist_ok=True)
    (task_dir / "fixture" / "seed.txt").write_text("fixture\n")
    (task_dir / "fixture" / "shop.py").write_text("def add_product():\n    pass\n")
    if with_evaluate:
        (task_dir / "evaluate").mkdir(exist_ok=True)
        (task_dir / "evaluate" / "run.sh").write_text("#!/bin/sh\nexit 0\n")
        (task_dir / "evaluate" / "solved").mkdir(exist_ok=True)
        (task_dir / "evaluate" / "solved" / "shop.py").write_text("# solution\n")


def test_prepare_visible_tasks_root_preserves_task_schema_and_excludes_evaluate(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _write_task(root / "tasks" / "alpha")

    visible = prepare_visible_tasks_root(root)

    assert visible == root / "visible-tasks"
    task_root = visible / "alpha"
    assert (task_root / "task.yaml").is_file()
    assert (task_root / "PRD.md").read_text(encoding="utf-8") == "prd\n"
    assert (task_root / "Prompt.md").read_text(encoding="utf-8") == "prompt\n"
    # The visible copy keeps the original task schema: fixture files stay under
    # fixture/ so load_task() detects the fixture and workspace prep copies the
    # starter code (flattened fixture files made fixture_path=None).
    assert (task_root / "fixture" / "seed.txt").read_text(encoding="utf-8") == "fixture\n"
    assert (task_root / "fixture" / "shop.py").is_file()
    assert not (task_root / "seed.txt").exists()
    assert not (task_root / "shop.py").exists()
    assert not (task_root / "evaluate").exists()
    assert not any(path.name in ("evaluate", "solved") for path in visible.rglob("*"))


def test_prepare_visible_tasks_root_removes_pycache(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _write_task(root / "tasks" / "alpha")
    pycache = root / "tasks" / "alpha" / "fixture" / "__pycache__"
    pycache.mkdir()
    (pycache / "shop.cpython-311.pyc").write_text("pyc\n")

    visible = prepare_visible_tasks_root(root)

    assert not any(path.name == "__pycache__" for path in visible.rglob("*"))


def test_prepare_visible_tasks_root_refuses_symlinked_sources(tmp_path: Path) -> None:
    import pytest

    from bench.workspace import WorkspaceError

    root = tmp_path / "repo"
    _write_task(root / "tasks" / "alpha")
    (root / "tasks" / "alpha" / "fixture" / "leak").symlink_to(
        root / "tasks" / "alpha" / "evaluate" / "solved" / "shop.py"
    )

    with pytest.raises(WorkspaceError):
        prepare_visible_tasks_root(root)


def test_container_mounts_mounts_visible_tree_without_evaluator_mount(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _write_task(root / "tasks" / "alpha")

    mounts = _container_mounts(root, root / "config" / "orchestra" / "agent-catalog.yaml")

    assert f"{root / 'visible-tasks'}:/bench/task-materials-source:ro" in mounts
    # The evaluator is never mounted; it is docker cp'd into a run-scoped temp
    # dir only during host-initiated grading.
    assert not any("/bench/evaluator-tasks" in mount for mount in mounts)
    assert not any(
        mount.startswith(f"{root / 'tasks'}:") for mount in mounts
    )


def test_apply_orchestra_tools_override_disables_by_setting_mode_off(tmp_path: Path, monkeypatch) -> None:
    env = _env(tmp_path)
    config_path = env.orchestra_runtime_dir / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "mode: orchestrate\n"
        "default_timeout: 1500\n"
        "tools_enabled_by_default: true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BENCH_ORCHESTRA_TOOLS_DEFAULT", "0")

    result = _apply_orchestra_tools_override(env)

    assert result is False
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert data["mode"] == "off"
    assert data["default_timeout"] == 1500
    assert "tools_enabled_by_default" not in data


def test_apply_orchestra_tools_override_enables_by_setting_orchestrate_mode(tmp_path: Path, monkeypatch) -> None:
    env = _env(tmp_path)
    config_path = env.orchestra_runtime_dir / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("mode: off\ndefault_timeout: 1500\n", encoding="utf-8")
    monkeypatch.setenv("BENCH_ORCHESTRA_TOOLS_DEFAULT", "1")

    result = _apply_orchestra_tools_override(env)

    assert result is True
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert data["mode"] == "orchestrate"
    assert data["default_timeout"] == 1500
