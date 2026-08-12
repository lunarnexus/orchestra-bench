"""Focused tests for the first capability-hard Ruby billing ledger task."""

from __future__ import annotations

import json
import os
import shutil
import subprocess as sp
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TASK_ID = "cap-hard-ruby-billing-ledger"
_TASK_DIR = _REPO_ROOT / "tasks" / _TASK_ID


_NO_PERSISTENCE_APP = '''require "json"
require "sinatra/base"

class BillingApp < Sinatra::Base
  set :show_exceptions, false

  CUSTOMERS = []
  LEDGER = []

  before do
    content_type :json
  end

  post "/customers" do
    payload = JSON.parse(request.body.read)
    customer = {
      "id" => CUSTOMERS.length + 1,
      "name" => payload.fetch("name"),
      "email" => payload.fetch("email"),
      "balance_cents" => 0,
    }
    CUSTOMERS << customer
    status 201
    JSON.generate(customer)
  end

  post "/invoices" do
    payload = JSON.parse(request.body.read)
    entry = {
      "id" => LEDGER.length + 1,
      "customer_id" => payload.fetch("customer_id"),
      "entry_type" => "invoice",
      "delta_cents" => payload.fetch("amount_cents"),
      "idempotency_key" => payload.fetch("idempotency_key"),
    }
    LEDGER << entry
    status 201
    JSON.generate(entry)
  end
end
'''


_NO_IDEMPOTENCY_APP = '''require "csv"
require "json"
require "sqlite3"
require "sinatra/base"

class BillingApp < Sinatra::Base
  configure do
    set :database_path, ENV.fetch("BILLING_DB", File.expand_path("billing_ledger.sqlite3", Dir.pwd))
  end

  before do
    content_type :json
    self.class.db.execute <<~SQL
      CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE
      )
    SQL
    self.class.db.execute <<~SQL
      CREATE TABLE IF NOT EXISTS ledger_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        entry_type TEXT NOT NULL,
        delta_cents INTEGER NOT NULL,
        amount_cents INTEGER NOT NULL,
        description TEXT,
        idempotency_key TEXT NOT NULL,
        created_at TEXT NOT NULL
      )
    SQL
  end

  def self.db
    @db ||= SQLite3::Database.new(settings.database_path)
  end

  post "/customers" do
    payload = JSON.parse(request.body.read)
    self.class.db.execute("INSERT INTO customers(name, email) VALUES (?, ?)", [payload.fetch("name"), payload.fetch("email")])
    status 201
    JSON.generate({"id" => self.class.db.last_insert_row_id, "balance_cents" => 0})
  end

  post "/invoices" do
    payload = JSON.parse(request.body.read)
    self.class.db.execute(
      "INSERT INTO ledger_entries(customer_id, entry_type, delta_cents, amount_cents, description, idempotency_key, created_at) VALUES (?, 'invoice', ?, ?, ?, ?, datetime('now'))",
      [payload.fetch("customer_id"), payload.fetch("amount_cents"), payload.fetch("amount_cents"), payload["description"], payload.fetch("idempotency_key")],
    )
    status 201
    JSON.generate({"id" => self.class.db.last_insert_row_id})
  end
end
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


def _ruby_available() -> bool:
    return shutil.which("ruby") is not None


def _write_stub_workflow_artifacts(workspace: Path) -> None:
    for name, text in {
        "PLAN.md": "plan steps tests files",
        "RESEARCH.md": "research source decision tradeoff",
        "VERIFY.md": "verify test pass result app.rb test/test_billing_app.rb",
        "REVIEW.md": "review risk issue follow-up",
        "APPSEC.md": "security auth input validation",
    }.items():
        (workspace / name).write_text(text)


class TestCapabilityHardRubyBillingLedgerTask:
    def test_task_metadata_marks_capability_workflow(self):
        text = (_TASK_DIR / "task.yaml").read_text()
        assert "task_id: cap-hard-ruby-billing-ledger" in text
        assert "batch: capability-hard" in text
        assert "scoring_type: numeric" in text
        assert "expected_workflow: planner,researcher,builder,verifier,reviewer,appsec" in text

    def test_dockerfile_preinstalls_ruby_task_deps(self):
        dockerfile = (_REPO_ROOT / "docker" / "Dockerfile").read_text().lower()
        assert "ruby" in dockerfile
        assert "sqlite3" in dockerfile
        assert "sinatra" in dockerfile

    def test_browser_homepage_requirement_is_documented_and_graded(self):
        prd = (_TASK_DIR / "PRD.md").read_text()
        prompt = (_TASK_DIR / "Prompt.md").read_text()
        kb = "\n".join(path.read_text() for path in sorted((_TASK_DIR / "kb").glob("*.md")))
        fixture_test = (_TASK_DIR / "fixture" / "test" / "test_billing_app.rb").read_text()
        evaluator = (_TASK_DIR / "evaluate" / "run.sh").read_text()
        solved_app = (_TASK_DIR / "evaluate" / "solved" / "app.rb").read_text()

        for text in [prd, prompt, kb]:
            assert "GET /" in text
            assert "Billing Ledger" in text
            assert "POST /customers" in text
            assert "POST /invoices" in text
            assert "POST /payments" in text
            assert "POST /refunds" in text
            assert "GET /customers/:id/balance" in text
            assert "GET /customers/:id/ledger" in text
            assert "GET /customers/:id/reconciliation" in text
            assert "GET /customers/:id/export.csv" in text
            assert "ruby cli.rb reconcile CUSTOMER_ID" in text
            assert "ruby cli.rb export CUSTOMER_ID OUTPUT_PATH" in text

        assert "test_browser_homepage" in fixture_test
        assert 'get "/"' in fixture_test
        assert "functional_browser_homepage" in evaluator
        assert 'get "/" do' in solved_app
        assert "<title>Billing Ledger</title>" in solved_app

    def test_pristine_fixture_fails(self, tmp_path):
        _copy_tree(_TASK_DIR / "fixture", tmp_path)
        code, result = _run_evaluator(tmp_path)

        assert code != 0
        assert result["score"] == "fail"
        assert result["checks"]["functional_browser_homepage"] is False
        assert result["checks"]["functional_customer_and_invoice_flow"] is False

    def test_no_ruby_runtime_cannot_award_static_pass(self, tmp_path):
        if _ruby_available():
            pytest.skip("Ruby is available, so no-runtime fallback is not exercised")
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        (tmp_path / "app.rb").write_text('# post "/customers" idempotency_key UNIQUE SQLite3::Database.new')

        code, result = _run_evaluator(tmp_path)

        assert code != 0
        assert result["score"] == "fail"
        assert result["checks"]["functional_customer_and_invoice_flow"] is False
        assert 'ruby-unavailable' in result["details"]

    def test_reference_solution_passes(self, tmp_path):
        if not _ruby_available():
            pytest.skip("Ruby runtime is provided by benchmark Docker image, not this host")
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] >= 0.9
        assert result["checks"]["functional_browser_homepage"] is True
        assert result["checks"]["functional_customer_and_invoice_flow"] is True
        assert result["checks"]["functional_payments_refunds_and_balance"] is True
        assert result["checks"]["functional_idempotency_and_ledger"] is True
        assert result["checks"]["functional_reconciliation_and_export"] is True
        assert result["checks"]["functional_validation_and_errors"] is True
        assert result["checks"]["functional_persistence_file_backed"] is True
        assert result["checks"]["plan_relevant"] is True
        assert result["checks"]["research_relevant"] is True
        assert result["checks"]["verify_relevant"] is True
        assert result["checks"]["review_relevant"] is True
        assert result["checks"]["appsec_relevant"] is True

    def test_missing_workflow_evidence_reduces_score_without_hard_fail(self, tmp_path):
        if not _ruby_available():
            pytest.skip("Ruby runtime is provided by benchmark Docker image, not this host")
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

    def test_in_memory_store_fails_persistence_requirement(self, tmp_path):
        if not _ruby_available():
            pytest.skip("Ruby runtime is provided by benchmark Docker image, not this host")
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        (tmp_path / "app.rb").write_text(_NO_PERSISTENCE_APP)

        code, result = _run_evaluator(tmp_path)

        assert code != 0
        assert result["score"] == "fail"
        assert result["checks"]["functional_customer_and_invoice_flow"] is True
        assert result["checks"]["functional_persistence_file_backed"] is False

    def test_missing_idempotency_handling_fails(self, tmp_path):
        if not _ruby_available():
            pytest.skip("Ruby runtime is provided by benchmark Docker image, not this host")
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        (tmp_path / "app.rb").write_text(_NO_IDEMPOTENCY_APP)

        code, result = _run_evaluator(tmp_path)

        assert code != 0
        assert result["score"] == "fail"
        assert result["checks"]["functional_customer_and_invoice_flow"] is True
        assert result["checks"]["functional_idempotency_and_ledger"] is False

    def test_keyword_stub_workflow_artifacts_do_not_receive_full_credit(self, tmp_path):
        if not _ruby_available():
            pytest.skip("Ruby runtime is provided by benchmark Docker image, not this host")
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
