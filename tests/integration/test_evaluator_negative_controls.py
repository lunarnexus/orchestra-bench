"""Run real graders against live applications with one deliberate defect."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
APPROVAL = "cap-normal-ts-approval-queue"
MERCHANT = "cap-advanced-merchant-reconciliation-suite"
AUDIT_CHECK = "functional_attachment_security_and_audit_history"


def grade(task, workspace):
    completed = subprocess.run(
        ["bash", str(ROOT / "tasks" / task / "evaluate/run.sh")],
        cwd=workspace,
        env=dict(os.environ, BENCH_WORKDIR=str(workspace)),
        capture_output=True, text=True, timeout=60,
    )
    assert completed.stdout.strip(), completed.stderr
    payload = json.loads(completed.stdout)
    assert completed.returncode in (0, 1), completed.stderr
    assert not payload.get("details", {}).get("functionality", {}).get("evidence", {}).get("exception"), payload
    return payload["checks"]


@pytest.mark.parametrize("mutation", [
    "none", "structured_decision", "unrelated_event", "missing_rejection", "wrong_submission", "oldest_first", "discard_attachment",
])
def test_approval_reference_and_mutants(tmp_path, mutation):
    if not shutil.which("node"):
        pytest.skip("Node is required for the live approval grader")
    workspace = tmp_path / "workspace"
    shutil.copytree(ROOT / "tasks" / APPROVAL / "evaluate/solved", workspace)
    server = workspace / "src/server.ts"
    text = server.read_text()
    replacements = {
        "structured_decision": (
            "addAudit(submission.id, decisionRaw, note);",
            'addAudit(submission.id, "moderation", JSON.stringify({decision: decisionRaw, note}));',
        ),
        "unrelated_event": (
            "addAudit(submission.id, decisionRaw, note);",
            'addAudit(submission.id, "viewed", "Administrator opened the page");',
        ),
        "missing_rejection": (
            "addAudit(submission.id, decisionRaw, note);",
            'addAudit(submission.id, decisionRaw === "approved" ? decisionRaw : "viewed", decisionRaw === "approved" ? note : "Page opened");',
        ),
        "wrong_submission": (
            "submission_id: submissionId,",
            'submission_id: action === "submitted" ? submissionId : submissionId + 1000,',
        ),
        "oldest_first": ("paginate(history, page, pageSize)", "paginate([...history].reverse(), page, pageSize)"),
        "discard_attachment": ('writeFileSync(fullPath, content, "utf8");', 'writeFileSync(fullPath, "", "utf8");'),
    }
    if mutation in replacements:
        old, new = replacements[mutation]
        assert text.count(old) == 1
        server.write_text(text.replace(old, new))
    checks = grade(APPROVAL, workspace)
    if mutation in ("none", "structured_decision"):
        assert all(checks.values()), checks
    else:
        # The grader must isolate the defect, not crash or fail unrelated features.
        assert not checks[AUDIT_CHECK], checks
        assert all(value for key, value in checks.items() if key != AUDIT_CHECK), checks


@pytest.mark.parametrize("corrupt_restart", [None, "approved", "manually_adjusted"])
@pytest.mark.parametrize("report_format", ["json", "html"])
def test_merchant_restart_preserves_decision_meaning(tmp_path, corrupt_restart, report_format):
    pytest.importorskip("fastapi")
    pytest.importorskip("uvicorn")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = (ROOT / "tests/fixtures/merchant_persistence_app.py").read_text()
    if corrupt_restart:
        assert source.count("CORRUPT_STATE = None") == 1
        source = source.replace("CORRUPT_STATE = None", f"CORRUPT_STATE = {corrupt_restart!r}")
    if report_format == "html":
        assert source.count("HTML_STATE_REPORT = False") == 1
        source = source.replace("HTML_STATE_REPORT = False", "HTML_STATE_REPORT = True")
    (workspace / "app.py").write_text(source)
    checks = grade(MERCHANT, workspace)
    assert checks["manual_decision_requires_reason_and_audits"]
    assert checks["audit_history_newest_first"]
    assert checks["data_survives_app_restart"] is (not corrupt_restart), checks
