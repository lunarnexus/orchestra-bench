"""Regression coverage for the approval queue's behavioral evaluator."""

from pathlib import Path

import pytest


@pytest.fixture
def evaluator(tmp_path):
    path = Path(__file__).resolve().parents[2] / "tasks/cap-normal-ts-approval-queue/evaluate/run.sh"
    source = path.read_text().split("<<'EOPY'\n", 1)[1].split("\nfunctional_checks, functional_details =", 1)[0]
    namespace = {"__name__": "approval_evaluator_test"}
    exec(compile(source, str(path), "exec"), namespace)
    return namespace


def history(*, initial="created", reverse=False):
    items = [
        {"id": "a2", "submission_id": "s1", "action": "approved", "detail": "safe to publish", "created_at": "2026-01-01T00:00:02Z"},
        {"id": "a1", "submission_id": "s1", "action": initial, "detail": "new submission", "created_at": "2026-01-01T00:00:01Z"},
    ]
    return list(reversed(items)) if reverse else items


@pytest.mark.parametrize("initial", ["created", "submitted", "submission_received"])
@pytest.mark.parametrize("key", ["items", "entries", "history", "audit"])
def test_history_accepts_unspecified_collection_and_initial_action(evaluator, initial, key):
    items = history(initial=initial)
    assert evaluator["_valid_audit_history"]({key: items}, "s1", {key: items[1:]})


def test_history_accepts_bare_list(evaluator):
    assert evaluator["_valid_audit_history"](history(), "s1", history()[1:])


@pytest.mark.parametrize("defect", ["reversed", "missing_initial", "missing_field", "wrong_submission", "duplicate_ids", "no_initial_event"])
def test_history_rejects_missing_or_incorrect_evidence(evaluator, defect):
    items = history()
    initial = history()[1:]
    if defect == "reversed":
        items.reverse()
    elif defect == "missing_initial":
        items.pop()
    elif defect == "missing_field":
        items[1].pop("detail")
    elif defect == "wrong_submission":
        items[1]["submission_id"] = "another"
    elif defect == "duplicate_ids":
        items[1]["id"] = items[0]["id"]
    else:
        initial = []
    assert not evaluator["_valid_audit_history"]({"items": items}, "s1", initial)


@pytest.mark.parametrize("action,detail,decision", [
    ("decision_approved", "approved by moderator", "approved"),
    ("approval", "safe to publish", "approved"),
    ("decided_rejected", "needs changes", "rejected"),
    ("moderation", {"decision": "approved", "note": "previously rejected"}, "approved"),
    ("moderation", '{"decision":"rejected"}', "rejected"),
    ("approved", "reject the alternative proposal", "approved"),
    ("moderation", "Submission approved", "approved"),
])
def test_history_records_decision_without_fixed_action_vocabulary(evaluator, action, detail, decision):
    items = history()
    items[0].update(action=action, detail=detail)
    assert evaluator["_valid_audit_history"](items, "s1", items[1:], decision)


@pytest.mark.parametrize("action,detail", [
    ("viewed", "Administrator opened the page"),
    ("viewed", "Opened the approval queue"),
    ("rejected", "safe to publish"),
    ("moderation", {"decision": "rejected", "note": "approved was requested"}),
])
def test_history_rejects_unrelated_or_wrong_decision(evaluator, action, detail):
    items = history()
    items[0].update(action=action, detail=detail)
    assert not evaluator["_valid_audit_history"](items, "s1", items[1:], "approved")


def test_request_disconnect_is_failed_response_not_evaluator_crash(evaluator, monkeypatch):
    def disconnected(*args, **kwargs):
        raise ConnectionResetError("application closed connection")

    monkeypatch.setattr(evaluator["urllib"].request, "urlopen", disconnected)
    assert evaluator["_json_request"]("GET", "http://127.0.0.1:3229/history") == (0, {})


def test_storage_uses_file_content_not_response_path(evaluator, tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "generated.txt").write_text("hello world")
    assert evaluator["_attachment_is_stored"](uploads, "hello world")


@pytest.mark.parametrize("defect", ["missing", "wrong_content", "symlink"])
def test_storage_rejects_absent_or_invalid_files(evaluator, tmp_path, defect):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    if defect == "wrong_content":
        (uploads / "generated.txt").write_text("not the submitted content")
    elif defect == "symlink":
        outside = tmp_path / "outside.txt"
        outside.write_text("hello world")
        (uploads / "generated.txt").symlink_to(outside)
    assert not evaluator["_attachment_is_stored"](uploads, "hello world")
