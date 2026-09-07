from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from bench.provenance import (
    build_run_metadata,
    collect_aux_skills_snapshot,
    collect_catalog_runtime_snapshot,
    collect_orchestra_config_snapshot,
    orchestra_tools_executed_from_events,
    snapshot_aux_skills,
    snapshot_catalog_runtime,
    snapshot_files,
    snapshot_orchestra_config,
)


V1_CATALOG = Path(__file__).resolve().parents[2] / "V1" / "config" / "orchestra" / "agent-catalog.yaml"


def test_snapshot_files_returns_a_stable_hash_and_ignores_gitkeep(tmp_path: Path) -> None:
    base = tmp_path / "config"
    base.mkdir()
    (base / ".gitkeep").write_text("")
    (base / "alpha.txt").write_text("one\n")

    snapshot = snapshot_files(base)

    assert snapshot["files"] == ["alpha.txt"]
    assert snapshot["sha256"]

    expected = sha256()
    expected.update(b"alpha.txt")
    expected.update(b"\0")
    expected.update(b"one\n")
    expected.update(b"\0")
    assert snapshot["sha256"] == expected.hexdigest()

    (base / "alpha.txt").write_text("two\n")
    updated = snapshot_files(base)
    assert updated["sha256"] != snapshot["sha256"]


def test_snapshot_aux_skills_and_orchestra_config_helpers(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    skills_dir = config_dir / "skills"
    (config_dir / "orchestra.json").parent.mkdir(parents=True, exist_ok=True)
    (config_dir / "orchestra.json").write_text("{}\n")
    (skills_dir / "builder" / "SKILL.md").parent.mkdir(parents=True, exist_ok=True)
    (skills_dir / "builder" / "SKILL.md").write_text("# builder\n")
    (skills_dir / "reviewer.md").write_text("# reviewer\n")
    (skills_dir / ".gitkeep").write_text("")

    aux_snapshot = snapshot_aux_skills(skills_dir)
    orchestra_snapshot = snapshot_orchestra_config(config_dir)

    assert aux_snapshot["aux_skill_names"] == ["builder", "reviewer.md"]
    assert aux_snapshot["aux_skills_enabled"] is True
    assert aux_snapshot["aux_skills_summary"] == "builder,reviewer.md"
    assert orchestra_snapshot["orchestra_config_files"] == ["orchestra.json", "skills/builder/SKILL.md", "skills/reviewer.md"]
    assert orchestra_snapshot["orchestra_config_sha256"]

    assert collect_aux_skills_snapshot(skills_dir) == aux_snapshot
    assert collect_orchestra_config_snapshot(config_dir) == orchestra_snapshot


def test_snapshot_catalog_runtime_and_run_metadata_merge_provenance(tmp_path: Path) -> None:
    catalog = tmp_path / "agent-catalog.yaml"
    catalog.write_text(
        "default_role: builder\n"
        "harness_configs:\n"
        "  pi:\n"
        "    harness: pi\n"
        "    command:\n"
        "    - pi\n"
        "    - --model\n"
        "    - '{model}'\n"
        "    - -p\n"
        "    - '{prompt}'\n"
        "roles:\n"
        "  builder:\n"
        "    harness_config: pi\n"
        "    model: qwen/big\n"
        "  reviewer:\n"
        "    harness_config: pi\n"
        "    model: qwen/big\n"
        "    enabled: false\n"
        "  verifier:\n"
        "    harness_config: pi\n"
        "    model: qwen/small\n"
    )

    snapshot = snapshot_catalog_runtime(catalog)
    metadata = build_run_metadata(
        task_id="smoke",
        run_id="run-1",
        catalog_path=catalog,
        role=None,
        orchestra=True,
        auto=False,
        extra_skills=["builder"],
        notes="first pass",
        catalog_label="config/orchestra/agent-catalog.yaml",
        runtime_snapshot={"pi_package_names": ["pi-codegraph"], "aux_skills_summary": "builder"},
    )

    assert snapshot["role_models"] == {"builder": "qwen/big", "reviewer": "qwen/big", "verifier": "qwen/small"}
    assert snapshot["role_models_summary"] == "builder=qwen/big, reviewer=qwen/big, verifier=qwen/small"
    assert snapshot["catalog_roles"] == ["builder", "reviewer", "verifier"]
    assert snapshot["catalog_roles_summary"] == "builder,reviewer,verifier"

    assert metadata["task_id"] == "smoke"
    assert metadata["run_id"] == "run-1"
    assert metadata["role"] == "builder"
    assert metadata["default_role"] == "builder"
    assert metadata["model"] == "qwen/big"
    assert metadata["orchestra"] is True
    assert metadata["auto"] is False
    assert metadata["extra_skills"] == ["builder"]
    assert metadata["catalog_path"] == "config/orchestra/agent-catalog.yaml"
    assert metadata["pi_package_names"] == ["pi-codegraph"]
    assert metadata["aux_skills_summary"] == "builder"
    assert metadata["catalog_sha256"]

    assert collect_catalog_runtime_snapshot(catalog) == snapshot


def _write_mode_catalog(catalog: Path) -> None:
    catalog.write_text(
        "default_role: builder\n"
        "harness_configs:\n"
        "  pi:\n"
        "    harness: pi\n"
        "    command:\n"
        "    - pi\n"
        "    - --model\n"
        "    - '{model}'\n"
        "    - -p\n"
        "    - '{prompt}'\n"
        "roles:\n"
        "  builder:\n"
        "    harness_config: pi\n"
        "    model: qwen/big\n",
    )


MODE_FACTS = [
    # full Orchestra auto run (--orchestra)
    {"orchestra": True, "no_orchestra": False, "no_orch_on": False, "tools_available": None, "requested": True},
    # tools available but /orch on skipped (--no-orch-on)
    {"orchestra": False, "no_orchestra": False, "no_orch_on": True, "tools_available": None, "requested": False},
    # Orchestra tools disabled and /orch on skipped (--no-orchestra --no-orch-on)
    {"orchestra": False, "no_orchestra": True, "no_orch_on": True, "tools_available": False, "requested": False},
]


def test_build_run_metadata_persists_explicit_mode_flags(tmp_path: Path) -> None:
    catalog = tmp_path / "agent-catalog.yaml"
    _write_mode_catalog(catalog)

    signatures = []
    for facts in MODE_FACTS:
        metadata = build_run_metadata(
            task_id="smoke",
            run_id="run-1",
            catalog_path=catalog,
            orchestra=facts["orchestra"],
            no_orchestra=facts["no_orchestra"],
            no_orch_on=facts["no_orch_on"],
            orchestra_tools_available=facts["tools_available"],
        )

        # Existing meaning of `orchestra` is preserved.
        assert metadata["orchestra"] == facts["orchestra"]
        assert metadata["no_orchestra"] == facts["no_orchestra"]
        assert isinstance(metadata["no_orchestra"], bool)
        assert metadata["no_orch_on"] == facts["no_orch_on"]
        assert isinstance(metadata["no_orch_on"], bool)
        assert metadata["orch_on_requested"] == facts["requested"]
        assert metadata["orchestra_tools_available"] == facts["tools_available"]
        signatures.append(
            (metadata["no_orchestra"], metadata["no_orch_on"], metadata["orch_on_requested"])
        )

    # The three auto modes are distinguishable from the flags alone.
    assert len(set(signatures)) == 3


def test_build_run_metadata_mode_flags_are_null_when_not_supplied(tmp_path: Path) -> None:
    catalog = tmp_path / "agent-catalog.yaml"
    _write_mode_catalog(catalog)

    metadata = build_run_metadata(task_id="smoke", run_id="run-1", catalog_path=catalog)

    assert metadata["no_orchestra"] is None
    assert metadata["no_orch_on"] is None
    assert metadata["orch_on_requested"] is None
    assert metadata["orchestra_tools_available"] is None
    assert metadata["orchestra_tools_executed"] is None


def test_build_run_metadata_persists_observed_execution_separately_from_availability(tmp_path: Path) -> None:
    catalog = tmp_path / "agent-catalog.yaml"
    _write_mode_catalog(catalog)

    # Configured availability stays unknown (no runtime proof) while observed
    # execution is proven by an actual non-error dispatch tool event.
    metadata = build_run_metadata(
        task_id="smoke",
        run_id="run-1",
        catalog_path=catalog,
        orchestra=False,
        no_orchestra=False,
        no_orch_on=True,
        orchestra_tools_available=None,
        orchestra_tools_executed=True,
    )

    assert metadata["orchestra_tools_available"] is None
    assert metadata["orchestra_tools_executed"] is True


def _write_harness_events(run_dir: Path, *events: dict) -> None:
    harness_dir = run_dir / "artifacts" / "harness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    (harness_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )


def test_orchestra_tools_executed_from_events_true_on_non_error_dispatch(tmp_path: Path) -> None:
    _write_harness_events(
        tmp_path,
        {"type": "tool_execution_start", "toolName": "orch_dispatch"},
        {
            "type": "tool_execution_end",
            "toolName": "orch_dispatch",
            "isError": False,
            "result": {"text": "Orchestra dispatched: builder"},
        },
    )

    assert orchestra_tools_executed_from_events(tmp_path) is True


def test_orchestra_tools_executed_from_events_false_when_no_successful_dispatch(tmp_path: Path) -> None:
    # Error-only dispatch attempts are not observed execution.
    _write_harness_events(
        tmp_path,
        {"type": "tool_execution_end", "toolName": "orch_dispatch", "isError": True},
    )
    assert orchestra_tools_executed_from_events(tmp_path) is False

    # Event log with other tool activity but no orch_dispatch at all.
    _write_harness_events(
        tmp_path,
        {"type": "tool_execution_end", "toolName": "bash", "isError": False},
        {"type": "tool_execution_start", "toolName": "orch_dispatch"},
    )
    assert orchestra_tools_executed_from_events(tmp_path) is False


def test_orchestra_tools_executed_from_events_null_without_event_source(tmp_path: Path) -> None:
    (tmp_path / "artifacts").mkdir(parents=True)

    # No readable harness event log means the fact is unproven, not false.
    assert orchestra_tools_executed_from_events(tmp_path) is None
