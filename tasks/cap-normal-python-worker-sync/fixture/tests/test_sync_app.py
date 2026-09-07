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

import pytest
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[1]


class _UpstreamHandler(BaseHTTPRequestHandler):
    attempts: dict[tuple[str, int], int] = {}
    received: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/sync":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        key = (str(payload.get("slug")), int(payload.get("version", 0)))
        self.__class__.attempts[key] = self.__class__.attempts.get(key, 0) + 1
        self.__class__.received.append(payload)
        should_retry = str(payload.get("slug", "")).startswith("retry-") and self.__class__.attempts[key] == 1
        body = {"upstream_id": f"up-{key[0]}-{key[1]}"}
        if should_retry:
            self.send_response(503)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "temporary_unavailable"}).encode("utf-8"))
            return
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode("utf-8"))

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


@pytest.fixture
def upstream_server():
    _UpstreamHandler.attempts = {}
    _UpstreamHandler.received = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _UpstreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", _UpstreamHandler
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.fixture
def client(tmp_path, monkeypatch, upstream_server):
    upstream_url, _ = upstream_server
    monkeypatch.setenv("SYNC_DB", str(tmp_path / "sync.sqlite3"))
    monkeypatch.setenv("SYNC_UPSTREAM_URL", upstream_url)
    monkeypatch.setenv("SYNC_ADMIN_TOKEN", "sync-admin")
    monkeypatch.setenv("SYNC_STALE_SECONDS", "1")
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    import app

    importlib.reload(app)
    return TestClient(app.app)


@pytest.fixture
def workspace_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_ROOT)
    return env


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": "sync-admin"}


def _run_worker(env: dict[str, str]) -> None:
    result = sp.run(
        [sys.executable, "worker.py", "--drain"],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_browser_homepage(client: TestClient):
    homepage = client.get("/")
    assert homepage.status_code == 200
    assert homepage.headers["content-type"].startswith("text/html")
    body = homepage.text
    assert "<title>Doc Sync</title>" in body
    assert "POST /documents" in body
    assert "POST /sync-jobs" in body
    assert "GET /sync-jobs/{job_id}" in body
    assert "GET /admin/sync-jobs" in body
    assert "GET /admin/sync-jobs/{job_id}/history" in body
    assert "worker" in body.lower()
    assert "retry" in body.lower()
    assert "conflict" in body.lower()


def test_document_sync_flow_and_polling(client: TestClient, workspace_env: dict[str, str]):
    created = client.post(
        "/documents",
        json={"slug": "launch-plan", "title": "Launch plan", "content": "Initial draft"},
    )
    assert created.status_code == 201
    assert created.json()["version"] == 1

    job = client.post(
        "/sync-jobs",
        json={"slug": "launch-plan", "idempotency_key": "launch-v1"},
    )
    assert job.status_code == 201
    job_id = job.json()["id"]

    _run_worker(workspace_env)

    polled = client.get(f"/sync-jobs/{job_id}")
    assert polled.status_code == 200
    payload = polled.json()
    assert payload["status"] == "succeeded"
    assert payload["attempts"] == 1
    assert payload["requested_version"] == 1

    history = client.get(f"/admin/sync-jobs/{job_id}/history?page=1&page_size=10", headers=_admin_headers())
    assert history.status_code == 200
    events = [item["event"] for item in history.json()["items"]]
    assert events[:3] == ["succeeded", "started", "queued"]


def test_retry_idempotency_and_conflict_handling(client: TestClient, workspace_env: dict[str, str], upstream_server):
    _, handler = upstream_server
    client.post(
        "/documents",
        json={"slug": "retry-report", "title": "Retry report", "content": "needs retry"},
    )
    first = client.post(
        "/sync-jobs",
        json={"slug": "retry-report", "idempotency_key": "retry-v1"},
    )
    replay = client.post(
        "/sync-jobs",
        json={"slug": "retry-report", "idempotency_key": "retry-v1"},
    )
    duplicate = client.post(
        "/sync-jobs",
        json={"slug": "retry-report", "idempotency_key": "retry-v1-other"},
    )
    assert first.status_code == 201
    assert replay.status_code == 200
    assert duplicate.status_code == 200
    assert replay.json()["id"] == first.json()["id"] == duplicate.json()["id"]

    _run_worker(workspace_env)

    retried = client.get(f"/sync-jobs/{first.json()['id']}").json()
    assert retried["status"] == "succeeded"
    assert retried["attempts"] == 2
    assert handler.attempts[("retry-report", 1)] == 2

    client.post(
        "/documents",
        json={"slug": "conflict-doc", "title": "Conflict doc", "content": "v1"},
    )
    conflict_job = client.post(
        "/sync-jobs",
        json={"slug": "conflict-doc", "idempotency_key": "conflict-v1"},
    )
    client.post(
        "/documents",
        json={"slug": "conflict-doc", "title": "Conflict doc", "content": "v2"},
    )

    _run_worker(workspace_env)

    conflicted = client.get(f"/sync-jobs/{conflict_job.json()['id']}").json()
    assert conflicted["status"] == "conflict"
    history = client.get(
        f"/admin/sync-jobs/{conflict_job.json()['id']}/history?page=1&page_size=10",
        headers=_admin_headers(),
    ).json()
    assert history["items"][0]["event"] == "conflict"


def test_stale_job_reclaim_and_persistence(client: TestClient, workspace_env: dict[str, str], tmp_path):
    created = client.post(
        "/documents",
        json={"slug": "stale-doc", "title": "Stale doc", "content": "keep me"},
    )
    job = client.post(
        "/sync-jobs",
        json={"slug": "stale-doc", "idempotency_key": "stale-v1"},
    )
    db_path = Path(os.environ["SYNC_DB"])
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE sync_jobs SET status = 'running', attempts = 1, claimed_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
            (job.json()["id"],),
        )
        conn.commit()

    _run_worker(workspace_env)

    payload = client.get(f"/sync-jobs/{job.json()['id']}").json()
    assert payload["status"] == "succeeded"
    assert payload["attempts"] == 2

    history = client.get(
        f"/admin/sync-jobs/{job.json()['id']}/history?page=1&page_size=10",
        headers=_admin_headers(),
    ).json()
    events = [item["event"] for item in history["items"]]
    assert "reclaimed" in events
    assert db_path.exists() and db_path.stat().st_size > 0

    import app

    importlib.reload(app)
    reloaded = TestClient(app.app)
    persisted = reloaded.get(f"/sync-jobs/{job.json()['id']}")
    assert persisted.status_code == 200
    assert persisted.json()["status"] == "succeeded"

    code = """
import importlib
import json
import os
import sys
from fastapi.testclient import TestClient
sys.path.insert(0, os.getcwd())
import app
importlib.reload(app)
client = TestClient(app.app)
job = client.get('/sync-jobs/1')
admin = client.get('/admin/sync-jobs?page=1&page_size=10', headers={'X-Admin-Token': 'sync-admin'})
print(json.dumps({'job_status': job.status_code, 'state': job.json().get('status'), 'admin_total': admin.json().get('total')}))
"""
    proc = sp.run([sys.executable, "-c", code], cwd=_ROOT, env=workspace_env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    fresh = json.loads(proc.stdout.strip())
    assert fresh["job_status"] == 200
    assert fresh["state"] == "succeeded"
    assert fresh["admin_total"] >= 1


def test_admin_listing_filters_and_status_codes(client: TestClient):
    client.post("/documents", json={"slug": "alpha", "title": "Alpha", "content": "One"})
    client.post("/sync-jobs", json={"slug": "alpha", "idempotency_key": "alpha-v1"})

    unauthorized = client.get("/admin/sync-jobs")
    assert unauthorized.status_code == 401

    invalid_page = client.get("/admin/sync-jobs?page=0", headers=_admin_headers())
    assert invalid_page.status_code == 400

    invalid_status = client.get("/admin/sync-jobs?status=weird", headers=_admin_headers())
    assert invalid_status.status_code == 400

    missing_doc = client.get("/documents/missing")
    assert missing_doc.status_code == 404

    missing_job = client.get("/sync-jobs/999")
    assert missing_job.status_code == 404

    invalid_body = client.post("/documents", json={"slug": "bad", "title": "No body"})
    assert invalid_body.status_code == 422

    listing = client.get("/admin/sync-jobs?slug=alpha&page=1&page_size=10", headers=_admin_headers())
    assert listing.status_code == 200
    payload = listing.json()
    assert payload["total"] == 1
    assert payload["items"][0]["slug"] == "alpha"
