"""Focused tests for the second capability-normal TypeScript approval queue task."""

from __future__ import annotations

import json
import os
import shutil
import subprocess as sp
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TASK_ID = "cap-normal-ts-approval-queue"
_TASK_DIR = _REPO_ROOT / "tasks" / _TASK_ID


_NO_PERSISTENCE_APP = r'''import { createServer } from "node:http";

const adminToken = "queue-admin";
const submissions: any[] = [];
const history = new Map<number, any[]>();
let nextId = 1;

function json(res: any, status: number, payload: unknown) {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(payload));
}

function now() {
  return new Date().toISOString();
}

function parseBody(req: any) {
  return new Promise<any>((resolve, reject) => {
    let raw = "";
    req.on("data", (chunk: Buffer) => {
      raw += chunk.toString("utf8");
    });
    req.on("end", () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch (error) {
        reject(error);
      }
    });
    req.on("error", reject);
  });
}

function logEntry(id: number, action: string, detail: string) {
  const items = history.get(id) || [];
  items.unshift({ id: items.length + 1, submissionId: id, action, detail, createdAt: now() });
  history.set(id, items);
}

createServer(async (req, res) => {
  try {
    const url = new URL(req.url || "/", "http://127.0.0.1");
    if (req.method === "GET" && url.pathname === "/health") {
      return json(res, 200, { ok: true });
    }

    if (req.method === "POST" && url.pathname === "/submissions") {
      const body = await parseBody(req);
      const submission = {
        id: nextId++,
        title: body.title,
        body: body.body,
        status: "pending",
        attachment: { originalName: body.attachmentName, storedPath: `uploads/${Date.now()}-${body.attachmentName}` },
        createdAt: now(),
        updatedAt: now(),
      };
      submissions.push(submission);
      logEntry(submission.id, "submitted", "created");
      return json(res, 201, submission);
    }

    if (req.method === "GET" && url.pathname === "/public/submissions") {
      const approved = submissions.filter((item) => item.status === "approved");
      return json(res, 200, { items: approved, total: approved.length, page: 1, pageSize: approved.length || 1 });
    }

    if (req.headers["x-admin-token"] !== adminToken && url.pathname.startsWith("/admin/")) {
      return json(res, 401, { error: "admin token required" });
    }

    if (req.method === "GET" && url.pathname === "/admin/submissions") {
      const status = url.searchParams.get("status");
      const items = status ? submissions.filter((item) => item.status === status) : submissions;
      return json(res, 200, { items, total: items.length, page: 1, pageSize: items.length || 1 });
    }

    const decisionMatch = url.pathname.match(/^\/admin\/submissions\/(\d+)\/decision$/);
    if (decisionMatch && req.method === "POST") {
      const submission = submissions.find((item) => item.id === Number(decisionMatch[1]));
      if (!submission) {
        return json(res, 404, { error: "submission not found" });
      }
      const body = await parseBody(req);
      submission.status = body.decision;
      submission.updatedAt = now();
      logEntry(submission.id, body.decision, body.note || body.reason || "updated");
      return json(res, 200, submission);
    }

    const historyMatch = url.pathname.match(/^\/admin\/submissions\/(\d+)\/history$/);
    if (historyMatch && req.method === "GET") {
      const id = Number(historyMatch[1]);
      const items = history.get(id) || [];
      return json(res, 200, { items, total: items.length, page: 1, pageSize: items.length || 1 });
    }

    return json(res, 404, { error: "not found" });
  } catch (error) {
    return json(res, 500, { error: String(error) });
  }
}).listen(Number(process.env.PORT || 3100), "127.0.0.1");
'''


_INSECURE_APP = r'''import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, resolve } from "node:path";

const adminToken = "queue-admin";
const dataFile = process.env.APPROVAL_QUEUE_DATA_FILE || "approval-queue.json";
let state = { nextId: 1, submissions: [], history: {} } as any;

try {
  state = JSON.parse(readFileSync(dataFile, "utf8"));
} catch {}

function save() {
  mkdirSync(dirname(resolve(dataFile)), { recursive: true });
  writeFileSync(dataFile, JSON.stringify(state, null, 2));
}

function json(res: any, status: number, payload: unknown) {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(payload));
}

function now() {
  return new Date().toISOString();
}

function parseBody(req: any) {
  return new Promise<any>((resolve, reject) => {
    let raw = "";
    req.on("data", (chunk: Buffer) => {
      raw += chunk.toString("utf8");
    });
    req.on("end", () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch (error) {
        reject(error);
      }
    });
    req.on("error", reject);
  });
}

function logEntry(id: number, action: string, detail: string) {
  const items = state.history[id] || [];
  items.unshift({ id: items.length + 1, submissionId: id, action, detail, createdAt: now() });
  state.history[id] = items;
}

createServer(async (req, res) => {
  try {
    const url = new URL(req.url || "/", "http://127.0.0.1");
    if (req.method === "GET" && url.pathname === "/health") {
      return json(res, 200, { ok: true });
    }

    if (req.method === "POST" && url.pathname === "/submissions") {
      const body = await parseBody(req);
      const submission = {
        id: state.nextId++,
        title: body.title,
        body: body.body,
        status: "pending",
        attachment: { originalName: body.attachmentName, storedPath: body.attachmentName },
        createdAt: now(),
        updatedAt: now(),
      };
      state.submissions.push(submission);
      logEntry(submission.id, "submitted", "created");
      save();
      return json(res, 201, submission);
    }

    if (req.method === "GET" && url.pathname === "/public/submissions") {
      const approved = state.submissions.filter((item: any) => item.status === "approved");
      return json(res, 200, { items: approved, total: approved.length, page: 1, pageSize: approved.length || 1 });
    }

    if (req.headers["x-admin-token"] !== adminToken && url.pathname.startsWith("/admin/")) {
      return json(res, 401, { error: "admin token required" });
    }

    if (req.method === "GET" && url.pathname === "/admin/submissions") {
      const status = url.searchParams.get("status");
      const items = status ? state.submissions.filter((item: any) => item.status === status) : state.submissions;
      return json(res, 200, { items, total: items.length, page: 1, pageSize: items.length || 1 });
    }

    const decisionMatch = url.pathname.match(/^\/admin\/submissions\/(\d+)\/decision$/);
    if (decisionMatch && req.method === "POST") {
      const submission = state.submissions.find((item: any) => item.id === Number(decisionMatch[1]));
      if (!submission) {
        return json(res, 404, { error: "submission not found" });
      }
      const body = await parseBody(req);
      submission.status = body.decision;
      submission.updatedAt = now();
      logEntry(submission.id, body.decision, body.note || body.reason || "updated");
      save();
      return json(res, 200, submission);
    }

    const historyMatch = url.pathname.match(/^\/admin\/submissions\/(\d+)\/history$/);
    if (historyMatch && req.method === "GET") {
      const id = Number(historyMatch[1]);
      const items = state.history[id] || [];
      return json(res, 200, { items, total: items.length, page: 1, pageSize: items.length || 1 });
    }

    return json(res, 404, { error: "not found" });
  } catch (error) {
    return json(res, 500, { error: String(error) });
  }
}).listen(Number(process.env.PORT || 3100), "127.0.0.1");
'''


def _copy_tree(src: Path, dest: Path) -> None:
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        target = dest / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _run_evaluator(workspace: Path) -> tuple[int, dict]:
    env = os.environ.copy()
    env["BENCH_REPO_ROOT"] = str(_REPO_ROOT)
    env["BENCH_TASKS"] = str(_REPO_ROOT / "tasks")
    env["BENCH_CURRENT_TASK"] = _TASK_ID
    result = sp.run(
        ["bash", str(_TASK_DIR / "evaluate" / "run.sh")],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
    )
    stdout = result.stdout.strip()
    start = stdout.find("{")
    if start < 0:
        raise AssertionError(f"evaluator produced no JSON\nstdout={result.stdout}\nstderr={result.stderr}")
    return result.returncode, json.loads(stdout[start:])


def _write_stub_workflow_artifacts(workspace: Path) -> None:
    for name, text in {
        "PLAN.md": "plan steps tests files",
        "RESEARCH.md": "research source decision tradeoff",
        "VERIFY.md": "verify test pass result src/server.ts tests/api.test.ts",
        "REVIEW.md": "review risk issue follow-up",
        "APPSEC.md": "security xss validation path traversal",
    }.items():
        (workspace / name).write_text(text)


class TestCapabilityHardTsApprovalQueueTask:
    def test_task_metadata_marks_capability_workflow(self):
        text = (_TASK_DIR / "task.yaml").read_text()
        assert "task_id: cap-normal-ts-approval-queue" in text
        assert "batch: capability-normal" in text
        assert "scoring_type: numeric" in text
        assert "expected_workflow:" not in text

    def test_browser_homepage_requirement_is_documented_and_graded(self):
        prd = (_TASK_DIR / "PRD.md").read_text()
        prompt = (_TASK_DIR / "Prompt.md").read_text()
        kb = "\n".join(path.read_text() for path in sorted((_TASK_DIR / "kb").glob("*.md")))
        fixture_test = (_TASK_DIR / "fixture" / "tests" / "api.test.ts").read_text()
        evaluator = (_TASK_DIR / "evaluate" / "run.sh").read_text()
        solved_server = (_TASK_DIR / "evaluate" / "solved" / "src" / "server.ts").read_text()

        for text in [prd, prompt, kb]:
            assert "GET /" in text
            assert "Approval Queue" in text
            assert "POST /submissions" in text
            assert "GET /public/submissions" in text
            assert "GET /admin/submissions" in text
            assert "POST /admin/submissions/:id/decision" in text
            assert "GET /admin/submissions/:id/history" in text
            assert "X-Admin-Token" in text

        assert 'test("browser homepage documents the approval workflow"' in fixture_test
        assert 'fetch(`${base}/`)' in fixture_test or 'fetch(`http://127.0.0.1:${PORT - 1}/`)' in fixture_test
        assert "functional_browser_homepage" in evaluator
        assert 'url.pathname === "/"' in solved_server
        assert "<title>Approval Queue</title>" in solved_server

    def test_pristine_fixture_fails(self, tmp_path):
        _copy_tree(_TASK_DIR / "fixture", tmp_path)
        code, result = _run_evaluator(tmp_path)

        assert code != 0
        assert result["score"] == "fail"
        assert result["checks"]["functional_browser_homepage"] is False
        assert result["checks"]["functional_submission_and_moderation_flow"] is False

    def test_reference_solution_passes(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] >= 0.9
        assert result["checks"]["functional_browser_homepage"] is True
        assert result["checks"]["functional_submission_and_moderation_flow"] is True
        assert result["checks"]["functional_public_visibility_and_sanitization"] is True
        assert result["checks"]["functional_attachment_security_and_audit_history"] is True
        assert result["checks"]["functional_pagination_filtering_and_status_codes"] is True
        assert result["checks"]["functional_persistence_file_backed"] is True
        assert result["checks"]["plan_relevant"] is True
        assert result["checks"]["research_relevant"] is True
        assert result["checks"]["verify_relevant"] is True
        assert result["checks"]["review_relevant"] is True
        assert result["checks"]["appsec_relevant"] is True

    def test_missing_workflow_evidence_reduces_score_without_hard_fail(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        for name in ["PLAN.md", "RESEARCH.md", "VERIFY.md", "REVIEW.md", "APPSEC.md"]:
            (tmp_path / name).unlink()

        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] == 0.7
        assert result["checks"]["plan_present"] is False
        assert result["checks"]["review_present"] is False
        assert result["checks"]["appsec_present"] is False

    def test_in_memory_queue_fails_persistence_requirement(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        (tmp_path / "src" / "server.ts").write_text(_NO_PERSISTENCE_APP)

        code, result = _run_evaluator(tmp_path)

        assert code != 0
        assert result["score"] == "fail"
        assert result["checks"]["functional_browser_homepage"] is False
        assert result["checks"]["functional_persistence_file_backed"] is False

    def test_missing_security_controls_fail(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        (tmp_path / "src" / "server.ts").write_text(_INSECURE_APP)

        code, result = _run_evaluator(tmp_path)

        assert code != 0
        assert result["score"] == "fail"
        assert result["checks"]["functional_attachment_security_and_audit_history"] is False
        assert result["checks"]["functional_public_visibility_and_sanitization"] is False

    def test_stripped_response_contract_fails(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        server_path = tmp_path / "src" / "server.ts"
        text = server_path.read_text()
        text = text.replace(
            '''function publicView(submission: Submission) {
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
''',
            '''function publicView(submission: Submission) {
  return {
    id: submission.id,
    status: submission.status,
    body_html: normalizeBodyHtml(submission.body),
  };
}

function adminView(submission: Submission) {
  return {
    id: submission.id,
    status: submission.status,
    attachment: submission.attachment_stored_path
      ? {
          stored_path: submission.attachment_stored_path,
        }
      : null,
  };
}
''',
        )
        server_path.write_text(text)

        code, result = _run_evaluator(tmp_path)

        assert code != 0
        assert result["score"] == "fail"
        assert result["checks"]["functional_submission_and_moderation_flow"] is False
        assert result["checks"]["functional_public_visibility_and_sanitization"] is False

    def test_equivalent_attachment_and_history_shapes_are_accepted(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        server_path = tmp_path / "src" / "server.ts"
        text = server_path.read_text()
        text = text.replace(
            '''function adminView(submission: Submission) {
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
''',
            '''function adminView(submission: Submission) {
  return {
    ...submission,
    attachment_name: submission.attachment_original_name,
    upload_path: submission.attachment_stored_path,
  };
}
''',
        )
        text = text.replace(
            '      return json(res, 200, paginate(history, page, pageSize));\n',
            '      return json(res, 200, { history: paginate(history, page, pageSize) });\n',
        )
        server_path.write_text(text)

        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["checks"]["functional_attachment_security_and_audit_history"] is True
        assert result["checks"]["functional_public_visibility_and_sanitization"] is True
        assert result["checks"]["functional_pagination_filtering_and_status_codes"] is True

    def test_keyword_stub_workflow_artifacts_do_not_receive_full_credit(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        _write_stub_workflow_artifacts(tmp_path)

        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] < 0.9
        assert result["checks"]["plan_relevant"] is False
        assert result["checks"]["research_relevant"] is False
        assert result["checks"]["verify_relevant"] is False
        assert result["checks"]["review_relevant"] is False
        assert result["checks"]["appsec_relevant"] is False
