#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
import json
from pathlib import Path
p=Path('answer.md')
text=p.read_text().lower() if p.exists() else ''
CHECKS={
    'answer_exists': p.exists(),
    'mentions_planner': 'planner' in text or ('mode' in text and 'plan' in text),
    'has_steps': 'slice' in text or 'step' in text,
    'has_risks': 'risk' in text,
    'has_verification': 'verification' in text or 'verify' in text,
    'dual_write': 'dual-write' in text,
    'backfill': 'backfill' in text,
    'rollback': 'rollback' in text or 'reversible' in text or 'reversib' in text,
    'legacy': 'legacy' in text,
    'chunk': 'chunk' in text,
    'verification': 'verification' in text,
    'risk': 'risk' in text,
}
score='pass' if all(CHECKS.values()) else 'fail'
print(json.dumps({'score':score,'checks':CHECKS,'details':'checks planner plan uses supplied scenario constraints'}, indent=2))
raise SystemExit(0 if score == 'pass' else 1)
EOPY
