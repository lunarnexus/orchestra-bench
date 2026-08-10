#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
import json
from pathlib import Path
p=Path('answer.md')
text=p.read_text().lower() if p.exists() else ''
CHECKS={
    'answer_exists': p.exists(),
    'mentions_reviewer': 'reviewer' in text or ('mode' in text and 'review' in text),
    'has_findings': 'finding' in text,
    'has_severity': 'high' in text or 'medium' in text or 'severity' in text,
    'has_fix': 'fix' in text or 'remediation' in text,
    'mutat': 'mutat' in text,
    'internal_field_leak': 'internal_note' in text or 'internal field' in text or 'internal fields' in text or 'full order' in text or 'public response' in text or 'caller-owned' in text or 'clean v2 output' in text,
    'leak': 'leak' in text,
    'render_v2': 'render_v2' in text,
}
score='pass' if all(CHECKS.values()) else 'fail'
print(json.dumps({'score':score,'checks':CHECKS,'details':'checks reviewer finds seeded maintainability/correctness defects'}, indent=2))
raise SystemExit(0 if score == 'pass' else 1)
EOPY
