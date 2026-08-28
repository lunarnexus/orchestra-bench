from fastapi import FastAPI, HTTPException

app = FastAPI(title="Doc Sync API")


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/documents")
def save_document(payload: dict):
    raise HTTPException(status_code=501, detail="TODO: implement SQLite-backed document create/update")


@app.get("/documents/{slug}")
def get_document(slug: str):
    raise HTTPException(status_code=501, detail="TODO: implement document lookup")


@app.post("/sync-jobs")
def create_sync_job(payload: dict):
    raise HTTPException(status_code=501, detail="TODO: implement durable sync jobs with idempotency")


@app.get("/sync-jobs/{job_id}")
def get_sync_job(job_id: int):
    raise HTTPException(status_code=501, detail="TODO: implement job polling")


@app.get("/admin/sync-jobs")
def list_sync_jobs(page: int = 1, page_size: int = 20, status: str | None = None, slug: str | None = None):
    raise HTTPException(status_code=501, detail="TODO: implement admin list, auth, and pagination")


@app.get("/admin/sync-jobs/{job_id}/history")
def job_history(job_id: int, page: int = 1, page_size: int = 20):
    raise HTTPException(status_code=501, detail="TODO: implement audit history")
