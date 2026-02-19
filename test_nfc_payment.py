"""
Script de test complet pour le paiement NFC.
Simule le flux terminal → API → debit du compte.

Usage:
    python test_nfc_payment.py
    python test_nfc_payment.py --card-uid 04AABBCCDD --amount 750
    python test_nfc_payment.py --base-url http://192.168.1.50:8000

Prerequis:
    pip install requests    (si pas deja installe)
"""

import argparse
import json
import sys

try:
    import requests
except ImportError:
    print("ERROR: 'requests' est requis.  pip install requests")
    sys.exit(1)


DEFAULT_BASE = 'http://127.0.0.1:8000'
DEFAULT_TERMINAL_ID = 'TERM-TEST-001'
DEFAULT_KEY = 'test-terminal-secret-key'
DEFAULT_UID = '04AABBCCDD'
DEFAULT_AMOUNT = 500


def main():
    parser = argparse.ArgumentParser(description='Test NFC payment API')
    parser.add_argument('--base-url', default=DEFAULT_BASE, help=f'Server URL (default: {DEFAULT_BASE})')
    parser.add_argument('--terminal-id', default=DEFAULT_TERMINAL_ID)
    parser.add_argument('--key', default=DEFAULT_KEY, help='Terminal API key')
    parser.add_argument('--card-uid', default=DEFAULT_UID, help='NFC card UID')
    parser.add_argument('--amount', type=float, default=DEFAULT_AMOUNT, help='Payment amount')
    parser.add_argument('--currency', default='FCFA')
    args = parser.parse_args()

    url = f'{args.base_url}/api/nfc/pay/'
    payload = {
        'terminal_id': args.terminal_id,
        'card_uid': args.card_uid,
        'amount': args.amount,
        'currency': args.currency,
    }
    headers = {
        'Content-Type': 'application/json',
        'X-Terminal-Key': args.key,
    }

    print('=' * 50)
    print('  NFC PAYMENT TEST')
    print('=' * 50)
    print(f'  URL         : {url}')
    print(f'  Terminal    : {args.terminal_id}')
    print(f'  Card UID    : {args.card_uid}')
    print(f'  Amount      : {args.amount} {args.currency}')
    print('-' * 50)
    print(f'  Payload     : {json.dumps(payload)}')
    print('-' * 50)

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
    except requests.ConnectionError:
        print(f'\n  ERREUR: Impossible de se connecter a {args.base_url}')
        print('  Assurez-vous que le serveur Django est lance:')
        print('      python manage.py runserver')
        sys.exit(1)

    print(f'\n  HTTP Status : {resp.status_code}')
    try:
        data = resp.json()
        print(f'  Response    :')
        print(json.dumps(data, indent=4, ensure_ascii=False))
    except Exception:
        print(f'  Raw body    : {resp.text[:500]}')

    print('=' * 50)

    if resp.status_code == 200 and data.get('success'):
        print('  ✅ PAIEMENT ACCEPTE')
        print(f'     Reference    : {data.get("reference")}')
        print(f'     Nouveau solde: {data.get("new_balance")} {args.currency}')
    elif resp.status_code == 200 and not data.get('success'):
        print(f'  🚫 PAIEMENT REFUSE: {data.get("reason")}')
    else:
        print(f'  ❌ ERREUR: {data.get("error", resp.text[:200])}')


if __name__ == '__main__':
    main()
