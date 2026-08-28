#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
import hashlib, hmac, json, subprocess, sys
from pathlib import Path
code = r'''
import billing, json, hmac, hashlib
assert billing.ingest_event({'event_id':'evt_1','customer_id':'cus_1','metric':'seat','quantity':2,'unit_price_cents':500}) is True
assert billing.ingest_event({'event_id':'evt_1','customer_id':'cus_1','metric':'seat','quantity':2,'unit_price_cents':500}) is False
assert billing.ingest_event({'event_id':'evt_2','customer_id':'cus_1','metric':'api','quantity':3,'unit_price_cents':25}) is True
invoice = billing.invoice_customer('cus_1')
assert invoice['customer_id'] == 'cus_1'
assert invoice['event_count'] == 2
assert invoice['total_cents'] == 1075
hook = billing.build_webhook(invoice, 'whsec_test')
payload = hook['payload']
assert payload['type'] == 'invoice.created'
assert payload['invoice']['total_cents'] == 1075
assert 'whsec_test' not in json.dumps(payload)
body = json.dumps(payload, sort_keys=True, separators=(',', ':'))
expected = hmac.new(b'whsec_test', body.encode(), hashlib.sha256).hexdigest()
assert hook['signature'] == expected
'''
res=subprocess.run([sys.executable,'-c',code],text=True,capture_output=True)
required = {
 'RESEARCH.md':['webhook_contract','hmac'],
 'PLAN.md':['plan'],
 'VERIFY.md':['python'],
 'REVIEW.md':['review'],
 'SECURITY.md':['hmac','secret'],
}
checks={'billing_passes':res.returncode==0,'source_exists':Path('billing.py').exists()}
for name, words in required.items():
    text=Path(name).read_text(errors='replace').lower() if Path(name).exists() else ''
    checks[f'{name}_evidence']=bool(text) and all(w.lower() in text for w in words)
score='pass' if all(checks.values()) else 'fail'
details=res.stderr or res.stdout
print(json.dumps({'score':score,'checks':checks,'details':details}, indent=2))
raise SystemExit(0 if score=='pass' else 1)
EOPY
