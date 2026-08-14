"""Focused tests for the third capability-normal Python worker sync task."""

from __future__ import annotations

import json
import os
import shutil
import subprocess as sp
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TASK_ID = "cap-normal-python-worker-sync"
_TASK_DIR = _REPO_ROOT / "tasks" / _TASK_ID


_IN_MEMORY_APP = r'''from fastapi import FastAPI

app = FastAPI(title="Doc Sync API")
_docs = {}
_jobs = []


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/documents", status_code=201)
def create_document(payload: dict):
    slug = payload["slug"]
    version = _docs.get(slug, {}).get("version", 0) + 1
    doc = {
        "slug": slug,
        "title": payload["title"],
        "content": payload["content"],
        "version": version,
        "sync_status": "dirty",
    }
    _docs[slug] = doc
    return doc


@app.post("/sync-jobs", status_code=201)
def create_job(payload: dict):
    job = {
        "id": len(_jobs) + 1,
        "slug": payload["slug"],
        "requested_version": _docs[payload["slug"]]["version"],
        "status": "succeeded",
        "attempts": 1,
        "idempotency_key": payload["idempotency_key"],
        "history": [],
    }
    _jobs.append(job)
    return job


@app.get("/sync-jobs/{job_id}")
def get_job(job_id: int):
    return next(job for job in _jobs if job["id"] == job_id)


@app.get("/admin/sync-jobs")
def list_jobs():
    return {"items": _jobs, "total": len(_jobs), "page": 1, "page_size": len(_jobs) or 1}


@app.get("/admin/sync-jobs/{job_id}/history")
def get_history(job_id: int):
    return {"items": [], "total": 0, "page": 1, "page_size": 10}
'''


_NO_RETRY_WORKER = r'''from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path


def main() -> int:
    db_path = Path(os.environ.get("SYNC_DB", "sync-jobs.sqlite3"))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, slug, requested_version, attempts FROM sync_jobs WHERE status = 'queued' ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        return 0
    payload = json.dumps({"slug": row["slug"], "version": row["requested_version"]}).encode("utf-8")
    request = urllib.request.Request(
        os.environ["SYNC_UPSTREAM_URL"].rstrip("/") + "/v1/sync",
        method="POST",
        data=payload,
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read()
            conn.execute(
                "UPDATE sync_jobs SET status = 'succeeded', attempts = attempts + 1 WHERE id = ?",
                (row["id"],),
            )
    except urllib.error.HTTPError as error:
        conn.execute(
            "UPDATE sync_jobs SET status = 'failed', attempts = attempts + 1, last_error = ? WHERE id = ?",
            (f\"http {error.code}\", row["id"]),
        )
    conn.commit()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
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
        "VERIFY.md": "verify test pass result app.py worker.py",
        "REVIEW.md": "review risk issue follow-up",
        "APPSEC.md": "security validation sqlite retry worker",
    }.items():
        (workspace / name).write_text(text)


def _write_labeled_filler_workflow_artifacts(workspace: Path) -> None:
    for name, text in {
        "PLAN.md": "1. Step mentions POST /documents, POST /sync-jobs, GET /sync-jobs/{job_id}, and GET /admin/sync-jobs for the task.\n2. Step mentions app.py, worker.py, tests/test_sync_app.py, pytest -q tests/test_sync_app.py, create_sync_job, and run_worker for the task.",
        "RESEARCH.md": "source: kb sqlite3 FastAPI idempotency_key claim_next_job process_next_job are noted here.\ndecision: avoid extra ORM and tradeoff terms are listed for this task.",
        "VERIFY.md": "command: pytest -q tests/test_sync_app.py\nresult: passed and app.py worker.py sync_core.py are noted here.",
        "REVIEW.md": "finding: response schemas 400 401 404 422 GET /sync-jobs/{job_id} GET /admin/sync-jobs are noted.\nrisk: status schema audit pagination risk are repeated here.",
        "APPSEC.md": "threat: X-Admin-Token parameter binding sync_core.py worker.py validation sqlite token are listed.\nmitigation: validation sqlite parameter worker token are repeated here.",
    }.items():
        (workspace / name).write_text(text)


def _write_prose_shaped_boilerplate_workflow_artifacts(workspace: Path) -> None:
    for name, text in {
        "PLAN.md": "Plan steps for the Python worker sync task:\n1. Inspect app.py, worker.py, sync_core.py, and tests/test_sync_app.py so POST /documents, POST /sync-jobs, GET /sync-jobs/{job_id}, and GET /admin/sync-jobs share one SQLite job model.\n2. Implement create_sync_job in sync_core.py and FastAPI routes in app.py with pagination, filters, validation, status codes, and SQLite-backed audit rows for queued, started, retry, conflict, reclaimed, and success events.\n3. Build worker.py processing around run_worker and process_next_job for queued jobs, transient retry handling, stale-job reclaim, and conflict detection when a document version changed before sync.\n4. Verify with pytest -q tests/test_sync_app.py and confirm the changed files app.py, worker.py, sync_core.py, and tests/test_sync_app.py cover retries, conflicts, audit history, and persistence.",
        "RESEARCH.md": "source: kb/api_contract.md and kb/worker_notes.md in the task workspace define the POST /sync-jobs flow, admin pagination fields, idempotency_key behavior, and the local fake upstream retry contract in app.py, worker.py, sync_core.py, and tests/test_sync_app.py.\ndecision: use FastAPI for app.py, sqlite3 for durable jobs/history, and a shared sync_core.py module with claim_next_job and process_next_job so worker.py can claim jobs and the API can poll the same state in tests/test_sync_app.py.\ntradeoff: avoid extra ORM and keep retry behavior simple while app.py, worker.py, sync_core.py, and tests/test_sync_app.py preserve idempotency_key handling.",
        "VERIFY.md": "command: pytest -q tests/test_sync_app.py\nresult: passed; app.py, worker.py, sync_core.py, and tests/test_sync_app.py cover SQLite persistence, retry behavior, stale reclaim, conflict handling, pagination, and status codes.\ncommand: python worker.py --drain\nresult: passed because worker.py drained queued jobs and left pollable states in app.py backed by sync_core.py and tests/test_sync_app.py.",
        "REVIEW.md": "finding: response schemas stay stable across app.py, worker.py, sync_core.py, and tests/test_sync_app.py because GET /sync-jobs/{job_id} and GET /admin/sync-jobs include the expected 400, 401, 404, and 422 behaviors with audit and pagination details.\nrisk: status schema audit pagination risk remains a follow-up concern, but app.py, worker.py, sync_core.py, and tests/test_sync_app.py currently cover the documented routes.",
        "APPSEC.md": "threat: X-Admin-Token, parameter binding, sync_core.py, worker.py, app.py, and tests/test_sync_app.py matter because validation and sqlite safety can regress when untrusted input reaches the worker token flow.\nmitigation: parameter binding, validation, sqlite protections, X-Admin-Token checks, and worker.py state handling remain in app.py and sync_core.py with coverage from tests/test_sync_app.py.",
    }.items():
        (workspace / name).write_text(text)


class TestCapabilityHardPythonWorkerSyncTask:
    def test_task_metadata_marks_capability_workflow(self):
        text = (_TASK_DIR / "task.yaml").read_text()
        assert "task_id: cap-normal-python-worker-sync" in text
        assert "batch: capability-normal" in text
        assert "scoring_type: numeric" in text
        assert "expected_workflow:" not in text

    def test_task_docs_require_browser_homepage(self):
        prd = (_TASK_DIR / "PRD.md").read_text()
        prompt = (_TASK_DIR / "Prompt.md").read_text()
        api_kb = (_TASK_DIR / "kb" / "api_contract.md").read_text()
        worker_kb = (_TASK_DIR / "kb" / "worker_notes.md").read_text()

        for text in [prd, prompt, api_kb]:
            assert "GET /" in text
            assert "Doc Sync" in text
            assert "GET /admin/sync-jobs" in text
            assert "GET /admin/sync-jobs/{job_id}/history" in text
        assert "POST /documents" in prd
        assert "POST /sync-jobs" in prd
        assert "GET /sync-jobs/{job_id}" in prd
        assert "worker" in worker_kb.lower()
        assert "retry" in worker_kb.lower()
        assert "conflict" in worker_kb.lower()

    def test_pristine_fixture_fails(self, tmp_path):
        _copy_tree(_TASK_DIR / "fixture", tmp_path)
        code, result = _run_evaluator(tmp_path)

        assert code != 0
        assert result["score"] == "fail"
        assert result["checks"]["functional_browser_homepage"] is False
        assert result["checks"]["functional_document_and_job_flow"] is False

    def test_reference_solution_passes(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] >= 0.9
        assert result["checks"]["functional_browser_homepage"] is True
        assert result["checks"]["functional_document_and_job_flow"] is True
        assert result["checks"]["functional_retry_dedup_and_conflict_handling"] is True
        assert result["checks"]["functional_stale_reclaim_and_audit_history"] is True
        assert result["checks"]["functional_pagination_filtering_and_status_codes"] is True
        assert result["checks"]["functional_persistence_file_backed"] is True
        assert result["checks"]["plan_relevant"] is True
        assert result["checks"]["research_relevant"] is True
        assert result["checks"]["verify_relevant"] is True
        assert result["checks"]["review_relevant"] is True
        assert result["checks"]["appsec_relevant"] is True

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

    def test_in_memory_app_fails_persistence_requirement(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        (tmp_path / "app.py").write_text(_IN_MEMORY_APP)

        code, result = _run_evaluator(tmp_path)

        assert code != 0
        assert result["score"] == "fail"
        assert result["checks"]["functional_browser_homepage"] is False
        assert result["checks"]["functional_persistence_file_backed"] is False

    def test_missing_retry_and_worker_recovery_fail(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        (tmp_path / "worker.py").write_text(_NO_RETRY_WORKER)

        code, result = _run_evaluator(tmp_path)

        assert code != 0
        assert result["score"] == "fail"
        assert result["checks"]["functional_retry_dedup_and_conflict_handling"] is False
        assert result["checks"]["functional_stale_reclaim_and_audit_history"] is False

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

    def test_labeled_filler_workflow_artifacts_do_not_receive_full_credit(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        _write_labeled_filler_workflow_artifacts(tmp_path)

        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] < 0.9
        assert result["checks"]["plan_relevant"] is False
        assert result["checks"]["research_relevant"] is False
        assert result["checks"]["verify_relevant"] is False
        assert result["checks"]["review_relevant"] is False
        assert result["checks"]["appsec_relevant"] is False

    def test_prose_shaped_boilerplate_workflow_artifacts_do_not_receive_full_credit(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        _write_prose_shaped_boilerplate_workflow_artifacts(tmp_path)

        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] < 0.9
        assert result["checks"]["plan_relevant"] is False
        assert result["checks"]["research_relevant"] is False
        assert result["checks"]["verify_relevant"] is False
        assert result["checks"]["review_relevant"] is False
        assert result["checks"]["appsec_relevant"] is False
