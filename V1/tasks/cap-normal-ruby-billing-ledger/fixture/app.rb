require "json"
require "sinatra/base"

class BillingApp < Sinatra::Base
  set :show_exceptions, false

  before do
    content_type :json
  end

  get "/health" do
    JSON.generate({"ok" => true})
  end

  post "/customers" do
    status 501
    JSON.generate({"error" => "not_implemented"})
  end

  post "/invoices" do
    status 501
    JSON.generate({"error" => "not_implemented"})
  end

  post "/payments" do
    status 501
    JSON.generate({"error" => "not_implemented"})
  end

  post "/refunds" do
    status 501
    JSON.generate({"error" => "not_implemented"})
  end

  get "/customers/:id/balance" do
    status 501
    JSON.generate({"error" => "not_implemented"})
  end

  get "/customers/:id/ledger" do
    status 501
    JSON.generate({"error" => "not_implemented"})
  end

  get "/customers/:id/reconciliation" do
    status 501
    JSON.generate({"error" => "not_implemented"})
  end

  get "/customers/:id/export.csv" do
    status 501
    JSON.generate({"error" => "not_implemented"})
  end
end
