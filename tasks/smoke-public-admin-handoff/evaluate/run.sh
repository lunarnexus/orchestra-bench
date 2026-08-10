#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
import json, subprocess, sys
from pathlib import Path
code = """
import support
r=support.submit_request('user@example.com','Billing','Need receipt')
assert r['status']=='pending'
assert r['id']
pending=support.admin_list(status='pending')
assert [x['id'] for x in pending] == [r['id']]
resolved=support.admin_resolve(r['id'], 'sent receipt')
assert resolved['status']=='resolved'
assert resolved['admin_note']=='sent receipt'
assert support.admin_list(status='pending') == []
assert support.admin_list(status='resolved')[0]['id'] == r['id']
try: support.admin_resolve('missing','x')
except KeyError: pass
else: raise AssertionError('missing id should fail')
"""
res=subprocess.run([sys.executable,'-c',code],text=True,capture_output=True)
CHECKS={'handoff_passes':res.returncode==0,'source_exists':Path('support.py').exists()}
DETAILS=res.stderr or res.stdout

import json
score = 'pass' if all(CHECKS.values()) else 'fail'
print(json.dumps({'score': score, 'checks': CHECKS, 'details': DETAILS}, indent=2))
raise SystemExit(0 if score == 'pass' else 1)
EOPY
