#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
import json
import subprocess
import sys
from pathlib import Path

code = """
import json
import shop

shop.add_product('sku-1', 'Notebook', 4.5)
shop.add_product('sku-2', 'Pencil', 1.25)
shop.add_customer('c-1', 'Ada')
shop.add_to_cart('c-1', 'sku-1', 2)
shop.add_to_cart('c-1', 'sku-2', 4)
order = shop.checkout('c-1')
assert order['order_id']
assert order['customer_id'] == 'c-1'
assert len(order['items']) == 2
assert round(order['total'], 2) == 14.0
assert shop.CUSTOMERS['c-1']['cart'] == []

shop.add_customer('c-2', 'Grace')
try:
    shop.add_to_cart('c-2', 'sku-404', 1)
    shop.checkout('c-2')
except Exception as exc:
    unknown_product_error = f"{type(exc).__name__}: {exc}"
else:
    raise AssertionError('unknown product should fail clearly')

shop.add_customer('c-3', 'Lin')
try:
    shop.checkout('c-3')
except Exception as exc:
    empty_cart_error = f"{type(exc).__name__}: {exc}"
else:
    raise AssertionError('empty cart should fail clearly')

try:
    shop.checkout('missing-customer')
except Exception as exc:
    missing_customer_error = f"{type(exc).__name__}: {exc}"
else:
    raise AssertionError('missing customer should fail clearly')

payload = {
    'checks': {
        'helpers_work': shop.PRODUCTS['sku-1']['price'] == 4.5 and shop.CUSTOMERS['c-1']['name'] == 'Ada',
        'checkout_returns_order_shape': (
            isinstance(order, dict)
            and bool(order['order_id'])
            and order['customer_id'] == 'c-1'
            and isinstance(order['items'], list)
            and order['items'][0]['sku'] == 'sku-1'
            and order['items'][0]['quantity'] == 2
            and round(order['total'], 2) == 14.0
        ),
        'cart_cleared_after_checkout': shop.CUSTOMERS['c-1']['cart'] == [],
        'missing_customer_fails': 'customer' in missing_customer_error.lower(),
        'unknown_product_fails': 'product' in unknown_product_error.lower() or 'sku' in unknown_product_error.lower(),
        'empty_cart_fails': 'cart' in empty_cart_error.lower(),
    },
    'details': {
        'functionality': {
            'checks': {
                'helpers_work': shop.PRODUCTS['sku-1']['price'] == 4.5 and shop.CUSTOMERS['c-1']['name'] == 'Ada',
                'checkout_returns_order_shape': (
                    isinstance(order, dict)
                    and bool(order['order_id'])
                    and order['customer_id'] == 'c-1'
                    and isinstance(order['items'], list)
                    and order['items'][0]['sku'] == 'sku-1'
                    and order['items'][0]['quantity'] == 2
                    and round(order['total'], 2) == 14.0
                ),
                'cart_cleared_after_checkout': shop.CUSTOMERS['c-1']['cart'] == [],
                'missing_customer_fails': 'customer' in missing_customer_error.lower(),
                'unknown_product_fails': 'product' in unknown_product_error.lower() or 'sku' in unknown_product_error.lower(),
                'empty_cart_fails': 'cart' in empty_cart_error.lower(),
            },
            'evidence': {
                'order': {
                    'order_id': order['order_id'],
                    'customer_id': order['customer_id'],
                    'total': round(order['total'], 2),
                    'item_count': len(order['items']),
                },
                'missing_customer_error': missing_customer_error,
                'unknown_product_error': unknown_product_error,
                'empty_cart_error': empty_cart_error,
            },
        },
    },
}
score = 'pass' if all(payload['checks'].values()) else 'fail'
print(json.dumps({'score': score, **payload}, indent=2, sort_keys=True))
raise SystemExit(0 if score == 'pass' else 1)
"""

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
            'checks': {key: False for key in ['helpers_work', 'checkout_returns_order_shape', 'cart_cleared_after_checkout', 'missing_customer_fails', 'unknown_product_fails', 'empty_cart_fails']},
            'evidence': {'raw': res.stderr or res.stdout, 'returncode': res.returncode},
        }
    }
functional_checks = details.get('functionality', {}).get('checks', {}) if isinstance(details, dict) else {}
score = 'pass' if functional_checks and all(functional_checks.values()) else 'fail'
print(json.dumps({'score': score, 'checks': dict(functional_checks), 'details': details}, indent=2, sort_keys=True))
raise SystemExit(0 if score == 'pass' else 1)
EOPY
