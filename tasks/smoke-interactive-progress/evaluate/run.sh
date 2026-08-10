#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
import json, subprocess, sys
from pathlib import Path
code = """
import lesson
s=lesson.start_session('u1','intro',['A','B'])
r1=lesson.submit_answer(s,'A')
assert r1['correct'] is True and r1['current_step']==1 and r1['score']==1 and not r1['completed']
r2=lesson.submit_answer(s,'wrong')
assert r2['correct'] is False and r2['current_step']==2 and r2['score']==1 and r2['completed']
try: lesson.submit_answer(s,'B')
except ValueError: pass
else: raise AssertionError('completed session should fail')
"""
res=subprocess.run([sys.executable,'-c',code],text=True,capture_output=True)
CHECKS={'progress_passes':res.returncode==0,'source_exists':Path('lesson.py').exists()}
DETAILS=res.stderr or res.stdout

import json
score = 'pass' if all(CHECKS.values()) else 'fail'
print(json.dumps({'score': score, 'checks': CHECKS, 'details': DETAILS}, indent=2))
raise SystemExit(0 if score == 'pass' else 1)
EOPY
