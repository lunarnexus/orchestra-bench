#!/usr/bin/env bash
set -euo pipefail
python3 - "$@" <<'PY'
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess as sp
import sys
import time
import traceback
import urllib.error
import urllib.request

_eval_support_dir = Path(os.environ.get("BENCH_REPO_ROOT", "")).resolve()
if _eval_support_dir.is_dir():
    sys.path.insert(0, str(_eval_support_dir))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from capability_helpers import evaluate_workflow_evidence
from rubric_helpers import evaluate_rubric


def _workspace() -> Path:
    return Path(os.environ.get("BENCH_WORKDIR") or os.getcwd()).resolve()



def _body_contains(payload: str, *needles: str) -> bool:
    return all(n in payload for n in needles)


def _has_route_reference(payload: str, method: str, path: str) -> bool:
    """Accept either literal route documentation or ordinary HTML controls/links."""
    lowered = payload.lower()
    literal = f"{method} {path}"
    if literal in payload:
        return True
    if method == "GET":
        return f'href="{path}"' in payload or f"href='{path}'" in payload
    if method == "POST":
        has_action = f'action="{path}"' in payload or f"action='{path}'" in payload
        has_method = 'method="post"' in lowered or "method='post'" in lowered
        return has_action and has_method
    return False


def _audit_events_newest_first(payload: str, *events: str) -> bool:
    """Check event ordering in the audit section, not by a specific HTML tag."""
    section = payload
    marker = payload.lower().find("audit")
    if marker >= 0:
        section = payload[marker:]
    cursor = 0
    for event in events:
        pos = section.find(event, cursor)
        if pos < 0:
            return False
        cursor = pos + len(event)
    return True


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(port: int, method: str, path: str, *, data: dict | None = None, headers: dict | None = None) -> tuple[int, dict, str]:
    url = f"http://127.0.0.1:{port}{path}"
    body = None
    req_headers = dict(headers or {})
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, method=method, headers=req_headers)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=10) as resp:
            return resp.status, dict(resp.headers), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read().decode("utf-8", "replace")


def _header(headers: dict, name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def _start_server(workspace: Path, db_path: Path, port: int):
    env = os.environ.copy()
    env.update({"SHORTLINK_DB": str(db_path), "SHORTLINK_ADMIN_TOKEN": "shortlink-admin"})
    proc = sp.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=workspace,
        env=env,
        stdout=sp.PIPE,
        stderr=sp.PIPE,
        text=True,
    )
    last_error = ""
    for _ in range(40):
        if proc.poll() is not None:
            out, err = proc.communicate(timeout=2)
            raise RuntimeError(f"uvicorn exited early: {proc.returncode}\nstdout={out}\nstderr={err}")
        try:
            status, _, _ = _request(port, "GET", "/")
            if status < 500:
                return proc
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.25)
    proc.terminate()
    try:
        out, err = proc.communicate(timeout=5)
    except Exception:
        proc.kill(); out, err = proc.communicate(timeout=5)
    raise RuntimeError(f"uvicorn did not become ready: {last_error}\nstdout={out}\nstderr={err}")


def _stop_server(proc) -> None:
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
            proc.wait(timeout=5)


def _run_functional_checks(workspace: Path) -> tuple[dict[str, object], dict[str, object]]:
    checks = {
        "functional_homepage": False,
        "functional_normal_shorten_redirect_stats": False,
        "functional_duplicate_and_links_filtering": False,
        "functional_suspicious_review_flow": False,
        "functional_admin_auth_and_decision_errors": False,
        "functional_url_safety_and_escaping": False,
        "functional_audit_history": False,
        "functional_persistence_sqlite": False,
    }
    details: dict[str, object] = {}

    db_path = workspace / ".evaluator-shortlinks.sqlite3"
    if db_path.exists():
        db_path.unlink()
    port = 18123 + (os.getpid() % 1000)
    admin_headers = {"X-Admin-Token": "shortlink-admin"}

    proc = None
    try:
        proc = _start_server(workspace, db_path, port)

        homepage_status, homepage_headers, homepage_body = _request(port, "GET", "/")
        checks["functional_homepage"] = (
            homepage_status == 200
            and "text/html" in homepage_headers.get("Content-Type", homepage_headers.get("content-type", ""))
            and "ShortLink Desk" in homepage_body
            and _has_route_reference(homepage_body, "POST", "/shorten")
            and _has_route_reference(homepage_body, "GET", "/links")
            and ("GET /stats/{code}" in homepage_body or "/stats/{code}" in homepage_body or "/stats/{{code}}" in homepage_body or "/stats/" in homepage_body)
            and ("GET /s/{code}" in homepage_body or "/s/{code}" in homepage_body or "/s/{{code}}" in homepage_body or "/s/" in homepage_body)
            and _has_route_reference(homepage_body, "GET", "/admin/review")
            and "suspicious" in homepage_body.lower()
            and "stats" in homepage_body.lower()
        )

        created_status, _, created_body = _request(port, "POST", "/shorten", data={"url": "https://example.com/docs?x=1&y=2", "alias": "docs"})
        stats_before_status, _, stats_before_body = _request(port, "GET", "/stats/docs")
        redirect_status, redirect_headers, _ = _request(port, "GET", "/s/docs")
        stats_after_status, _, stats_after_body = _request(port, "GET", "/stats/docs")
        checks["functional_normal_shorten_redirect_stats"] = (
            created_status in (200, 201)
            and ("https://example.com/docs?x=1&y=2" in created_body or "https://example.com/docs?x=1&amp;y=2" in created_body)
            and _body_contains(created_body, "docs", "approved", "/s/docs", "/stats/docs")
            and stats_before_status == 200
            and "0" in stats_before_body
            and redirect_status in (301, 302, 303, 307, 308)
            and _header(redirect_headers, "Location") == "https://example.com/docs?x=1&y=2"
            and stats_after_status == 200
            and "1" in stats_after_body
        )

        duplicate_status, _, _ = _request(port, "POST", "/shorten", data={"url": "https://example.com/other", "alias": "docs"})
        listing_status, _, listing_body = _request(port, "GET", "/links?status=approved")
        bad_filter_status, _, _ = _request(port, "GET", "/links?status=weird")
        checks["functional_duplicate_and_links_filtering"] = (
            duplicate_status == 409
            and listing_status == 200
            and "docs" in listing_body
            and "approved" in listing_body
            and bad_filter_status == 400
        )

        pending_status, _, pending_body = _request(port, "POST", "/shorten", data={"url": "http://127.0.0.1:9999/admin", "alias": "local-admin"})
        pending_redirect_status, _, _ = _request(port, "GET", "/s/local-admin")
        review_no_auth_status, _, _ = _request(port, "GET", "/admin/review")
        review_status, _, review_body = _request(port, "GET", "/admin/review", headers=admin_headers)
        approved_status, _, _ = _request(port, "POST", "/admin/review/local-admin/decision", data={"decision": "approve", "reason": "Looks safe for this fixture"}, headers=admin_headers)
        approved_redirect_status, approved_redirect_headers, _ = _request(port, "GET", "/s/local-admin")
        checks["functional_suspicious_review_flow"] = (
            pending_status in (200, 201)
            and _body_contains(pending_body, "local-admin", "pending")
            and pending_redirect_status == 403
            and review_no_auth_status == 401
            and review_status == 200
            and "local-admin" in review_body
            and approved_status in (200, 204)
            and approved_redirect_status in (301, 302, 303, 307, 308)
            and _header(approved_redirect_headers, "Location") == "http://127.0.0.1:9999/admin"
        )

        second_decision_status, _, _ = _request(port, "POST", "/admin/review/local-admin/decision", data={"decision": "reject", "reason": "too late"}, headers=admin_headers)
        invalid_decision_status, _, _ = _request(port, "POST", "/admin/review/missing/decision", data={"decision": "approve", "reason": "missing"}, headers=admin_headers)
        bad_decision_status, _, _ = _request(port, "POST", "/admin/review/docs/decision", data={"decision": "maybe", "reason": "bad"}, headers=admin_headers)
        no_auth_decision_status, _, _ = _request(port, "POST", "/admin/review/docs/decision", data={"decision": "approve"})
        checks["functional_admin_auth_and_decision_errors"] = (
            second_decision_status == 409
            and invalid_decision_status == 404
            and bad_decision_status == 400
            and no_auth_decision_status == 401
        )

        js_status, _, _ = _request(port, "POST", "/shorten", data={"url": "javascript:alert(1)", "alias": "badjs"})
        data_status, _, _ = _request(port, "POST", "/shorten", data={"url": "data:text/html,hello", "alias": "baddata"})
        bad_alias_status, _, _ = _request(port, "POST", "/shorten", data={"url": "https://example.com", "alias": "bad alias!"})
        xss_status, _, _ = _request(port, "POST", "/shorten", data={"url": "https://example.com/?q=<script>alert(1)</script>", "alias": "xss"})
        xss_stats_status, _, xss_stats_body = _request(port, "GET", "/stats/xss")
        checks["functional_url_safety_and_escaping"] = (
            js_status == 422
            and data_status == 422
            and bad_alias_status == 422
            and xss_status in (200, 201)
            and xss_stats_status == 200
            and "<script>alert(1)</script>" not in xss_stats_body
            and "&lt;script&gt;" in xss_stats_body
        )

        local_stats_status, _, local_stats_body = _request(port, "GET", "/stats/local-admin")
        checks["functional_audit_history"] = (
            local_stats_status == 200
            and _audit_events_newest_first(local_stats_body, "redirected", "approved", "marked_pending")
            and "created" in local_stats_body
        )

        _stop_server(proc); proc = None
        proc = _start_server(workspace, db_path, port)
        reloaded_stats_status, _, reloaded_stats_body = _request(port, "GET", "/stats/docs")
        reloaded_redirect_status, reloaded_redirect_headers, _ = _request(port, "GET", "/s/docs")
        checks["functional_persistence_sqlite"] = (
            db_path.exists()
            and db_path.stat().st_size > 0
            and reloaded_stats_status == 200
            and "docs" in reloaded_stats_body
            and reloaded_redirect_status in (301, 302, 303, 307, 308)
            and _header(reloaded_redirect_headers, "Location") == "https://example.com/docs?x=1&y=2"
        )

        if db_path.exists():
            with sqlite3.connect(db_path) as conn:
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            details["sqlite_tables"] = sorted(tables)

        details.update({
            "port": port,
            "homepage_status": homepage_status,
            "created_status": created_status,
            "redirect_status": redirect_status,
            "redirect_location": _header(redirect_headers, "Location"),
            "duplicate_status": duplicate_status,
            "pending_status": pending_status,
            "approved_redirect_location": _header(approved_redirect_headers, "Location"),
        })
        return checks, details
    finally:
        _stop_server(proc)

def main() -> int:
    workspace = _workspace()
    task_id = os.environ.get("BENCH_TASK_ID", "cap-advanced-url-shortener-review")
    run_id = os.environ.get("BENCH_RUN_ID", "manual")
    checks: dict[str, object] = {}
    details: dict[str, object] = {}

    try:
        functional_checks, functional_details = _run_functional_checks(workspace)
        checks.update(functional_checks)
        details["functional_details"] = functional_details
    except Exception as exc:
        details["exception"] = str(exc)
        details["traceback"] = traceback.format_exc()
        for name in [
            "functional_homepage",
            "functional_normal_shorten_redirect_stats",
            "functional_duplicate_and_links_filtering",
            "functional_suspicious_review_flow",
            "functional_admin_auth_and_decision_errors",
            "functional_url_safety_and_escaping",
            "functional_audit_history",
            "functional_persistence_sqlite",
        ]:
            checks.setdefault(name, False)

    workflow = evaluate_workflow_evidence(
        workspace,
        artifact_specs={
            "plan": {"required_terms": ["route", "sqlite", "review"], "min_words": 25, "min_substantive_lines": 2},
            "research": {"required_terms": ["javascript:", "data:", "private", "escaping"], "min_words": 25, "min_substantive_lines": 2},
            "verify": {"required_terms": ["shorten", "redirect", "stats", "pending"], "min_words": 25, "min_substantive_lines": 2},
            "review": {"required_terms": ["duplicate", "audit", "status"], "min_words": 25, "min_substantive_lines": 2},
            "appsec": {"required_terms": ["xss", "admin", "private", "validation"], "min_words": 25, "min_substantive_lines": 2},
            "final_summary": {"weight": 0.0},
        },
        changed_files=["app.py"],
    )
    checks.update(workflow.get("checks", {}))
    details["workflow"] = workflow

    rubric = {
        "functional": {
            "weight": 0.70,
            "checks": {
                "functional_homepage": {"weight": 0.08, "critical": True},
                "functional_normal_shorten_redirect_stats": {"weight": 0.13, "critical": True},
                "functional_duplicate_and_links_filtering": {"weight": 0.07},
                "functional_suspicious_review_flow": {"weight": 0.14, "critical": True},
                "functional_admin_auth_and_decision_errors": {"weight": 0.07},
                "functional_url_safety_and_escaping": {"weight": 0.09, "critical": True},
                "functional_audit_history": {"weight": 0.05},
                "functional_persistence_sqlite": {"weight": 0.07, "critical": True},
            },
        },
        "workflow": {
            "weight": 0.30,
            "checks": {
                "plan_credit": {"weight": 0.06},
                "research_credit": {"weight": 0.06},
                "verify_credit": {"weight": 0.06},
                "review_credit": {"weight": 0.06},
                "appsec_credit": {"weight": 0.06},
            },
        },
    }
    scored = evaluate_rubric(rubric, checks, threshold=0.70)
    result = {
        "task_id": task_id,
        "run_id": run_id,
        "score": scored["score"],
        "score_numeric": scored["score_numeric"],
        "checks": scored["checks"],
        "rubric": scored["rubric"],
        "details": json.dumps(details, sort_keys=True),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["score"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
PY
