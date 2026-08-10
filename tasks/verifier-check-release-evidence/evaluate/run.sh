#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
import json
from pathlib import Path
p=Path('answer.md')
text=p.read_text().lower() if p.exists() else ''
CHECKS={
    'answer_exists': p.exists(),
    'mentions_verifier': 'verifier' in text or ('mode' in text and 'verify' in text),
    'has_verdict': 'verdict' in text,
    'has_evidence': 'evidence' in text,
    'has_residual_or_missing': 'residual' in text or 'missing' in text or 'failure' in text,
    'fail': 'fail' in text,
    'latency': 'latency' in text,
    'rollback': 'rollback' in text,
    'tests': 'tests' in text,
    'monitoring': 'monitoring' in text,
}
score='pass' if all(CHECKS.values()) else 'fail'
print(json.dumps({'score':score,'checks':CHECKS,'details':'checks verifier reaches evidence-backed verdict'}, indent=2))
raise SystemExit(0 if score == 'pass' else 1)
EOPY
