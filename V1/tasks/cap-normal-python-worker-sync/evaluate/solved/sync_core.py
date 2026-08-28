from __future__ import annotations

import json
import os
import sqlite3
import urllib.error
import urllib.request
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

JOB_STATUSES = {"queued", "running", "succeeded", "failed", "conflict"}
_TRANSIENT_HTTP = {502, 503, 504}


@dataclass
class JobResult:
    action: str
    job_id: int | None


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def db_path() -> str:
    return os.environ.get("SYNC_DB", "sync-jobs.sqlite3")


def upstream_url() -> str:
    return os.environ.get("SYNC_UPSTREAM_URL", "http://127.0.0.1:3999").rstrip("/")


def admin_token() -> str:
    return os.environ.get("SYNC_ADMIN_TOKEN", "sync-admin")


def stale_seconds() -> int:
    return int(os.environ.get("SYNC_STALE_SECONDS", "30"))


def max_attempts() -> int:
    return int(os.environ.get("SYNC_MAX_ATTEMPTS", "3"))


def connect() -> sqlite3.Connection:
    path = Path(db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
            slug TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            version INTEGER NOT NULL,
            sync_status TEXT NOT NULL,
            last_synced_version INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sync_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL,
            requested_version INTEGER NOT NULL,
            status TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            claimed_at TEXT,
            finished_at TEXT,
            upstream_ref TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(slug) REFERENCES documents(slug)
        );
        CREATE TABLE IF NOT EXISTS job_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            event TEXT NOT NULL,
            detail TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(job_id) REFERENCES sync_jobs(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_sync_jobs_status_created ON sync_jobs(status, created_at, id);
        CREATE INDEX IF NOT EXISTS idx_sync_jobs_slug_version ON sync_jobs(slug, requested_version, id);
        CREATE INDEX IF NOT EXISTS idx_job_history_job_id ON job_history(job_id, id DESC);
        """
    )
    conn.commit()
    return conn


def row_to_document(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "slug": row["slug"],
        "title": row["title"],
        "content": row["content"],
        "version": row["version"],
        "sync_status": row["sync_status"],
        "last_synced_version": row["last_synced_version"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_job(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "slug": row["slug"],
        "requested_version": row["requested_version"],
        "status": row["status"],
        "idempotency_key": row["idempotency_key"],
        "attempts": row["attempts"],
        "last_error": row["last_error"],
        "claimed_at": row["claimed_at"],
        "finished_at": row["finished_at"],
        "upstream_ref": row["upstream_ref"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_history(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "event": row["event"],
        "detail": row["detail"],
        "created_at": row["created_at"],
    }


def log_history(conn: sqlite3.Connection, job_id: int, event: str, detail: str) -> None:
    conn.execute(
        "INSERT INTO job_history(job_id, event, detail, created_at) VALUES (?, ?, ?, ?)",
        (job_id, event, detail, now_iso()),
    )


def save_document(*, slug: str, title: str, content: str) -> tuple[dict[str, Any], bool]:
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM documents WHERE slug = ?", (slug,)).fetchone()
        timestamp = now_iso()
        if row is None:
            conn.execute(
                """
                INSERT INTO documents(slug, title, content, version, sync_status, last_synced_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (slug, title, content, 1, "dirty", None, timestamp, timestamp),
            )
            created = True
        else:
            conn.execute(
                """
                UPDATE documents
                SET title = ?, content = ?, version = ?, sync_status = ?, updated_at = ?
                WHERE slug = ?
                """,
                (title, content, int(row["version"]) + 1, "dirty", timestamp, slug),
            )
            created = False
        conn.commit()
        saved = conn.execute("SELECT * FROM documents WHERE slug = ?", (slug,)).fetchone()
        return row_to_document(saved), created


def get_document(slug: str) -> dict[str, Any] | None:
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM documents WHERE slug = ?", (slug,)).fetchone()
        return row_to_document(row)


def get_job(job_id: int) -> dict[str, Any] | None:
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM sync_jobs WHERE id = ?", (job_id,)).fetchone()
        return row_to_job(row)


def get_history(job_id: int, *, page: int, page_size: int) -> dict[str, Any]:
    offset = (page - 1) * page_size
    with closing(connect()) as conn:
        total = conn.execute("SELECT COUNT(*) FROM job_history WHERE job_id = ?", (job_id,)).fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM job_history WHERE job_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (job_id, page_size, offset),
        ).fetchall()
    return {
        "items": [row_to_history(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def list_jobs(*, page: int, page_size: int, status: str | None, slug: str | None) -> dict[str, Any]:
    offset = (page - 1) * page_size
    where: list[str] = []
    params: list[Any] = []
    if status is not None:
        where.append("status = ?")
        params.append(status)
    if slug:
        where.append("slug = ?")
        params.append(slug)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    with closing(connect()) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM sync_jobs {where_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM sync_jobs {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, page_size, offset],
        ).fetchall()
    return {
        "items": [row_to_job(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def create_sync_job(*, slug: str, idempotency_key: str) -> tuple[dict[str, Any], bool]:
    with closing(connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing_by_key = conn.execute(
            "SELECT * FROM sync_jobs WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing_by_key is not None:
            conn.commit()
            return row_to_job(existing_by_key), False

        doc = conn.execute("SELECT * FROM documents WHERE slug = ?", (slug,)).fetchone()
        if doc is None:
            conn.rollback()
            raise KeyError(slug)

        version = int(doc["version"])
        existing_equivalent = conn.execute(
            """
            SELECT * FROM sync_jobs
            WHERE slug = ? AND requested_version = ? AND status IN ('queued', 'running', 'succeeded')
            ORDER BY id DESC
            LIMIT 1
            """,
            (slug, version),
        ).fetchone()
        if existing_equivalent is not None:
            conn.commit()
            return row_to_job(existing_equivalent), False

        timestamp = now_iso()
        cur = conn.execute(
            """
            INSERT INTO sync_jobs(slug, requested_version, status, idempotency_key, attempts, last_error, claimed_at, finished_at, upstream_ref, created_at, updated_at)
            VALUES (?, ?, 'queued', ?, 0, NULL, NULL, NULL, NULL, ?, ?)
            """,
            (slug, version, idempotency_key, timestamp, timestamp),
        )
        job_id = int(cur.lastrowid)
        log_history(conn, job_id, "queued", f"queued {slug} v{version}")
        conn.commit()
        row = conn.execute("SELECT * FROM sync_jobs WHERE id = ?", (job_id,)).fetchone()
        return row_to_job(row), True


def _finish_job(conn: sqlite3.Connection, *, job_id: int, status: str, last_error: str | None = None, upstream_ref: str | None = None) -> None:
    timestamp = now_iso()
    conn.execute(
        """
        UPDATE sync_jobs
        SET status = ?, last_error = ?, upstream_ref = ?, finished_at = ?, updated_at = ?, claimed_at = NULL
        WHERE id = ?
        """,
        (status, last_error, upstream_ref, timestamp, timestamp, job_id),
    )


def _requeue_job(conn: sqlite3.Connection, *, job_id: int, last_error: str) -> None:
    conn.execute(
        "UPDATE sync_jobs SET status = 'queued', last_error = ?, claimed_at = NULL, updated_at = ? WHERE id = ?",
        (last_error, now_iso(), job_id),
    )


def _mark_document_synced(conn: sqlite3.Connection, *, slug: str, version: int) -> None:
    conn.execute(
        "UPDATE documents SET sync_status = 'synced', last_synced_version = ?, updated_at = ? WHERE slug = ?",
        (version, now_iso(), slug),
    )


def claim_next_job() -> dict[str, Any] | None:
    with closing(connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cutoff = (datetime.now(UTC) - timedelta(seconds=stale_seconds())).replace(microsecond=0).isoformat()
        row = conn.execute(
            """
            SELECT * FROM sync_jobs
            WHERE status = 'queued'
               OR (status = 'running' AND claimed_at IS NOT NULL AND claimed_at < ?)
            ORDER BY CASE WHEN status = 'queued' THEN 0 ELSE 1 END, id ASC
            LIMIT 1
            """,
            (cutoff,),
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        attempts = int(row["attempts"]) + 1
        timestamp = now_iso()
        conn.execute(
            "UPDATE sync_jobs SET status = 'running', attempts = ?, claimed_at = ?, updated_at = ? WHERE id = ?",
            (attempts, timestamp, timestamp, row["id"]),
        )
        if row["status"] == "running":
            log_history(conn, int(row["id"]), "reclaimed", "reclaimed stale running job")
        log_history(conn, int(row["id"]), "started", f"attempt {attempts}")
        conn.commit()
        fresh = conn.execute("SELECT * FROM sync_jobs WHERE id = ?", (row["id"],)).fetchone()
        return row_to_job(fresh)


def _send_upstream(document: dict[str, Any]) -> tuple[bool, str | None, str | None, bool]:
    payload = json.dumps(
        {
            "slug": document["slug"],
            "title": document["title"],
            "content": document["content"],
            "version": document["version"],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        upstream_url() + "/v1/sync",
        method="POST",
        data=payload,
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = json.loads(response.read().decode("utf-8") or "{}")
            return True, body.get("upstream_id"), None, False
    except urllib.error.HTTPError as error:
        try:
            detail = error.read().decode("utf-8")
        except Exception:
            detail = ""
        return False, None, f"http {error.code}: {detail}".strip(), error.code in _TRANSIENT_HTTP
    except urllib.error.URLError as error:
        return False, None, f"network error: {error}", True


def process_next_job() -> JobResult:
    job = claim_next_job()
    if job is None:
        return JobResult("idle", None)

    slug = str(job["slug"])
    with closing(connect()) as conn:
        doc_row = conn.execute("SELECT * FROM documents WHERE slug = ?", (slug,)).fetchone()
        if doc_row is None:
            _finish_job(conn, job_id=int(job["id"]), status="failed", last_error="document missing")
            log_history(conn, int(job["id"]), "failed", "document missing during processing")
            conn.commit()
            return JobResult("failed", int(job["id"]))
        document = row_to_document(doc_row)
        if int(document["version"]) != int(job["requested_version"]):
            _finish_job(conn, job_id=int(job["id"]), status="conflict", last_error="document changed since queue")
            log_history(conn, int(job["id"]), "conflict", f"document advanced to v{document['version']}")
            conn.commit()
            return JobResult("conflict", int(job["id"]))

    ok, upstream_ref, error_text, transient = _send_upstream(document)

    with closing(connect()) as conn:
        current = conn.execute("SELECT * FROM sync_jobs WHERE id = ?", (job["id"],)).fetchone()
        attempts = int(current["attempts"]) if current is not None else int(job["attempts"])
        if ok:
            _finish_job(conn, job_id=int(job["id"]), status="succeeded", upstream_ref=upstream_ref)
            _mark_document_synced(conn, slug=slug, version=int(job["requested_version"]))
            log_history(conn, int(job["id"]), "succeeded", f"synced to upstream {upstream_ref or 'ok'}")
            conn.commit()
            return JobResult("succeeded", int(job["id"]))
        if transient and attempts < max_attempts():
            _requeue_job(conn, job_id=int(job["id"]), last_error=error_text or "transient failure")
            log_history(conn, int(job["id"]), "retry_scheduled", error_text or "transient failure")
            conn.commit()
            return JobResult("retry", int(job["id"]))
        _finish_job(conn, job_id=int(job["id"]), status="failed", last_error=error_text or "sync failed")
        log_history(conn, int(job["id"]), "failed", error_text or "sync failed")
        conn.commit()
        return JobResult("failed", int(job["id"]))


def run_worker(*, drain: bool = False, max_jobs: int | None = None) -> dict[str, Any]:
    processed = 0
    actions: list[str] = []
    while True:
        result = process_next_job()
        actions.append(result.action)
        if result.action == "idle":
            break
        processed += 1
        if max_jobs is not None and processed >= max_jobs:
            break
        if not drain:
            break
    return {"processed": processed, "actions": actions}
