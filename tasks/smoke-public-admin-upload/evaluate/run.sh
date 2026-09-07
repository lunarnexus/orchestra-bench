#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
import json
import subprocess
import sys
from pathlib import Path

code = r'''
import json
import uploads
upload = uploads.submit_upload('u1', 'report.txt', 'hello')
pending = uploads.admin_list(status='pending')
approved = uploads.admin_approve(upload['id'])

payload = {
    'checks': {
        'submit_upload_creates_pending_record': upload['status'] == 'pending' and upload['filename'] == 'report.txt' and upload['path'].startswith(uploads.STORAGE_ROOT.rstrip('/') + '/'),
        'admin_list_filters_pending_uploads': [item['id'] for item in pending] == [upload['id']],
        'admin_approve_marks_upload_approved': approved['status'] == 'approved' and approved['id'] == upload['id'],
        'admin_approve_missing_upload_fails': False,
        'rejected_uploads_raise_value_error': False,
    },
    'details': {
        'functionality': {
            'checks': {
                'submit_upload_creates_pending_record': upload['status'] == 'pending' and upload['filename'] == 'report.txt' and upload['path'].startswith(uploads.STORAGE_ROOT.rstrip('/') + '/'),
                'admin_list_filters_pending_uploads': [item['id'] for item in pending] == [upload['id']],
                'admin_approve_marks_upload_approved': approved['status'] == 'approved' and approved['id'] == upload['id'],
                'admin_approve_missing_upload_fails': False,
                'rejected_uploads_raise_value_error': False,
            },
            'evidence': {
                'upload': upload,
                'pending_ids': [item['id'] for item in pending],
                'approved_upload': approved,
            },
        },
    },
}
for bad in ['../secret.txt', '/tmp/x.txt', 'avatar.png', 'nested/file.md']:
    try:
        uploads.submit_upload('u1', bad, 'x')
    except ValueError:
        continue
    else:
        raise AssertionError(f'{bad} should be rejected')
payload['checks']['rejected_uploads_raise_value_error'] = True
payload['details']['functionality']['checks']['rejected_uploads_raise_value_error'] = True
payload['details']['functionality']['evidence']['rejected_filenames'] = ['../secret.txt', '/tmp/x.txt', 'avatar.png', 'nested/file.md']
try:
    uploads.admin_approve('missing')
except KeyError:
    payload['checks']['admin_approve_missing_upload_fails'] = True
    payload['details']['functionality']['checks']['admin_approve_missing_upload_fails'] = True
    payload['details']['functionality']['evidence']['missing_upload_error'] = 'KeyError'
else:
    raise AssertionError('missing upload should fail')

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
            'checks': {key: False for key in ['submit_upload_creates_pending_record', 'admin_list_filters_pending_uploads', 'admin_approve_marks_upload_approved', 'admin_approve_missing_upload_fails', 'rejected_uploads_raise_value_error']},
            'evidence': {'raw': res.stderr or res.stdout, 'returncode': res.returncode},
        }
    }
functional_checks = details.get('functionality', {}).get('checks', {}) if isinstance(details, dict) else {}
score = 'pass' if functional_checks and all(functional_checks.values()) else 'fail'
print(json.dumps({'score': score, 'checks': dict(functional_checks), 'details': details}, indent=2, sort_keys=True))
raise SystemExit(0 if score == 'pass' else 1)
EOPY
