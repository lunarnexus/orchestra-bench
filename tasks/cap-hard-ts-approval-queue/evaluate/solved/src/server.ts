import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { basename, dirname, extname, join, resolve } from "node:path";

type Status = "pending" | "approved" | "rejected";

type Submission = {
  id: number;
  title: string;
  submitter_email: string;
  body: string;
  status: Status;
  attachment_original_name: string | null;
  attachment_stored_path: string | null;
  created_at: string;
  updated_at: string;
};

type AuditEntry = {
  id: number;
  submission_id: number;
  action: string;
  detail: string;
  created_at: string;
};

type State = {
  nextSubmissionId: number;
  historyBySubmission: Record<string, AuditEntry[]>;
  submissions: Submission[];
};

const DATA_FILE = resolve(process.env.APPROVAL_QUEUE_DATA_FILE || "approval-queue-data.json");
const UPLOAD_DIR = resolve(process.env.APPROVAL_QUEUE_UPLOAD_DIR || "uploads");
const ADMIN_TOKEN = process.env.APPROVAL_QUEUE_ADMIN_TOKEN || "queue-admin";

function now() {
  return new Date().toISOString();
}

function json(res: any, status: number, payload: unknown, headers: Record<string, string> = {}) {
  res.writeHead(status, { "content-type": "application/json", ...headers });
  res.end(JSON.stringify(payload));
}

function escapeHtml(value: string) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function normalizeBodyHtml(value: string) {
  return escapeHtml(value).replace(/\n/g, "<br />");
}

function parsePositiveInt(raw: string | null, fallback: number) {
  if (raw == null || raw === "") return fallback;
  const value = Number.parseInt(raw, 10);
  if (!Number.isFinite(value) || value < 1) {
    throw validationError("page and page_size must be positive integers", 400);
  }
  return value;
}

function validationError(message: string, status = 422) {
  const error = new Error(message) as Error & { statusCode?: number };
  error.statusCode = status;
  return error;
}

function ensureDirs() {
  mkdirSync(dirname(DATA_FILE), { recursive: true });
  mkdirSync(UPLOAD_DIR, { recursive: true });
}

function loadState(): State {
  ensureDirs();
  try {
    const parsed = JSON.parse(readFileSync(DATA_FILE, "utf8"));
    return {
      nextSubmissionId: Number(parsed.nextSubmissionId) || 1,
      submissions: Array.isArray(parsed.submissions) ? parsed.submissions : [],
      historyBySubmission: parsed.historyBySubmission && typeof parsed.historyBySubmission === "object" ? parsed.historyBySubmission : {},
    };
  } catch {
    return { nextSubmissionId: 1, submissions: [], historyBySubmission: {} };
  }
}

let state = loadState();

function saveState() {
  ensureDirs();
  const tmp = `${DATA_FILE}.tmp`;
  writeFileSync(tmp, JSON.stringify(state, null, 2));
  renameSync(tmp, DATA_FILE);
}

function parseBody(req: any): Promise<any> {
  return new Promise((resolveBody, reject) => {
    let raw = "";
    req.on("data", (chunk: Buffer) => {
      raw += chunk.toString("utf8");
      if (raw.length > 1_000_000) {
        reject(validationError("payload too large", 422));
      }
    });
    req.on("end", () => {
      try {
        resolveBody(raw ? JSON.parse(raw) : {});
      } catch {
        reject(validationError("invalid json", 400));
      }
    });
    req.on("error", reject);
  });
}

function requireString(value: unknown, field: string) {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw validationError(`${field} is required`);
  }
  return value.trim();
}

function validateAttachmentName(name: string) {
  if (!name || name.trim().length === 0) {
    throw validationError("attachment_name must not be empty");
  }
  if (name.includes("/") || name.includes("\\") || name.includes("..") || name.startsWith(".")) {
    throw validationError("attachment_name must be a plain file name");
  }
  return name.trim();
}

function safeFileName(originalName: string) {
  const clean = basename(originalName)
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^[-.]+|[-.]+$/g, "");
  return clean || `attachment${extname(originalName).toLowerCase() || ".txt"}`;
}

function writeAttachment(submissionId: number, originalName: string, content: string) {
  const fileName = `submission-${submissionId}-${safeFileName(originalName)}`;
  const relativePath = join(basename(UPLOAD_DIR), fileName).replace(/\\/g, "/");
  const fullPath = resolve(UPLOAD_DIR, fileName);
  writeFileSync(fullPath, content, "utf8");
  return relativePath;
}

function addAudit(submissionId: number, action: string, detail: string) {
  const key = String(submissionId);
  const current = state.historyBySubmission[key] || [];
  const entry: AuditEntry = {
    id: current.length + 1,
    submission_id: submissionId,
    action,
    detail,
    created_at: now(),
  };
  state.historyBySubmission[key] = [entry, ...current];
}

function submissionOr404(id: number) {
  const item = state.submissions.find((submission) => submission.id === id);
  if (!item) {
    throw validationError("submission not found", 404);
  }
  return item;
}

function paginate<T>(items: T[], page: number, pageSize: number) {
  const start = (page - 1) * pageSize;
  const end = start + pageSize;
  return {
    items: items.slice(start, end),
    total: items.length,
    page,
    page_size: pageSize,
  };
}

function publicView(submission: Submission) {
  return {
    id: submission.id,
    status: submission.status,
    title_html: escapeHtml(submission.title),
    body_html: normalizeBodyHtml(submission.body),
    attachment: submission.attachment_stored_path
      ? {
          original_name: submission.attachment_original_name,
          stored_path: submission.attachment_stored_path,
        }
      : null,
    created_at: submission.created_at,
    updated_at: submission.updated_at,
  };
}

function adminView(submission: Submission) {
  return {
    ...submission,
    attachment: submission.attachment_stored_path
      ? {
          original_name: submission.attachment_original_name,
          stored_path: submission.attachment_stored_path,
        }
      : null,
  };
}

function homepageHtml() {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Approval Queue</title>
  </head>
  <body>
    <h1>Approval Queue</h1>
    <p>Submit content for moderation, review the public approved list, and use the admin queue and audit history routes from this browser entrypoint.</p>
    <p>Admin routes require <code>X-Admin-Token</code>. Public text is escaped before it is rendered so unsafe HTML is not published raw.</p>
    <section>
      <h2>Submit for review</h2>
      <form id="submission-form">
        <label>Title <input name="title" type="text" value="Quarterly launch plan" required /></label>
        <label>Email <input name="submitter_email" type="email" value="author@example.test" required /></label>
        <label>Body <textarea name="body" required>Need approval for &lt;script&gt;alert('xss')&lt;/script&gt; launch notes</textarea></label>
        <label>Attachment name <input name="attachment_name" type="text" value="launch-plan.pdf" /></label>
        <label>Attachment content <textarea name="attachment_content">fixture attachment</textarea></label>
        <button type="submit">POST /submissions</button>
      </form>
      <pre id="submission-result">Use POST /submissions to create a pending moderation item.</pre>
    </section>
    <section>
      <h2>Public approved list</h2>
      <form id="public-form">
        <button type="submit">GET /public/submissions</button>
      </form>
      <pre id="public-result">GET /public/submissions returns approved items with title_html and body_html.</pre>
    </section>
    <section>
      <h2>Admin moderation and history</h2>
      <form id="admin-list-form">
        <label>Token <input name="token" type="text" value="${escapeHtml(ADMIN_TOKEN)}" /></label>
        <label>Status <input name="status" type="text" value="pending" /></label>
        <button type="submit">GET /admin/submissions</button>
      </form>
      <form id="decision-form">
        <label>Token <input name="token" type="text" value="${escapeHtml(ADMIN_TOKEN)}" /></label>
        <label>Submission id <input name="submission_id" type="number" min="1" value="1" required /></label>
        <label>Decision <input name="decision" type="text" value="approved" required /></label>
        <label>Note <input name="note" type="text" value="Looks safe to publish" required /></label>
        <button type="submit">POST /admin/submissions/{id}/decision</button>
      </form>
      <form id="history-form">
        <label>Token <input name="token" type="text" value="${escapeHtml(ADMIN_TOKEN)}" /></label>
        <label>Submission id <input name="submission_id" type="number" min="1" value="1" required /></label>
        <button type="submit">GET /admin/submissions/{id}/history</button>
      </form>
      <pre id="admin-result">Admin route references: GET /admin/submissions, POST /admin/submissions/{id}/decision, and GET /admin/submissions/{id}/history.</pre>
    </section>
    <script>
      const submissionForm = document.getElementById("submission-form");
      const publicForm = document.getElementById("public-form");
      const adminListForm = document.getElementById("admin-list-form");
      const decisionForm = document.getElementById("decision-form");
      const historyForm = document.getElementById("history-form");
      const submissionResult = document.getElementById("submission-result");
      const publicResult = document.getElementById("public-result");
      const adminResult = document.getElementById("admin-result");

      submissionForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const payload = Object.fromEntries(new FormData(submissionForm).entries());
        const response = await fetch("/submissions", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload),
        });
        submissionResult.textContent = JSON.stringify(await response.json(), null, 2);
      });

      publicForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const response = await fetch("/public/submissions?page=1&page_size=20");
        publicResult.textContent = JSON.stringify(await response.json(), null, 2);
      });

      adminListForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = new FormData(adminListForm);
        const params = new URLSearchParams({page: "1", page_size: "20"});
        const status = form.get("status");
        if (status) params.set("status", String(status));
        const response = await fetch("/admin/submissions?" + params.toString(), {
          headers: {"X-Admin-Token": String(form.get("token") || "")},
        });
        adminResult.textContent = JSON.stringify(await response.json(), null, 2);
      });

      decisionForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = new FormData(decisionForm);
        const submissionId = form.get("submission_id");
        const response = await fetch("/admin/submissions/" + submissionId + "/decision", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Admin-Token": String(form.get("token") || ""),
          },
          body: JSON.stringify({
            decision: String(form.get("decision") || ""),
            note: String(form.get("note") || ""),
          }),
        });
        adminResult.textContent = JSON.stringify(await response.json(), null, 2);
      });

      historyForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = new FormData(historyForm);
        const submissionId = form.get("submission_id");
        const response = await fetch("/admin/submissions/" + submissionId + "/history?page=1&page_size=20", {
          headers: {"X-Admin-Token": String(form.get("token") || "")},
        });
        adminResult.textContent = JSON.stringify(await response.json(), null, 2);
      });
    </script>
  </body>
</html>`;
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url || "/", "http://127.0.0.1");
  try {
    if (req.method === "GET" && url.pathname === "/") {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(homepageHtml());
      return;
    }

    if (req.method === "GET" && url.pathname === "/health") {
      return json(res, 200, { ok: true });
    }

    if (req.method === "POST" && url.pathname === "/submissions") {
      const body = await parseBody(req);
      const title = requireString(body.title, "title");
      const submitterEmail = requireString(body.submitter_email, "submitter_email");
      const textBody = requireString(body.body, "body");
      const attachmentName = body.attachment_name == null ? null : validateAttachmentName(String(body.attachment_name));
      const attachmentContent = attachmentName == null ? null : String(body.attachment_content ?? "");

      const createdAt = now();
      const submissionId = state.nextSubmissionId++;
      const storedPath = attachmentName ? writeAttachment(submissionId, attachmentName, attachmentContent || "") : null;
      const submission: Submission = {
        id: submissionId,
        title,
        submitter_email: submitterEmail,
        body: textBody,
        status: "pending",
        attachment_original_name: attachmentName,
        attachment_stored_path: storedPath,
        created_at: createdAt,
        updated_at: createdAt,
      };
      state.submissions = [submission, ...state.submissions];
      addAudit(submission.id, "submitted", `created by ${submitterEmail}`);
      saveState();
      return json(res, 201, adminView(submission));
    }

    if (req.method === "GET" && url.pathname === "/public/submissions") {
      const page = parsePositiveInt(url.searchParams.get("page"), 1);
      const pageSize = parsePositiveInt(url.searchParams.get("page_size"), 20);
      const approved = state.submissions.filter((submission) => submission.status === "approved").map(publicView);
      return json(res, 200, paginate(approved, page, pageSize));
    }

    if (url.pathname.startsWith("/admin/")) {
      if ((req.headers["x-admin-token"] || "") !== ADMIN_TOKEN) {
        return json(res, 401, { error: "admin token required" });
      }
    }

    if (req.method === "GET" && url.pathname === "/admin/submissions") {
      const page = parsePositiveInt(url.searchParams.get("page"), 1);
      const pageSize = parsePositiveInt(url.searchParams.get("page_size"), 20);
      const status = url.searchParams.get("status");
      if (status && !["pending", "approved", "rejected"].includes(status)) {
        throw validationError("status must be pending, approved, or rejected");
      }
      const items = state.submissions.filter((submission) => !status || submission.status === status).map(adminView);
      return json(res, 200, paginate(items, page, pageSize));
    }

    const decisionMatch = url.pathname.match(/^\/admin\/submissions\/(\d+)\/decision$/);
    if (decisionMatch && req.method === "POST") {
      const submission = submissionOr404(Number(decisionMatch[1]));
      const body = await parseBody(req);
      const decisionRaw = requireString(body.decision, "decision").toLowerCase();
      if (decisionRaw !== "approved" && decisionRaw !== "rejected") {
        throw validationError("decision must be approved or rejected");
      }
      const note = requireString(body.note, "note");
      submission.status = decisionRaw as Status;
      submission.updated_at = now();
      addAudit(submission.id, decisionRaw, note);
      saveState();
      return json(res, 200, adminView(submission));
    }

    const historyMatch = url.pathname.match(/^\/admin\/submissions\/(\d+)\/history$/);
    if (historyMatch && req.method === "GET") {
      submissionOr404(Number(historyMatch[1]));
      const page = parsePositiveInt(url.searchParams.get("page"), 1);
      const pageSize = parsePositiveInt(url.searchParams.get("page_size"), 20);
      const history = state.historyBySubmission[String(historyMatch[1])] || [];
      return json(res, 200, paginate(history, page, pageSize));
    }

    return json(res, 404, { error: "not found" });
  } catch (error: any) {
    const status = Number(error?.statusCode) || 500;
    const message = typeof error?.message === "string" ? error.message : "internal error";
    return json(res, status, { error: message });
  }
});

server.listen(Number(process.env.PORT || 3100), "127.0.0.1");

process.on("SIGTERM", () => {
  server.close(() => process.exit(0));
});
