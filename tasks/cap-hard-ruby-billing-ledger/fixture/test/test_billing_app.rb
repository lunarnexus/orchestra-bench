ENV["RACK_ENV"] = "test"
ENV["BILLING_DB"] ||= File.expand_path("../tmp/test-billing.sqlite3", __dir__)

require "fileutils"
require "json"
require "minitest/autorun"
require "open3"
require "rack/test"
require_relative "../app"

class BillingAppTest < Minitest::Test
  include Rack::Test::Methods

  def app
    BillingApp
  end

  def setup
    FileUtils.rm_f(db_path)
    BillingApp.reset_connection! if BillingApp.respond_to?(:reset_connection!)
  end

  def teardown
    BillingApp.reset_connection! if BillingApp.respond_to?(:reset_connection!)
    FileUtils.rm_f(db_path)
    FileUtils.rm_f(export_path)
  end

  def test_browser_homepage_documents_routes_and_cli_parity
    get "/"
    assert_equal 200, last_response.status
    assert_includes last_response.headers.fetch("Content-Type"), "text/html"
    body = last_response.body
    assert_includes body, "<title>Billing Ledger</title>"
    assert_includes body, "POST /customers"
    assert_includes body, "POST /invoices"
    assert_includes body, "POST /payments"
    assert_includes body, "POST /refunds"
    assert_includes body, "GET /customers/:id/balance"
    assert_includes body, "GET /customers/:id/ledger"
    assert_includes body, "GET /customers/:id/reconciliation"
    assert_includes body, "GET /customers/:id/export.csv"
    assert_includes body, "ruby cli.rb reconcile CUSTOMER_ID"
    assert_includes body, "ruby cli.rb export CUSTOMER_ID OUTPUT_PATH"
  end

  def test_invoice_payment_refund_flow_and_idempotency
    customer_id = create_customer

    post_json("/invoices", {
      customer_id: customer_id,
      amount_cents: 5000,
      description: "May usage",
      idempotency_key: "inv-may-001",
    })
    assert_equal 201, last_response.status
    invoice = json_body

    post_json("/invoices", {
      customer_id: customer_id,
      amount_cents: 5000,
      description: "May usage",
      idempotency_key: "inv-may-001",
    })
    assert_equal 200, last_response.status
    assert_equal invoice["id"], json_body["id"]

    post_json("/payments", {
      customer_id: customer_id,
      amount_cents: 1500,
      reference: "wire-1001",
      idempotency_key: "pay-1001",
    })
    assert_equal 201, last_response.status

    post_json("/refunds", {
      customer_id: customer_id,
      amount_cents: 500,
      reason: "service credit",
      idempotency_key: "credit-1001",
    })
    assert_equal 201, last_response.status

    get "/customers/#{customer_id}/balance"
    assert_equal 200, last_response.status
    assert_equal 3000, json_body.fetch("balance_cents")

    get "/customers/#{customer_id}/ledger"
    assert_equal 200, last_response.status
    ledger = json_body
    assert_equal 3, ledger.fetch("total")
    assert_equal ["refund", "payment", "invoice"], ledger.fetch("items").map { |item| item.fetch("entry_type") }
    assert_equal 3000, ledger.fetch("balance_cents")
  end

  def test_validation_reconciliation_and_cli_export
    customer_id = create_customer(email: "ap@acme.test")

    post_json("/invoices", {
      customer_id: customer_id,
      amount_cents: -5,
      description: "bad",
      idempotency_key: "inv-bad",
    })
    assert_equal 422, last_response.status

    post_json("/payments", {
      customer_id: 999,
      amount_cents: 100,
      reference: "missing",
      idempotency_key: "pay-missing",
    })
    assert_equal 404, last_response.status

    post_json("/invoices", {
      customer_id: customer_id,
      amount_cents: 2500,
      description: "April usage",
      idempotency_key: "inv-apr-001",
    })
    assert_equal 201, last_response.status

    post_json("/payments", {
      customer_id: customer_id,
      amount_cents: 500,
      reference: "wire-2002",
      idempotency_key: "pay-2002",
    })
    assert_equal 201, last_response.status

    get "/customers/#{customer_id}/reconciliation"
    assert_equal 200, last_response.status
    reconciliation = json_body
    assert_equal true, reconciliation.fetch("balanced")
    assert_equal 2500, reconciliation.fetch("totals").fetch("invoice_cents")
    assert_equal 500, reconciliation.fetch("totals").fetch("payment_cents")
    assert_equal 0, reconciliation.fetch("totals").fetch("refund_cents")

    stdout, status = Open3.capture2({"BILLING_DB" => db_path}, "ruby", File.expand_path("../cli.rb", __dir__), "reconcile", customer_id.to_s)
    assert status.success?
    cli_payload = JSON.parse(stdout)
    assert_equal 2000, cli_payload.fetch("balance_cents")

    _, export_status = Open3.capture2({"BILLING_DB" => db_path}, "ruby", File.expand_path("../cli.rb", __dir__), "export", customer_id.to_s, export_path)
    assert export_status.success?
    csv = File.read(export_path)
    assert_includes csv.lines.first, "entry_type"
    assert_includes csv, "invoice"
    assert_includes csv, "payment"
  end

  def test_persistence_across_reset
    customer_id = create_customer(email: "persist@acme.test")
    post_json("/invoices", {
      customer_id: customer_id,
      amount_cents: 4000,
      description: "Persisted",
      idempotency_key: "persist-1",
    })
    assert_equal 201, last_response.status

    BillingApp.reset_connection! if BillingApp.respond_to?(:reset_connection!)

    get "/customers/#{customer_id}/balance"
    assert_equal 200, last_response.status
    assert_equal 4000, json_body.fetch("balance_cents")
    assert File.exist?(db_path)
  end

  private

  def db_path
    ENV.fetch("BILLING_DB")
  end

  def export_path
    File.expand_path("../tmp/export.csv", __dir__)
  end

  def create_customer(email: "billing@acme.test")
    post_json("/customers", {name: "Acme Co", email: email})
    assert_equal 201, last_response.status
    json_body.fetch("id")
  end

  def post_json(path, payload)
    post path, JSON.generate(payload), {"CONTENT_TYPE" => "application/json"}
  end

  def json_body
    JSON.parse(last_response.body)
  end
end
