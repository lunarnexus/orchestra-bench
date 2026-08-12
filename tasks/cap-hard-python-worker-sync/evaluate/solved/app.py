from __future__ import annotations

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

import sync_core

app = FastAPI(title="Doc Sync API")


@app.get("/", response_class=HTMLResponse)
def homepage() -> str:
    return """
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>Doc Sync</title>
      </head>
      <body>
        <h1>Doc Sync</h1>
        <p>Create or update a document, queue a sync job, poll job state, and inspect admin history from this browser entrypoint.</p>
        <p>The worker processes queued jobs asynchronously, performs retry handling for transient upstream failures, and marks stale document versions as conflict instead of syncing old content.</p>
        <section>
          <h2>Document create or update</h2>
          <form id="document-form">
            <label>Slug <input name="slug" type="text" value="launch-plan" required /></label>
            <label>Title <input name="title" type="text" value="Launch plan" required /></label>
            <label>Content <textarea name="content" required>Initial draft</textarea></label>
            <button type="submit">POST /documents</button>
          </form>
          <pre id="document-result">POST /documents creates or updates a local document row.</pre>
        </section>
        <section>
          <h2>Queue and poll sync jobs</h2>
          <form id="job-form">
            <label>Slug <input name="slug" type="text" value="launch-plan" required /></label>
            <label>Idempotency key <input name="idempotency_key" type="text" value="launch-v1" required /></label>
            <button type="submit">POST /sync-jobs</button>
          </form>
          <form id="poll-form">
            <label>Job id <input name="job_id" type="number" min="1" value="1" required /></label>
            <button type="submit">GET /sync-jobs/{job_id}</button>
          </form>
          <pre id="job-result">POST /sync-jobs queues the current document version and GET /sync-jobs/{job_id} polls its status.</pre>
        </section>
        <section>
          <h2>Admin list and history</h2>
          <p>Use <code>X-Admin-Token: sync-admin</code> when calling admin routes.</p>
          <form id="admin-list-form">
            <label>Token <input name="token" type="text" value="sync-admin" /></label>
            <label>Status <input name="status" type="text" value="" /></label>
            <label>Slug <input name="slug" type="text" value="" /></label>
            <button type="submit">GET /admin/sync-jobs</button>
          </form>
          <form id="admin-history-form">
            <label>Token <input name="token" type="text" value="sync-admin" /></label>
            <label>Job id <input name="job_id" type="number" min="1" value="1" required /></label>
            <button type="submit">GET /admin/sync-jobs/{job_id}/history</button>
          </form>
          <pre id="admin-result">Admin route references: GET /admin/sync-jobs and GET /admin/sync-jobs/{job_id}/history.</pre>
        </section>
        <script>
          const documentForm = document.getElementById("document-form");
          const jobForm = document.getElementById("job-form");
          const pollForm = document.getElementById("poll-form");
          const adminListForm = document.getElementById("admin-list-form");
          const adminHistoryForm = document.getElementById("admin-history-form");
          const documentResult = document.getElementById("document-result");
          const jobResult = document.getElementById("job-result");
          const adminResult = document.getElementById("admin-result");

          documentForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const payload = Object.fromEntries(new FormData(documentForm).entries());
            const response = await fetch("/documents", {
              method: "POST",
              headers: {"Content-Type": "application/json"},
              body: JSON.stringify(payload),
            });
            documentResult.textContent = JSON.stringify(await response.json(), null, 2);
          });

          jobForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const payload = Object.fromEntries(new FormData(jobForm).entries());
            const response = await fetch("/sync-jobs", {
              method: "POST",
              headers: {"Content-Type": "application/json"},
              body: JSON.stringify(payload),
            });
            jobResult.textContent = JSON.stringify(await response.json(), null, 2);
          });

          pollForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const jobId = new FormData(pollForm).get("job_id");
            const response = await fetch(`/sync-jobs/${jobId}`);
            jobResult.textContent = JSON.stringify(await response.json(), null, 2);
          });

          adminListForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const form = new FormData(adminListForm);
            const token = form.get("token");
            const status = form.get("status");
            const slug = form.get("slug");
            const params = new URLSearchParams({page: "1", page_size: "20"});
            if (status) params.set("status", String(status));
            if (slug) params.set("slug", String(slug));
            const response = await fetch(`/admin/sync-jobs?${params.toString()}`, {
              headers: {"X-Admin-Token": String(token)},
            });
            adminResult.textContent = JSON.stringify(await response.json(), null, 2);
          });

          adminHistoryForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const form = new FormData(adminHistoryForm);
            const token = form.get("token");
            const jobId = form.get("job_id");
            const response = await fetch(`/admin/sync-jobs/${jobId}/history?page=1&page_size=20`, {
              headers: {"X-Admin-Token": String(token)},
            });
            adminResult.textContent = JSON.stringify(await response.json(), null, 2);
          });
        </script>
      </body>
    </html>
    """.strip()


class DocumentPayload(BaseModel):
    slug: str = Field(min_length=1, pattern=r"^[a-z0-9-]+$")
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)


class SyncJobPayload(BaseModel):
    slug: str = Field(min_length=1, pattern=r"^[a-z0-9-]+$")
    idempotency_key: str = Field(min_length=1)


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


def _require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if x_admin_token != sync_core.admin_token():
        raise HTTPException(status_code=401, detail="admin token required")


def _validate_pagination(page: int, page_size: int) -> None:
    if page < 1 or page_size < 1:
        raise HTTPException(status_code=400, detail="page and page_size must be positive")


@app.post("/documents")
def save_document(payload: DocumentPayload):
    document, created = sync_core.save_document(
        slug=payload.slug,
        title=payload.title,
        content=payload.content,
    )
    return JSONResponse(status_code=201 if created else 200, content=document)


@app.get("/documents/{slug}")
def get_document(slug: str):
    document = sync_core.get_document(slug)
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")
    return document


@app.post("/sync-jobs")
def create_sync_job(payload: SyncJobPayload):
    try:
        job, created = sync_core.create_sync_job(slug=payload.slug, idempotency_key=payload.idempotency_key)
    except KeyError:
        raise HTTPException(status_code=404, detail="document not found") from None
    return JSONResponse(status_code=201 if created else 200, content=job)


@app.get("/sync-jobs/{job_id}")
def get_sync_job(job_id: int):
    job = sync_core.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.get("/admin/sync-jobs")
def list_sync_jobs(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    slug: str | None = None,
    _: None = Depends(_require_admin),
):
    _validate_pagination(page, page_size)
    if status is not None and status not in sync_core.JOB_STATUSES:
        raise HTTPException(status_code=400, detail="invalid status filter")
    return sync_core.list_jobs(page=page, page_size=page_size, status=status, slug=slug)


@app.get("/admin/sync-jobs/{job_id}/history")
def job_history(job_id: int, page: int = 1, page_size: int = 20, _: None = Depends(_require_admin)):
    _validate_pagination(page, page_size)
    job = sync_core.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return sync_core.get_history(job_id, page=page, page_size=page_size)
