from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Helpdesk API")

_ADMIN_TOKEN = "helpdesk-admin"
_ALLOWED_STATUSES = {"open", "in_progress", "closed"}
_ALLOWED_PRIORITIES = {"low", "normal", "high", "urgent"}


class TicketCreate(BaseModel):
    email: str = Field(min_length=3)
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)


class TicketTriage(BaseModel):
    status: Literal["open", "in_progress", "closed"]
    priority: Literal["low", "normal", "high", "urgent"]
    admin_note: str = Field(min_length=1)


def _db_path() -> str:
    return os.environ.get("HELPDESK_DB", "helpdesk.sqlite3")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL,
            priority TEXT NOT NULL,
            admin_note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            actor TEXT NOT NULL,
            detail TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
        );
        """
    )
    conn.commit()
    return conn


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _ticket_from_row(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "email": row["email"],
        "subject": row["subject"],
        "body": row["body"],
        "status": row["status"],
        "priority": row["priority"],
        "admin_note": row["admin_note"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _log_action(conn: sqlite3.Connection, *, ticket_id: int, action: str, actor: str, detail: str) -> None:
    conn.execute(
        "INSERT INTO audit_log(ticket_id, action, actor, detail, created_at) VALUES (?, ?, ?, ?, ?)",
        (ticket_id, action, actor, detail, _now()),
    )


def _require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if x_admin_token != _ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="admin token required")


def _ticket_or_404(conn: sqlite3.Connection, ticket_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return row


@app.get("/", response_class=HTMLResponse)
def homepage() -> str:
    return """
    <!doctype html>
    <html lang=\"en\">
      <head>
        <meta charset=\"utf-8\" />
        <title>Helpdesk</title>
      </head>
      <body>
        <h1>Helpdesk</h1>
        <p>Public users can submit tickets, and admins can triage or inspect audit history with the documented API routes below.</p>
        <section>
          <h2>Submit a ticket</h2>
          <form id=\"ticket-form\" action=\"/tickets\" method=\"post\">
            <label>Email <input name=\"email\" type=\"email\" required /></label>
            <label>Subject <input name=\"subject\" type=\"text\" required /></label>
            <label>Body <textarea name=\"body\" required></textarea></label>
            <button type=\"submit\">Create ticket</button>
          </form>
          <pre id=\"ticket-result\">Submit a ticket to POST /tickets.</pre>
        </section>
        <section>
          <h2>Admin routes</h2>
          <p>Use <code>X-Admin-Token: helpdesk-admin</code> when calling these APIs.</p>
          <form id=\"admin-list-form\">
            <label>Admin token <input name=\"token\" type=\"text\" value=\"helpdesk-admin\" /></label>
            <button type=\"submit\">Load GET /admin/tickets</button>
          </form>
          <form id=\"admin-triage-form\">
            <label>Ticket id <input name=\"ticket_id\" type=\"number\" min=\"1\" /></label>
            <label>Status <input name=\"status\" type=\"text\" value=\"in_progress\" /></label>
            <label>Priority <input name=\"priority\" type=\"text\" value=\"high\" /></label>
            <label>Admin note <input name=\"admin_note\" type=\"text\" value=\"Assigned\" /></label>
            <button type=\"submit\">POST /admin/tickets/{ticket_id}/triage</button>
          </form>
          <form id=\"admin-audit-form\">
            <label>Ticket id <input name=\"ticket_id\" type=\"number\" min=\"1\" /></label>
            <button type=\"submit\">GET /admin/tickets/{ticket_id}/audit</button>
          </form>
          <pre id=\"admin-result\">Admin controls reference GET /admin/tickets, POST /admin/tickets/{ticket_id}/triage, and GET /admin/tickets/{ticket_id}/audit.</pre>
        </section>
        <script>
          const ticketForm = document.getElementById("ticket-form");
          const ticketResult = document.getElementById("ticket-result");
          const adminListForm = document.getElementById("admin-list-form");
          const adminTriageForm = document.getElementById("admin-triage-form");
          const adminAuditForm = document.getElementById("admin-audit-form");
          const adminResult = document.getElementById("admin-result");

          ticketForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const form = new FormData(ticketForm);
            const payload = Object.fromEntries(form.entries());
            const response = await fetch("/tickets", {
              method: "POST",
              headers: {"Content-Type": "application/json"},
              body: JSON.stringify(payload),
            });
            ticketResult.textContent = JSON.stringify(await response.json(), null, 2);
          });

          adminListForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const token = new FormData(adminListForm).get("token");
            const response = await fetch("/admin/tickets?page=1&page_size=20", {
              headers: {"X-Admin-Token": token},
            });
            adminResult.textContent = JSON.stringify(await response.json(), null, 2);
          });

          adminTriageForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const form = Object.fromEntries(new FormData(adminTriageForm).entries());
            const token = new FormData(adminListForm).get("token");
            const response = await fetch(`/admin/tickets/${form.ticket_id}/triage`, {
              method: "POST",
              headers: {"Content-Type": "application/json", "X-Admin-Token": token},
              body: JSON.stringify({
                status: form.status,
                priority: form.priority,
                admin_note: form.admin_note,
              }),
            });
            adminResult.textContent = JSON.stringify(await response.json(), null, 2);
          });

          adminAuditForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const ticketId = new FormData(adminAuditForm).get("ticket_id");
            const token = new FormData(adminListForm).get("token");
            const response = await fetch(`/admin/tickets/${ticketId}/audit?page=1&page_size=20`, {
              headers: {"X-Admin-Token": token},
            });
            adminResult.textContent = JSON.stringify(await response.json(), null, 2);
          });
        </script>
      </body>
    </html>
    """


@app.post("/tickets", status_code=201)
def create_ticket(payload: TicketCreate):
    now = _now()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO tickets(email, subject, body, status, priority, admin_note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (payload.email, payload.subject, payload.body, "open", "normal", None, now, now),
        )
        ticket_id = int(cur.lastrowid)
        _log_action(
            conn,
            ticket_id=ticket_id,
            action="created",
            actor="public",
            detail=f"ticket submitted by {payload.email}",
        )
        conn.commit()
        row = _ticket_or_404(conn, ticket_id)
        return _ticket_from_row(row)


@app.get("/admin/tickets")
def list_tickets(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    _: None = Depends(_require_admin),
):
    if page < 1 or page_size < 1:
        raise HTTPException(status_code=400, detail="page and page_size must be positive")
    if status is not None and status not in _ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail="invalid status filter")

    offset = (page - 1) * page_size
    with _connect() as conn:
        if status is None:
            total = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
            rows = conn.execute(
                "SELECT * FROM tickets ORDER BY id DESC LIMIT ? OFFSET ?",
                (page_size, offset),
            ).fetchall()
        else:
            total = conn.execute("SELECT COUNT(*) FROM tickets WHERE status = ?", (status,)).fetchone()[0]
            rows = conn.execute(
                "SELECT * FROM tickets WHERE status = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (status, page_size, offset),
            ).fetchall()

    return {
        "items": [_ticket_from_row(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.post("/admin/tickets/{ticket_id}/triage")
def triage_ticket(ticket_id: int, payload: TicketTriage, _: None = Depends(_require_admin)):
    with _connect() as conn:
        _ticket_or_404(conn, ticket_id)
        now = _now()
        conn.execute(
            """
            UPDATE tickets
            SET status = ?, priority = ?, admin_note = ?, updated_at = ?
            WHERE id = ?
            """,
            (payload.status, payload.priority, payload.admin_note, now, ticket_id),
        )
        _log_action(
            conn,
            ticket_id=ticket_id,
            action="triaged",
            actor="admin",
            detail=f"status={payload.status} priority={payload.priority} note={payload.admin_note}",
        )
        conn.commit()
        row = _ticket_or_404(conn, ticket_id)
        return _ticket_from_row(row)


@app.get("/admin/tickets/{ticket_id}/audit")
def ticket_audit(ticket_id: int, page: int = 1, page_size: int = 20, _: None = Depends(_require_admin)):
    if page < 1 or page_size < 1:
        raise HTTPException(status_code=400, detail="page and page_size must be positive")

    offset = (page - 1) * page_size
    with _connect() as conn:
        _ticket_or_404(conn, ticket_id)
        total = conn.execute("SELECT COUNT(*) FROM audit_log WHERE ticket_id = ?", (ticket_id,)).fetchone()[0]
        rows = conn.execute(
            """
            SELECT id, ticket_id, action, actor, detail, created_at
            FROM audit_log
            WHERE ticket_id = ?
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (ticket_id, page_size, offset),
        ).fetchall()

    return {
        "items": [
            {
                "id": row["id"],
                "ticket_id": row["ticket_id"],
                "action": row["action"],
                "actor": row["actor"],
                "detail": row["detail"],
                "created_at": row["created_at"],
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
