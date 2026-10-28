#!/usr/bin/env bash
set -euo pipefail
eval_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export EVAL_DIR="$eval_dir"
export PYTHONPATH="${eval_dir}${PYTHONPATH:+:${PYTHONPATH}}"
python3 - "$@" <<'PY'
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess as sp
import sys
import time
import traceback
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


CHECK_NAMES = [
    "app_starts_and_homepage_documents_routes",
    "schema_initializes_and_persists",
    "ledger_import_is_idempotent",
    "settlement_import_is_idempotent",
    "happy_path_reconciliation_matches_records",
    "tier_tolerance_policy_applied",
    "network_b_late_window_policy_applied",
    "refund_reversal_policy_applied",
    "duplicates_and_unexpected_settlements_detected",
    "exception_queue_and_admin_auth_work",
    "manual_decision_requires_reason_and_audits",
    "audit_history_newest_first",
    "daily_report_totals_apply_exclusions",
    "merchant_report_includes_audit_and_exceptions",
    "csv_export_is_deterministic_and_safe",
    "html_escaping_blocks_script_injection",
    "data_survives_app_restart",
]

# --- Evaluator-defined truth -------------------------------------------------
# Ledger batch (all posted 2025-06-01, all USD unless noted):
#   TX-1001 M-100 standard  100.00   TX-1002 M-100 standard   50.00
#   TX-2001 M-200 premium  1000.00   TX-3001 M-300 training  250.00
#   TX-4001 M-400 standard   75.00   TX-6001 M-500 standard   60.00 (x2, dup id)
#   TX-9001 M-100 standard  -40.00   (refund, original TX-1001)
#   TX-8001 M-500 standard   20.00   TX-1101 M-100 standard   30.00
#   TX-1201 M-100 standard   80.00   TX-1301 M-900 standard    15.00
# Executive daily total (training excluded): 1450.00; with training: 1700.00.
#
# network_a (2-day late window):
#   TX-1001 100.00 in-time; TX-1002 50.01 within standard tol 0.01;
#   TX-2001 1000.99 within premium tol 1.00; TX-4001 75.00 EUR (currency
#   mismatch vs USD ledger); TX-7001 10.00 (unexpected, no ledger entry);
#   TX-6001 60.00 (one of two ledger rows); refund orig TX-1001 -40.00
#   (matches ledger TX-9001 via original id); refund orig TX-9999 -15.00
#   (refund/reversal mismatch, no original); TX-1201 80.20 (0.20 > 0.01
#   standard tolerance -> amount mismatch).
# network_b (5-day late window):
#   TX-3001 settled 2025-06-06 (5 days -> NOT late on network B);
#   TX-1101 settled 2025-06-08 (7 days -> late even on network B).
#
# Expected run-1 exceptions (9): amount_mismatch TX-1201, currency_mismatch
# TX-4001, missing_settlement TX-8001, missing_settlement TX-1301,
# missing_settlement TX-6001, late_settlement TX-1101,
# duplicate_transaction_id TX-6001, unexpected_settlement TX-7001,
# refund_reversal_mismatch (original TX-9999). Matched >= 6.

LEDGER_BATCH = {
    "batch_id": "ledger-batch-1",
    "records": [
        {"record_id": "L1", "transaction_id": "TX-1001", "merchant_id": "M-100", "merchant_name": "Acme Foods", "merchant_tier": "standard", "amount": 100.00, "currency": "USD", "posted_on": "2025-06-01", "original_transaction_id": None},
        {"record_id": "L2", "transaction_id": "TX-1002", "merchant_id": "M-100", "merchant_name": "Acme Foods", "merchant_tier": "standard", "amount": 50.00, "currency": "USD", "posted_on": "2025-06-01", "original_transaction_id": None},
        {"record_id": "L3", "transaction_id": "TX-2001", "merchant_id": "M-200", "merchant_name": "Northwind Trading", "merchant_tier": "premium", "amount": 1000.00, "currency": "USD", "posted_on": "2025-06-01", "original_transaction_id": None},
        {"record_id": "L4", "transaction_id": "TX-3001", "merchant_id": "M-300", "merchant_name": "Training Corp", "merchant_tier": "training", "amount": 250.00, "currency": "USD", "posted_on": "2025-06-01", "original_transaction_id": None},
        {"record_id": "L5", "transaction_id": "TX-4001", "merchant_id": "M-400", "merchant_name": "Euro Bistro", "merchant_tier": "standard", "amount": 75.00, "currency": "USD", "posted_on": "2025-06-01", "original_transaction_id": None},
        {"record_id": "L6", "transaction_id": "TX-6001", "merchant_id": "M-500", "merchant_name": "Harbor Goods", "merchant_tier": "standard", "amount": 60.00, "currency": "USD", "posted_on": "2025-06-01", "original_transaction_id": None},
        {"record_id": "L7", "transaction_id": "TX-6001", "merchant_id": "M-500", "merchant_name": "Harbor Goods", "merchant_tier": "standard", "amount": 60.00, "currency": "USD", "posted_on": "2025-06-01", "original_transaction_id": None},
        {"record_id": "L8", "transaction_id": "TX-9001", "merchant_id": "M-100", "merchant_name": "Acme Foods", "merchant_tier": "standard", "amount": -40.00, "currency": "USD", "posted_on": "2025-06-01", "original_transaction_id": "TX-1001"},
        {"record_id": "L9", "transaction_id": "TX-8001", "merchant_id": "M-500", "merchant_name": "Harbor Goods", "merchant_tier": "standard", "amount": 20.00, "currency": "USD", "posted_on": "2025-06-01", "original_transaction_id": None},
        {"record_id": "L10", "transaction_id": "TX-1101", "merchant_id": "M-100", "merchant_name": "Acme Foods", "merchant_tier": "standard", "amount": 30.00, "currency": "USD", "posted_on": "2025-06-01", "original_transaction_id": None},
        {"record_id": "L11", "transaction_id": "TX-1201", "merchant_id": "M-100", "merchant_name": "Acme Foods", "merchant_tier": "standard", "amount": 80.00, "currency": "USD", "posted_on": "2025-06-01", "original_transaction_id": None},
        {"record_id": "L12", "transaction_id": "TX-1301", "merchant_id": "M-900", "merchant_name": "<script>alert(1)</script>Shop", "merchant_tier": "standard", "amount": 15.00, "currency": "USD", "posted_on": "2025-06-01", "original_transaction_id": None},
    ],
}

SETTLEMENT_BATCH_A = {
    "batch_id": "settle-a-1",
    "records": [
        {"record_id": "S1", "transaction_id": "TX-1001", "amount": 100.00, "currency": "USD", "settled_on": "2025-06-02", "original_transaction_id": None},
        {"record_id": "S2", "transaction_id": "TX-1002", "amount": 50.01, "currency": "USD", "settled_on": "2025-06-02", "original_transaction_id": None},
        {"record_id": "S3", "transaction_id": "TX-2001", "amount": 1000.99, "currency": "USD", "settled_on": "2025-06-02", "original_transaction_id": None},
        {"record_id": "S4", "transaction_id": "TX-4001", "amount": 75.00, "currency": "EUR", "settled_on": "2025-06-02", "original_transaction_id": None},
        {"record_id": "S5", "transaction_id": "TX-7001", "amount": 10.00, "currency": "USD", "settled_on": "2025-06-02", "original_transaction_id": None},
        {"record_id": "S6", "transaction_id": "TX-6001", "amount": 60.00, "currency": "USD", "settled_on": "2025-06-02", "original_transaction_id": None},
        {"record_id": "S7", "transaction_id": "SETTLE-RF-1", "amount": -40.00, "currency": "USD", "settled_on": "2025-06-02", "original_transaction_id": "TX-1001"},
        {"record_id": "S8", "transaction_id": "SETTLE-RF-2", "amount": -15.00, "currency": "USD", "settled_on": "2025-06-02", "original_transaction_id": "TX-9999"},
        {"record_id": "S9", "transaction_id": "TX-1201", "amount": 80.20, "currency": "USD", "settled_on": "2025-06-02", "original_transaction_id": None},
    ],
}

SETTLEMENT_BATCH_B = {
    "batch_id": "settle-b-1",
    "records": [
        {"record_id": "SB1", "transaction_id": "TX-3001", "amount": 250.00, "currency": "USD", "settled_on": "2025-06-06", "original_transaction_id": None},
        {"record_id": "SB2", "transaction_id": "TX-1101", "amount": 30.00, "currency": "USD", "settled_on": "2025-06-08", "original_transaction_id": None},
    ],
}

DAILY_DATE = "2025-06-01"
EXPECTED_EXECUTIVE_TOTAL = 1450.00
EXPECTED_WITH_TRAINING_TOTAL = 1700.00
ADMIN_TOKEN = "recon-admin"


def _workspace() -> Path:
    return Path(os.environ.get("BENCH_WORKDIR") or os.getcwd()).resolve()


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


def _json(body: str) -> dict:
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _has_route_reference(payload: str, method: str, path: str) -> bool:
    """Accept route documentation or HTML controls with equivalent parameter names."""
    payload = re.sub(r"\{[A-Za-z_][A-Za-z0-9_]*\}", "{parameter}", payload)
    path = re.sub(r"\{[A-Za-z_][A-Za-z0-9_]*\}", "{parameter}", path)
    lowered = payload.lower()
    if f"{method} {path}" in payload:
        return True
    if method == "GET":
        return f'href="{path}"' in payload or f"href='{path}'" in payload
    if method == "POST":
        has_action = f'action="{path}"' in payload or f"action='{path}'" in payload
        has_method = 'method="post"' in lowered or "method='post'" in lowered
        return has_action and has_method
    return False


def _start_server(workspace: Path, db_path: Path, port: int):
    env = os.environ.copy()
    env.update({"RECON_DB": str(db_path), "RECON_ADMIN_TOKEN": ADMIN_TOKEN})
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
        proc.kill()
        out, err = proc.communicate(timeout=5)
    raise RuntimeError(f"uvicorn did not become ready: {last_error}\nstdout={out}\nstderr={err}")


def _stop_server(proc) -> None:
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
            proc.wait(timeout=5)


def _collection_items(payload: dict, *keys: str) -> list:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    for key in keys:
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
        if isinstance(candidate, dict):
            for inner in ("items", "results", "records"):
                nested = candidate.get(inner)
                if isinstance(nested, list):
                    return [item for item in nested if isinstance(item, dict)]
    return []


def _item_field(item: dict, *keys: str) -> object:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _normalize_category(value: object) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _exceptions_for(items: list, *, transaction_id: str | None = None, category: str | None = None) -> list:
    found = []
    for item in items:
        tx = str(_item_field(item, "transaction_id", "tx_id", "transaction") or "")
        cat = _normalize_category(_item_field(item, "category", "type", "kind", "status"))
        if transaction_id and transaction_id not in tx:
            continue
        if category and category not in cat:
            continue
        found.append(item)
    return found


def _find_number(payload: dict, *keys: str) -> float | None:
    """Recursively find the first numeric value under any candidate key."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in keys and isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        for value in payload.values():
            if isinstance(value, (dict, list)):
                found = _find_number(value, *keys) if isinstance(value, dict) else None
                if found is not None:
                    return found
    elif isinstance(payload, list):
        for value in payload:
            if isinstance(value, dict):
                found = _find_number(value, *keys)
                if found is not None:
                    return found
    return None


def _audit_section(body: str) -> str:
    marker = body.lower().find("audit")
    return body[marker:] if marker >= 0 else ""


def _report_state_counts(payload: object) -> dict[str, float] | None:
    """Read documented exception-state counts independently of response wrappers."""
    states = ("pending", "approved", "rejected", "manually_adjusted")
    if isinstance(payload, str):
        try:
            return _report_state_counts(json.loads(payload))
        except ValueError:
            pass
        parts = []

        class ReportText(HTMLParser):
            def handle_data(self, data):
                parts.append(data)

        parser = ReportText()
        parser.feed(payload)
        text = " ".join(parts).lower()
        marker = re.search(r"(?:counts\s+by\s+state|state\s+counts)", text)
        if marker is None:
            return None
        pairs = re.findall(r"\b(pending|approved|rejected|manually_adjusted)\b\s*:?\s*(\d+(?:\.\d+)?)\b", text[marker.end():])
        counts = {}
        for state, count in pairs:
            counts.setdefault(state, float(count))
        return {state: counts.get(state, 0) for state in states} if counts else None
    if not isinstance(payload, dict):
        return None
    if any(state in payload for state in states):
        counts = {state: payload.get(state, 0) for state in states}
        if all(isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
               for value in counts.values()):
            return counts
    for value in payload.values():
        found = _report_state_counts(value)
        if found is not None:
            return found
    return None


def _run_functional_checks(workspace: Path) -> tuple[dict[str, bool], dict[str, object]]:
    checks = {name: False for name in CHECK_NAMES}
    details: dict[str, object] = {}

    db_path = workspace / ".evaluator-recon.sqlite3"
    if db_path.exists():
        db_path.unlink()
    port = 18203 + (os.getpid() % 900)
    admin_headers = {"X-Admin-Token": ADMIN_TOKEN}

    proc = None
    try:
        proc = _start_server(workspace, db_path, port)

        # 1. Homepage documents the route surface.
        homepage_status, homepage_headers, homepage_body = _request(port, "GET", "/")
        checks["app_starts_and_homepage_documents_routes"] = (
            homepage_status == 200
            and "text/html" in (homepage_headers.get("Content-Type") or homepage_headers.get("content-type") or "")
            and "Reconciliation" in homepage_body
            and _has_route_reference(homepage_body, "POST", "/imports/ledger")
            and _has_route_reference(homepage_body, "POST", "/imports/settlements/{network}")
            and _has_route_reference(homepage_body, "POST", "/reconcile/run")
            and _has_route_reference(homepage_body, "GET", "/admin/exceptions")
            and _has_route_reference(homepage_body, "POST", "/admin/exceptions/{id}/decision")
            and _has_route_reference(homepage_body, "GET", "/reports/daily")
            and _has_route_reference(homepage_body, "GET", "/reports/merchant/{merchant_id}")
            and _has_route_reference(homepage_body, "GET", "/reports/exceptions")
            and _has_route_reference(homepage_body, "GET", "/exports/reconciliation.csv")
        )

        # 3. Ledger import, idempotent on re-import.
        ledger_status, _, _ = _request(port, "POST", "/imports/ledger", data=LEDGER_BATCH)
        ledger_again_status, _, _ = _request(port, "POST", "/imports/ledger", data=LEDGER_BATCH)
        daily_after_import_status, _, daily_after_import_body = _request(port, "GET", f"/reports/daily?date={DAILY_DATE}")
        daily_after_import = _json(daily_after_import_body)
        total_after_import = _find_number(daily_after_import, "total_amount", "executive_total", "total", "sum_amount", "gross_amount")
        checks["ledger_import_is_idempotent"] = (
            ledger_status in (200, 201)
            and ledger_again_status in (200, 201)
            and total_after_import is not None
            and abs(total_after_import - EXPECTED_EXECUTIVE_TOTAL) <= 0.01
        )

        # 2. SQLite schema initialized and persisted.
        schema_ok = False
        if db_path.exists() and db_path.stat().st_size > 0:
            try:
                with sqlite3.connect(db_path) as conn:
                    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                schema_ok = len(tables) >= 1
                details["sqlite_tables"] = sorted(tables)
            except sqlite3.DatabaseError as exc:
                details["sqlite_error"] = str(exc)
        checks["schema_initializes_and_persists"] = schema_ok

        # 4. Settlement imports, idempotent on re-import.
        settle_a_status, _, _ = _request(port, "POST", "/imports/settlements/network_a", data=SETTLEMENT_BATCH_A)
        settle_b_status, _, _ = _request(port, "POST", "/imports/settlements/network_b", data=SETTLEMENT_BATCH_B)
        run1_status, _, run1_body = _request(port, "POST", "/reconcile/run")
        run1 = _json(run1_body)
        settle_a_again_status, _, _ = _request(port, "POST", "/imports/settlements/network_a", data=SETTLEMENT_BATCH_A)
        settle_b_again_status, _, _ = _request(port, "POST", "/imports/settlements/network_b", data=SETTLEMENT_BATCH_B)
        run2_status, _, run2_body = _request(port, "POST", "/reconcile/run")
        run2 = _json(run2_body)

        def _run_counts(run: dict) -> dict[str, float | None]:
            return {
                "matched": _find_number(run, "matched", "matched_count"),
                "exceptions": _find_number(run, "exceptions", "exception_count", "unmatched"),
            }

        counts1 = _run_counts(run1)
        counts2 = _run_counts(run2)
        checks["settlement_import_is_idempotent"] = (
            settle_a_status in (200, 201)
            and settle_b_status in (200, 201)
            and settle_a_again_status in (200, 201)
            and settle_b_again_status in (200, 201)
            and run1_status == 200
            and run2_status == 200
            and counts1["matched"] is not None
            and counts2["matched"] is not None
            and counts1["matched"] == counts2["matched"]
            and (counts1["exceptions"] is None or counts1["exceptions"] == counts2["exceptions"])
        )

        # 5. Happy path reconciliation.
        run_id = _item_field(run1, "run_id", "id")
        checks["happy_path_reconciliation_matches_records"] = (
            run1_status == 200
            and bool(run_id)
            and counts1["matched"] is not None
            and counts1["matched"] >= 6
        )

        exceptions_status, _, exceptions_body = _request(port, "GET", "/admin/exceptions", headers=admin_headers)
        exceptions_payload = _json(exceptions_body)
        exception_items = _collection_items(exceptions_payload, "exceptions", "items", "results")
        exceptions_total = _find_number(exceptions_payload, "total")
        if exceptions_total is None:
            exceptions_total = float(len(exception_items))

        # 6. Tier tolerance: within-tolerance rows matched, out-of-tolerance row excepted.
        checks["tier_tolerance_policy_applied"] = (
            not _exceptions_for(exception_items, transaction_id="TX-1002", category="amount_mismatch")
            and not _exceptions_for(exception_items, transaction_id="TX-2001", category="amount_mismatch")
            and bool(_exceptions_for(exception_items, transaction_id="TX-1201", category="amount_mismatch"))
        )

        # 7. Network B late window: TX-3001 (5 days) not late, TX-1101 (7 days) late.
        checks["network_b_late_window_policy_applied"] = (
            not _exceptions_for(exception_items, transaction_id="TX-3001", category="late_settlement")
            and bool(_exceptions_for(exception_items, transaction_id="TX-1101", category="late_settlement"))
        )

        # 8. Refund/reversal matching by original id.
        checks["refund_reversal_policy_applied"] = (
            not _exceptions_for(exception_items, transaction_id="TX-9001", category="refund_reversal_mismatch")
            and not _exceptions_for(exception_items, transaction_id="TX-1001", category="refund_reversal_mismatch")
            and bool(
                _exceptions_for(exception_items, category="refund_reversal_mismatch")
                and any("TX-9999" in json.dumps(item) for item in _exceptions_for(exception_items, category="refund_reversal_mismatch"))
            )
        )

        # 9. Duplicates and unexpected/missing settlements.
        checks["duplicates_and_unexpected_settlements_detected"] = (
            bool(_exceptions_for(exception_items, transaction_id="TX-6001", category="duplicate_transaction_id"))
            and bool(_exceptions_for(exception_items, transaction_id="TX-7001", category="unexpected_settlement"))
            and bool(_exceptions_for(exception_items, transaction_id="TX-8001", category="missing_settlement"))
        )

        # 10. Exception queue and admin auth.
        no_auth_status, _, _ = _request(port, "GET", "/admin/exceptions")
        missing_decision_status, _, _ = _request(
            port,
            "POST",
            "/admin/exceptions/999999/decision",
            data={"decision": "approve", "reason": "missing exception"},
            headers=admin_headers,
        )
        checks["exception_queue_and_admin_auth_work"] = (
            no_auth_status == 401
            and exceptions_status == 200
            and exceptions_total is not None
            and exceptions_total >= 7
            and missing_decision_status == 404
        )

        # 11. Manual decision requires reason and writes audit events.
        amount_exception = _exceptions_for(exception_items, transaction_id="TX-1201", category="amount_mismatch")
        late_exception = _exceptions_for(exception_items, transaction_id="TX-1101", category="late_settlement")
        amount_id = _item_field(amount_exception[0], "id", "exception_id") if amount_exception else None
        late_id = _item_field(late_exception[0], "id", "exception_id") if late_exception else None
        no_reason_status, _, _ = _request(
            port,
            "POST",
            f"/admin/exceptions/{late_id}/decision",
            data={"decision": "manual_adjust"},
            headers=admin_headers,
        )
        manual_status, _, _ = _request(
            port,
            "POST",
            f"/admin/exceptions/{late_id}/decision",
            data={"decision": "manual_adjust", "reason": "evaluator manual adjustment"},
            headers=admin_headers,
        )
        approve_status, _, _ = _request(
            port,
            "POST",
            f"/admin/exceptions/{amount_id}/decision",
            data={"decision": "approve", "reason": "evaluator approval"},
            headers=admin_headers,
        )
        redecide_status, _, _ = _request(
            port,
            "POST",
            f"/admin/exceptions/{amount_id}/decision",
            data={"decision": "reject", "reason": "too late"},
            headers=admin_headers,
        )
        checks["manual_decision_requires_reason_and_audits"] = (
            late_id is not None
            and amount_id is not None
            and no_reason_status == 422
            and manual_status == 200
            and approve_status == 200
            and redecide_status == 409
        )

        # 12. Audit history newest first (approve on TX-1201 is newer than manual_adjust on TX-1101).
        merchant_m100_status, merchant_m100_headers, merchant_m100_body = _request(port, "GET", "/reports/merchant/M-100")
        audit_section = _audit_section(merchant_m100_body)
        approval_position = audit_section.find("evaluator approval")
        manual_position = audit_section.find("evaluator manual adjustment")
        checks["audit_history_newest_first"] = (
            merchant_m100_status == 200
            and 0 <= approval_position < manual_position
        )

        # 13. Daily report executive totals exclude training merchants.
        daily_status, _, daily_body = _request(port, "GET", f"/reports/daily?date={DAILY_DATE}")
        daily = _json(daily_body)
        daily_total = _find_number(daily, "total_amount", "executive_total", "total", "sum_amount", "gross_amount")
        checks["daily_report_totals_apply_exclusions"] = (
            daily_status == 200
            and daily_total is not None
            and abs(daily_total - EXPECTED_EXECUTIVE_TOTAL) <= 0.01
            and abs(daily_total - EXPECTED_WITH_TRAINING_TOTAL) > 0.01
        )

        # 14. Merchant report includes exceptions and audit history.
        checks["merchant_report_includes_audit_and_exceptions"] = (
            merchant_m100_status == 200
            and "text/html" in (merchant_m100_headers.get("Content-Type") or merchant_m100_headers.get("content-type") or "")
            and "M-100" in merchant_m100_body
            and ("TX-1201" in merchant_m100_body or "amount_mismatch" in merchant_m100_body or "amount mismatch" in merchant_m100_body.lower())
            and "audit" in merchant_m100_body.lower()
            and ("TX-1101" in merchant_m100_body or "late_settlement" in merchant_m100_body or "late settlement" in merchant_m100_body.lower())
        )

        # 15. CSV export deterministic and safe.
        csv_ok = False
        if run_id:
            csv1_status, csv1_headers, csv1_body = _request(port, "GET", f"/exports/reconciliation.csv?run_id={run_id}")
            csv2_status, _, csv2_body = _request(port, "GET", f"/exports/reconciliation.csv?run_id={run_id}")
            traversal_status, _, traversal_body = _request(port, "GET", "/exports/reconciliation.csv?run_id=..%2F..%2Fetc%2Fpasswd")
            first_line = csv1_body.splitlines()[0] if csv1_body else ""
            csv_ok = (
                csv1_status == 200
                and ("csv" in (csv1_headers.get("Content-Type") or csv1_headers.get("content-type") or "") or "text/plain" in (csv1_headers.get("Content-Type") or csv1_headers.get("content-type") or ""))
                and first_line.lower().startswith("transaction_id")
                and "TX-1001" in csv1_body
                and csv1_body == csv2_body
                and csv2_status == 200
                and traversal_status in (400, 404)
                and "root:" not in traversal_body
            )
            details["csv_status"] = csv1_status
            details["csv_traversal_status"] = traversal_status
            details["csv_first_line"] = first_line[:120]
        checks["csv_export_is_deterministic_and_safe"] = csv_ok

        # 16. HTML escaping blocks script injection from merchant names.
        xss_status, _, xss_body = _request(port, "GET", "/reports/merchant/M-900")
        checks["html_escaping_blocks_script_injection"] = (
            xss_status == 200
            and "&lt;script&gt;" in xss_body
            and "<script>alert(1)</script>" not in xss_body
        )

        # 17. Data and decision meaning survive an app restart.
        states_status, _, states_body = _request(port, "GET", "/reports/exceptions")
        decision_states = _report_state_counts(states_body)
        _stop_server(proc)
        proc = None
        proc = _start_server(workspace, db_path, port)
        persisted_daily_status, _, persisted_daily_body = _request(port, "GET", f"/reports/daily?date={DAILY_DATE}")
        persisted_daily = _json(persisted_daily_body)
        persisted_total = _find_number(persisted_daily, "total_amount", "executive_total", "total", "sum_amount", "gross_amount")
        persisted_exceptions_status, _, _ = _request(port, "GET", "/admin/exceptions", headers=admin_headers)
        persisted_merchant_status, _, persisted_merchant_body = _request(port, "GET", "/reports/merchant/M-100")
        persisted_audit = _audit_section(persisted_merchant_body)
        persisted_states_status, _, persisted_states_body = _request(port, "GET", "/reports/exceptions")
        persisted_decision_states = _report_state_counts(persisted_states_body)
        # Resolved decisions belong in reports/audit, not the unresolved queue.
        # Both decisions must remain terminal even if audit rows alone survived.
        persisted_decision_statuses = [
            _request(
                port,
                "POST",
                f"/admin/exceptions/{exception_id}/decision",
                data={"decision": "reject", "reason": "restart terminal-state probe"},
                headers=admin_headers,
            )[0]
            for exception_id in (amount_id, late_id)
        ]
        checks["data_survives_app_restart"] = (
            persisted_daily_status == 200
            and persisted_total is not None
            and abs(persisted_total - EXPECTED_EXECUTIVE_TOTAL) <= 0.01
            and persisted_exceptions_status == 200
            and persisted_merchant_status == 200
            and "evaluator approval" in persisted_audit
            and "evaluator manual adjustment" in persisted_audit
            and persisted_decision_statuses == [409, 409]
            and states_status == persisted_states_status == 200
            and decision_states is not None
            and decision_states["approved"] >= 1
            and decision_states["manually_adjusted"] >= 1
            and decision_states == persisted_decision_states
        )

        details.update({
            "port": port,
            "homepage_status": homepage_status,
            "ledger_status": ledger_status,
            "settle_a_status": settle_a_status,
            "settle_b_status": settle_b_status,
            "run1_status": run1_status,
            "run1": run1,
            "run2": run2,
            "exceptions_status": exceptions_status,
            "exceptions_total": exceptions_total,
            "exception_items": exception_items[:20],
            "amount_exception_id": amount_id,
            "late_exception_id": late_id,
            "no_reason_status": no_reason_status,
            "manual_status": manual_status,
            "approve_status": approve_status,
            "redecide_status": redecide_status,
            "daily_total": daily_total,
            "merchant_m100_status": merchant_m100_status,
            "xss_status": xss_status,
            "persisted_total": persisted_total,
            "decision_states_before_restart": decision_states,
            "decision_states_after_restart": persisted_decision_states,
            "db_path": str(db_path),
            "db_exists": db_path.exists(),
            "db_size": db_path.stat().st_size if db_path.exists() else 0,
        })
        return checks, details
    finally:
        _stop_server(proc)


def main() -> int:
    workspace = _workspace()
    details: dict[str, object] = {"workspace": str(workspace)}
    try:
        checks, functional_details = _run_functional_checks(workspace)
        details["functional_details"] = functional_details
    except Exception as exc:
        details["exception"] = str(exc)
        details["traceback"] = traceback.format_exc()
        checks = {name: False for name in CHECK_NAMES}
    checks = {name: bool(checks.get(name)) for name in CHECK_NAMES}
    score = "pass" if all(checks.values()) else "fail"
    result = {
        "task_id": os.environ.get("BENCH_TASK_ID", "cap-advanced-merchant-reconciliation-suite"),
        "run_id": os.environ.get("BENCH_RUN_ID", "manual"),
        "score": score,
        "checks": checks,
        "details": {
            "functionality": {
                "checks": checks,
                "evidence": details,
            }
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if score == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
PY
