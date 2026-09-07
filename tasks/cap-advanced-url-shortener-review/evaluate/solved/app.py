from __future__ import annotations

import html
import os
import random
import re
import sqlite3
import string
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

app = FastAPI(title="ShortLink Desk")
ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]+$")
STATUSES = {"approved", "pending", "rejected"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_path() -> Path:
    return Path(os.environ.get("SHORTLINK_DB", "shortlinks.sqlite3"))


def admin_token() -> str:
    return os.environ.get("SHORTLINK_ADMIN_TOKEN", "shortlink-admin")


def conn():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS links (
            code TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            status TEXT NOT NULL,
            clicks INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            last_visited_at TEXT
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            event TEXT NOT NULL,
            detail TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    c.commit()
    return c


def add_audit(c, code: str, event: str, detail: str = "") -> None:
    c.execute(
        "INSERT INTO audit_events(code,event,detail,created_at) VALUES(?,?,?,?)",
        (code, event, detail, now()),
    )


def row_to_dict(row):
    return dict(row) if row else None


def render_page(title: str, body: str, status_code: int = 200):
    return HTMLResponse(
        f"""<!doctype html><html><head><title>{html.escape(title)}</title></head>
        <body><h1>{html.escape(title)}</h1>{body}</body></html>""",
        status_code=status_code,
    )


async def request_data(request: Request) -> dict:
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        return await request.json()
    body = (await request.body()).decode()
    data = {}
    for part in body.split("&"):
        if not part or "=" not in part:
            continue
        from urllib.parse import unquote_plus
        k, v = part.split("=", 1)
        data[unquote_plus(k)] = unquote_plus(v)
    return data


def url_status(raw_url: str) -> tuple[bool, str, str]:
    try:
        parsed = urlparse(raw_url)
    except Exception:
        return False, "", "Malformed URL"
    scheme = (parsed.scheme or "").lower()
    if scheme in {"javascript", "data"}:
        return False, "", "Unsafe URL scheme"
    if scheme not in {"http", "https"} or not parsed.hostname:
        return False, "", "Only absolute http(s) URLs are supported"
    host = parsed.hostname.lower()
    suspicious = (
        host in {"localhost", "127.0.0.1"}
        or host.startswith("10.")
        or host.startswith("192.168.")
        or any(host.startswith(f"172.{i}.") for i in range(16, 32))
        or host.endswith(".internal")
    )
    return True, "pending" if suspicious else "approved", ""


def generate_code(c) -> str:
    alphabet = string.ascii_lowercase + string.digits
    while True:
        code = "".join(random.choice(alphabet) for _ in range(6))
        if not c.execute("SELECT 1 FROM links WHERE code=?", (code,)).fetchone():
            return code


def get_link(c, code):
    return c.execute("SELECT * FROM links WHERE code=?", (code,)).fetchone()


@app.get("/", response_class=HTMLResponse)
def homepage():
    return render_page(
        "ShortLink Desk",
        """
        <p>Approved links redirect immediately. Suspicious links require admin review. Stats track visits.</p>
        <form method="post" action="/shorten">
          <label>Long URL <input name="url"></label>
          <label>Optional alias <input name="alias"></label>
          <button type="submit">Shorten</button>
        </form>
        <ul>
          <li>POST /shorten</li><li>GET /links</li><li>GET /stats/{code}</li>
          <li>GET /s/{code}</li><li>GET /admin/review</li>
        </ul>
        """,
    )


@app.post("/shorten")
async def shorten(request: Request):
    data = await request_data(request)
    raw_url = str(data.get("url") or "").strip()
    alias = str(data.get("alias") or "").strip()
    ok, status, reason = url_status(raw_url)
    if not ok:
        return JSONResponse({"error": reason}, status_code=422)
    if alias and not ALIAS_RE.match(alias):
        return JSONResponse({"error": "Invalid alias"}, status_code=422)
    with conn() as c:
        code = alias or generate_code(c)
        if c.execute("SELECT 1 FROM links WHERE code=?", (code,)).fetchone():
            return JSONResponse({"error": "Duplicate alias"}, status_code=409)
        ts = now()
        c.execute(
            "INSERT INTO links(code,url,status,clicks,created_at) VALUES(?,?,?,?,?)",
            (code, raw_url, status, 0, ts),
        )
        add_audit(c, code, "created", raw_url)
        if status == "pending":
            add_audit(c, code, "marked_pending", "Suspicious internal/private destination")
        c.commit()
    return JSONResponse({"url": raw_url, "code": code, "status": status, "short_url": f"/s/{code}", "stats_url": f"/stats/{code}"}, status_code=201)


@app.get("/s/{code}")
def redirect_short(code: str):
    with conn() as c:
        row = get_link(c, code)
        if not row:
            return JSONResponse({"error": "Unknown link"}, status_code=404)
        if row["status"] == "pending":
            return JSONResponse({"error": "Pending review"}, status_code=403)
        if row["status"] == "rejected":
            return JSONResponse({"error": "Rejected"}, status_code=410)
        ts = now()
        c.execute("UPDATE links SET clicks=clicks+1,last_visited_at=? WHERE code=?", (ts, code))
        add_audit(c, code, "redirected", row["url"])
        c.commit()
        return RedirectResponse(row["url"], status_code=302)


@app.get("/stats/{code}", response_class=HTMLResponse)
def stats(code: str):
    with conn() as c:
        row = get_link(c, code)
        if not row:
            return JSONResponse({"error": "Unknown link"}, status_code=404)
        events = c.execute("SELECT * FROM audit_events WHERE code=? ORDER BY id DESC", (code,)).fetchall()
    items = "".join(f"<li>{html.escape(e['event'])}: {html.escape(e['detail'])} — {html.escape(e['created_at'])}</li>" for e in events)
    body = f"""
    <p>Code: {html.escape(row['code'])}</p>
    <p>Original URL: {html.escape(row['url'])}</p>
    <p>Status: {html.escape(row['status'])}</p>
    <p>Click count: {row['clicks']}</p>
    <p>Created: {html.escape(row['created_at'])}</p>
    <p>Last visited: {html.escape(row['last_visited_at'] or '')}</p>
    <h2>Audit history</h2><ul>{items}</ul>
    """
    return render_page("ShortLink Desk Stats", body)


@app.get("/links", response_class=HTMLResponse)
def links(status: str | None = None):
    if status and status not in STATUSES:
        return JSONResponse({"error": "Invalid status"}, status_code=400)
    with conn() as c:
        if status:
            rows = c.execute("SELECT * FROM links WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM links ORDER BY created_at DESC").fetchall()
    body = "<table>" + "".join(
        f"<tr><td>{html.escape(r['code'])}</td><td>{html.escape(r['url'])}</td><td>{html.escape(r['status'])}</td><td>{r['clicks']}</td><td>{html.escape(r['created_at'])}</td><td><a href='/stats/{html.escape(r['code'])}'>stats</a></td></tr>"
        for r in rows
    ) + "</table>"
    return render_page("ShortLink Desk Links", body)


def require_admin(token: str | None):
    return token == admin_token()


@app.get("/admin/review", response_class=HTMLResponse)
def review(x_admin_token: str | None = Header(default=None)):
    if not require_admin(x_admin_token):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    with conn() as c:
        rows = c.execute("SELECT * FROM links WHERE status='pending' ORDER BY created_at DESC").fetchall()
    body = "<ul>" + "".join(
        f"<li>{html.escape(r['code'])} {html.escape(r['url'])} {html.escape(r['created_at'])} POST /admin/review/{html.escape(r['code'])}/decision approve reject</li>"
        for r in rows
    ) + "</ul>"
    return render_page("ShortLink Desk Review", body)


@app.post("/admin/review/{code}/decision")
async def decide(code: str, request: Request, x_admin_token: str | None = Header(default=None)):
    if not require_admin(x_admin_token):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    data = await request_data(request)
    decision = str(data.get("decision") or "").lower()
    reason = str(data.get("reason") or "")
    if decision not in {"approve", "reject"}:
        return JSONResponse({"error": "Invalid decision"}, status_code=400)
    new_status = "approved" if decision == "approve" else "rejected"
    event = "approved" if decision == "approve" else "rejected"
    with conn() as c:
        row = get_link(c, code)
        if not row:
            return JSONResponse({"error": "Unknown link"}, status_code=404)
        if row["status"] != "pending":
            return JSONResponse({"error": "Already decided"}, status_code=409)
        c.execute("UPDATE links SET status=? WHERE code=?", (new_status, code))
        add_audit(c, code, event, reason)
        c.commit()
    return JSONResponse({"code": code, "status": new_status})
