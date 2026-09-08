#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
import json
import subprocess
import sys
from pathlib import Path

code = r'''
import json
import support
request = support.submit_request('user@example.com', 'Billing', 'Need receipt')
created_id = request['id']
created_pending = request['status'] == 'pending' and bool(created_id)
pending = support.admin_list(status='pending')
resolved = support.admin_resolve(created_id, 'sent receipt')

payload = {
    'checks': {
        'submit_request_creates_pending_request': created_pending,
        'admin_list_filters_pending_requests': [item['id'] for item in pending] == [created_id],
        'admin_resolve_updates_status_and_note': resolved['status'] == 'resolved' and resolved['admin_note'] == 'sent receipt',
        'admin_list_filters_resolved_requests': support.admin_list(status='resolved')[0]['id'] == created_id,
        'admin_resolve_missing_request_fails': False,
    },
    'details': {
        'functionality': {
            'checks': {
                'submit_request_creates_pending_request': created_pending,
                'admin_list_filters_pending_requests': [item['id'] for item in pending] == [created_id],
                'admin_resolve_updates_status_and_note': resolved['status'] == 'resolved' and resolved['admin_note'] == 'sent receipt',
                'admin_list_filters_resolved_requests': support.admin_list(status='resolved')[0]['id'] == created_id,
                'admin_resolve_missing_request_fails': False,
            },
            'evidence': {
                'request': request,
                'pending_ids': [item['id'] for item in pending],
                'resolved_request': resolved,
            },
        },
    },
}
try:
    support.admin_resolve('missing', 'x')
except KeyError:
    payload['checks']['admin_resolve_missing_request_fails'] = True
    payload['details']['functionality']['checks']['admin_resolve_missing_request_fails'] = True
    payload['details']['functionality']['evidence']['missing_request_error'] = 'KeyError'
else:
    raise AssertionError('missing id should fail')

score = 'pass' if all(payload['checks'].values()) else 'fail'
print(json.dumps({'score': score, **payload}, indent=2, sort_keys=True))
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
            'checks': {key: False for key in ['submit_request_creates_pending_request', 'admin_list_filters_pending_requests', 'admin_resolve_updates_status_and_note', 'admin_list_filters_resolved_requests', 'admin_resolve_missing_request_fails']},
            'evidence': {'raw': res.stderr or res.stdout, 'returncode': res.returncode},
        }
    }
functional_checks = details.get('functionality', {}).get('checks', {}) if isinstance(details, dict) else {}
score = 'pass' if functional_checks and all(functional_checks.values()) else 'fail'
print(json.dumps({'score': score, 'checks': dict(functional_checks), 'details': details}, indent=2, sort_keys=True))
raise SystemExit(0 if score == 'pass' else 1)
EOPY
