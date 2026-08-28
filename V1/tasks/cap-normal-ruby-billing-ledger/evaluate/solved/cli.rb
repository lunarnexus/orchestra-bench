#!/usr/bin/env ruby
require "fileutils"
require "json"
require_relative "./app"

BillingApp.setup!

command = ARGV.shift
case command
when "reconcile"
  customer_id = Integer(ARGV.fetch(0))
  puts JSON.generate(BillingApp.reconciliation_for(customer_id))
when "export"
  customer_id = Integer(ARGV.fetch(0))
  output_path = File.expand_path(ARGV.fetch(1), Dir.pwd)
  FileUtils.mkdir_p(File.dirname(output_path))
  File.write(output_path, BillingApp.export_csv(customer_id))
  puts output_path
else
  warn "usage: ruby cli.rb reconcile CUSTOMER_ID | export CUSTOMER_ID OUTPUT_PATH"
  exit 1
end
