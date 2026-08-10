#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
import json
from pathlib import Path
p=Path('answer.md')
text=p.read_text().lower() if p.exists() else ''
CHECKS={'answer_exists':p.exists(),'mentions_role':'builder' in text,'implemented':'implemented' in text,'tests':'tests' in text,'files':'files' in text}
DETAILS='checked answer.md for role-specific deliverable markers'

import json
score = 'pass' if all(CHECKS.values()) else 'fail'
print(json.dumps({'score': score, 'checks': CHECKS, 'details': DETAILS}, indent=2))
raise SystemExit(0 if score == 'pass' else 1)
EOPY
