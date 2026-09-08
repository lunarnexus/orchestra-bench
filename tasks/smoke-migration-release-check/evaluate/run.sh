#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
import json
import subprocess
import sys
from pathlib import Path

code = r'''
import json
from pathlib import Path
import migration
old = [
    {'id': 'u1', 'name': 'Ada Lovelace', 'email': 'ada@example.com', 'token': 'secret-token', 'tier': 'pro'},
    {'id': 'u2', 'name': 'Grace Hopper', 'email': 'grace@example.com', 'private_note': 'internal only'},
]
new = migration.migrate(old)
migrated_creates_new_schema = new[0]['full_name'] == 'Ada Lovelace' and new[0]['contact']['email'] == 'ada@example.com'
migrated_preserves_unknown_fields = new[0]['tier'] == 'pro' and new[0]['token'] == 'secret-token'
migration.write_release_notes(new, 'release_notes.md')
notes = Path('release_notes.md').read_text()
rolled = migration.rollback(new)

payload = {
    'checks': {
        'migrate_creates_new_schema': migrated_creates_new_schema,
        'migrate_preserves_unknown_fields': migrated_preserves_unknown_fields,
        'rollback_restores_legacy_fields': rolled[0]['name'] == 'Ada Lovelace' and rolled[0]['email'] == 'ada@example.com' and rolled[1]['private_note'] == 'internal only',
        'release_notes_are_written': Path('release_notes.md').exists() and '2' in notes,
        'release_notes_hide_secret_values': 'secret-token' not in notes and 'internal only' not in notes,
    },
    'details': {
        'functionality': {
            'checks': {
                'migrate_creates_new_schema': migrated_creates_new_schema,
                'migrate_preserves_unknown_fields': migrated_preserves_unknown_fields,
                'rollback_restores_legacy_fields': rolled[0]['name'] == 'Ada Lovelace' and rolled[0]['email'] == 'ada@example.com' and rolled[1]['private_note'] == 'internal only',
                'release_notes_are_written': Path('release_notes.md').exists() and '2' in notes,
                'release_notes_hide_secret_values': 'secret-token' not in notes and 'internal only' not in notes,
            },
            'evidence': {
                'migrated_records': new,
                'rolled_back_records': rolled,
                'release_notes_path': 'release_notes.md',
                'release_notes_excerpt': notes[:400],
            },
        },
    },
}
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
            'checks': {key: False for key in ['migrate_creates_new_schema', 'migrate_preserves_unknown_fields', 'rollback_restores_legacy_fields', 'release_notes_are_written', 'release_notes_hide_secret_values']},
            'evidence': {'raw': res.stderr or res.stdout, 'returncode': res.returncode},
        }
    }
functional_checks = details.get('functionality', {}).get('checks', {}) if isinstance(details, dict) else {}
score = 'pass' if functional_checks and all(functional_checks.values()) else 'fail'
print(json.dumps({'score': score, 'checks': dict(functional_checks), 'details': details}, indent=2, sort_keys=True))
raise SystemExit(0 if score == 'pass' else 1)
EOPY
