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
    'swallow': 'swallow' in text,
    'transport': 'transport' in text,
    'json': 'json' in text,
    'not_found': 'not found' in text,
}
score='pass' if all(CHECKS.values()) else 'fail'
print(json.dumps({'score':score,'checks':CHECKS,'details':'checks reviewer finds seeded maintainability/correctness defects'}, indent=2))
raise SystemExit(0 if score == 'pass' else 1)
EOPY
