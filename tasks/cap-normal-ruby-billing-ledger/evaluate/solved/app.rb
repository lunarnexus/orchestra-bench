require "csv"
require "json"
require "sqlite3"
require "time"
require "sinatra/base"

class BillingApp < Sinatra::Base
  configure do
    set :show_exceptions, false
    set :database_path, ENV.fetch("BILLING_DB", File.expand_path("billing_ledger.sqlite3", Dir.pwd))
  end

  before do
    content_type :json
    self.class.setup!
  end

  get "/" do
    content_type "text/html"
    <<~HTML
      <!doctype html>
      <html lang="en">
        <head>
          <meta charset="utf-8" />
          <title>Billing Ledger</title>
        </head>
        <body>
          <h1>Billing Ledger</h1>
          <p>Use this browser entrypoint to create customers, record invoices, payments, and refunds, then inspect balances, ledger history, reconciliation, CSV export, and CLI parity.</p>
          <section>
            <h2>Customer and billing routes</h2>
            <ul>
              <li>POST /customers</li>
              <li>POST /invoices</li>
              <li>POST /payments</li>
              <li>POST /refunds</li>
            </ul>
          </section>
          <section>
            <h2>Balance and ledger</h2>
            <ul>
              <li>GET /customers/:id/balance</li>
              <li>GET /customers/:id/ledger</li>
            </ul>
          </section>
          <section>
            <h2>Reconciliation and export</h2>
            <ul>
              <li>GET /customers/:id/reconciliation</li>
              <li>GET /customers/:id/export.csv</li>
            </ul>
          </section>
          <section>
            <h2>CLI parity</h2>
            <ul>
              <li>ruby cli.rb reconcile CUSTOMER_ID</li>
              <li>ruby cli.rb export CUSTOMER_ID OUTPUT_PATH</li>
            </ul>
          </section>
        </body>
      </html>
    HTML
  end

  error JSON::ParserError do
    status 400
    JSON.generate({"error" => "invalid_json"})
  end

  not_found do
    status 404
    JSON.generate({"error" => "not_found"})
  end

  helpers do
    def json_response(payload, status_code = 200)
      status status_code
      JSON.generate(payload)
    end

    def validation_error!(message)
      halt 422, JSON.generate({"error" => "validation_error", "message" => message})
    end

    def parse_json_body(required_keys = [])
      payload = request.body.read.to_s.strip
      data = payload.empty? ? {} : JSON.parse(payload)
      required_keys.each do |key|
        validation_error!("missing #{key}") unless data.key?(key)
      end
      data
    end

    def integer_amount!(value)
      amount = Integer(value)
      validation_error!("amount_cents must be positive") if amount <= 0
      amount
    rescue ArgumentError, TypeError
      validation_error!("amount_cents must be positive")
    end

    def customer!(customer_id)
      row = self.class.find_customer(customer_id)
      halt 404, JSON.generate({"error" => "customer_not_found"}) unless row
      row
    end
  end

  class << self
    def db
      @db ||= begin
        database = SQLite3::Database.new(settings.database_path)
        database.results_as_hash = true
        database.execute("PRAGMA foreign_keys = ON")
        database
      end
    end

    def reset_connection!
      @db&.close
      @db = nil
    rescue StandardError
      @db = nil
    end

    def setup!
      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS customers (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          email TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL
        )
      SQL
      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS ledger_entries (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_id INTEGER NOT NULL,
          entry_type TEXT NOT NULL,
          amount_cents INTEGER NOT NULL,
          delta_cents INTEGER NOT NULL,
          idempotency_key TEXT NOT NULL UNIQUE,
          reference TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY(customer_id) REFERENCES customers(id)
        )
      SQL
    end

    def timestamp
      Time.now.utc.iso8601
    end

    def find_customer(customer_id)
      db.get_first_row("SELECT * FROM customers WHERE id = ?", [customer_id])
    end

    def balance_for(customer_id)
      db.get_first_value("SELECT COALESCE(SUM(delta_cents), 0) FROM ledger_entries WHERE customer_id = ?", [customer_id]).to_i
    end

    def serialize_customer(row)
      {
        "id" => row["id"],
        "name" => row["name"],
        "email" => row["email"],
        "created_at" => row["created_at"],
        "balance_cents" => balance_for(row["id"]),
      }
    end

    def serialize_entry(row)
      {
        "id" => row["id"],
        "customer_id" => row["customer_id"],
        "entry_type" => row["entry_type"],
        "amount_cents" => row["amount_cents"],
        "delta_cents" => row["delta_cents"],
        "idempotency_key" => row["idempotency_key"],
        "reference" => row["reference"],
        "created_at" => row["created_at"],
      }
    end

    def ledger_rows(customer_id)
      db.execute("SELECT * FROM ledger_entries WHERE customer_id = ? ORDER BY id ASC", [customer_id])
    end

    def ledger_items(customer_id)
      running = 0
      ascending = ledger_rows(customer_id).map do |row|
        running += row["delta_cents"].to_i
        serialize_entry(row).merge("running_balance_cents" => running)
      end
      ascending.reverse
    end

    def reconciliation_for(customer_id)
      customer = find_customer(customer_id)
      raise KeyError, "customer_not_found" unless customer

      items = ledger_items(customer_id)
      invoice_cents = items.select { |item| item["entry_type"] == "invoice" }.sum { |item| item["amount_cents"].to_i }
      payment_cents = items.select { |item| item["entry_type"] == "payment" }.sum { |item| item["amount_cents"].to_i }
      refund_cents = items.select { |item| item["entry_type"] == "refund" }.sum { |item| item["amount_cents"].to_i }
      balance_cents = balance_for(customer_id)
      derived = invoice_cents - payment_cents - refund_cents

      {
        "customer_id" => customer_id.to_i,
        "balance_cents" => balance_cents,
        "balanced" => derived == balance_cents,
        "totals" => {
          "invoice_cents" => invoice_cents,
          "payment_cents" => payment_cents,
          "refund_cents" => refund_cents,
        },
        "total_entries" => items.length,
      }
    end

    def export_csv(customer_id)
      customer = find_customer(customer_id)
      raise KeyError, "customer_not_found" unless customer

      CSV.generate do |csv|
        csv << %w[id customer_id entry_type amount_cents delta_cents idempotency_key reference created_at running_balance_cents]
        ledger_items(customer_id).each do |item|
          csv << [
            item["id"],
            item["customer_id"],
            item["entry_type"],
            item["amount_cents"],
            item["delta_cents"],
            item["idempotency_key"],
            item["reference"],
            item["created_at"],
            item["running_balance_cents"],
          ]
        end
      end
    end
  end

  post "/customers" do
    payload = parse_json_body(%w[name email])
    now = self.class.timestamp
    self.class.db.execute(
      "INSERT INTO customers(name, email, created_at) VALUES (?, ?, ?)",
      [payload["name"].to_s.strip, payload["email"].to_s.strip, now],
    )
    customer = self.class.find_customer(self.class.db.last_insert_row_id)
    json_response(self.class.serialize_customer(customer), 201)
  rescue SQLite3::ConstraintException
    validation_error!("email must be unique")
  end

  post "/invoices" do
    create_entry!("invoice", 1, reference_field: "description")
  end

  post "/payments" do
    create_entry!("payment", -1, reference_field: "reference")
  end

  post "/refunds" do
    create_entry!("refund", -1, reference_field: "reason")
  end

  get "/customers/:id/balance" do
    customer = customer!(params[:id])
    json_response(self.class.serialize_customer(customer))
  end

  get "/customers/:id/ledger" do
    customer!(params[:id])
    items = self.class.ledger_items(params[:id])
    json_response({
      "customer_id" => params[:id].to_i,
      "items" => items,
      "total" => items.length,
      "balance_cents" => self.class.balance_for(params[:id]),
    })
  end

  get "/customers/:id/reconciliation" do
    customer!(params[:id])
    json_response(self.class.reconciliation_for(params[:id]))
  end

  get "/customers/:id/export.csv" do
    customer!(params[:id])
    content_type "text/csv"
    attachment "customer-#{params[:id]}-ledger.csv"
    self.class.export_csv(params[:id])
  end

  def create_entry!(entry_type, multiplier, reference_field:)
    payload = parse_json_body(%w[customer_id amount_cents idempotency_key])
    customer!(payload["customer_id"])
    amount_cents = integer_amount!(payload["amount_cents"])
    key = payload["idempotency_key"].to_s.strip
    validation_error!("idempotency_key is required") if key.empty?

    existing = self.class.db.get_first_row("SELECT * FROM ledger_entries WHERE idempotency_key = ?", [key])
    if existing
      return json_response(
        self.class.serialize_entry(existing).merge("balance_cents" => self.class.balance_for(existing["customer_id"])),
        200,
      )
    end

    now = self.class.timestamp
    self.class.db.execute(
      "INSERT INTO ledger_entries(customer_id, entry_type, amount_cents, delta_cents, idempotency_key, reference, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
      [payload["customer_id"], entry_type, amount_cents, amount_cents * multiplier, key, payload[reference_field], now],
    )
    created = self.class.db.get_first_row("SELECT * FROM ledger_entries WHERE id = ?", [self.class.db.last_insert_row_id])
    json_response(
      self.class.serialize_entry(created).merge("balance_cents" => self.class.balance_for(payload["customer_id"])),
      201,
    )
  end
end

BillingApp.run! if $PROGRAM_NAME == __FILE__
