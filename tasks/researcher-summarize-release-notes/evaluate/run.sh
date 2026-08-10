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
    'create_invoice': 'create_invoice' in text,
    'negative_quantities': 'negative quantities' in text,
    'send_invoice_email': 'send_invoice_email' in text,
    'canonical_json': 'canonical json' in text,
    'no_database_migration': 'no database migration' in text,
    'sources': 'sources' in text,
    'recommendation': 'recommendation' in text,
}
score='pass' if all(CHECKS.values()) else 'fail'
print(json.dumps({'score':score,'checks':CHECKS,'details':'checks researcher answer cites supplied evidence and conclusion'}, indent=2))
raise SystemExit(0 if score == 'pass' else 1)
EOPY
