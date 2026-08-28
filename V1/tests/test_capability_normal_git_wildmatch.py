from __future__ import annotations

import json
import os
import shutil
import subprocess as sp
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TASK_ID = "cap-normal-git-wildmatch"
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
    assert "task_id: cap-normal-git-wildmatch" in text
    assert "family: capability" in text
    assert "batch: capability-normal" in text
    assert "scoring_type: numeric" in text
    assert "cap-oss" not in text
    assert "expected_workflow:" not in text


def test_prompt_and_prd_expose_evaluator_contract():
    prd = (_TASK_DIR / "PRD.md").read_text()
    prompt = (_TASK_DIR / "Prompt.md").read_text()
    evaluator = (_TASK_DIR / "evaluate" / "run.sh").read_text()
    for text in [prd, prompt]:
        assert "wildmatch-cli" in text
        assert "pathmatch" in text
        assert "ipathmatch" in text
        assert "PLAN.md" in text
        assert "APPSEC.md" in text
    assert "Dispatch" in "\n".join(prompt.splitlines()[:6])
    assert "wildmatch_matches_reference" in evaluator
    assert "reference_matches_upstream_expectations" in evaluator
    assert "performance_guard" in evaluator


def test_upstream_provenance_is_evaluator_only_not_fixture_visible():
    fixture_text = "\n".join(p.read_text(errors="replace") for p in (_TASK_DIR / "fixture").rglob("*") if p.is_file())
    assert "upstream-wildmatch" not in fixture_text
    assert (_TASK_DIR / "evaluate" / "solved" / "upstream-wildmatch.c").exists()
    assert (_TASK_DIR / "evaluate" / "solved" / "upstream-t3070-wildmatch.sh").exists()


def test_evaluator_is_oracle_driven_from_exact_upstream_files():
    evaluator = (_TASK_DIR / "evaluate" / "run.sh").read_text()
    upstream = (_TASK_DIR / "evaluate" / "solved" / "upstream-t3070-wildmatch.sh").read_text()
    assert "parse_upstream_match_cases" in evaluator
    assert "upstream-t3070-wildmatch.sh" in evaluator
    assert "upstream-wildmatch.c" in evaluator
    assert "reference_builds" in evaluator
    assert "wildmatch_matches_reference" in evaluator
    assert "reference_matches_upstream_expectations" in evaluator
    assert "match 1 1 0 0 'foo/bar' 'foo/**/bar'" in upstream
    assert "match 1 1 0 0 'foo' '**/foo'" in upstream


def test_fixture_cli_modes_match_git_test_tool_semantics():
    main = (_TASK_DIR / "fixture" / "main.c").read_text()
    header = (_TASK_DIR / "fixture" / "wildmatch.h").read_text()
    assert "wildmatch\") == 0) flags = WM_PATHNAME" in main
    assert "iwildmatch\") == 0) flags = WM_PATHNAME | WM_CASEFOLD" in main
    assert "pathmatch\") == 0) flags = 0" in main
    assert "ipathmatch\") == 0) flags = WM_CASEFOLD" in main
    assert "#define WM_CASEFOLD 1" in header
    assert "#define WM_PATHNAME 2" in header


def _add_git_compat_shim(workspace: Path) -> None:
    (workspace / "git-compat-util.h").write_text(
        "#ifndef GIT_COMPAT_UTIL_H\n"
        "#define GIT_COMPAT_UTIL_H\n"
        "#include <ctype.h>\n"
        "#include <stddef.h>\n"
        "#include <stdio.h>\n"
        "#include <stdlib.h>\n"
        "#include <string.h>\n"
        "static inline int is_glob_special(int c) {\n"
        "    return c == '*' || c == '?' || c == '[' || c == '\\\\';\n"
        "}\n"
        "#endif\n"
    )


def test_reference_solution_passes_evaluator(tmp_path):
    ws = tmp_path / "workspace"
    _copy_tree(_TASK_DIR / "fixture", ws)
    shutil.copy2(_TASK_DIR / "evaluate" / "solved" / "upstream-wildmatch.c", ws / "wildmatch.c")
    shutil.copy2(_TASK_DIR / "evaluate" / "solved" / "upstream-wildmatch.h", ws / "wildmatch.h")
    _add_git_compat_shim(ws)
    for name in ["PLAN.md", "RESEARCH.md", "VERIFY.md", "REVIEW.md", "APPSEC.md"]:
        (ws / name).write_text(
            "This wildmatch reference solution is verified against upstream Git t3070 pattern, "
            "pathname, bracket, casefold, and security/performance behavior with make and oracle tests."
        )
    result = _run_evaluator(ws)
    assert result["score"] == "pass"
    assert result["checks"]["wildmatch_matches_reference"] is True
    details = json.loads(result["details"])
    assert details["cases_compared"] == 760
    assert details["cases_matching_reference"] == 760
    assert details["failed_total"] == 0


def test_pristine_fixture_fails_behaviorally(tmp_path):
    ws = tmp_path / "workspace"
    _copy_tree(_TASK_DIR / "fixture", ws)
    result = _run_evaluator(ws)
    assert result["score"] == "fail"
    assert result["checks"]["builds"] is True
    assert result["checks"]["wildmatch_vectors"] is False
    details = json.loads(result["details"])
    assert details["failed_total"] > 0
    assert "failed_by_mode" in details
    assert "failed_by_feature_hint" in details


def test_keyword_stub_workflow_artifacts_do_not_pass(tmp_path):
    ws = tmp_path / "workspace"
    _copy_tree(_TASK_DIR / "fixture", ws)
    for name in ["PLAN.md", "RESEARCH.md", "VERIFY.md", "REVIEW.md", "APPSEC.md"]:
        (ws / name).write_text("wildmatch pattern pathname bracket test security verify")
    result = _run_evaluator(ws)
    assert result["score"] == "fail"
    assert result["score_numeric"] < 0.85
