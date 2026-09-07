#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
import json
import subprocess
import sys
from pathlib import Path

code = r'''
import billing
import hashlib
import hmac
import json

first = billing.ingest_event({'event_id': 'evt_1', 'customer_id': 'cus_1', 'metric': 'seat', 'quantity': 2, 'unit_price_cents': 500})
duplicate = billing.ingest_event({'event_id': 'evt_1', 'customer_id': 'cus_1', 'metric': 'seat', 'quantity': 2, 'unit_price_cents': 500})
second = billing.ingest_event({'event_id': 'evt_2', 'customer_id': 'cus_1', 'metric': 'api', 'quantity': 3, 'unit_price_cents': 25})
invoice = billing.invoice_customer('cus_1')
hook = billing.build_webhook(invoice, 'whsec_test')
payload = hook['payload']
body = json.dumps(payload, sort_keys=True, separators=(',', ':'))
expected = hmac.new(b'whsec_test', body.encode(), hashlib.sha256).hexdigest()

payload_summary = {
    'checks': {
        'ingest_event_accepts_new_events': first is True and second is True,
        'ingest_event_rejects_duplicates': duplicate is False,
        'invoice_customer_summarizes_usage': invoice['customer_id'] == 'cus_1' and invoice['event_count'] == 2 and invoice['total_cents'] == 1075,
        'build_webhook_signs_canonical_payload': payload['type'] == 'invoice.created' and payload['invoice']['total_cents'] == 1075 and hook['signature'] == expected,
        'build_webhook_hides_secret': 'whsec_test' not in json.dumps(payload),
    },
    'details': {
        'functionality': {
            'checks': {
                'ingest_event_accepts_new_events': first is True and second is True,
                'ingest_event_rejects_duplicates': duplicate is False,
                'invoice_customer_summarizes_usage': invoice['customer_id'] == 'cus_1' and invoice['event_count'] == 2 and invoice['total_cents'] == 1075,
                'build_webhook_signs_canonical_payload': payload['type'] == 'invoice.created' and payload['invoice']['total_cents'] == 1075 and hook['signature'] == expected,
                'build_webhook_hides_secret': 'whsec_test' not in json.dumps(payload),
            },
            'evidence': {
                'invoice': invoice,
                'webhook': hook,
                'canonical_body': body,
                'expected_signature': expected,
            },
        },
    },
}
score = 'pass' if all(payload_summary['checks'].values()) else 'fail'
print(json.dumps({'score': score, **payload_summary}, indent=2, sort_keys=True))
raise SystemExit(0 if score == 'pass' else 1)
'''

res = subprocess.run([sys.executable, '-c', code], text=True, capture_output=True)
inner_payload = None
if res.stdout.strip():
    try:
        inner_payload = json.loads(res.stdout)
    except json.JSONDecodeError:
        inner_payload = None
if isinstance(inner_payload, dict):
    details = inner_payload.get('details', {})
else:
    details = {
        'functionality': {
            'checks': {key: False for key in ['ingest_event_accepts_new_events', 'ingest_event_rejects_duplicates', 'invoice_customer_summarizes_usage', 'build_webhook_signs_canonical_payload', 'build_webhook_hides_secret']},
            'evidence': {'raw': res.stderr or res.stdout, 'returncode': res.returncode},
        }
    }
functional_checks = details.get('functionality', {}).get('checks', {}) if isinstance(details, dict) else {}
score = 'pass' if functional_checks and all(functional_checks.values()) else 'fail'
print(json.dumps({'score': score, 'checks': dict(functional_checks), 'details': details}, indent=2, sort_keys=True))
raise SystemExit(0 if score == 'pass' else 1)
EOPY
