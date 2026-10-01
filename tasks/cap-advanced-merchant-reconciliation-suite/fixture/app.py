"""Merchant Reconciliation Desk — FastAPI entrypoint (fixture skeleton).

Starter skeleton for the benchmark task: routes exist, handlers are 501
TODO stubs. Implement behavior against PRD.md and the kb/ policy corpus.
Modules: db, importer, reconcile, reports, audit, security.
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

import audit
import db
import importer
import reconcile
import reports
import security

app = FastAPI(title="Merchant Reconciliation Desk")


@app.on_event("startup")
def _startup() -> None:
    # TODO: db.init_schema() — schema must initialize automatically.
    pass


@app.get("/", response_class=HTMLResponse)
def homepage() -> str:
    return """
    <html><head><title>Merchant Reconciliation Desk</title></head>
    <body>
      <h1>Merchant Reconciliation Desk</h1>
      <p>Fixture skeleton: implement imports, reconciliation, exception
      review, audit history, reports, and CSV export.</p>
      <h2>Routes</h2>
      <ul>
        <li>POST /imports/ledger</li>
        <li>POST /imports/settlements/{network}</li>
        <li>POST /reconcile/run</li>
        <li>GET /admin/exceptions</li>
        <li>POST /admin/exceptions/{exception_id}/decision</li>
        <li>GET /reports/daily?date=YYYY-MM-DD</li>
        <li>GET /reports/merchant/{merchant_id}</li>
        <li>GET /reports/exceptions</li>
        <li>GET /exports/reconciliation.csv?run_id=...</li>
      </ul>
    </body></html>
    """


@app.post("/imports/ledger")
def post_import_ledger(payload: dict):
    # TODO: delegate to importer.import_ledger(payload).
    raise HTTPException(status_code=501, detail="TODO: implement POST /imports/ledger")


@app.post("/imports/settlements/{network}")
def post_import_settlements(network: str, payload: dict):
    # TODO: delegate to importer.import_settlements(network, payload);
    # reject unknown networks.
    raise HTTPException(status_code=501, detail="TODO: implement POST /imports/settlements/{network}")


@app.post("/reconcile/run")
def post_reconcile_run():
    # TODO: delegate to reconcile.run_reconciliation().
    raise HTTPException(status_code=501, detail="TODO: implement POST /reconcile/run")


@app.get("/admin/exceptions")
def get_admin_exceptions():
    # TODO: list unresolved exceptions; require X-Admin-Token (401 if bad).
    raise HTTPException(status_code=501, detail="TODO: implement GET /admin/exceptions")


@app.post("/admin/exceptions/{exception_id}/decision")
def post_exception_decision(exception_id: int, payload: dict):
    # TODO: approve / reject / manual_adjust with reason; 401 bad token,
    # 422 missing reason for manual_adjust, 409 non-pending; audit every
    # decision via audit.record_event.
    raise HTTPException(status_code=501, detail="TODO: implement POST /admin/exceptions/{id}/decision")


@app.get("/reports/daily")
def get_daily_report(date: str):
    # TODO: delegate to reports.daily_report(date); exclude training/test
    # merchants from executive totals.
    raise HTTPException(status_code=501, detail="TODO: implement GET /reports/daily")


@app.get("/reports/merchant/{merchant_id}")
def get_merchant_report(merchant_id: str):
    # TODO: delegate to reports.merchant_report(merchant_id); include
    # audit events and exceptions.
    raise HTTPException(status_code=501, detail="TODO: implement GET /reports/merchant/{merchant_id}")


@app.get("/reports/exceptions")
def get_exceptions_report():
    # TODO: delegate to reports.exceptions_report(); counts by category
    # and state.
    raise HTTPException(status_code=501, detail="TODO: implement GET /reports/exceptions")


@app.get("/exports/reconciliation.csv")
def get_reconciliation_csv(run_id: str):
    # TODO: delegate to reports.export_csv(run_id) + security.safe_export_path.
    raise HTTPException(status_code=501, detail="TODO: implement GET /exports/reconciliation.csv")
