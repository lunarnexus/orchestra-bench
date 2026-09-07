import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PORT = 3211;
const BASE = `http://127.0.0.1:${PORT}`;

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForHealth(base: string) {
  for (let index = 0; index < 40; index += 1) {
    try {
      const response = await fetch(`${base}/health`);
      if (response.ok) {
        return;
      }
    } catch {}
    await wait(100);
  }
  throw new Error("server did not become healthy");
}

test("browser homepage documents the approval workflow", async () => {
  const port = PORT - 1;
  const base = `http://127.0.0.1:${port}`;
  const runDir = await mkdtemp(join(tmpdir(), "approval-queue-test-"));
  const child = spawn("node", ["--experimental-strip-types", "src/server.ts"], {
    env: {
      ...process.env,
      PORT: String(port),
      APPROVAL_QUEUE_DATA_FILE: join(runDir, "queue.json"),
      APPROVAL_QUEUE_UPLOAD_DIR: join(runDir, "uploads"),
      APPROVAL_QUEUE_ADMIN_TOKEN: "queue-admin",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  try {
    await waitForHealth(base);

    const response = await fetch(`${base}/`);
    assert.equal(response.status, 200);
    assert.match(response.headers.get("content-type") || "", /text\/html/);
    const html = await response.text();
    assert.match(html, /<title>Approval Queue<\/title>/);
    assert.match(html, /<h1>Approval Queue<\/h1>/);
    assert.match(html, /POST \/submissions/);
    assert.match(html, /GET \/public\/submissions/);
    assert.match(html, /GET \/admin\/submissions/);
    assert.match(html, /POST \/admin\/submissions\/\{id\}\/decision/);
    assert.match(html, /GET \/admin\/submissions\/\{id\}\/history/);
    assert.match(html, /X-Admin-Token/);
  } finally {
    child.kill("SIGTERM");
    await rm(runDir, { recursive: true, force: true });
  }
});

test("approval flow, public visibility, and persistence", async () => {
  const runDir = await mkdtemp(join(tmpdir(), "approval-queue-test-"));
  const child = spawn("node", ["--experimental-strip-types", "src/server.ts"], {
    env: {
      ...process.env,
      PORT: String(PORT),
      APPROVAL_QUEUE_DATA_FILE: join(runDir, "queue.json"),
      APPROVAL_QUEUE_UPLOAD_DIR: join(runDir, "uploads"),
      APPROVAL_QUEUE_ADMIN_TOKEN: "queue-admin",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  try {
    await waitForHealth(BASE);

    const created = await fetch(`${BASE}/submissions`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        title: "Launch <script>alert(1)</script>",
        submitter_email: "author@example.test",
        body: "Hello <script>alert(2)</script>",
        attachment_name: "launch-plan.pdf",
        attachment_content: "hello world",
      }),
    });
    assert.equal(created.status, 201);
    const submission = await created.json();
    assert.equal(submission.title, "Launch <script>alert(1)</script>");
    assert.equal(submission.submitter_email, "author@example.test");
    assert.equal(submission.status, "pending");
    assert.ok(submission.created_at);
    assert.ok(submission.updated_at);

    const approved = await fetch(`${BASE}/admin/submissions/${submission.id}/decision`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-admin-token": "queue-admin",
      },
      body: JSON.stringify({ decision: "approved", note: "safe" }),
    });
    assert.equal(approved.status, 200);

    const publicList = await fetch(`${BASE}/public/submissions`);
    assert.equal(publicList.status, 200);
    const payload = await publicList.json();
    assert.equal(payload.total, 1);
    assert.equal(payload.items[0].status, "approved");
    assert.match(payload.items[0].title_html, /&lt;script&gt;/);
    assert.ok(payload.items[0].created_at);
    assert.match(payload.items[0].body_html, /&lt;script&gt;/);

    const audit = await fetch(`${BASE}/admin/submissions/${submission.id}/history`, {
      headers: { "x-admin-token": "queue-admin" },
    });
    assert.equal(audit.status, 200);
    const auditPayload = await audit.json();
    assert.equal(auditPayload.items[0].submission_id, submission.id);
    assert.equal(auditPayload.items[0].action, "approved");
    assert.ok(auditPayload.items[0].created_at);
  } finally {
    child.kill("SIGTERM");
    await rm(runDir, { recursive: true, force: true });
  }
});

test("rejects traversal attachment names", async () => {
  const port = PORT + 1;
  const base = `http://127.0.0.1:${port}`;
  const runDir = await mkdtemp(join(tmpdir(), "approval-queue-test-"));
  const child = spawn("node", ["--experimental-strip-types", "src/server.ts"], {
    env: {
      ...process.env,
      PORT: String(port),
      APPROVAL_QUEUE_DATA_FILE: join(runDir, "queue.json"),
      APPROVAL_QUEUE_UPLOAD_DIR: join(runDir, "uploads"),
      APPROVAL_QUEUE_ADMIN_TOKEN: "queue-admin",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  try {
    await waitForHealth(base);

    const response = await fetch(`${base}/submissions`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        title: "Bad",
        submitter_email: "bad@example.test",
        body: "Bad",
        attachment_name: "../secret.txt",
        attachment_content: "oops",
      }),
    });
    assert.equal(response.status, 422);
  } finally {
    child.kill("SIGTERM");
    await rm(runDir, { recursive: true, force: true });
  }
});
