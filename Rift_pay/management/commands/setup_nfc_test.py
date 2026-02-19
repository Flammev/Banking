"""
Management command to set up a test NFC terminal and display
everything needed to run a payment test.

Usage:
    python manage.py setup_nfc_test
    python manage.py setup_nfc_test --terminal-id TERM-001 --merchant "Boutique Test"
    python manage.py setup_nfc_test --reset   (recreate from scratch)
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.hashers import make_password
from Rift_pay.models import NFCTerminal


DEFAULT_TERMINAL_ID = 'TERM-TEST-001'
DEFAULT_MERCHANT = 'Terminal de Test'
DEFAULT_LOCATION = 'Localhost / Dev'
DEFAULT_RAW_KEY = 'test-terminal-secret-key'


class Command(BaseCommand):
    help = 'Create a test NFC terminal for development / demo purposes'

    def add_arguments(self, parser):
        parser.add_argument('--terminal-id', type=str, default=DEFAULT_TERMINAL_ID,
                            help=f'Terminal identifier (default: {DEFAULT_TERMINAL_ID})')
        parser.add_argument('--merchant', type=str, default=DEFAULT_MERCHANT,
                            help=f'Merchant name (default: {DEFAULT_MERCHANT})')
        parser.add_argument('--location', type=str, default=DEFAULT_LOCATION,
                            help=f'Location label (default: {DEFAULT_LOCATION})')
        parser.add_argument('--key', type=str, default=DEFAULT_RAW_KEY,
                            help=f'Raw API key for the terminal (default: {DEFAULT_RAW_KEY})')
        parser.add_argument('--reset', action='store_true',
                            help='Delete existing terminal and recreate')

    def handle(self, *args, **options):
        terminal_id = options['terminal_id']
        merchant = options['merchant']
        location = options['location']
        raw_key = options['key']

        if options['reset']:
            deleted, _ = NFCTerminal.objects.filter(terminal_id=terminal_id).delete()
            if deleted:
                self.stdout.write(self.style.WARNING(f'Deleted existing terminal {terminal_id}'))

        terminal, created = NFCTerminal.objects.get_or_create(
            terminal_id=terminal_id,
            defaults={
                'merchant_name': merchant,
                'location': location,
                'api_key_hash': make_password(raw_key),
                'is_active': True,
            }
        )

        if not created:
            self.stdout.write(self.style.WARNING(f'Terminal {terminal_id} already exists.'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Terminal {terminal_id} created.'))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('═' * 56))
        self.stdout.write(self.style.SUCCESS('  NFC TEST TERMINAL READY'))
        self.stdout.write(self.style.SUCCESS('═' * 56))
        self.stdout.write(f'  Terminal ID :  {terminal.terminal_id}')
        self.stdout.write(f'  Merchant    :  {terminal.merchant_name}')
        self.stdout.write(f'  Location    :  {terminal.location}')
        self.stdout.write(f'  API Key     :  {raw_key}')
        self.stdout.write(f'  Active      :  {terminal.is_active}')
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('── How to test ──'))
        self.stdout.write('')
        self.stdout.write('  1) Link your NFC card via the web UI:')
        self.stdout.write('     http://127.0.0.1:8000/nfc/cards/')
        self.stdout.write('')
        self.stdout.write('  2) Simulate a terminal payment with curl:')
        self.stdout.write('')
        self.stdout.write(self.style.HTTP_INFO(
            f'     curl -X POST http://127.0.0.1:8000/api/nfc/pay/ \\\n'
            f'       -H "Content-Type: application/json" \\\n'
            f'       -H "X-Terminal-Key: {raw_key}" \\\n'
            f'       -d \'{{"terminal_id": "{terminal_id}", '
            f'"card_uid": "VOTRE_UID_ICI", "amount": 500}}\''
        ))
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('── Read your NFC card UID ──'))
        self.stdout.write('')
        self.stdout.write('  Option A: Lecteur USB (ACR122U) + script Python')
        self.stdout.write('     pip install pyscard')
        self.stdout.write('     python manage.py read_nfc_uid')
        self.stdout.write('')
        self.stdout.write('  Option B: Telephone Android avec NFC')
        self.stdout.write('     Install "NFC Tools" from Play Store')
        self.stdout.write('     Tap your card → read the UID')
        self.stdout.write('')
        self.stdout.write('  Option C: Tester sans carte physique')
        self.stdout.write('     Use any fake UID like "04AABBCCDD"')
        self.stdout.write(self.style.SUCCESS('═' * 56))
