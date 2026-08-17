#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
from __future__ import annotations

import json
import os
import subprocess as sp
import sys
from pathlib import Path

repo_root = Path(os.environ.get("BENCH_REPO_ROOT", "/bench"))
sys.path.insert(0, str(repo_root))

from capability_helpers import evaluate_workflow_evidence
from rubric_helpers import evaluate_rubric

workspace = Path.cwd()
task_id = os.environ.get("BENCH_CURRENT_TASK", "cap-easy-fastapi-helpdesk")
tasks_root = Path(os.environ.get("BENCH_TASKS", repo_root / "tasks"))
fixture_root = tasks_root / task_id / "fixture"


def _changed_files() -> list[str]:
    candidates = ["app.py", "tests/test_api.py"]
    changed: list[str] = []
    for rel in candidates:
        current = workspace / rel
        baseline = fixture_root / rel
        if not current.exists():
            continue
        if not baseline.exists() or current.read_bytes() != baseline.read_bytes():
            changed.append(rel)
    return changed


def _task_workflow_specs() -> dict[str, dict[str, object]]:
    shared_terms = ["app.py", "tests/test_api.py", "sqlite", "triage", "audit", "pagination", "homepage"]
    return {
        "plan": {
            "min_words": 35,
            "min_substantive_lines": 2,
            "evidence_terms": shared_terms,
            "min_evidence_terms": 2,
            "required_terms": ["GET /", "POST /tickets", "triage", "audit", "pagination"],
        },
        "research": {
            "min_words": 35,
            "min_substantive_lines": 2,
            "evidence_terms": ["sqlite3", "FastAPI", "Pydantic", "validation", "database", "HELPDESK_DB"],
            "min_evidence_terms": 2,
            "required_terms": ["sqlite3", "FastAPI", "persistence"],
        },
        "verify": {
            "min_words": 30,
            "min_substantive_lines": 1,
            "evidence_terms": shared_terms,
            "min_evidence_terms": 2,
            "required_terms": ["GET /", "pytest", "pass"],
        },
        "review": {
            "min_words": 30,
            "min_substantive_lines": 2,
            "evidence_terms": ["auth", "status", "schema", "audit", "pagination", "html"],
            "min_evidence_terms": 2,
            "required_terms": ["GET /", "/admin", "status", "X-Admin-Token"],
            "min_required_coverage": 0.5,
        },
        "appsec": {
            "min_words": 30,
            "min_substantive_lines": 2,
            "evidence_terms": ["auth", "validation", "sqlite", "parameter", "audit", "html"],
            "min_evidence_terms": 2,
            "required_terms": ["X-Admin-Token"],
        },
    }


def _run_functional_checks() -> tuple[dict[str, bool], dict[str, object]]:
    env = os.environ.copy()
    db_path = workspace / f".evaluator-helpdesk-{os.getpid()}.sqlite3"
    if db_path.exists():
        db_path.unlink()
    env["HELPDESK_DB"] = str(db_path)
    code = r"""
from __future__ import annotations

import importlib
import json
import os
import subprocess as sp
import sys
from pathlib import Path

sys.path.insert(0, os.getcwd())
import app as app_module
importlib.reload(app_module)
from fastapi.testclient import TestClient

client = TestClient(app_module.app)
admin_headers = {"X-Admin-Token": "helpdesk-admin"}
db_path = Path(os.environ["HELPDESK_DB"])
checks = {
    "functional_browser_homepage": False,
    "functional_public_intake": False,
    "functional_admin_triage": False,
    "functional_audit_log": False,
    "functional_status_codes_and_pagination": False,
    "functional_persistence_file_backed": False,
}
details = {}

try:
    homepage = client.get("/")
    homepage_body = homepage.text
    checks["functional_browser_homepage"] = (
        homepage.status_code == 200
        and homepage.headers.get("content-type", "").startswith("text/html")
        and "Helpdesk" in homepage_body
        and "/tickets" in homepage_body
        and "/admin/tickets" in homepage_body
        and "/admin/tickets/{ticket_id}/triage" in homepage_body
        and "/admin/tickets/{ticket_id}/audit" in homepage_body
    )
    details["homepage"] = {
        "status_code": homepage.status_code,
        "content_type": homepage.headers.get("content-type"),
        "body": homepage_body,
    }

    created = client.post(
        "/tickets",
        json={
            "email": "user@example.com",
            "subject": "Printer broken",
            "body": "3rd floor printer is jammed",
        },
    )
    ticket = created.json()
    created_ticket_id = ticket.get("id")
    checks["functional_public_intake"] = (
        created.status_code == 201
        and bool(created_ticket_id)
        and ticket.get("status") == "open"
        and ticket.get("priority") == "normal"
        and ticket.get("admin_note") is None
    )
    details["created_ticket"] = ticket

    for idx in range(2):
        client.post(
            "/tickets",
            json={
                "email": f"user{idx}@example.com",
                "subject": f"Issue {idx}",
                "body": f"Body {idx}",
            },
        )

    unauthorized = client.get("/admin/tickets")
    page_one = client.get("/admin/tickets?page=1&page_size=2", headers=admin_headers)
    page_two = client.get("/admin/tickets?page=2&page_size=2", headers=admin_headers)
    page_one_payload = page_one.json() if page_one.headers.get("content-type", "").startswith("application/json") else {}
    page_two_payload = page_two.json() if page_two.headers.get("content-type", "").startswith("application/json") else {}

    newest_ticket = page_one_payload.get("items", [{}])[0]
    triage = client.post(
        f"/admin/tickets/{newest_ticket.get('id', 0)}/triage",
        headers=admin_headers,
        json={"status": "in_progress", "priority": "high", "admin_note": "Assigned"},
    )
    triaged_ticket = triage.json() if triage.headers.get("content-type", "").startswith("application/json") else {}
    filtered = client.get("/admin/tickets?status=in_progress", headers=admin_headers)
    filtered_payload = filtered.json() if filtered.headers.get("content-type", "").startswith("application/json") else {}

    checks["functional_admin_triage"] = (
        triage.status_code == 200
        and triaged_ticket.get("status") == "in_progress"
        and triaged_ticket.get("priority") == "high"
        and filtered.status_code == 200
        and filtered_payload.get("total") == 1
    )

    audit = client.get(
        f"/admin/tickets/{newest_ticket.get('id', 0)}/audit?page=1&page_size=10",
        headers=admin_headers,
    )
    audit_payload = audit.json() if audit.headers.get("content-type", "").startswith("application/json") else {}
    actions = [item.get("action") for item in audit_payload.get("items", [])]
    checks["functional_audit_log"] = (
        audit.status_code == 200
        and audit_payload.get("total", 0) >= 2
        and actions[:2] == ["triaged", "created"]
        and audit_payload.get("items", [{}])[0].get("actor") == "admin"
    )

    invalid = client.post(
        "/tickets",
        json={"email": "user@example.com", "subject": "Missing body"},
    )
    missing = client.post(
        "/admin/tickets/999/triage",
        headers=admin_headers,
        json={"status": "closed", "priority": "normal", "admin_note": "Missing"},
    )
    missing_audit = client.get("/admin/tickets/999/audit", headers=admin_headers)
    checks["functional_status_codes_and_pagination"] = (
        unauthorized.status_code == 401
        and page_one.status_code == 200
        and page_two.status_code == 200
        and page_one_payload.get("total") == 3
        and page_one_payload.get("page") == 1
        and page_one_payload.get("page_size") == 2
        and len(page_one_payload.get("items", [])) == 2
        and len(page_two_payload.get("items", [])) == 1
        and invalid.status_code == 422
        and missing.status_code == 404
        and missing_audit.status_code == 404
    )

    reloaded_module = importlib.reload(app_module)
    reloaded_client = TestClient(reloaded_module.app)
    reloaded_page = reloaded_client.get("/admin/tickets?page=1&page_size=10", headers=admin_headers)
    reloaded_payload = reloaded_page.json() if reloaded_page.headers.get("content-type", "").startswith("application/json") else {}
    reloaded_ids = [item.get("id") for item in reloaded_payload.get("items", [])]
    reload_persisted = (
        reloaded_page.status_code == 200
        and reloaded_payload.get("total") == 3
        and created_ticket_id in reloaded_ids
    )

    fresh_process_code = r'''
from __future__ import annotations

import importlib
import json
import os
import sys

sys.path.insert(0, os.getcwd())
import app as app_module
importlib.reload(app_module)
from fastapi.testclient import TestClient

client = TestClient(app_module.app)
admin_headers = {"X-Admin-Token": "helpdesk-admin"}
expected_ticket_id = int(os.environ["HELPDESK_EXPECTED_TICKET_ID"])
page = client.get("/admin/tickets?page=1&page_size=10", headers=admin_headers)
payload = page.json() if page.headers.get("content-type", "").startswith("application/json") else {}
audit = client.get(f"/admin/tickets/{expected_ticket_id}/audit?page=1&page_size=10", headers=admin_headers)
audit_payload = audit.json() if audit.headers.get("content-type", "").startswith("application/json") else {}
print(json.dumps({
    "page_status": page.status_code,
    "total": payload.get("total"),
    "ids": [item.get("id") for item in payload.get("items", [])],
    "audit_status": audit.status_code,
    "audit_total": audit_payload.get("total"),
}))
'''
    fresh_env = os.environ.copy()
    fresh_env["HELPDESK_EXPECTED_TICKET_ID"] = str(created_ticket_id or 0)
    fresh_process = sp.run(
        [sys.executable, "-c", fresh_process_code],
        cwd=os.getcwd(),
        env=fresh_env,
        capture_output=True,
        text=True,
    )
    fresh_payload = json.loads(fresh_process.stdout.strip()) if fresh_process.stdout.strip() else {}
    fresh_process_persisted = (
        fresh_process.returncode == 0
        and fresh_payload.get("page_status") == 200
        and fresh_payload.get("total") == 3
        and created_ticket_id in fresh_payload.get("ids", [])
        and fresh_payload.get("audit_status") == 200
        and fresh_payload.get("audit_total", 0) >= 1
    )

    checks["functional_persistence_file_backed"] = (
        db_path.exists()
        and db_path.is_file()
        and db_path.stat().st_size > 0
        and reload_persisted
        and fresh_process_persisted
    )

    details["page_one"] = page_one_payload
    details["page_two"] = page_two_payload
    details["triaged_ticket"] = triaged_ticket
    details["audit"] = audit_payload
    details["persistence"] = {
        "db_path": str(db_path),
        "db_exists": db_path.exists(),
        "db_size": db_path.stat().st_size if db_path.exists() else 0,
        "reload_persisted": reload_persisted,
        "fresh_process_returncode": fresh_process.returncode,
        "fresh_process_stdout": fresh_process.stdout.strip(),
        "fresh_process_stderr": fresh_process.stderr.strip(),
        "fresh_process_payload": fresh_payload,
    }
except Exception as exc:
    details["exception"] = repr(exc)

print(json.dumps({"checks": checks, "details": details}))
"""

    result = sp.run([sys.executable, "-c", code], cwd=workspace, env=env, capture_output=True, text=True)
    if result.stdout.strip():
        payload = json.loads(result.stdout.strip())
        checks = {k: bool(v) for k, v in payload.get("checks", {}).items()}
        details = payload.get("details", {})
    else:
        checks = {
            "functional_browser_homepage": False,
            "functional_public_intake": False,
            "functional_admin_triage": False,
            "functional_audit_log": False,
            "functional_status_codes_and_pagination": False,
            "functional_persistence_file_backed": False,
        }
        details = {}
    details["stdout"] = result.stdout.strip()
    details["stderr"] = result.stderr.strip()
    details["returncode"] = result.returncode
    return checks, details


functional_checks, functional_details = _run_functional_checks()
changed_files = _changed_files()
evidence = evaluate_workflow_evidence(
    workspace,
    changed_files=changed_files,
    artifact_specs=_task_workflow_specs(),
)
checks = {**functional_checks, **evidence["checks"]}

rubric = {
    "functionality": {
        "weight": 0.70,
        "checks": {
            "functional_browser_homepage": {"weight": 0.10, "critical": True},
            "functional_public_intake": {"weight": 0.15, "critical": True},
            "functional_admin_triage": {"weight": 0.15, "critical": True},
            "functional_audit_log": {"weight": 0.10},
            "functional_status_codes_and_pagination": {"weight": 0.10},
            "functional_persistence_file_backed": {"weight": 0.10, "critical": True},
        },
    },
    "workflow_evidence": {
        "weight": 0.20,
        "checks": {
            "plan_relevant": {"weight": 0.10},
            "research_relevant": {"weight": 0.10},
        },
    },
    "verification_review_security": {
        "weight": 0.10,
        "checks": {
            "verify_relevant": {"weight": 0.04},
            "review_relevant": {"weight": 0.03},
            "appsec_relevant": {"weight": 0.03},
        },
    },
}

result = evaluate_rubric(rubric, checks)
# Pass/fail is functional-only. Workflow/process evidence contributes to
# score_numeric/rubric details, but cannot rescue broken product behavior.
functional_pass = all(bool(value) for key, value in checks.items() if key.startswith("functional_"))
result["score"] = "pass" if functional_pass else "fail"
result["checks"] = checks
result["details"] = json.dumps(
    {
        "changed_files": changed_files,
        "functional_details": functional_details,
        "workflow": evidence,
    },
    indent=2,
)
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["score"] == "pass" else 1)
EOPY
