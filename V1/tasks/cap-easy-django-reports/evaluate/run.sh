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
task_id = os.environ.get("BENCH_CURRENT_TASK", "cap-easy-django-reports")
tasks_root = Path(os.environ.get("BENCH_TASKS", repo_root / "tasks"))
fixture_root = tasks_root / task_id / "fixture"


def _changed_files() -> list[str]:
    candidates = ["manage.py", "tests/test_reports.py"]
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
    shared_terms = ["manage.py", "tests/test_reports.py", "django", "sqlite", "reports/history", "csv", "homepage"]
    return {
        "plan": {
            "min_words": 35,
            "min_substantive_lines": 2,
            "evidence_terms": shared_terms,
            "min_evidence_terms": 2,
            "required_terms": ["GET /", "POST /events", "GET /reports/summary", "GET /reports/history"],
        },
        "research": {
            "min_words": 35,
            "min_substantive_lines": 2,
            "evidence_terms": ["REPORTS_DB", "SQLite", "sqlite3", "Django", "file-backed", "history", "persistence", "CSV"],
            "min_evidence_terms": 2,
            "required_terms": ["Django"],
        },
        "verify": {
            "min_words": 20,
            "min_substantive_lines": 1,
            "evidence_terms": shared_terms,
            "min_evidence_terms": 2,
            "required_terms": ["pass", "pytest", "persistence", "history"],
        },
        "review": {
            "min_words": 30,
            "min_substantive_lines": 2,
            "evidence_terms": ["status codes", "pagination", "history", "schema", "permissions"],
            "min_evidence_terms": 2,
            "required_terms": ["reports", "status", "pagination", "history"],
            "min_required_coverage": 0.5,
        },
        "appsec": {
            "min_words": 30,
            "min_substantive_lines": 2,
            "evidence_terms": ["auth", "validation", "sqlite", "csv", "orm"],
            "min_evidence_terms": 2,
            "required_terms": ["X-Report-Token", "SQLite", "validation"],
        },
    }


def _run_functional_checks() -> tuple[dict[str, bool], dict[str, object]]:
    env = os.environ.copy()
    reports_db = workspace / ".evaluator-reports.sqlite3"
    if reports_db.exists():
        reports_db.unlink()
    env["REPORTS_DB"] = str(reports_db)
    code = r"""
from __future__ import annotations

import csv
import importlib
import io
import json
import os
import subprocess as sp
import sys
import time
from pathlib import Path

sys.path.insert(0, os.getcwd())
import manage as app_module
importlib.reload(app_module)
from django.test import Client

client = Client()
admin_headers = {"HTTP_X_REPORT_TOKEN": "reports-admin"}
db_path = Path(os.environ["REPORTS_DB"])
checks = {
    "functional_browser_homepage": False,
    "functional_event_ingest": False,
    "functional_grouped_summary_filters": False,
    "functional_export_json_csv": False,
    "functional_validation_status_codes_permissions": False,
    "functional_report_run_history": False,
    "functional_persistence_file_backed": False,
    "functional_summary_performance_budget": False,
}
details = {}

try:
    homepage = client.get("/")
    homepage_body = homepage.content.decode("utf-8")
    checks["functional_browser_homepage"] = (
        homepage.status_code == 200
        and homepage.headers.get("Content-Type", "").startswith("text/html")
        and "Reports" in homepage_body
        and "/events" in homepage_body
        and "X-Report-Token" in homepage_body
        and "/reports/summary" in homepage_body
        and "format=csv" in homepage_body
        and "/reports/history" in homepage_body
    )
    details["homepage"] = {
        "status_code": homepage.status_code,
        "content_type": homepage.headers.get("Content-Type"),
        "body": homepage_body,
    }

    events = [
        {"event_type": "sale", "occurred_on": "2024-05-01", "category": "books", "amount": 1200},
        {"event_type": "refund", "occurred_on": "2024-05-01", "category": "books", "amount": 200},
        {"event_type": "sale", "occurred_on": "2024-05-02", "category": "games", "amount": 900},
        {"event_type": "sale", "occurred_on": "2024-05-03", "category": "books", "amount": 500},
    ]
    created_responses = [client.post("/events", data=event, content_type="application/json") for event in events]
    created_payloads = [response.json() for response in created_responses]
    checks["functional_event_ingest"] = (
        all(response.status_code == 201 for response in created_responses)
        and created_payloads[0].get("id") == 1
        and created_payloads[0].get("event_type") == "sale"
        and created_payloads[1].get("event_type") == "refund"
    )

    unauthorized = client.get("/reports/summary")
    summary = client.get(
        "/reports/summary?start_date=2024-05-01&end_date=2024-05-03&category=books&page=1&page_size=5",
        **admin_headers,
    )
    summary_payload = summary.json() if summary.headers.get("content-type", "").startswith("application/json") else {}
    page_two = client.get("/reports/summary?page=2&page_size=2", **admin_headers)
    page_two_payload = page_two.json() if page_two.headers.get("content-type", "").startswith("application/json") else {}
    checks["functional_grouped_summary_filters"] = (
        summary.status_code == 200
        and summary_payload.get("total") == 2
        and summary_payload.get("items", [{}])[0].get("date") == "2024-05-03"
        and summary_payload.get("items", [{}, {}])[1].get("date") == "2024-05-01"
        and summary_payload.get("items", [{}, {}])[1].get("sales_total") == 1200
        and summary_payload.get("items", [{}, {}])[1].get("refund_total") == 200
        and summary_payload.get("items", [{}, {}])[1].get("net_total") == 1000
        and summary_payload.get("items", [{}, {}])[1].get("event_count") == 2
        and page_two.status_code == 200
        and page_two_payload.get("total") == 3
        and len(page_two_payload.get("items", [])) == 1
    )

    csv_response = client.get("/reports/summary?format=csv&page=1&page_size=10", **admin_headers)
    csv_rows = list(csv.DictReader(io.StringIO(csv_response.content.decode("utf-8")))) if csv_response.status_code == 200 else []
    json_response = client.get("/reports/summary?page=1&page_size=10", **admin_headers)
    json_payload = json_response.json() if json_response.headers.get("content-type", "").startswith("application/json") else {}
    checks["functional_export_json_csv"] = (
        csv_response.status_code == 200
        and csv_response.headers.get("content-type", "").startswith("text/csv")
        and len(csv_rows) == 3
        and csv_rows[0].get("date") == "2024-05-03"
        and csv_rows[2].get("refund_total") == "200"
        and json_response.status_code == 200
        and json_payload.get("total") == 3
    )

    invalid_event = client.post(
        "/events",
        data={"event_type": "oops", "occurred_on": "bad-date", "category": "", "amount": -1},
        content_type="application/json",
    )
    invalid_page = client.get("/reports/summary?page=0", **admin_headers)
    invalid_format = client.get("/reports/summary?format=xml", **admin_headers)
    invalid_range = client.get("/reports/summary?start_date=2024-05-04&end_date=2024-05-01", **admin_headers)
    history_unauthorized = client.get("/reports/history")
    checks["functional_validation_status_codes_permissions"] = (
        unauthorized.status_code == 401
        and invalid_event.status_code == 400
        and invalid_page.status_code == 400
        and invalid_format.status_code == 400
        and invalid_range.status_code == 400
        and history_unauthorized.status_code == 401
    )

    history = client.get("/reports/history?page=1&page_size=10", **admin_headers)
    history_payload = history.json() if history.headers.get("content-type", "").startswith("application/json") else {}
    history_items = history_payload.get("items", [])
    first_history = history_items[0] if history_items else {}
    second_history = history_items[1] if len(history_items) > 1 else {}
    first_row_count = next(
        (
            first_history.get(key)
            for key in ["returned_rows", "row_count", "result_count", "rows_returned", "rows"]
            if first_history.get(key) is not None
        ),
        None,
    )
    checks["functional_report_run_history"] = (
        history.status_code == 200
        and history_payload.get("total", 0) >= 3
        and first_history.get("format") == "json"
        and second_history.get("format") == "csv"
        and first_row_count == 3
    )

    for index in range(250):
        client.post(
            "/events",
            data={
                "event_type": "sale" if index % 4 else "refund",
                "occurred_on": f"2024-06-{(index % 10) + 1:02d}",
                "category": f"cat-{index % 5}",
                "amount": 50 + index,
            },
            content_type="application/json",
        )
    started = time.perf_counter()
    perf_response = client.get("/reports/summary?page=1&page_size=20", **admin_headers)
    elapsed = time.perf_counter() - started
    checks["functional_summary_performance_budget"] = perf_response.status_code == 200 and elapsed < 1.25

    reloaded_module = importlib.reload(app_module)
    reloaded_client = Client()
    reloaded_page = reloaded_client.get("/reports/summary?page=1&page_size=10", **admin_headers)
    reloaded_payload = reloaded_page.json() if reloaded_page.headers.get("content-type", "").startswith("application/json") else {}
    reload_persisted = reloaded_page.status_code == 200 and reloaded_payload.get("total", 0) >= 3

    fresh_process_code = r'''
from __future__ import annotations
import importlib
import json
import os
import sys
sys.path.insert(0, os.getcwd())
import manage as app_module
importlib.reload(app_module)
from django.test import Client
client = Client()
headers = {"HTTP_X_REPORT_TOKEN": "reports-admin"}
summary = client.get("/reports/summary?page=1&page_size=10", **headers)
history = client.get("/reports/history?page=1&page_size=10", **headers)
summary_payload = summary.json() if summary.headers.get("content-type", "").startswith("application/json") else {}
history_payload = history.json() if history.headers.get("content-type", "").startswith("application/json") else {}
print(json.dumps({
    "summary_status": summary.status_code,
    "summary_total": summary_payload.get("total"),
    "history_status": history.status_code,
    "history_total": history_payload.get("total"),
}))
'''
    fresh_process = sp.run(
        [sys.executable, "-c", fresh_process_code],
        cwd=os.getcwd(),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    fresh_payload = json.loads(fresh_process.stdout.strip()) if fresh_process.stdout.strip() else {}
    checks["functional_persistence_file_backed"] = (
        db_path.exists()
        and db_path.is_file()
        and db_path.stat().st_size > 0
        and reload_persisted
        and fresh_process.returncode == 0
        and fresh_payload.get("summary_status") == 200
        and int(fresh_payload.get("summary_total") or 0) >= 3
        and fresh_payload.get("history_status") == 200
        and int(fresh_payload.get("history_total") or 0) >= 3
    )

    details["created"] = created_payloads
    details["summary"] = summary_payload
    details["page_two"] = page_two_payload
    details["history"] = history_payload
    details["performance"] = {"elapsed_seconds": elapsed}
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
            "functional_event_ingest": False,
            "functional_grouped_summary_filters": False,
            "functional_export_json_csv": False,
            "functional_validation_status_codes_permissions": False,
            "functional_report_run_history": False,
            "functional_persistence_file_backed": False,
            "functional_summary_performance_budget": False,
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
            "functional_event_ingest": {"weight": 0.10, "critical": True},
            "functional_grouped_summary_filters": {"weight": 0.15, "critical": True},
            "functional_export_json_csv": {"weight": 0.10},
            "functional_validation_status_codes_permissions": {"weight": 0.10, "critical": True},
            "functional_report_run_history": {"weight": 0.10},
            "functional_persistence_file_backed": {"weight": 0.10, "critical": True},
            "functional_summary_performance_budget": {"weight": 0.05},
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
