from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from bench.provenance import (
    build_run_metadata,
    collect_aux_skills_snapshot,
    collect_catalog_runtime_snapshot,
    collect_orchestra_config_snapshot,
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
    assert snapshot["enabled_roles"] == ["builder", "verifier"]
    assert snapshot["enabled_roles_summary"] == "builder,verifier"

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
