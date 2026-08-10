#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
import json
from pathlib import Path
p=Path('answer.md')
text=p.read_text().lower() if p.exists() else ''
CHECKS={
    'answer_exists': p.exists(),
    'mentions_appsec': 'appsec' in text or ('mode' in text and 'appsec' in text),
    'has_risk': 'risk' in text,
    'has_impact': 'impact' in text,
    'has_mitigation': 'mitigation' in text or 'remediation' in text,
    'xss': 'xss' in text,
    'name': 'name' in text,
    'attacker': 'attacker' in text,
    'browser': 'browser' in text,
    'escape': 'escape' in text,
}
score='pass' if all(CHECKS.values()) else 'fail'
print(json.dumps({'score':score,'checks':CHECKS,'details':'checks appsec identifies concrete attack path and mitigation'}, indent=2))
raise SystemExit(0 if score == 'pass' else 1)
EOPY
