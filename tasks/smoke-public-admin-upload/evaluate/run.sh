#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
import json, subprocess, sys
from pathlib import Path
code = r'''
import uploads
u = uploads.submit_upload('u1', 'report.txt', 'hello')
assert u['status'] == 'pending'
assert u['filename'] == 'report.txt'
assert u['path'].startswith(uploads.STORAGE_ROOT.rstrip('/') + '/')
assert uploads.admin_list(status='pending')[0]['id'] == u['id']
approved = uploads.admin_approve(u['id'])
assert approved['status'] == 'approved'
assert uploads.admin_list(status='pending') == []
assert uploads.admin_list(status='approved')[0]['id'] == u['id']
for bad in ['../secret.txt', '/tmp/x.txt', 'avatar.png', 'nested/file.md']:
    try: uploads.submit_upload('u1', bad, 'x')
    except ValueError: pass
    else: raise AssertionError(f'{bad} should be rejected')
try: uploads.admin_approve('missing')
except KeyError: pass
else: raise AssertionError('missing upload should fail')
'''
res=subprocess.run([sys.executable,'-c',code],text=True,capture_output=True)
required = {
 'RESEARCH.md':['storage_policy'],
 'PLAN.md':['plan'],
 'VERIFY.md':['verification'],
 'REVIEW.md':['review'],
 'SECURITY.md':['path','traversal'],
}
checks={'upload_passes':res.returncode==0,'source_exists':Path('uploads.py').exists()}
for name, words in required.items():
    text=Path(name).read_text(errors='replace').lower() if Path(name).exists() else ''
    checks[f'{name}_evidence']=bool(text) and all(w.lower() in text for w in words)
score='pass' if all(checks.values()) else 'fail'
details=res.stderr or res.stdout
print(json.dumps({'score':score,'checks':checks,'details':details}, indent=2))
raise SystemExit(0 if score=='pass' else 1)
EOPY
