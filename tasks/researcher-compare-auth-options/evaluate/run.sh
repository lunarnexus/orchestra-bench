#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
import json
from pathlib import Path
p=Path('answer.md')
text=p.read_text().lower() if p.exists() else ''
CHECKS={
    'answer_exists': p.exists(),
    'mentions_researcher': 'researcher' in text or 'research result' in text,
    'has_sources': 'source' in text or 'citation' in text,
    'has_recommendation': 'recommendation' in text or 'answer:' in text,
    'has_tradeoffs_or_uncertainty': 'tradeoff' in text or 'uncertainty' in text or 'confidence' in text,
    'sessioncookie': 'sessioncookie' in text,
    'csrf': 'csrf' in text,
    'browser': 'browser' in text,
    'apikey': 'apikey' in text,
    'machine_to_machine': 'machine-to-machine' in text,
    'sources': 'sources' in text,
    'tradeoffs': 'tradeoffs' in text,
}
score='pass' if all(CHECKS.values()) else 'fail'
print(json.dumps({'score':score,'checks':CHECKS,'details':'checks researcher answer cites supplied evidence and conclusion'}, indent=2))
raise SystemExit(0 if score == 'pass' else 1)
EOPY
