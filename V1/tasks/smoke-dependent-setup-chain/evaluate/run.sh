#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
import json, subprocess, sys
from pathlib import Path
code = """
import shop
shop.add_product('sku-1', 'Notebook', 4.5)
shop.add_product('sku-2', 'Pencil', 1.25)
shop.add_customer('c-1', 'Ada')
shop.add_to_cart('c-1', 'sku-1', 2)
shop.add_to_cart('c-1', 'sku-2', 4)
order = shop.checkout('c-1')
assert order['customer_id'] == 'c-1'
assert round(order['total'], 2) == 14.0
assert len(order['items']) == 2
assert shop.CUSTOMERS['c-1']['cart'] == []
try: shop.checkout('c-1')
except ValueError: pass
else: raise AssertionError('empty cart should fail')
"""
res=subprocess.run([sys.executable,'-c',code],text=True,capture_output=True)
CHECKS={'workflow_passes':res.returncode==0,'source_exists':Path('shop.py').exists()}
DETAILS=res.stderr or res.stdout

import json
score = 'pass' if all(CHECKS.values()) else 'fail'
print(json.dumps({'score': score, 'checks': CHECKS, 'details': DETAILS}, indent=2))
raise SystemExit(0 if score == 'pass' else 1)
EOPY
