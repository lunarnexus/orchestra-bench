#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
import json, subprocess, sys
from pathlib import Path
code = r'''
from pathlib import Path
import migration
old = [
 {'id':'u1','name':'Ada Lovelace','email':'ada@example.com','token':'secret-token','tier':'pro'},
 {'id':'u2','name':'Grace Hopper','email':'grace@example.com','private_note':'internal only'},
]
new = migration.migrate(old)
assert new[0]['full_name'] == 'Ada Lovelace'
assert new[0]['contact']['email'] == 'ada@example.com'
assert new[0]['tier'] == 'pro'
assert new[0]['token'] == 'secret-token'
rolled = migration.rollback(new)
assert rolled[0]['name'] == 'Ada Lovelace'
assert rolled[0]['email'] == 'ada@example.com'
assert rolled[0]['tier'] == 'pro'
assert rolled[1]['private_note'] == 'internal only'
migration.write_release_notes(new, 'release_notes.md')
text = Path('release_notes.md').read_text()
assert '2' in text
assert 'secret-token' not in text
assert 'internal only' not in text
'''
res=subprocess.run([sys.executable,'-c',code],text=True,capture_output=True)
required = {
 'RESEARCH.md':['release_policy','preserve'],
 'PLAN.md':['plan'],
 'VERIFY.md':['verify'],
 'REVIEW.md':['review'],
 'SECURITY.md':['token','private_note'],
}
checks={'migration_passes':res.returncode==0,'source_exists':Path('migration.py').exists(),'release_notes_exists':Path('release_notes.md').exists()}
for name, words in required.items():
    text=Path(name).read_text(errors='replace').lower() if Path(name).exists() else ''
    checks[f'{name}_evidence']=bool(text) and all(w.lower() in text for w in words)
score='pass' if all(checks.values()) else 'fail'
details=res.stderr or res.stdout
print(json.dumps({'score':score,'checks':checks,'details':details}, indent=2))
raise SystemExit(0 if score=='pass' else 1)
EOPY
