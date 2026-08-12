from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HELPDESK_DB", str(tmp_path / "helpdesk.sqlite3"))
    import app

    importlib.reload(app)
    return TestClient(app.app)


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": "helpdesk-admin"}


def test_browser_homepage_is_available_and_references_helpdesk_workflows(client: TestClient):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert "Helpdesk" in body
    assert '<form' in body
    assert 'action="/tickets"' in body or "action='/tickets'" in body
    assert "/admin/tickets" in body
    assert "/admin/tickets/{ticket_id}/triage" in body
    assert "/admin/tickets/{ticket_id}/audit" in body


def test_public_ticket_intake_returns_201_and_persists_ticket(client: TestClient):
    response = client.post(
        "/tickets",
        json={
            "email": "user@example.com",
            "subject": "Printer broken",
            "body": "3rd floor printer is jammed",
        },
    )

    assert response.status_code == 201
    ticket = response.json()
    assert ticket["id"] >= 1
    assert ticket["email"] == "user@example.com"
    assert ticket["subject"] == "Printer broken"
    assert ticket["body"] == "3rd floor printer is jammed"
    assert ticket["status"] == "open"
    assert ticket["priority"] == "normal"
    assert ticket["admin_note"] is None
    assert ticket["created_at"]
    assert ticket["updated_at"]


def test_admin_list_requires_token_and_supports_pagination_and_status_filter(client: TestClient):
    for idx in range(3):
        response = client.post(
            "/tickets",
            json={
                "email": f"user{idx}@example.com",
                "subject": f"Issue {idx}",
                "body": f"Body {idx}",
            },
        )
        assert response.status_code == 201

    unauthorized = client.get("/admin/tickets")
    assert unauthorized.status_code == 401

    page_one = client.get("/admin/tickets?page=1&page_size=2", headers=_admin_headers())
    assert page_one.status_code == 200
    payload = page_one.json()
    assert payload["total"] == 3
    assert payload["page"] == 1
    assert payload["page_size"] == 2
    assert len(payload["items"]) == 2
    assert payload["items"][0]["subject"] == "Issue 2"

    first_ticket = payload["items"][0]
    triage = client.post(
        f"/admin/tickets/{first_ticket['id']}/triage",
        headers=_admin_headers(),
        json={"status": "in_progress", "priority": "high", "admin_note": "Assigned"},
    )
    assert triage.status_code == 200

    filtered = client.get("/admin/tickets?status=in_progress", headers=_admin_headers())
    assert filtered.status_code == 200
    filtered_payload = filtered.json()
    assert filtered_payload["total"] == 1
    assert filtered_payload["items"][0]["id"] == first_ticket["id"]


def test_triage_and_audit_log_track_admin_changes(client: TestClient):
    create = client.post(
        "/tickets",
        json={
            "email": "ops@example.com",
            "subject": "VPN broken",
            "body": "Cannot connect from home",
        },
    )
    ticket = create.json()

    triage = client.post(
        f"/admin/tickets/{ticket['id']}/triage",
        headers=_admin_headers(),
        json={"status": "closed", "priority": "urgent", "admin_note": "Resolved remotely"},
    )
    assert triage.status_code == 200
    updated = triage.json()
    assert updated["status"] == "closed"
    assert updated["priority"] == "urgent"
    assert updated["admin_note"] == "Resolved remotely"

    audit = client.get(
        f"/admin/tickets/{ticket['id']}/audit?page=1&page_size=10",
        headers=_admin_headers(),
    )
    assert audit.status_code == 200
    payload = audit.json()
    assert payload["total"] >= 2
    actions = [item["action"] for item in payload["items"]]
    assert actions[:2] == ["triaged", "created"]
    assert payload["items"][0]["actor"] == "admin"
    assert payload["items"][1]["actor"] == "public"


def test_status_codes_for_validation_and_missing_ticket(client: TestClient):
    invalid = client.post(
        "/tickets",
        json={"email": "user@example.com", "subject": "Missing body"},
    )
    assert invalid.status_code == 422

    missing = client.post(
        "/admin/tickets/999/triage",
        headers=_admin_headers(),
        json={"status": "closed", "priority": "normal", "admin_note": "No ticket"},
    )
    assert missing.status_code == 404

    missing_audit = client.get("/admin/tickets/999/audit", headers=_admin_headers())
    assert missing_audit.status_code == 404
