#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
from __future__ import annotations

import json
import os
import subprocess as sp
import sys
from pathlib import Path

repo_root = Path(os.environ.get("BENCH_REPO_ROOT", "/bench"))
sys.path.insert(0, str(repo_root))

from capability_helpers import evaluate_workflow_evidence
from rubric_helpers import evaluate_rubric

workspace = Path.cwd()
task_id = os.environ.get("BENCH_CURRENT_TASK", "cap-normal-express-inventory")
tasks_root = Path(os.environ.get("BENCH_TASKS", repo_root / "tasks"))
fixture_root = tasks_root / task_id / "fixture"
evaluator_db_path = workspace / ".tmp-evaluator-inventory.json"


def _changed_files() -> list[str]:
    candidates = ["app.js", "tests/api.test.js"]
    changed: list[str] = []
    for rel in candidates:
        current = workspace / rel
        baseline = fixture_root / rel
        if not current.exists():
            continue
        if not baseline.exists() or current.read_bytes() != baseline.read_bytes():
            changed.append(rel)
    return changed


def _task_workflow_specs() -> dict[str, dict[str, object]]:
    shared_terms = ["app.js", "tests/api.test.js", "homepage", "ledger", "low-stock", "adjustments", "file-backed"]
    return {
        "plan": {
            "min_words": 35,
            "min_substantive_lines": 2,
            "evidence_terms": shared_terms,
            "min_evidence_terms": 2,
            "required_terms": ["GET /", "POST /products", "POST /products/{product_id}/adjustments", "GET /reports/low-stock", "GET /products/{product_id}/ledger", "app.js", "tests/api.test.js", "node --test tests/api.test.js"],
            "required_patterns": [r"(?mi)^\s*(?:[-*]\s*)?(?:1\.\s|step\s*1\b|step:\s)", r"(?mi)^\s*(?:[-*]\s*)?(?:2\.\s|step\s*2\b)"],
        },
        "research": {
            "min_words": 35,
            "min_substantive_lines": 2,
            "evidence_terms": ["kb", "api contract", "file-backed", "Node", "tradeoff"],
            "min_evidence_terms": 2,
            "required_terms": ["kb", "api contract", "file-backed", "Node", "no external network"],
            "required_patterns": [r"(?mi)^\s*[-*]?\s*source\s*:", r"(?mi)^\s*[-*]?\s*decision\s*:", r"(?mi)^\s*[-*]?\s*tradeoff\s*:"],
        },
        "verify": {
            "min_words": 30,
            "min_substantive_lines": 1,
            "evidence_terms": shared_terms,
            "min_evidence_terms": 2,
            "required_terms": ["GET /", "node --test tests/api.test.js", "passed"],
            "required_patterns": [r"(?mi)^\s*[-*]?\s*command\s*:", r"(?mi)^\s*[-*]?\s*result\s*:"],
        },
        "review": {
            "min_words": 30,
            "min_substantive_lines": 2,
            "evidence_terms": ["status codes", "homepage", "ledger", "delete", "validation", "schema"],
            "min_evidence_terms": 2,
            "required_terms": ["GET /", "GET /products/{product_id}", "POST /products/{product_id}/adjustments", "GET /products/{product_id}/ledger", "status codes"],
            "required_patterns": [r"(?mi)^\s*[-*]?\s*finding\s*:", r"(?mi)^\s*[-*]?\s*risk\s*:"],
        },
        "appsec": {
            "min_words": 30,
            "min_substantive_lines": 2,
            "evidence_terms": ["validation", "homepage", "duplicate sku", "atomic", "file", "persistence"],
            "min_evidence_terms": 2,
            "required_terms": ["GET /", "duplicate SKU", "atomic", "file"],
            "required_patterns": [r"(?mi)^\s*[-*]?\s*threat\s*:", r"(?mi)^\s*[-*]?\s*mitigation\s*:"],
        },
    }


def _run_functional_checks() -> tuple[dict[str, bool], dict[str, object]]:
    env = os.environ.copy()
    if evaluator_db_path.exists():
        evaluator_db_path.unlink()
    env["INVENTORY_DB"] = str(evaluator_db_path)
    code = r"""
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const dbPath = process.env.INVENTORY_DB;

function loadServer() {
  const modulePath = path.join(process.cwd(), 'app.js');
  delete require.cache[modulePath];
  delete require.cache[require.resolve(modulePath)];
  return require(modulePath).createServer;
}

function listen(server) {
  return new Promise((resolve, reject) => {
    server.listen(0, '127.0.0.1', () => resolve(server.address()));
    server.once('error', reject);
  });
}

function close(server) {
  return new Promise((resolve, reject) => {
    server.close((error) => error ? reject(error) : resolve());
  });
}

async function request(baseUrl, pathname, options = {}) {
  const response = await fetch(`${baseUrl}${pathname}`, {
    headers: { 'content-type': 'application/json', ...(options.headers || {}) },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  return { status: response.status, payload };
}

async function withServer(fn) {
  const createServer = loadServer();
  const server = createServer();
  const address = await listen(server);
  const baseUrl = `http://${address.address}:${address.port}`;
  try {
    return await fn(baseUrl);
  } finally {
    await close(server);
  }
}

(async () => {
  const checks = {
    functional_browser_homepage: false,
    functional_product_crud: false,
    functional_stock_adjustments: false,
    functional_low_stock_reporting: false,
    functional_validation_status_codes: false,
    functional_audit_ledger_history: false,
    functional_persistence_file_backed: false,
  };
  const details = {};

  try {
    let productId = 0;
    await withServer(async (baseUrl) => {
      const homepageResponse = await fetch(`${baseUrl}/`);
      const homepageBody = await homepageResponse.text();
      checks.functional_browser_homepage = (
        homepageResponse.status === 200
        && (homepageResponse.headers.get('content-type') || '').startsWith('text/html')
        && homepageBody.includes('<title>Inventory</title>')
        && homepageBody.includes('Create product')
        && homepageBody.includes('List products')
        && homepageBody.includes('Adjust stock')
        && homepageBody.includes('/reports/low-stock')
        && homepageBody.includes('/products/{product_id}/ledger')
      );
      details.homepage = {
        status: homepageResponse.status,
        contentType: homepageResponse.headers.get('content-type'),
        body: homepageBody,
      };

      const created = await request(baseUrl, '/products', {
        method: 'POST',
        body: {
          sku: 'SKU-100',
          name: 'Stapler',
          priceCents: 1299,
          stock: 8,
          lowStockThreshold: 3,
        },
      });
      productId = created.payload && created.payload.id;
      const listed = await request(baseUrl, '/products');
      const fetched = await request(baseUrl, `/products/${productId}`);
      const updated = await request(baseUrl, `/products/${productId}`, {
        method: 'PATCH',
        body: { name: 'Heavy Stapler', lowStockThreshold: 4 },
      });
      const second = await request(baseUrl, '/products', {
        method: 'POST',
        body: {
          sku: 'SKU-200',
          name: 'Paper',
          priceCents: 599,
          stock: 20,
          lowStockThreshold: 5,
        },
      });
      const removed = await request(baseUrl, `/products/${second.payload.id}`, { method: 'DELETE' });
      const missingDeleted = await request(baseUrl, `/products/${second.payload.id}`);

      checks.functional_product_crud = (
        created.status === 201
        && !!productId
        && listed.status === 200
        && listed.payload.total === 1
        && fetched.status === 200
        && fetched.payload.sku === 'SKU-100'
        && updated.status === 200
        && updated.payload.name === 'Heavy Stapler'
        && updated.payload.lowStockThreshold === 4
        && removed.status === 204
        && missingDeleted.status === 404
      );

      const adjusted = await request(baseUrl, `/products/${productId}/adjustments`, {
        method: 'POST',
        body: { delta: -5, reason: 'Cycle count correction' },
      });
      const lowStock = await request(baseUrl, '/reports/low-stock');
      const ledger = await request(baseUrl, `/products/${productId}/ledger?page=1&page_size=10`);

      checks.functional_stock_adjustments = (
        adjusted.status === 200
        && adjusted.payload.product.stock === 3
        && adjusted.payload.ledgerEntry.delta === -5
      );
      checks.functional_low_stock_reporting = (
        lowStock.status === 200
        && lowStock.payload.total === 1
        && lowStock.payload.items[0].sku === 'SKU-100'
      );
      checks.functional_audit_ledger_history = (
        ledger.status === 200
        && ledger.payload.total >= 3
        && JSON.stringify(ledger.payload.items.slice(0, 3).map((entry) => entry.action)) === JSON.stringify(['adjusted', 'updated', 'created'])
        && ledger.payload.items[0].actor === 'api'
      );

      const invalid = await request(baseUrl, '/products', {
        method: 'POST',
        body: { sku: 'BAD-1', name: 'Missing stock', priceCents: 300 },
      });
      const duplicate = await request(baseUrl, '/products', {
        method: 'POST',
        body: {
          sku: 'SKU-100',
          name: 'Other Stapler',
          priceCents: 1399,
          stock: 1,
          lowStockThreshold: 1,
        },
      });
      const insufficient = await request(baseUrl, `/products/${productId}/adjustments`, {
        method: 'POST',
        body: { delta: -99, reason: 'Bad count' },
      });
      const missingLedger = await request(baseUrl, '/products/999/ledger');

      checks.functional_validation_status_codes = (
        invalid.status === 400
        && duplicate.status === 409
        && insufficient.status === 409
        && missingLedger.status === 404
      );

      details.first_run = { created, listed, fetched, updated, adjusted, lowStock, ledger, invalid, duplicate, insufficient, missingLedger };
    });

    const reloadResult = await withServer(async (baseUrl) => {
      return await request(baseUrl, '/products');
    });

    const freshProcess = spawnSync(process.execPath, ['-e', `
      const { createServer } = require('./app');
      function listen(server) {
        return new Promise((resolve, reject) => {
          server.listen(0, '127.0.0.1', () => resolve(server.address()));
          server.once('error', reject);
        });
      }
      function close(server) {
        return new Promise((resolve, reject) => {
          server.close((error) => error ? reject(error) : resolve());
        });
      }
      async function request(baseUrl, pathname) {
        const response = await fetch(baseUrl + pathname);
        const text = await response.text();
        const payload = text ? JSON.parse(text) : null;
        return { status: response.status, payload };
      }
      (async () => {
        const server = createServer();
        const address = await listen(server);
        const baseUrl = 'http://' + address.address + ':' + address.port;
        const listed = await request(baseUrl, '/products');
        const lowStock = await request(baseUrl, '/reports/low-stock');
        await close(server);
        process.stdout.write(JSON.stringify({ listed, lowStock }));
      })().catch((error) => {
        process.stderr.write(String(error));
        process.exit(1);
      });
    `], {
      cwd: process.cwd(),
      env: process.env,
      encoding: 'utf8',
    });
    const freshPayload = freshProcess.stdout ? JSON.parse(freshProcess.stdout) : null;

    checks.functional_persistence_file_backed = (
      fs.existsSync(dbPath)
      && fs.statSync(dbPath).size > 0
      && reloadResult.status === 200
      && reloadResult.payload.total === 1
      && freshProcess.status === 0
      && freshPayload
      && freshPayload.listed.status === 200
      && freshPayload.listed.payload.total === 1
      && freshPayload.lowStock.status === 200
      && freshPayload.lowStock.payload.total === 1
    );

    details.persistence = {
      dbPath,
      dbExists: fs.existsSync(dbPath),
      dbSize: fs.existsSync(dbPath) ? fs.statSync(dbPath).size : 0,
      reloadResult,
      freshProcess: {
        status: freshProcess.status,
        stdout: freshProcess.stdout,
        stderr: freshProcess.stderr,
        payload: freshPayload,
      },
    };
  } catch (error) {
    details.exception = String(error && error.stack || error);
  }

  process.stdout.write(JSON.stringify({ checks, details }));
})().catch((error) => {
  process.stdout.write(JSON.stringify({
    checks: {
      functional_browser_homepage: false,
      functional_product_crud: false,
      functional_stock_adjustments: false,
      functional_low_stock_reporting: false,
      functional_validation_status_codes: false,
      functional_audit_ledger_history: false,
      functional_persistence_file_backed: false,
    },
    details: { top_level_exception: String(error && error.stack || error) },
  }));
  process.exit(0);
});
"""

    result = sp.run(["node", "-e", code], cwd=workspace, env=env, capture_output=True, text=True)
    if result.stdout.strip():
        payload = json.loads(result.stdout.strip())
        checks = {k: bool(v) for k, v in payload.get("checks", {}).items()}
        details = payload.get("details", {})
    else:
        checks = {
            "functional_browser_homepage": False,
            "functional_product_crud": False,
            "functional_stock_adjustments": False,
            "functional_low_stock_reporting": False,
            "functional_validation_status_codes": False,
            "functional_audit_ledger_history": False,
            "functional_persistence_file_backed": False,
        }
        details = {}
    details["stdout"] = result.stdout.strip()
    details["stderr"] = result.stderr.strip()
    details["returncode"] = result.returncode
    return checks, details


functional_checks, functional_details = _run_functional_checks()
changed_files = _changed_files()
evidence = evaluate_workflow_evidence(
    workspace,
    changed_files=changed_files,
    artifact_specs=_task_workflow_specs(),
)
checks = {**functional_checks, **evidence["checks"]}

rubric = {
    "functionality": {
        "weight": 0.70,
        "checks": {
            "functional_browser_homepage": {"weight": 0.10, "critical": True},
            "functional_product_crud": {"weight": 0.10, "critical": True},
            "functional_stock_adjustments": {"weight": 0.15, "critical": True},
            "functional_low_stock_reporting": {"weight": 0.10},
            "functional_validation_status_codes": {"weight": 0.10},
            "functional_audit_ledger_history": {"weight": 0.05},
            "functional_persistence_file_backed": {"weight": 0.10, "critical": True},
        },
    },
    "workflow_evidence": {
        "weight": 0.20,
        "checks": {
            "plan_relevant": {"weight": 0.10},
            "research_relevant": {"weight": 0.10},
        },
    },
    "verification_review_security": {
        "weight": 0.10,
        "checks": {
            "verify_relevant": {"weight": 0.04},
            "verify_mentions_changed_files": {"weight": 0.02},
            "review_relevant": {"weight": 0.02},
            "appsec_relevant": {"weight": 0.02},
        },
    },
}

result = evaluate_rubric(rubric, checks)
result["checks"] = checks
result["details"] = json.dumps(
    {
        "changed_files": changed_files,
        "functional_details": functional_details,
        "workflow": evidence,
    },
    indent=2,
)
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["score"] == "pass" else 1)
EOPY
