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

async function waitForHealth(base: string = BASE) {
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
  const runDir = await mkdtemp(join(tmpdir(), "approval-queue-test-"));
  const child = spawn("node", ["--experimental-strip-types", "src/server.ts"], {
    env: {
      ...process.env,
      PORT: String(PORT - 1),
      APPROVAL_QUEUE_DATA_FILE: join(runDir, "queue.json"),
      APPROVAL_QUEUE_UPLOAD_DIR: join(runDir, "uploads"),
      APPROVAL_QUEUE_ADMIN_TOKEN: "queue-admin",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  try {
    await waitForHealth(`http://127.0.0.1:${PORT - 1}`);

    const response = await fetch(`http://127.0.0.1:${PORT - 1}/`);
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
  const child = spawn("node", ["--experimental-strip-types", "src/server.ts"], {
    env: {
      ...process.env,
      PORT: String(PORT),
      APPROVAL_QUEUE_DATA_FILE: ".test-approval-queue.json",
      APPROVAL_QUEUE_UPLOAD_DIR: ".test-uploads",
      APPROVAL_QUEUE_ADMIN_TOKEN: "queue-admin",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  try {
    await waitForHealth();

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
    assert.match(payload.items[0].body_html, /&lt;script&gt;/);
  } finally {
    child.kill("SIGTERM");
  }
});

test("rejects traversal attachment names", async () => {
  const child = spawn("node", ["--experimental-strip-types", "src/server.ts"], {
    env: {
      ...process.env,
      PORT: String(PORT + 1),
      APPROVAL_QUEUE_DATA_FILE: ".test-approval-queue-2.json",
      APPROVAL_QUEUE_UPLOAD_DIR: ".test-uploads-2",
      APPROVAL_QUEUE_ADMIN_TOKEN: "queue-admin",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  try {
    for (let index = 0; index < 40; index += 1) {
      try {
        const response = await fetch(`http://127.0.0.1:${PORT + 1}/health`);
        if (response.ok) break;
      } catch {}
      await wait(100);
    }

    const response = await fetch(`http://127.0.0.1:${PORT + 1}/submissions`, {
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
  }
});
