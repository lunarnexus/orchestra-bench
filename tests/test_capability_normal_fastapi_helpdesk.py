"""Focused tests for the first capability-easy FastAPI helpdesk task."""

from __future__ import annotations

import json
import os
import shutil
import subprocess as sp
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TASK_ID = "cap-normal-fastapi-helpdesk"
_TASK_DIR = _REPO_ROOT / "tasks" / _TASK_ID


_IN_MEMORY_APP = '''from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Helpdesk API")

_ADMIN_TOKEN = "helpdesk-admin"
_TICKETS: list[dict[str, object]] = []
_AUDIT: dict[int, list[dict[str, object]]] = {}


class TicketCreate(BaseModel):
    email: str = Field(min_length=3)
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)


class TicketTriage(BaseModel):
    status: Literal["open", "in_progress", "closed"]
    priority: Literal["low", "normal", "high", "urgent"]
    admin_note: str = Field(min_length=1)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if x_admin_token != _ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="admin token required")


def _ticket_or_404(ticket_id: int) -> dict[str, object]:
    for ticket in _TICKETS:
        if ticket["id"] == ticket_id:
            return ticket
    raise HTTPException(status_code=404, detail="ticket not found")


def _log(ticket_id: int, action: str, actor: str, detail: str) -> None:
    entry = {
        "id": len(_AUDIT.get(ticket_id, [])) + 1,
        "ticket_id": ticket_id,
        "action": action,
        "actor": actor,
        "detail": detail,
        "created_at": _now(),
    }
    _AUDIT.setdefault(ticket_id, []).insert(0, entry)


@app.post("/tickets", status_code=201)
def create_ticket(payload: TicketCreate):
    ticket_id = len(_TICKETS) + 1
    now = _now()
    ticket = {
        "id": ticket_id,
        "email": payload.email,
        "subject": payload.subject,
        "body": payload.body,
        "status": "open",
        "priority": "normal",
        "admin_note": None,
        "created_at": now,
        "updated_at": now,
    }
    _TICKETS.insert(0, ticket)
    _log(ticket_id, "created", "public", f"ticket submitted by {payload.email}")
    return ticket


@app.get("/admin/tickets")
def list_tickets(page: int = 1, page_size: int = 20, status: str | None = None, _: None = Depends(_require_admin)):
    if page < 1 or page_size < 1:
        raise HTTPException(status_code=400, detail="page and page_size must be positive")
    items = [ticket for ticket in _TICKETS if status is None or ticket["status"] == status]
    start = (page - 1) * page_size
    end = start + page_size
    return {"items": items[start:end], "total": len(items), "page": page, "page_size": page_size}


@app.post("/admin/tickets/{ticket_id}/triage")
def triage_ticket(ticket_id: int, payload: TicketTriage, _: None = Depends(_require_admin)):
    ticket = _ticket_or_404(ticket_id)
    ticket["status"] = payload.status
    ticket["priority"] = payload.priority
    ticket["admin_note"] = payload.admin_note
    ticket["updated_at"] = _now()
    _log(ticket_id, "triaged", "admin", f"status={payload.status} priority={payload.priority} note={payload.admin_note}")
    return ticket


@app.get("/admin/tickets/{ticket_id}/audit")
def ticket_audit(ticket_id: int, page: int = 1, page_size: int = 20, _: None = Depends(_require_admin)):
    _ticket_or_404(ticket_id)
    if page < 1 or page_size < 1:
        raise HTTPException(status_code=400, detail="page and page_size must be positive")
    items = _AUDIT.get(ticket_id, [])
    start = (page - 1) * page_size
    end = start + page_size
    return {"items": items[start:end], "total": len(items), "page": page, "page_size": page_size}
'''


def _copy_tree(src: Path, dest: Path) -> None:
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        target = dest / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _run_evaluator(workspace: Path) -> tuple[int, dict]:
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
    )
    stdout = result.stdout.strip()
    start = stdout.find("{")
    if start < 0:
        raise AssertionError(f"evaluator produced no JSON\nstdout={result.stdout}\nstderr={result.stderr}")
    return result.returncode, json.loads(stdout[start:])


def _write_stub_workflow_artifacts(workspace: Path) -> None:
    for name, text in {
        "PLAN.md": "plan steps tests files",
        "RESEARCH.md": "research source decision tradeoff",
        "VERIFY.md": "verify test pass result app.py tests/test_api.py",
        "REVIEW.md": "review risk issue follow-up",
        "APPSEC.md": "security auth input validation",
    }.items():
        (workspace / name).write_text(text)


def _write_token_salad_workflow_artifacts(workspace: Path) -> None:
    for name, text in {
        "PLAN.md": "plan steps tests files app.py sqlite triage audit pagination",
        "RESEARCH.md": "research source decision tradeoff sqlite kb fixture tests api contract",
        "VERIFY.md": "verify test pass result app.py tests/test_api.py sqlite triage audit pagination",
        "REVIEW.md": "review risk issue follow-up auth status schema audit pagination",
        "APPSEC.md": "security auth input validation sqlite parameter audit",
    }.items():
        (workspace / name).write_text(text)


def _write_padded_filler_workflow_artifacts(workspace: Path) -> None:
    for name, text in {
        "PLAN.md": "Plan and files for app.py with sqlite, triage, audit, and pagination are noted here. Plan and tests are mentioned again with files and steps.",
        "RESEARCH.md": "Research and source decision tradeoff for sqlite, kb, fixture tests, and api contract are listed here. Source and tradeoff notes are repeated here.",
        "VERIFY.md": "Verify and test pass result for app.py, tests/test_api.py, sqlite, triage, audit, and pagination are noted here. Test result evidence is repeated.",
        "REVIEW.md": "Review and risk issue follow-up for auth, status, schema, audit, and pagination are noted here. Review risk and status are repeated.",
        "APPSEC.md": "Security and auth input validation for sqlite, parameter, and audit are noted here. Security validation and parameter notes are repeated.",
    }.items():
        (workspace / name).write_text(text)


def _write_labeled_filler_workflow_artifacts(workspace: Path) -> None:
    for name, text in {
        "PLAN.md": "1. Step has POST /tickets and POST /admin/tickets/{ticket_id}/triage for noted work.\n2. Step has GET /admin/tickets/{ticket_id}/audit and pagination for noted work.",
        "RESEARCH.md": "source: kb and api contract are listed for the task.\ndecision: sqlite3 is listed as the decision.\ntradeoff: fixture tests and tradeoff are listed for the task.",
        "VERIFY.md": "command: pytest -q tests/test_api.py\nresult: passed and app.py tests/test_api.py sqlite triage audit pagination are listed.",
        "REVIEW.md": "finding: auth status codes schema audit pagination and /admin/* are listed here.\nrisk: status codes and schema risk are listed here.",
        "APPSEC.md": "threat: X-Admin-Token auth validation sqlite parameter audit are listed here.\nmitigation: parameter binding validation and audit are listed here.",
    }.items():
        (workspace / name).write_text(text)


class TestCapabilityNormalFastapiHelpdeskTask:
    def test_task_metadata_marks_capability_workflow(self):
        text = (_TASK_DIR / "task.yaml").read_text()
        assert "task_id: cap-normal-fastapi-helpdesk" in text
        assert "batch: capability-easy" in text
        assert "scoring_type: numeric" in text
        assert "expected_workflow: planner,researcher,builder,verifier,reviewer,appsec" in text

    def test_pristine_fixture_fails(self, tmp_path):
        _copy_tree(_TASK_DIR / "fixture", tmp_path)
        code, result = _run_evaluator(tmp_path)

        assert code != 0
        assert result["score"] == "fail"
        assert result["checks"]["functional_browser_homepage"] is False
        assert result["checks"]["functional_public_intake"] is False

    def test_reference_solution_passes(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] >= 0.9
        assert result["checks"]["functional_browser_homepage"] is True
        assert result["checks"]["functional_public_intake"] is True
        assert result["checks"]["functional_admin_triage"] is True
        assert result["checks"]["functional_audit_log"] is True
        assert result["checks"]["functional_status_codes_and_pagination"] is True
        assert result["checks"]["functional_persistence_file_backed"] is True
        assert result["checks"]["plan_relevant"] is True
        assert result["checks"]["research_relevant"] is True
        assert result["checks"]["verify_relevant"] is True
        assert result["checks"]["review_relevant"] is True
        assert result["checks"]["appsec_relevant"] is True

    def test_reference_solution_ignores_stale_evaluator_database(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        stale_db = tmp_path / ".evaluator-helpdesk.sqlite3"
        stale_db.write_bytes(b"stale")

        code, result = _run_evaluator(tmp_path)
        details = json.loads(result["details"])
        page_one = details["functional_details"]["page_one"]

        assert code == 0
        assert result["checks"]["functional_admin_triage"] is True
        assert result["checks"]["functional_status_codes_and_pagination"] is True
        assert result["checks"]["functional_persistence_file_backed"] is True
        assert page_one["total"] == 3

    def test_missing_workflow_evidence_reduces_score_without_hard_fail(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        for name in ["PLAN.md", "RESEARCH.md", "VERIFY.md", "REVIEW.md", "APPSEC.md"]:
            (tmp_path / name).unlink()

        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] == 0.7
        assert result["checks"]["plan_present"] is False
        assert result["checks"]["review_present"] is False
        assert result["checks"]["appsec_present"] is False

    def test_in_memory_ticket_store_fails_persistence_requirement(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        (tmp_path / "app.py").write_text(_IN_MEMORY_APP)

        code, result = _run_evaluator(tmp_path)

        assert code != 0
        assert result["score"] == "fail"
        assert result["checks"]["functional_public_intake"] is True
        assert result["checks"]["functional_persistence_file_backed"] is False

    def test_keyword_stub_workflow_artifacts_do_not_receive_full_credit(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        _write_stub_workflow_artifacts(tmp_path)

        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] < 0.9
        assert result["checks"]["plan_relevant"] is False
        assert result["checks"]["research_relevant"] is False
        assert result["checks"]["verify_relevant"] is False
        assert result["checks"]["review_relevant"] is False
        assert result["checks"]["appsec_relevant"] is False

    def test_token_salad_workflow_artifacts_do_not_receive_full_credit(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        _write_token_salad_workflow_artifacts(tmp_path)

        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] < 0.9
        assert result["checks"]["plan_relevant"] is False
        assert result["checks"]["research_relevant"] is False
        assert result["checks"]["verify_relevant"] is False
        assert result["checks"]["review_relevant"] is False
        assert result["checks"]["appsec_relevant"] is False

    def test_padded_filler_workflow_artifacts_do_not_receive_full_credit(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        _write_padded_filler_workflow_artifacts(tmp_path)

        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] < 0.9
        assert result["checks"]["plan_relevant"] is False
        assert result["checks"]["research_relevant"] is False
        assert result["checks"]["verify_relevant"] is False
        assert result["checks"]["review_relevant"] is False
        assert result["checks"]["appsec_relevant"] is False

    def test_labeled_filler_workflow_artifacts_do_not_receive_full_credit(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        _write_labeled_filler_workflow_artifacts(tmp_path)

        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] < 0.9
        assert result["checks"]["plan_relevant"] is False
        assert result["checks"]["research_relevant"] is False
        assert result["checks"]["review_relevant"] is False
