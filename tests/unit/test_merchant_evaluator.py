"""Exercise the merchant evaluator without starting an application server."""

import json
from pathlib import Path

import pytest


EVALUATOR = (
    Path(__file__).resolve().parents[2]
    / "tasks/cap-advanced-merchant-reconciliation-suite/evaluate/run.sh"
)


@pytest.fixture
def evaluator():
    source = EVALUATOR.read_text().split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    namespace = {"__name__": "merchant_evaluator_test"}
    exec(compile(source, str(EVALUATOR), "exec"), namespace)
    return namespace


def run_checks(evaluator, monkeypatch, tmp_path, *, reverse_audit=False,
               lose_decisions=None, lose_audit=False, lose_totals=False,
               decision_label="approve", change_decision=None):
    starts = 0

    def start_server(*args):
        nonlocal starts
        starts += 1
        return object()

    def request(port, method, path, *, data=None, headers=None):
        restarted = starts > 1
        if method == "POST" and path.endswith("/decision"):
            if restarted:
                lost = lose_decisions and path == f"/admin/exceptions/{lose_decisions}/decision"
                return (200 if lost else 409), {}, "{}"
            if "999999" in path:
                return 404, {}, "{}"
            if not data.get("reason"):
                return 422, {}, "{}"
            return (409 if data["reason"] == "too late" else 200), {}, "{}"
        if path == "/admin/exceptions":
            # Resolved decisions are deliberately absent from the pending queue.
            items = [
                {"id": 1, "transaction_id": "TX-1201", "category": "amount_mismatch", "state": "pending"},
                {"id": 2, "transaction_id": "TX-1101", "category": "late_settlement", "state": "pending"},
            ] if not restarted else []
            return 200, {}, json.dumps({"items": items, "total": len(items)})
        if path.startswith("/reports/daily"):
            total = 0 if restarted and lose_totals else 1450
            return 200, {}, json.dumps({"total_amount": total})
        if path == "/reports/exceptions":
            counts = {"approved": 1, "manually_adjusted": 1, "rejected": 0}
            if restarted and change_decision:
                counts[change_decision] -= 1
                counts["rejected"] += 1
            return 200, {}, json.dumps({"by_state": counts})
        if path == "/reports/merchant/M-100":
            events = [f"{decision_label}: evaluator approval", "manual_adjust: evaluator manual adjustment"]
            if reverse_audit:
                events.reverse()
            if restarted and lose_audit:
                events = []
            return 200, {}, "<h2>Audit</h2>" + "".join(f"<p>{e}</p>" for e in events)
        return 200, {"Content-Type": "text/html"}, "{}"

    monkeypatch.setitem(evaluator, "_start_server", start_server)
    monkeypatch.setitem(evaluator, "_stop_server", lambda proc: None)
    monkeypatch.setitem(evaluator, "_request", request)
    return evaluator["_run_functional_checks"](tmp_path)[0]


@pytest.mark.parametrize("payload", [
    {"by_state": {"approved": 1, "manually_adjusted": 1}},
    '{"summary":{"by_state":{"approved":1,"manually_adjusted":1}}}',
    '<p>Counts by state: approved: 1, manually_adjusted: 1</p>',
    '<h2>Counts by state</h2><ul><li>approved: 1</li><li>manually_adjusted: 1</li></ul>',
])
def test_state_counts_accept_documented_json_or_html_reports(evaluator, payload):
    assert evaluator["_report_state_counts"](payload) == {
        "approved": 1, "manually_adjusted": 1, "pending": 0, "rejected": 0,
    }


@pytest.mark.parametrize("decision_label", ["approve", "approved"])
def test_audit_order_accepts_action_or_state_wording(evaluator, monkeypatch, tmp_path, decision_label):
    checks = run_checks(evaluator, monkeypatch, tmp_path, decision_label=decision_label)
    assert checks["audit_history_newest_first"]


def test_audit_order_rejects_oldest_first(evaluator, monkeypatch, tmp_path):
    checks = run_checks(evaluator, monkeypatch, tmp_path, reverse_audit=True)
    assert not checks["audit_history_newest_first"]


def test_restart_accepts_unresolved_only_queue(evaluator, monkeypatch, tmp_path):
    checks = run_checks(evaluator, monkeypatch, tmp_path)
    assert checks["data_survives_app_restart"]


@pytest.mark.parametrize("loss", [
    {"lose_decisions": 1}, {"lose_decisions": 2},
    {"lose_audit": True}, {"lose_totals": True},
    {"change_decision": "approved"}, {"change_decision": "manually_adjusted"},
])
def test_restart_rejects_lost_state(evaluator, monkeypatch, tmp_path, loss):
    checks = run_checks(evaluator, monkeypatch, tmp_path, **loss)
    assert not checks["data_survives_app_restart"]


@pytest.mark.parametrize("parameter", ["id", "exception_id"])
def test_route_documentation_accepts_equivalent_parameter_names(evaluator, parameter):
    assert evaluator["_has_route_reference"](
        f"<li>POST /admin/exceptions/{{{parameter}}}/decision</li>",
        "POST", "/admin/exceptions/{id}/decision",
    )


@pytest.mark.parametrize("documentation", [
    "GET /admin/exceptions/{exception_id}/decision",
    "POST /admin/other/{exception_id}/decision",
    "POST /admin/exceptions/{exception_id}/delete",
])
def test_route_documentation_rejects_wrong_method_or_path(evaluator, documentation):
    assert not evaluator["_has_route_reference"](
        documentation, "POST", "/admin/exceptions/{id}/decision",
    )
