from __future__ import annotations

import json
import os
import shutil
import subprocess as sp
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TASK_ID = "cap-advanced-openssh-config-resolver"
_TASK_DIR = _REPO_ROOT / "tasks" / _TASK_ID


def _copy_tree(src: Path, dest: Path) -> None:
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        target = dest / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _run_evaluator(workspace: Path) -> dict:
    env = os.environ.copy()
    env["BENCH_REPO_ROOT"] = str(_REPO_ROOT)
    env["BENCH_TASKS"] = str(_REPO_ROOT / "tasks")
    env["BENCH_CURRENT_TASK"] = _TASK_ID
    result = sp.run(
        ["bash", str(_TASK_DIR / "evaluate" / "run.sh")],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    start = result.stdout.find("{")
    assert start >= 0, f"evaluator produced no JSON\nstdout={result.stdout}\nstderr={result.stderr}"
    return json.loads(result.stdout[start:])


def test_task_metadata_uses_existing_capability_tier():
    text = (_TASK_DIR / "task.yaml").read_text()
    assert "task_id: cap-advanced-openssh-config-resolver" in text
    assert "family: capability" in text
    assert "batch: capability-advanced" in text
    assert "scoring_type: numeric" in text
    assert "cap-oss" not in text
    assert "expected_workflow:" not in text


def test_prompt_and_prd_expose_evaluator_contract():
    prd = (_TASK_DIR / "PRD.md").read_text()
    prompt = (_TASK_DIR / "Prompt.md").read_text()
    evaluator = (_TASK_DIR / "evaluate" / "run.sh").read_text()
    for text in [prd, prompt]:
        assert "ssh_config_resolve.py" in text
        assert "Host" in text
        assert "Include" in text
        assert "first" in text.lower() and "wins" in text.lower()
        assert "PLAN.md" in text
        assert "APPSEC.md" in text
    assert "Dispatch" in "\n".join(prompt.splitlines()[:6])
    assert "config_cases" in evaluator
    assert "openssh_client_available" in evaluator
    assert "ssh -G" in evaluator
    assert "oracle_cases" in evaluator


def test_dockerfile_installs_openssh_client_for_oracle():
    dockerfile = (_REPO_ROOT / "docker" / "Dockerfile").read_text().lower()
    assert "openssh-client" in dockerfile


def test_upstream_provenance_is_evaluator_only_not_fixture_visible():
    fixture_text = "\n".join(p.read_text(errors="replace") for p in (_TASK_DIR / "fixture").rglob("*") if p.is_file())
    assert "readconf.c" not in fixture_text
    assert "cfgmatch.sh" not in fixture_text
    assert (_TASK_DIR / "evaluate" / "solved" / "upstream-readconf.c").exists()
    assert (_TASK_DIR / "evaluate" / "solved" / "upstream-cfgmatch.sh").exists()


def test_prd_uses_ssh_g_as_supported_subset_oracle():
    prd = (_TASK_DIR / "PRD.md").read_text()
    assert "ssh -G -F CONFIG HOST" in prd
    assert "Values should match OpenSSH `ssh -G -F CONFIG HOST`" in prd
    assert "ProxyCommand` should be reported as the raw effective string shown by `ssh -G`" in prd


def test_reference_solution_passes_evaluator(tmp_path):
    if shutil.which("ssh") is None:
        raise AssertionError("OpenSSH client is required for this task evaluator")
    ws = tmp_path / "workspace"
    _copy_tree(_TASK_DIR / "fixture", ws)
    shutil.copy2(
        _TASK_DIR / "evaluate" / "solved" / "reference_ssh_config_resolve.py",
        ws / "ssh_config_resolve.py",
    )
    for name in ["PLAN.md", "RESEARCH.md", "VERIFY.md", "REVIEW.md", "APPSEC.md"]:
        (ws / name).write_text(
            "This OpenSSH config resolver reference is verified with ssh -G oracle tests for Host, "
            "Include, precedence, parse, config, and security/error behavior."
        )
    result = _run_evaluator(ws)
    assert result["score"] == "pass"
    assert result["checks"]["config_cases"] is True
    details = json.loads(result["details"])
    assert details["case_passed"] == details["case_total"]
    assert details["failed_total"] == 0


def test_pristine_fixture_fails_behaviorally(tmp_path):
    ws = tmp_path / "workspace"
    _copy_tree(_TASK_DIR / "fixture", ws)
    result = _run_evaluator(ws)
    assert result["score"] == "fail"
    assert result["checks"]["syntax_ok"] is True
    assert result["checks"]["config_cases"] is False
    details = json.loads(result["details"])
    assert details["failed_total"] > 0
    assert "failed_by_case_type" in details
    assert "failed_by_key" in details


def test_keyword_stub_workflow_artifacts_do_not_pass(tmp_path):
    ws = tmp_path / "workspace"
    _copy_tree(_TASK_DIR / "fixture", ws)
    for name in ["PLAN.md", "RESEARCH.md", "VERIFY.md", "REVIEW.md", "APPSEC.md"]:
        (ws / name).write_text("openssh host include precedence config parse test security")
    result = _run_evaluator(ws)
    assert result["score"] == "fail"
    assert result["score_numeric"] < 0.85
