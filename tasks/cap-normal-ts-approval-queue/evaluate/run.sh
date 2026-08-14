#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
from __future__ import annotations

import json
import os
import shutil
import subprocess as sp
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

repo_root = Path(os.environ.get("BENCH_REPO_ROOT", "/bench"))
sys.path.insert(0, str(repo_root))

from capability_helpers import evaluate_workflow_evidence
from rubric_helpers import evaluate_rubric

workspace = Path.cwd()
task_id = os.environ.get("BENCH_CURRENT_TASK", "cap-normal-ts-approval-queue")
tasks_root = Path(os.environ.get("BENCH_TASKS", repo_root / "tasks"))
fixture_root = tasks_root / task_id / "fixture"


def _changed_files() -> list[str]:
    candidates = ["package.json", "src/server.ts", "tests/api.test.ts"]
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
        "src/server.ts",
        "tests/api.test.ts",
        "persistence",
        "approved",
        "rejected",
        "pagination",
        "xss",
        "attachment",
    ]
    return {
        "plan": {
            "min_words": 35,
            "min_substantive_lines": 2,
            "evidence_terms": shared_terms,
            "min_evidence_terms": 3,
            "required_terms": [
                "POST /submissions",
                "GET /public/submissions",
                "POST /admin/submissions/:id/decision",
                "src/server.ts",
                "tests/api.test.ts",
                "node --test --experimental-strip-types tests/api.test.ts",
            ],
            "required_patterns": [
                r"(?mi)^\s*(?:[-*]\s*)?(?:1\.\s|step\s*1\b)",
                r"(?mi)^\s*(?:[-*]\s*)?(?:2\.\s|step\s*2\b)",
            ],
        },
        "research": {
            "min_words": 35,
            "min_substantive_lines": 2,
            "evidence_terms": ["kb", "TypeScript", "Node", "attachment", "tradeoff"],
            "min_evidence_terms": 2,
            "required_terms": ["kb", "TypeScript", "attachment_name", "APPROVAL_QUEUE_DATA_FILE", "avoid extra ORM"],
            "required_patterns": [
                r"(?mi)^\s*[-*]?\s*source\s*:",
                r"(?mi)^\s*[-*]?\s*decision\s*:",
                r"(?mi)^\s*[-*]?\s*tradeoff\s*:",
            ],
        },
        "verify": {
            "min_words": 30,
            "min_substantive_lines": 1,
            "evidence_terms": shared_terms,
            "min_evidence_terms": 2,
            "required_terms": ["node --test --experimental-strip-types tests/api.test.ts", "passed"],
            "required_patterns": [
                r"(?mi)^\s*[-*]?\s*command\s*:",
                r"(?mi)^\s*[-*]?\s*result\s*:",
            ],
        },
        "review": {
            "min_words": 30,
            "min_substantive_lines": 2,
            "evidence_terms": ["response schemas", "status", "audit", "pagination", "risk"],
            "min_evidence_terms": 2,
            "required_terms": ["response schemas", "400", "401", "404", "422"],
            "required_patterns": [
                r"(?mi)^\s*[-*]?\s*finding\s*:",
                r"(?mi)^\s*[-*]?\s*risk\s*:",
            ],
        },
        "appsec": {
            "min_words": 30,
            "min_substantive_lines": 2,
            "evidence_terms": ["xss", "attachment_name", "validation", "token", "audit"],
            "min_evidence_terms": 2,
            "required_terms": ["attachment_name", "X-Admin-Token", "path traversal"],
            "required_patterns": [
                r"(?mi)^\s*[-*]?\s*threat\s*:",
                r"(?mi)^\s*[-*]?\s*mitigation\s*:",
            ],
        },
    }


def _json_request(method: str, url: str, payload: dict | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, method=method, data=data)
    request.add_header("content-type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            raw = response.read().decode("utf-8")
            return response.getcode(), json.loads(raw or "{}")
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8")
        return error.code, json.loads(raw or "{}")


def _wait_for_health(base_url: str) -> bool:
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=2) as response:
                if response.getcode() == 200:
                    return True
        except Exception:
            time.sleep(0.1)
    return False


def _unwrap_collection(payload: dict | object, *keys: str) -> dict:
    if not isinstance(payload, dict):
        return {}
    for key in keys:
        candidate = payload.get(key)
        if isinstance(candidate, dict):
            return candidate
    return payload


def _attachment_stored_path(payload: dict | object) -> str | None:
    if not isinstance(payload, dict):
        return None
    attachment = payload.get("attachment")
    if isinstance(attachment, dict):
        for key in ["stored_path", "storage_path", "upload_path", "path"]:
            value = attachment.get(key)
            if isinstance(value, str) and value:
                return value
    for key in ["attachment_stored_path", "stored_path", "upload_path", "attachment_path"]:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _run_functional_checks() -> tuple[dict[str, bool], dict[str, object]]:
    node = shutil.which("node")
    if not node:
        checks = {
            "functional_browser_homepage": False,
            "functional_submission_and_moderation_flow": False,
            "functional_public_visibility_and_sanitization": False,
            "functional_attachment_security_and_audit_history": False,
            "functional_pagination_filtering_and_status_codes": False,
            "functional_persistence_file_backed": False,
        }
        return checks, {"mode": "node-unavailable", "node_available": False}

    port = 3229
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update(
        {
            "PORT": str(port),
            "APPROVAL_QUEUE_DATA_FILE": str(workspace / ".evaluator-approval-queue.json"),
            "APPROVAL_QUEUE_UPLOAD_DIR": str(workspace / ".evaluator-uploads"),
            "APPROVAL_QUEUE_ADMIN_TOKEN": "queue-admin",
        }
    )
    data_path = Path(env["APPROVAL_QUEUE_DATA_FILE"])
    upload_dir = Path(env["APPROVAL_QUEUE_UPLOAD_DIR"])
    if data_path.exists():
        data_path.unlink()
    if upload_dir.exists():
        shutil.rmtree(upload_dir)

    process = sp.Popen(
        [node, "--experimental-strip-types", "src/server.ts"],
        cwd=workspace,
        env=env,
        stdout=sp.PIPE,
        stderr=sp.PIPE,
        text=True,
    )
    stdout = ""
    stderr = ""
    try:
        if not _wait_for_health(base_url):
            process.terminate()
            out, err = process.communicate(timeout=5)
            checks = {
                "functional_browser_homepage": False,
                "functional_submission_and_moderation_flow": False,
                "functional_public_visibility_and_sanitization": False,
                "functional_attachment_security_and_audit_history": False,
                "functional_pagination_filtering_and_status_codes": False,
                "functional_persistence_file_backed": False,
            }
            return checks, {"startup_failed": True, "stdout": out, "stderr": err, "returncode": process.returncode}

        homepage_request = urllib.request.Request(f"{base_url}/", headers={"accept": "text/html"})
        try:
            with urllib.request.urlopen(homepage_request, timeout=5) as response:
                homepage_status = response.getcode()
                homepage_type = response.headers.get("content-type", "")
                homepage_html = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            homepage_status = error.code
            homepage_type = error.headers.get("content-type", "")
            homepage_html = error.read().decode("utf-8")

        unauthorized_status, _ = _json_request("GET", f"{base_url}/admin/submissions")
        traversal_status, _ = _json_request(
            "POST",
            f"{base_url}/submissions",
            {
                "title": "Bad attachment",
                "submitter_email": "bad@example.test",
                "body": "bad",
                "attachment_name": "../secret.txt",
                "attachment_content": "oops",
            },
        )
        first_status, first_payload = _json_request(
            "POST",
            f"{base_url}/submissions",
            {
                "title": "Launch <script>alert(1)</script>",
                "submitter_email": "author@example.test",
                "body": "Body <script>alert(2)</script>",
                "attachment_name": "launch-plan.pdf",
                "attachment_content": "hello world",
            },
        )
        second_status, second_payload = _json_request(
            "POST",
            f"{base_url}/submissions",
            {
                "title": "Reject me",
                "submitter_email": "reject@example.test",
                "body": "plain text",
                "attachment_name": "notes.txt",
                "attachment_content": "notes",
            },
        )
        pre_public_status, pre_public = _json_request("GET", f"{base_url}/public/submissions")
        approve_status, approve_payload = _json_request(
            "POST",
            f"{base_url}/admin/submissions/{first_payload.get('id')}/decision",
            {"decision": "approved", "note": "safe to publish"},
            {"X-Admin-Token": "queue-admin"},
        )
        reject_status, reject_payload = _json_request(
            "POST",
            f"{base_url}/admin/submissions/{second_payload.get('id')}/decision",
            {"decision": "rejected", "note": "needs cleanup"},
            {"X-Admin-Token": "queue-admin"},
        )
        public_status, public_payload = _json_request("GET", f"{base_url}/public/submissions?page=1&page_size=1")
        admin_rejected_status, admin_rejected = _json_request(
            "GET",
            f"{base_url}/admin/submissions?status=rejected&page=1&page_size=5",
            headers={"X-Admin-Token": "queue-admin"},
        )
        history_status, history_payload = _json_request(
            "GET",
            f"{base_url}/admin/submissions/{first_payload.get('id')}/history",
            headers={"X-Admin-Token": "queue-admin"},
        )
        bad_page_status, _ = _json_request("GET", f"{base_url}/public/submissions?page=0")
        missing_status, _ = _json_request(
            "POST",
            f"{base_url}/admin/submissions/999/decision",
            {"decision": "approved", "note": "missing"},
            {"X-Admin-Token": "queue-admin"},
        )
        invalid_json_request = urllib.request.Request(
            f"{base_url}/submissions",
            method="POST",
            data=b"{",
            headers={"content-type": "application/json"},
        )
        try:
            urllib.request.urlopen(invalid_json_request, timeout=5)
            invalid_json_status = 200
        except urllib.error.HTTPError as error:
            invalid_json_status = error.code

        first_attachment = _attachment_stored_path(first_payload)
        attachment_prefix = f"{upload_dir.name}/"
        public_listing = _unwrap_collection(public_payload, "submissions", "results", "data")
        public_items = public_listing.get("items", []) if isinstance(public_listing, dict) else []
        public_item = public_items[0] if public_items else {}
        history_listing = _unwrap_collection(history_payload, "history", "audit", "data")
        history_items = history_listing.get("items", []) if isinstance(history_listing, dict) else []
        admin_rejected_listing = _unwrap_collection(admin_rejected, "submissions", "results", "data")
        rejected_items = admin_rejected_listing.get("items", []) if isinstance(admin_rejected_listing, dict) else []
        required_submission_fields = {"id", "title", "submitter_email", "status", "created_at", "updated_at"}
        first_fields_ok = isinstance(first_payload, dict) and required_submission_fields.issubset(first_payload.keys())
        public_fields_ok = {
            "id",
            "title_html",
            "body_html",
            "status",
            "created_at",
            "updated_at",
        }.issubset(public_item.keys())
        audit_fields_ok = bool(history_items) and {
            "id",
            "submission_id",
            "action",
            "detail",
            "created_at",
        }.issubset(history_items[0].keys())

        checks = {
            "functional_browser_homepage": (
                homepage_status == 200
                and "text/html" in homepage_type.lower()
                and "<title>Approval Queue</title>" in homepage_html
                and "<h1>Approval Queue</h1>" in homepage_html
                and "POST /submissions" in homepage_html
                and "GET /public/submissions" in homepage_html
                and "GET /admin/submissions" in homepage_html
                and "POST /admin/submissions/{id}/decision" in homepage_html
                and "GET /admin/submissions/{id}/history" in homepage_html
                and "X-Admin-Token" in homepage_html
            ),
            "functional_submission_and_moderation_flow": (
                first_status == 201
                and second_status == 201
                and first_fields_ok
                and approve_status == 200
                and reject_status == 200
                and approve_payload.get("status") == "approved"
                and reject_payload.get("status") == "rejected"
            ),
            "functional_public_visibility_and_sanitization": (
                pre_public_status == 200
                and pre_public.get("total") == 0
                and public_status == 200
                and public_listing.get("total") == 1
                and public_fields_ok
                and public_item.get("status") == "approved"
                and "<script>" not in str(public_item.get("body_html", ""))
                and "&lt;script&gt;" in str(public_item.get("body_html", ""))
            ),
            "functional_attachment_security_and_audit_history": (
                traversal_status == 422
                and isinstance(first_attachment, str)
                and first_attachment.startswith(attachment_prefix)
                and ".." not in first_attachment
                and not first_attachment.startswith("/")
                and (workspace / first_attachment).exists()
                and history_status == 200
                and history_listing.get("total") == 2
                and audit_fields_ok
                and [item.get("action") for item in history_items] == ["approved", "submitted"]
            ),
            "functional_pagination_filtering_and_status_codes": (
                unauthorized_status == 401
                and admin_rejected_status == 200
                and admin_rejected_listing.get("total") == 1
                and rejected_items
                and rejected_items[0].get("status") == "rejected"
                and bad_page_status == 400
                and invalid_json_status == 400
                and missing_status == 404
            ),
            "functional_persistence_file_backed": False,
        }

        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=5)
        except sp.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)

        process = sp.Popen(
            [node, "--experimental-strip-types", "src/server.ts"],
            cwd=workspace,
            env=env,
            stdout=sp.PIPE,
            stderr=sp.PIPE,
            text=True,
        )
        if _wait_for_health(base_url):
            persisted_status, persisted_payload = _json_request("GET", f"{base_url}/public/submissions")
            persisted_listing = _unwrap_collection(persisted_payload, "submissions", "results", "data")
            checks["functional_persistence_file_backed"] = (
                data_path.exists()
                and data_path.stat().st_size > 0
                and upload_dir.exists()
                and persisted_status == 200
                and persisted_listing.get("total") == 1
                and (persisted_listing.get("items") or [{}])[0].get("status") == "approved"
            )
        else:
            persisted_status, persisted_payload = 0, {}

        details = {
            "homepage_status": homepage_status,
            "homepage_type": homepage_type,
            "homepage_excerpt": homepage_html[:500],
            "first_payload": first_payload,
            "second_payload": second_payload,
            "pre_public": pre_public,
            "public_payload": public_payload,
            "history_payload": history_payload,
            "admin_rejected": admin_rejected,
            "data_path": str(data_path),
            "data_exists": data_path.exists(),
            "data_size": data_path.stat().st_size if data_path.exists() else 0,
            "upload_dir": str(upload_dir),
            "upload_files": sorted(str(path.relative_to(workspace)) for path in upload_dir.rglob("*") if path.is_file()) if upload_dir.exists() else [],
            "persisted_status": persisted_status,
            "persisted_payload": persisted_payload,
        }
        return checks, details
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                out, err = process.communicate(timeout=5)
            except sp.TimeoutExpired:
                process.kill()
                out, err = process.communicate(timeout=5)
            stdout += out
            stderr += err


def _default_fail_checks() -> dict[str, bool]:
    return {
        "functional_browser_homepage": False,
        "functional_submission_and_moderation_flow": False,
        "functional_public_visibility_and_sanitization": False,
        "functional_attachment_security_and_audit_history": False,
        "functional_pagination_filtering_and_status_codes": False,
        "functional_persistence_file_backed": False,
    }


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
            "functional_submission_and_moderation_flow": {"weight": 0.12, "critical": True},
            "functional_public_visibility_and_sanitization": {"weight": 0.12, "critical": True},
            "functional_attachment_security_and_audit_history": {"weight": 0.14, "critical": True},
            "functional_pagination_filtering_and_status_codes": {"weight": 0.08},
            "functional_persistence_file_backed": {"weight": 0.14, "critical": True},
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
            "verify_mentions_changed_files": {"weight": 0.02},
            "review_relevant": {"weight": 0.02},
            "appsec_relevant": {"weight": 0.02},
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
