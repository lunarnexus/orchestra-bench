"""Focused tests for the second capability-easy Express-style inventory task."""

from __future__ import annotations

import json
import os
import shutil
import subprocess as sp
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TASK_ID = "cap-easy-express-inventory"
_TASK_DIR = _REPO_ROOT / "tasks" / _TASK_ID


_IN_MEMORY_APP = r'''const http = require("node:http");

const products = [];
const ledger = new Map();
let nextId = 1;

function json(res, status, payload) {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(payload));
}

function now() {
  return new Date().toISOString();
}

function parseBody(req) {
  return new Promise((resolve, reject) => {
    let raw = "";
    req.on("data", (chunk) => {
      raw += chunk;
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

function entry(productId, action, detail, extra = {}) {
  const items = ledger.get(productId) || [];
  items.unshift({ id: items.length + 1, productId, action, actor: "api", detail, createdAt: now(), ...extra });
  ledger.set(productId, items);
}

function createServer() {
  return http.createServer(async (req, res) => {
    try {
      const url = new URL(req.url, "http://127.0.0.1");
      if (req.method === "POST" && url.pathname === "/products") {
        const body = await parseBody(req);
        const product = {
          id: nextId++,
          sku: body.sku,
          name: body.name,
          priceCents: body.priceCents,
          stock: body.stock,
          lowStockThreshold: body.lowStockThreshold,
          createdAt: now(),
          updatedAt: now(),
        };
        products.unshift(product);
        entry(product.id, "created", `created ${product.sku}`);
        return json(res, 201, product);
      }

      if (req.method === "GET" && url.pathname === "/products") {
        return json(res, 200, { items: products, total: products.length });
      }

      const productMatch = url.pathname.match(/^\/products\/(\d+)$/);
      if (productMatch && req.method === "GET") {
        const product = products.find((item) => item.id === Number(productMatch[1]));
        if (!product) {
          return json(res, 404, { error: "product not found" });
        }
        return json(res, 200, product);
      }

      if (productMatch && req.method === "PATCH") {
        const product = products.find((item) => item.id === Number(productMatch[1]));
        if (!product) {
          return json(res, 404, { error: "product not found" });
        }
        const body = await parseBody(req);
        if (body.name) {
          product.name = body.name;
        }
        if (typeof body.lowStockThreshold === "number") {
          product.lowStockThreshold = body.lowStockThreshold;
        }
        product.updatedAt = now();
        entry(product.id, "updated", "updated product");
        return json(res, 200, product);
      }

      if (productMatch && req.method === "DELETE") {
        const index = products.findIndex((item) => item.id === Number(productMatch[1]));
        if (index === -1) {
          return json(res, 404, { error: "product not found" });
        }
        products.splice(index, 1);
        return res.writeHead(204).end();
      }

      const adjustmentMatch = url.pathname.match(/^\/products\/(\d+)\/adjustments$/);
      if (adjustmentMatch && req.method === "POST") {
        const product = products.find((item) => item.id === Number(adjustmentMatch[1]));
        if (!product) {
          return json(res, 404, { error: "product not found" });
        }
        const body = await parseBody(req);
        product.stock += body.delta;
        product.updatedAt = now();
        entry(product.id, "adjusted", body.reason || "adjusted", { delta: body.delta, stockAfter: product.stock });
        return json(res, 200, { product, ledgerEntry: ledger.get(product.id)[0] });
      }

      const ledgerMatch = url.pathname.match(/^\/products\/(\d+)\/ledger$/);
      if (ledgerMatch && req.method === "GET") {
        const productId = Number(ledgerMatch[1]);
        if (!products.find((item) => item.id === productId)) {
          return json(res, 404, { error: "product not found" });
        }
        const items = ledger.get(productId) || [];
        return json(res, 200, { items, total: items.length, page: 1, pageSize: items.length || 1 });
      }

      if (req.method === "GET" && url.pathname === "/reports/low-stock") {
        const items = products.filter((item) => item.stock <= item.lowStockThreshold);
        return json(res, 200, { items, total: items.length });
      }

      return json(res, 404, { error: "not found" });
    } catch (error) {
      return json(res, 500, { error: String(error) });
    }
  });
}

module.exports = { createServer };
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
        "VERIFY.md": "verify test pass result app.js tests/api.test.js",
        "REVIEW.md": "review risk issue follow-up",
        "APPSEC.md": "security validation input persistence",
    }.items():
        (workspace / name).write_text(text)


def _write_token_salad_workflow_artifacts(workspace: Path) -> None:
    for name, text in {
        "PLAN.md": "plan steps tests files app.js adjustments ledger low-stock report",
        "RESEARCH.md": "research source decision tradeoff kb api contract file-backed persistence",
        "VERIFY.md": "verify test pass result app.js tests/api.test.js adjustments ledger low-stock",
        "REVIEW.md": "review risk issue follow-up status codes ledger delete validation",
        "APPSEC.md": "security validation duplicate sku file persistence atomic write",
    }.items():
        (workspace / name).write_text(text)


def _write_padded_filler_workflow_artifacts(workspace: Path) -> None:
    for name, text in {
        "PLAN.md": "Plan and files for app.js with adjustments, ledger, low-stock report, and tests are noted here. Plan and tests are mentioned again with files and steps.",
        "RESEARCH.md": "Research and source decision tradeoff for kb, api contract, and file-backed persistence are listed here. Source and tradeoff notes are repeated here.",
        "VERIFY.md": "Verify and test pass result for app.js, tests/api.test.js, adjustments, ledger, and low-stock report are noted here. Test result evidence is repeated.",
        "REVIEW.md": "Review and risk issue follow-up for status codes, ledger, delete, and validation are noted here. Review risk and status are repeated.",
        "APPSEC.md": "Security and validation notes for duplicate sku, file persistence, and atomic write are noted here. Security validation and persistence notes are repeated.",
    }.items():
        (workspace / name).write_text(text)


def _write_labeled_filler_workflow_artifacts(workspace: Path) -> None:
    for name, text in {
        "PLAN.md": "1. Step has POST /products and POST /products/{product_id}/adjustments for noted work.\n2. Step has GET /reports/low-stock and GET /products/{product_id}/ledger for noted work.",
        "RESEARCH.md": "source: kb and api contract are listed for the task.\ndecision: file-backed persistence is listed as the decision.\ntradeoff: no external network and tradeoff are listed for the task.",
        "VERIFY.md": "command: node --test tests/api.test.js\nresult: passed and app.js tests/api.test.js adjustments ledger low-stock report are listed.",
        "REVIEW.md": "finding: status codes ledger delete validation and GET /products/{product_id} are listed here.\nrisk: status codes and ledger risk are listed here.",
        "APPSEC.md": "threat: duplicate sku validation file persistence atomic write are listed here.\nmitigation: validation atomic write and file persistence are listed here.",
    }.items():
        (workspace / name).write_text(text)


class TestCapabilityNormalExpressInventoryTask:
    def test_task_metadata_marks_capability_workflow(self):
        text = (_TASK_DIR / "task.yaml").read_text()
        assert "task_id: cap-easy-express-inventory" in text
        assert "batch: capability-easy" in text
        assert "scoring_type: numeric" in text
        assert "expected_workflow: planner,researcher,builder,verifier,reviewer,appsec" in text

    def test_pristine_fixture_fails(self, tmp_path):
        _copy_tree(_TASK_DIR / "fixture", tmp_path)
        code, result = _run_evaluator(tmp_path)

        assert code != 0
        assert result["score"] == "fail"
        assert result["checks"]["functional_browser_homepage"] is False
        assert result["checks"]["functional_product_crud"] is False

    def test_reference_solution_passes(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] >= 0.9
        assert result["checks"]["functional_browser_homepage"] is True
        assert result["checks"]["functional_product_crud"] is True
        assert result["checks"]["functional_stock_adjustments"] is True
        assert result["checks"]["functional_low_stock_reporting"] is True
        assert result["checks"]["functional_validation_status_codes"] is True
        assert result["checks"]["functional_audit_ledger_history"] is True
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

    def test_evaluator_ignores_stale_workspace_database(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        (tmp_path / ".evaluator-inventory.json").write_text(
            json.dumps(
                {
                    "nextProductId": 2,
                    "nextLedgerId": 4,
                    "products": [
                        {
                            "id": 1,
                            "sku": "SKU-100",
                            "name": "Heavy Stapler",
                            "priceCents": 1299,
                            "stock": 3,
                            "lowStockThreshold": 4,
                            "createdAt": "2026-08-11T23:32:35.208Z",
                            "updatedAt": "2026-08-11T23:32:35.245Z",
                        }
                    ],
                    "ledger": [
                        {"id": 1, "productId": 1, "action": "created", "actor": "api", "detail": "created SKU-100", "createdAt": "2026-08-11T23:32:35.208Z", "stockAfter": 8},
                        {"id": 2, "productId": 1, "action": "updated", "actor": "api", "detail": "updated SKU-100", "createdAt": "2026-08-11T23:32:35.245Z", "stockAfter": 8},
                        {"id": 3, "productId": 1, "action": "adjusted", "actor": "api", "detail": "Cycle count correction (-5)", "createdAt": "2026-08-11T23:32:35.264Z", "delta": -5, "stockAfter": 3},
                    ],
                }
            )
        )

        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["checks"]["functional_product_crud"] is True
        assert result["checks"]["functional_stock_adjustments"] is True

    def test_in_memory_inventory_fails_persistence_requirement(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        (tmp_path / "app.js").write_text(_IN_MEMORY_APP)

        code, result = _run_evaluator(tmp_path)

        assert code != 0
        assert result["score"] == "fail"
        assert result["checks"]["functional_browser_homepage"] is False
        assert result["checks"]["functional_product_crud"] is True
        assert result["checks"]["functional_persistence_file_backed"] is False

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

    def test_token_salad_workflow_artifacts_do_not_receive_full_credit(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        _write_token_salad_workflow_artifacts(tmp_path)

        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] < 0.9
        assert result["checks"]["plan_relevant"] is False
        assert result["checks"]["research_relevant"] is False
        assert result["checks"]["verify_relevant"] is False
        assert result["checks"]["review_relevant"] is False
        assert result["checks"]["appsec_relevant"] is False

    def test_padded_filler_workflow_artifacts_do_not_receive_full_credit(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        _write_padded_filler_workflow_artifacts(tmp_path)

        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] < 0.9
        assert result["checks"]["plan_relevant"] is False
        assert result["checks"]["research_relevant"] is False
        assert result["checks"]["verify_relevant"] is False
        assert result["checks"]["review_relevant"] is False
        assert result["checks"]["appsec_relevant"] is False

    def test_labeled_filler_workflow_artifacts_do_not_receive_full_credit(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        _write_labeled_filler_workflow_artifacts(tmp_path)

        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] < 0.9
        assert result["checks"]["plan_relevant"] is False
        assert result["checks"]["research_relevant"] is False
        assert result["checks"]["review_relevant"] is False
