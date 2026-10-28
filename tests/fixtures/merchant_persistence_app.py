"""Live HTTP control for the persistence grader, not a reconciliation solution.

Models real SQLite state, decisions, reports and process restarts. Financial
policy checks remain outside this focused control application's scope.
"""

from collections import Counter
import html
import json
import os
import sqlite3

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse


CORRUPT_STATE = None
HTML_STATE_REPORT = False
app = FastAPI()
DB = os.environ["RECON_DB"]


def save():
    with sqlite3.connect(DB) as conn:
        conn.execute("INSERT OR REPLACE INTO snapshot VALUES (1, ?)", (json.dumps(state),))


with sqlite3.connect(DB) as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS snapshot (id INTEGER PRIMARY KEY, payload TEXT)")
    row = conn.execute("SELECT payload FROM snapshot WHERE id=1").fetchone()
state = json.loads(row[0]) if row else {
    "records": [], "audit": [],
    "exceptions": [
        {"id": 1, "transaction_id": "TX-1201", "category": "amount_mismatch", "state": "pending"},
        {"id": 2, "transaction_id": "TX-1101", "category": "late_settlement", "state": "pending"},
    ],
}
if row and CORRUPT_STATE:
    # Deliberate mutation: terminal status and audit survive, but the decision changes.
    for item in state["exceptions"]:
        if item["state"] == CORRUPT_STATE:
            item["state"] = "rejected"
save()


@app.get("/", response_class=HTMLResponse)
def home():
    return "<h1>Merchant Reconciliation Desk</h1>"


@app.post("/imports/ledger")
async def ledger(request: Request):
    state["records"] = (await request.json())["records"]
    save()
    return {"imported": len(state["records"])}


@app.post("/imports/settlements/{network}")
def settlements(network: str):
    return {"imported": 0}


@app.post("/reconcile/run")
def reconcile():
    return {"run_id": "control-run", "matched": 6, "exceptions": 2}


def require_admin(request):
    if request.headers.get("X-Admin-Token") != os.environ["RECON_ADMIN_TOKEN"]:
        raise HTTPException(401)


@app.get("/admin/exceptions")
def pending(request: Request):
    require_admin(request)
    items = [item for item in state["exceptions"] if item["state"] == "pending"]
    return {"items": items, "total": len(items)}


@app.post("/admin/exceptions/{exception_id}/decision")
async def decide(exception_id: int, request: Request):
    require_admin(request)
    item = next((item for item in state["exceptions"] if item["id"] == exception_id), None)
    if item is None:
        raise HTTPException(404)
    if item["state"] != "pending":
        raise HTTPException(409)
    body = await request.json()
    if body["decision"] == "manual_adjust" and not body.get("reason"):
        raise HTTPException(422)
    item["state"] = {"approve": "approved", "reject": "rejected", "manual_adjust": "manually_adjusted"}[body["decision"]]
    state["audit"].insert(0, body)
    save()
    return item


@app.get("/reports/daily")
def daily(date: str):
    return {"total_amount": sum(record["amount"] for record in state["records"]
                                if record["posted_on"] == date and record["merchant_tier"] != "training")}


@app.get("/reports/exceptions")
def summary():
    counts = dict(Counter(item["state"] for item in state["exceptions"]))
    if HTML_STATE_REPORT:
        rows = "".join(f"<li>{key}: {count}</li>" for key, count in counts.items())
        return HTMLResponse(f"<h2>Counts by state</h2><ul>{rows}</ul>")
    return {"by_state": counts, "total": len(state["exceptions"])}


@app.get("/reports/merchant/{merchant_id}", response_class=HTMLResponse)
def merchant(merchant_id: str):
    exceptions = "".join(f"<li>{item['transaction_id']} {item['state']}</li>" for item in state["exceptions"])
    audit = "".join(f"<li>{html.escape(item['decision'])} {html.escape(item['reason'])}</li>" for item in state["audit"])
    return f"<h1>{html.escape(merchant_id)}</h1><ul>{exceptions}</ul><h2>Audit</h2><ul>{audit}</ul>"


@app.get("/exports/reconciliation.csv", response_class=PlainTextResponse)
def export(run_id: str):
    if ".." in run_id or "/" in run_id:
        raise HTTPException(400)
    return "transaction_id,merchant_id,amount,currency,category,state\nTX-1001,M-100,100,USD,matched,matched\n"
