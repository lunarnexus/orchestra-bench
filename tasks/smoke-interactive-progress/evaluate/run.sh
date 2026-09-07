#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
import json
import subprocess
import sys
from pathlib import Path

code = r'''
import json
import lesson
session = lesson.start_session('u1', 'intro', ['A', 'B'])
first = lesson.submit_answer(session, 'A')
second = lesson.submit_answer(session, 'wrong')

payload = {
    'checks': {
        'start_session_initializes_progress': session['step'] == 2 and session['score'] == 1 and session['completed'] is True,
        'first_answer_advances_and_scores': first['correct'] is True and first['current_step'] == 1 and first['score'] == 1 and first['completed'] is False,
        'second_answer_advances_and_completes': second['correct'] is False and second['current_step'] == 2 and second['score'] == 1 and second['completed'] is True,
        'completed_session_rejects_extra_answers': False,
    },
    'details': {
        'functionality': {
            'checks': {
                'start_session_initializes_progress': session['step'] == 2 and session['score'] == 1 and session['completed'] is True,
                'first_answer_advances_and_scores': first['correct'] is True and first['current_step'] == 1 and first['score'] == 1 and first['completed'] is False,
                'second_answer_advances_and_completes': second['correct'] is False and second['current_step'] == 2 and second['score'] == 1 and second['completed'] is True,
                'completed_session_rejects_extra_answers': False,
            },
            'evidence': {
                'session': session,
                'first_submission': first,
                'second_submission': second,
            },
        },
    },
}
try:
    lesson.submit_answer(session, 'B')
except ValueError:
    payload['checks']['completed_session_rejects_extra_answers'] = True
    payload['details']['functionality']['checks']['completed_session_rejects_extra_answers'] = True
    payload['details']['functionality']['evidence']['extra_answer_error'] = 'ValueError'
else:
    raise AssertionError('completed session should fail')

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
            'checks': {key: False for key in ['start_session_initializes_progress', 'first_answer_advances_and_scores', 'second_answer_advances_and_completes', 'completed_session_rejects_extra_answers']},
            'evidence': {'raw': res.stderr or res.stdout, 'returncode': res.returncode},
        }
    }
functional_checks = details.get('functionality', {}).get('checks', {}) if isinstance(details, dict) else {}
score = 'pass' if functional_checks and all(functional_checks.values()) else 'fail'
print(json.dumps({'score': score, 'checks': dict(functional_checks), 'details': details}, indent=2, sort_keys=True))
raise SystemExit(0 if score == 'pass' else 1)
EOPY
