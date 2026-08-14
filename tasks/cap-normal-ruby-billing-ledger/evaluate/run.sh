#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess as sp
import sys
from pathlib import Path

repo_root = Path(os.environ.get("BENCH_REPO_ROOT", "/bench"))
sys.path.insert(0, str(repo_root))

from capability_helpers import evaluate_workflow_evidence
from rubric_helpers import evaluate_rubric

workspace = Path.cwd()
task_id = os.environ.get("BENCH_CURRENT_TASK", "cap-normal-ruby-billing-ledger")
tasks_root = Path(os.environ.get("BENCH_TASKS", repo_root / "tasks"))
fixture_root = tasks_root / task_id / "fixture"


def _changed_files() -> list[str]:
    candidates = ["app.rb", "cli.rb", "test/test_billing_app.rb"]
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
    shared_terms = [
        "app.rb",
        "cli.rb",
        "test/test_billing_app.rb",
        "sqlite",
        "idempotency",
        "ledger",
        "reconciliation",
        "export",
    ]
    return {
        "plan": {
            "min_words": 35,
            "min_substantive_lines": 2,
            "evidence_terms": shared_terms,
            "min_evidence_terms": 3,
            "required_terms": [
                "POST /invoices",
                "POST /payments",
                "POST /refunds",
                "GET /customers/:id/ledger",
                "app.rb",
                "cli.rb",
                "test/test_billing_app.rb",
                "ruby -Itest test/test_billing_app.rb",
            ],
            "required_patterns": [
                r"(?mi)^\s*(?:[-*]\s*)?(?:1\.\s|step\s*1\b)",
                r"(?mi)^\s*(?:[-*]\s*)?(?:2\.\s|step\s*2\b)",
            ],
        },
        "research": {
            "min_words": 35,
            "min_substantive_lines": 2,
            "evidence_terms": ["kb", "api contract", "sqlite3", "Sinatra", "tradeoff"],
            "min_evidence_terms": 2,
            "required_terms": [
                "kb",
                "sqlite3",
                "Sinatra",
                "idempotency_key",
                "avoid extra ORM",
            ],
            "required_patterns": [
                r"(?mi)^\s*[-*]?\s*source\s*:",
                r"(?mi)^\s*[-*]?\s*decision\s*:",
                r"(?mi)^\s*[-*]?\s*tradeoff\s*:",
            ],
        },
        "verify": {
            "min_words": 30,
            "min_substantive_lines": 1,
            "evidence_terms": shared_terms,
            "min_evidence_terms": 2,
            "required_terms": ["ruby -Itest test/test_billing_app.rb", "passed"],
            "required_patterns": [
                r"(?mi)^\s*[-*]?\s*command\s*:",
                r"(?mi)^\s*[-*]?\s*result\s*:",
            ],
        },
        "review": {
            "min_words": 30,
            "min_substantive_lines": 2,
            "evidence_terms": ["status codes", "schema", "ledger", "idempotency", "export"],
            "min_evidence_terms": 2,
            "required_terms": ["response schemas", "idempotent", "400", "422", "404"],
            "required_patterns": [
                r"(?mi)^\s*[-*]?\s*finding\s*:",
                r"(?mi)^\s*[-*]?\s*risk\s*:",
            ],
        },
        "appsec": {
            "min_words": 30,
            "min_substantive_lines": 2,
            "evidence_terms": ["input", "validation", "sqlite", "parameter", "idempotency"],
            "min_evidence_terms": 2,
            "required_terms": ["idempotency_key", "parameter binding"],
            "required_patterns": [
                r"(?mi)^\s*[-*]?\s*threat\s*:",
                r"(?mi)^\s*[-*]?\s*mitigation\s*:",
            ],
        },
    }


def _run_functional_checks() -> tuple[dict[str, bool], dict[str, object]]:
    ruby = shutil.which("ruby")
    if ruby:
        return _run_ruby_checks(ruby)
    checks = {
        "functional_browser_homepage": False,
        "functional_customer_and_invoice_flow": False,
        "functional_payments_refunds_and_balance": False,
        "functional_idempotency_and_ledger": False,
        "functional_reconciliation_and_export": False,
        "functional_validation_and_errors": False,
        "functional_persistence_file_backed": False,
    }
    return checks, {"mode": "ruby-unavailable", "ruby_available": False}


def _run_ruby_checks(ruby: str) -> tuple[dict[str, bool], dict[str, object]]:
    env = os.environ.copy()
    env["BILLING_DB"] = str(workspace / ".evaluator-billing.sqlite3")
    env["EVAL_RUBY"] = ruby
    code = r'''
require "json"
require "fileutils"
require "open3"
require "rack/test"

ENV["RACK_ENV"] = "test"
ENV["BILLING_DB"] ||= File.expand_path(".evaluator-billing.sqlite3", Dir.pwd)

require_relative "./app"

class EvalHarness
  include Rack::Test::Methods

  def app
    BillingApp
  end

  def post_json(path, payload)
    post path, JSON.generate(payload), {"CONTENT_TYPE" => "application/json"}
  end

  def json_body
    JSON.parse(last_response.body)
  end
end

checks = {
  "functional_browser_homepage" => false,
  "functional_customer_and_invoice_flow" => false,
  "functional_payments_refunds_and_balance" => false,
  "functional_idempotency_and_ledger" => false,
  "functional_reconciliation_and_export" => false,
  "functional_validation_and_errors" => false,
  "functional_persistence_file_backed" => false,
}
details = {}

db_path = ENV.fetch("BILLING_DB")
FileUtils.rm_f(db_path)
BillingApp.reset_connection! if BillingApp.respond_to?(:reset_connection!)
harness = EvalHarness.new

begin
  harness.get("/")
  homepage_status = harness.last_response.status
  homepage_content_type = harness.last_response.headers["Content-Type"].to_s
  homepage_body = harness.last_response.body.to_s
  checks["functional_browser_homepage"] = (
    homepage_status == 200 &&
    homepage_content_type.include?("text/html") &&
    homepage_body.include?("<title>Billing Ledger</title>") &&
    homepage_body.include?("POST /customers") &&
    homepage_body.include?("POST /invoices") &&
    homepage_body.include?("POST /payments") &&
    homepage_body.include?("POST /refunds") &&
    homepage_body.include?("GET /customers/:id/balance") &&
    homepage_body.include?("GET /customers/:id/ledger") &&
    homepage_body.include?("GET /customers/:id/reconciliation") &&
    homepage_body.include?("GET /customers/:id/export.csv") &&
    homepage_body.include?("ruby cli.rb reconcile CUSTOMER_ID") &&
    homepage_body.include?("ruby cli.rb export CUSTOMER_ID OUTPUT_PATH")
  )

  harness.post_json("/customers", {name: "Acme Co", email: "billing@acme.test"})
  customer = harness.json_body
  customer_id = customer["id"]
  checks["functional_customer_and_invoice_flow"] = (
    harness.last_response.status == 201 &&
    !customer_id.nil? &&
    customer["balance_cents"] == 0
  )

  harness.post_json("/invoices", {
    customer_id: customer_id,
    amount_cents: 5000,
    description: "May usage",
    idempotency_key: "inv-may-001",
  })
  invoice = harness.json_body
  first_invoice_status = harness.last_response.status

  harness.post_json("/invoices", {
    customer_id: customer_id,
    amount_cents: 5000,
    description: "May usage",
    idempotency_key: "inv-may-001",
  })
  replay = harness.json_body
  replay_status = harness.last_response.status

  harness.post_json("/payments", {
    customer_id: customer_id,
    amount_cents: 1500,
    reference: "wire-1001",
    idempotency_key: "pay-1001",
  })
  payment_status = harness.last_response.status

  harness.post_json("/refunds", {
    customer_id: customer_id,
    amount_cents: 500,
    reason: "service credit",
    idempotency_key: "credit-1001",
  })
  refund_status = harness.last_response.status

  harness.get("/customers/#{customer_id}/balance")
  balance = harness.json_body
  balance_status = harness.last_response.status
  checks["functional_payments_refunds_and_balance"] = (
    payment_status == 201 &&
    refund_status == 201 &&
    balance_status == 200 &&
    balance["balance_cents"] == 3000
  )

  harness.get("/customers/#{customer_id}/ledger")
  ledger = harness.json_body
  ledger_status = harness.last_response.status
  types = ledger.fetch("items", []).map { |item| item["entry_type"] }
  running = ledger.fetch("items", []).map { |item| item["running_balance_cents"] }
  checks["functional_idempotency_and_ledger"] = (
    first_invoice_status == 201 &&
    replay_status == 200 &&
    replay["id"] == invoice["id"] &&
    ledger_status == 200 &&
    ledger["total"] == 3 &&
    types == ["refund", "payment", "invoice"] &&
    running == [3000, 3500, 5000]
  )

  harness.get("/customers/#{customer_id}/reconciliation")
  reconciliation = harness.json_body
  reconciliation_status = harness.last_response.status

  harness.get("/customers/#{customer_id}/export.csv")
  export_status = harness.last_response.status
  export_body = harness.last_response.body

  cli_reconcile_out, cli_reconcile_status = Open3.capture2({"BILLING_DB" => db_path}, ENV.fetch("EVAL_RUBY"), File.expand_path("cli.rb", Dir.pwd), "reconcile", customer_id.to_s)
  cli_reconcile = cli_reconcile_out.strip.empty? ? {} : JSON.parse(cli_reconcile_out)
  cli_export_path = File.expand_path("tmp/evaluator-export.csv", Dir.pwd)
  FileUtils.mkdir_p(File.dirname(cli_export_path))
  _, cli_export_status = Open3.capture2({"BILLING_DB" => db_path}, ENV.fetch("EVAL_RUBY"), File.expand_path("cli.rb", Dir.pwd), "export", customer_id.to_s, cli_export_path)
  cli_export_body = File.exist?(cli_export_path) ? File.read(cli_export_path) : ""

  checks["functional_reconciliation_and_export"] = (
    reconciliation_status == 200 &&
    reconciliation["balanced"] == true &&
    reconciliation.dig("totals", "invoice_cents") == 5000 &&
    reconciliation.dig("totals", "payment_cents") == 1500 &&
    reconciliation.dig("totals", "refund_cents") == 500 &&
    export_status == 200 &&
    export_body.include?("entry_type") &&
    export_body.include?("invoice") &&
    cli_reconcile_status.success? &&
    cli_reconcile["balance_cents"] == 3000 &&
    cli_export_status.success? &&
    cli_export_body.include?("refund")
  )

  harness.post("/payments", "not-json", {"CONTENT_TYPE" => "application/json"})
  invalid_json_status = harness.last_response.status
  harness.post_json("/refunds", {customer_id: 999, amount_cents: 100, reason: "missing", idempotency_key: "refund-missing"})
  missing_customer_status = harness.last_response.status
  harness.post_json("/invoices", {customer_id: customer_id, amount_cents: 0, description: "bad", idempotency_key: "inv-bad"})
  invalid_amount_status = harness.last_response.status
  checks["functional_validation_and_errors"] = (
    invalid_json_status == 400 &&
    missing_customer_status == 404 &&
    invalid_amount_status == 422
  )

  BillingApp.reset_connection! if BillingApp.respond_to?(:reset_connection!)
  harness.get("/customers/#{customer_id}/balance")
  reloaded = harness.json_body
  reloaded_status = harness.last_response.status

  cli_reloaded_out, cli_reloaded_status = Open3.capture2({"BILLING_DB" => db_path}, ENV.fetch("EVAL_RUBY"), File.expand_path("cli.rb", Dir.pwd), "reconcile", customer_id.to_s)
  cli_reloaded = cli_reloaded_out.strip.empty? ? {} : JSON.parse(cli_reloaded_out)

  checks["functional_persistence_file_backed"] = (
    File.exist?(db_path) &&
    File.size(db_path) > 0 &&
    reloaded_status == 200 &&
    reloaded["balance_cents"] == 3000 &&
    cli_reloaded_status.success? &&
    cli_reloaded["balance_cents"] == 3000
  )

  details = {
    customer: customer,
    invoice: invoice,
    replay: replay,
    balance: balance,
    ledger: ledger,
    reconciliation: reconciliation,
    db_path: db_path,
    db_exists: File.exist?(db_path),
    db_size: File.exist?(db_path) ? File.size(db_path) : 0,
  }
rescue StandardError => e
  details["exception"] = {class: e.class.name, message: e.message, backtrace: e.backtrace&.first(6)}
end

puts JSON.generate({checks: checks, details: details})
'''
    result = sp.run([ruby, "-e", code], cwd=workspace, env=env, capture_output=True, text=True)
    if result.stdout.strip():
        payload = json.loads(result.stdout.strip())
        checks = {k: bool(v) for k, v in payload.get("checks", {}).items()}
        details = payload.get("details", {})
    else:
        checks = {
            "functional_browser_homepage": False,
            "functional_customer_and_invoice_flow": False,
            "functional_payments_refunds_and_balance": False,
            "functional_idempotency_and_ledger": False,
            "functional_reconciliation_and_export": False,
            "functional_validation_and_errors": False,
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
            "functional_browser_homepage": {"weight": 0.05, "critical": True},
            "functional_customer_and_invoice_flow": {"weight": 0.15, "critical": True},
            "functional_payments_refunds_and_balance": {"weight": 0.15},
            "functional_idempotency_and_ledger": {"weight": 0.15, "critical": True},
            "functional_reconciliation_and_export": {"weight": 0.10},
            "functional_validation_and_errors": {"weight": 0.05},
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
# Pass/fail is functional-only. Workflow/process evidence contributes to
# score_numeric/rubric details, but cannot rescue broken product behavior.
functional_pass = all(bool(value) for key, value in checks.items() if key.startswith("functional_"))
result["score"] = "pass" if functional_pass else "fail"
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
