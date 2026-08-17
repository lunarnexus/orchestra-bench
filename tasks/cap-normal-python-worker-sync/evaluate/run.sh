#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
from __future__ import annotations

import importlib
import json
import os
import sqlite3
import subprocess as sp
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

repo_root = Path(os.environ.get("BENCH_REPO_ROOT", "/bench"))
sys.path.insert(0, str(repo_root))

from capability_helpers import evaluate_workflow_evidence
from rubric_helpers import evaluate_rubric

workspace = Path.cwd()
task_id = os.environ.get("BENCH_CURRENT_TASK", "cap-normal-python-worker-sync")
tasks_root = Path(os.environ.get("BENCH_TASKS", repo_root / "tasks"))
fixture_root = tasks_root / task_id / "fixture"


class UpstreamHandler(BaseHTTPRequestHandler):
    attempts: dict[tuple[str, int], int] = {}

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/sync":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        key = (str(payload.get("slug")), int(payload.get("version", 0)))
        self.__class__.attempts[key] = self.__class__.attempts.get(key, 0) + 1
        should_retry = key[0].startswith("retry-") and self.__class__.attempts[key] == 1
        if should_retry:
            self.send_response(503)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "temporary_unavailable"}).encode("utf-8"))
            return
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"upstream_id": f"up-{key[0]}-{key[1]}"}).encode("utf-8"))

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def _changed_files() -> list[str]:
    candidates = ["app.py", "worker.py", "sync_core.py", "tests/test_sync_app.py"]
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
    shared_terms = [
        "app.py",
        "worker.py",
        "sync_core.py",
        "tests/test_sync_app.py",
        "sqlite",
        "retry",
        "conflict",
        "stale",
        "pagination",
    ]
    return {
        "plan": {
            "min_words": 35,
            "min_substantive_lines": 2,
            "evidence_terms": shared_terms,
            "min_evidence_terms": 3,
            "required_terms": [
                "GET /",
                "POST /documents",
                "POST /sync-jobs",
                "admin",
                "worker",
                "idempotency",
                "retry",
            ],
        },
        "research": {
            "min_words": 35,
            "min_substantive_lines": 2,
            "evidence_terms": ["sqlite3", "FastAPI", "retry", "worker", "idempotency", "persistence"],
            "min_evidence_terms": 2,
            "required_terms": ["sqlite3", "FastAPI", "idempotency", "worker", "retry"],
        },
        "verify": {
            "min_words": 30,
            "min_substantive_lines": 1,
            "evidence_terms": shared_terms,
            "min_evidence_terms": 2,
            "required_terms": ["GET /", "pytest", "pass", "worker", "queued jobs"],
        },
        "review": {
            "min_words": 30,
            "min_substantive_lines": 2,
            "evidence_terms": ["status", "schema", "audit", "pagination", "risk"],
            "min_evidence_terms": 2,
            "required_terms": ["GET /", "400", "401", "404", "422", "admin", "retry", "newest first"],
        },
        "appsec": {
            "min_words": 30,
            "min_substantive_lines": 2,
            "evidence_terms": ["validation", "sqlite", "parameter", "worker", "token"],
            "min_evidence_terms": 2,
            "required_terms": ["GET /", "X-Admin-Token", "worker"],
        },
    }


def _run_worker(env: dict[str, str]) -> tuple[int, str, str]:
    result = sp.run(
        [sys.executable, "worker.py", "--drain"],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _run_functional_checks() -> tuple[dict[str, bool], dict[str, object]]:
    checks = {
        "functional_browser_homepage": False,
        "functional_document_and_job_flow": False,
        "functional_retry_dedup_and_conflict_handling": False,
        "functional_stale_reclaim_and_audit_history": False,
        "functional_pagination_filtering_and_status_codes": False,
        "functional_persistence_file_backed": False,
    }
    details: dict[str, object] = {}

    server = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = os.environ.copy()
        env["SYNC_DB"] = str(workspace / ".evaluator-sync.sqlite3")
        env["SYNC_UPSTREAM_URL"] = f"http://127.0.0.1:{server.server_port}"
        env["SYNC_ADMIN_TOKEN"] = "sync-admin"
        env["SYNC_STALE_SECONDS"] = "1"
        os.environ.update(
            {
                "SYNC_DB": env["SYNC_DB"],
                "SYNC_UPSTREAM_URL": env["SYNC_UPSTREAM_URL"],
                "SYNC_ADMIN_TOKEN": env["SYNC_ADMIN_TOKEN"],
                "SYNC_STALE_SECONDS": env["SYNC_STALE_SECONDS"],
            }
        )
        sys.path.insert(0, str(workspace))
        import app as app_module

        importlib.reload(app_module)
        from fastapi.testclient import TestClient

        client = TestClient(app_module.app)
        admin_headers = {"X-Admin-Token": "sync-admin"}

        homepage = client.get("/")
        homepage_body = homepage.text
        checks["functional_browser_homepage"] = (
            homepage.status_code == 200
            and homepage.headers.get("content-type", "").startswith("text/html")
            and "Doc Sync" in homepage_body
            and "POST /documents" in homepage_body
            and "POST /sync-jobs" in homepage_body
            and "GET /sync-jobs/{job_id}" in homepage_body
            and "GET /admin/sync-jobs" in homepage_body
            and "GET /admin/sync-jobs/{job_id}/history" in homepage_body
            and "worker" in homepage_body.lower()
            and "retry" in homepage_body.lower()
            and "conflict" in homepage_body.lower()
        )

        created = client.post("/documents", json={"slug": "launch-plan", "title": "Launch plan", "content": "Initial draft"})
        created_payload = created.json() if created.headers.get("content-type", "").startswith("application/json") else {}
        job = client.post("/sync-jobs", json={"slug": "launch-plan", "idempotency_key": "launch-v1"})
        job_payload = job.json() if job.headers.get("content-type", "").startswith("application/json") else {}
        worker_code, worker_stdout, worker_stderr = _run_worker(env)
        polled = client.get(f"/sync-jobs/{job_payload.get('id', 0)}")
        polled_payload = polled.json() if polled.headers.get("content-type", "").startswith("application/json") else {}
        history = client.get(
            f"/admin/sync-jobs/{job_payload.get('id', 0)}/history?page=1&page_size=10",
            headers=admin_headers,
        )
        history_payload = history.json() if history.headers.get("content-type", "").startswith("application/json") else {}
        events = [item.get("event") for item in history_payload.get("items", [])]
        checks["functional_document_and_job_flow"] = (
            created.status_code == 201
            and created_payload.get("version") == 1
            and job.status_code == 201
            and worker_code == 0
            and polled.status_code == 200
            and polled_payload.get("status") == "succeeded"
            and polled_payload.get("attempts") == 1
            and events[:3] == ["succeeded", "started", "queued"]
        )

        client.post("/documents", json={"slug": "retry-report", "title": "Retry report", "content": "needs retry"})
        first = client.post("/sync-jobs", json={"slug": "retry-report", "idempotency_key": "retry-v1"})
        replay = client.post("/sync-jobs", json={"slug": "retry-report", "idempotency_key": "retry-v1"})
        duplicate = client.post("/sync-jobs", json={"slug": "retry-report", "idempotency_key": "retry-v1-other"})
        first_payload = first.json() if first.headers.get("content-type", "").startswith("application/json") else {}
        worker_retry_code, _, _ = _run_worker(env)
        retried = client.get(f"/sync-jobs/{first_payload.get('id', 0)}")
        retried_payload = retried.json() if retried.headers.get("content-type", "").startswith("application/json") else {}

        client.post("/documents", json={"slug": "conflict-doc", "title": "Conflict doc", "content": "v1"})
        conflict = client.post("/sync-jobs", json={"slug": "conflict-doc", "idempotency_key": "conflict-v1"})
        conflict_payload = conflict.json() if conflict.headers.get("content-type", "").startswith("application/json") else {}
        client.post("/documents", json={"slug": "conflict-doc", "title": "Conflict doc", "content": "v2"})
        worker_conflict_code, _, _ = _run_worker(env)
        conflicted = client.get(f"/sync-jobs/{conflict_payload.get('id', 0)}")
        conflicted_payload = conflicted.json() if conflicted.headers.get("content-type", "").startswith("application/json") else {}
        checks["functional_retry_dedup_and_conflict_handling"] = (
            first.status_code == 201
            and replay.status_code == 200
            and duplicate.status_code == 200
            and replay.json().get("id") == first_payload.get("id") == duplicate.json().get("id")
            and worker_retry_code == 0
            and retried_payload.get("status") == "succeeded"
            and retried_payload.get("attempts") == 2
            and UpstreamHandler.attempts.get(("retry-report", 1)) == 2
            and worker_conflict_code == 0
            and conflicted_payload.get("status") == "conflict"
        )

        stale_doc = client.post("/documents", json={"slug": "stale-doc", "title": "Stale doc", "content": "keep me"})
        stale_job = client.post("/sync-jobs", json={"slug": "stale-doc", "idempotency_key": "stale-v1"})
        stale_payload = stale_job.json() if stale_job.headers.get("content-type", "").startswith("application/json") else {}
        db_path = Path(env["SYNC_DB"])
        if db_path.exists():
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    "UPDATE sync_jobs SET status = 'running', attempts = 1, claimed_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
                    (stale_payload.get("id", 0),),
                )
                conn.commit()
        worker_stale_code, _, _ = _run_worker(env)
        stale_polled = client.get(f"/sync-jobs/{stale_payload.get('id', 0)}")
        stale_polled_payload = stale_polled.json() if stale_polled.headers.get("content-type", "").startswith("application/json") else {}
        stale_history = client.get(
            f"/admin/sync-jobs/{stale_payload.get('id', 0)}/history?page=1&page_size=10",
            headers=admin_headers,
        )
        stale_history_payload = stale_history.json() if stale_history.headers.get("content-type", "").startswith("application/json") else {}
        stale_events = [item.get("event") for item in stale_history_payload.get("items", [])]
        checks["functional_stale_reclaim_and_audit_history"] = (
            worker_stale_code == 0
            and stale_polled_payload.get("status") == "succeeded"
            and stale_polled_payload.get("attempts") == 2
            and "reclaimed" in stale_events
            and "succeeded" in stale_events
        )

        unauthorized = client.get("/admin/sync-jobs")
        invalid_page = client.get("/admin/sync-jobs?page=0", headers=admin_headers)
        invalid_status = client.get("/admin/sync-jobs?status=weird", headers=admin_headers)
        missing_doc = client.get("/documents/missing")
        missing_job = client.get("/sync-jobs/999")
        invalid_body = client.post("/documents", json={"slug": "bad", "title": "No body"})
        listing = client.get("/admin/sync-jobs?slug=launch-plan&page=1&page_size=10", headers=admin_headers)
        listing_payload = listing.json() if listing.headers.get("content-type", "").startswith("application/json") else {}
        checks["functional_pagination_filtering_and_status_codes"] = (
            unauthorized.status_code == 401
            and invalid_page.status_code == 400
            and invalid_status.status_code == 400
            and missing_doc.status_code == 404
            and missing_job.status_code == 404
            and invalid_body.status_code == 422
            and listing.status_code == 200
            and listing_payload.get("total", 0) >= 1
            and listing_payload.get("items", [{}])[0].get("slug") == "launch-plan"
        )

        importlib.reload(app_module)
        reloaded_client = TestClient(app_module.app)
        reloaded = reloaded_client.get(f"/sync-jobs/{job_payload.get('id', 0)}")
        reloaded_payload = reloaded.json() if reloaded.headers.get("content-type", "").startswith("application/json") else {}
        fresh_code = r'''
import importlib
import json
import os
import sys
from fastapi.testclient import TestClient
sys.path.insert(0, os.getcwd())
import app
importlib.reload(app)
client = TestClient(app.app)
job = client.get("/sync-jobs/1")
admin = client.get("/admin/sync-jobs?page=1&page_size=10", headers={"X-Admin-Token": "sync-admin"})
print(json.dumps({"job_status": job.status_code, "state": job.json().get("status"), "admin_total": admin.json().get("total")}))
'''
        fresh = sp.run([sys.executable, "-c", fresh_code], cwd=workspace, env=env, capture_output=True, text=True)
        fresh_payload = json.loads(fresh.stdout.strip()) if fresh.stdout.strip() else {}
        checks["functional_persistence_file_backed"] = (
            db_path.exists()
            and db_path.stat().st_size > 0
            and reloaded.status_code == 200
            and reloaded_payload.get("status") == "succeeded"
            and fresh.returncode == 0
            and fresh_payload.get("job_status") == 200
            and fresh_payload.get("state") == "succeeded"
            and fresh_payload.get("admin_total", 0) >= 1
        )

        details = {
            "homepage": {
                "status_code": homepage.status_code,
                "content_type": homepage.headers.get("content-type"),
                "body": homepage_body,
            },
            "created": created_payload,
            "job": job_payload,
            "polled": polled_payload,
            "history_events": events,
            "retry_job": retried_payload,
            "conflict_job": conflicted_payload,
            "stale_job": stale_polled_payload,
            "stale_events": stale_events,
            "listing": listing_payload,
            "db_path": str(db_path),
            "db_exists": db_path.exists(),
            "db_size": db_path.stat().st_size if db_path.exists() else 0,
            "worker_stdout": worker_stdout,
            "worker_stderr": worker_stderr,
            "fresh_payload": fresh_payload,
        }
    except Exception as exc:
        details["exception"] = repr(exc)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

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
            "functional_document_and_job_flow": {"weight": 0.15, "critical": True},
            "functional_retry_dedup_and_conflict_handling": {"weight": 0.20, "critical": True},
            "functional_stale_reclaim_and_audit_history": {"weight": 0.10},
            "functional_pagination_filtering_and_status_codes": {"weight": 0.05},
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
