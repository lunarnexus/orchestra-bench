from fastapi import FastAPI, HTTPException

app = FastAPI(title="Helpdesk API")


@app.post("/tickets")
def create_ticket(payload: dict):
    raise HTTPException(status_code=501, detail="TODO: implement public ticket intake")


@app.get("/admin/tickets")
def list_tickets(page: int = 1, page_size: int = 20, status: str | None = None):
    raise HTTPException(status_code=501, detail="TODO: implement admin pagination and auth")


@app.post("/admin/tickets/{ticket_id}/triage")
def triage_ticket(ticket_id: int, payload: dict):
    raise HTTPException(status_code=501, detail="TODO: implement admin triage")


@app.get("/admin/tickets/{ticket_id}/audit")
def ticket_audit(ticket_id: int, page: int = 1, page_size: int = 20):
    raise HTTPException(status_code=501, detail="TODO: implement audit log")
