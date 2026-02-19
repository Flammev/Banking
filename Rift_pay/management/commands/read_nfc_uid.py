"""
Management command to read the UID of an NFC card using a USB reader
(e.g. ACR122U).

Requires:  pip install pyscard

Usage:
    python manage.py read_nfc_uid
    python manage.py read_nfc_uid --link          (link card to logged-in user)
    python manage.py read_nfc_uid --link --user 1  (link card to user_id=1)
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Read the UID from a physical NFC card using a USB reader (requires pyscard)'

    def add_arguments(self, parser):
        parser.add_argument('--link', action='store_true',
                            help='Automatically link the card to a user after reading')
        parser.add_argument('--user', type=int, default=None,
                            help='User ID to link the card to (used with --link)')

    def handle(self, *args, **options):
        try:
            from smartcard.System import readers
            from smartcard.util import toHexString
        except ImportError:
            self.stderr.write(self.style.ERROR(
                'pyscard is not installed.\n'
                'Install it with:  pip install pyscard\n'
                'On Windows you may also need the PC/SC driver for your reader.'
            ))
            return

        reader_list = readers()
        if not reader_list:
            self.stderr.write(self.style.ERROR(
                'No NFC/smart card reader detected.\n'
                'Plug in your USB reader (e.g. ACR122U) and try again.'
            ))
            return

        reader = reader_list[0]
        self.stdout.write(f'Using reader: {reader}')
        self.stdout.write(self.style.WARNING('Place your NFC card on the reader...'))

        try:
            connection = reader.createConnection()
            connection.connect()
        except Exception as e:
            self.stderr.write(self.style.ERROR(
                f'Could not connect to card: {e}\n'
                'Make sure a card is placed on the reader.'
            ))
            return

        # APDU command: GET UID (works for MIFARE, NTAG, etc.)
        GET_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]
        try:
            data, sw1, sw2 = connection.transmit(GET_UID)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Card communication error: {e}'))
            return

        if sw1 == 0x90 and sw2 == 0x00:
            uid = toHexString(data).replace(' ', '')
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS(f'  Card UID: {uid}'))
            self.stdout.write(f'  (length: {len(data)} bytes)')
            self.stdout.write('')

            if options['link']:
                self._link_card(uid, options['user'])
            else:
                self.stdout.write('You can now enter this UID in the NFC Cards page:')
                self.stdout.write('  http://127.0.0.1:8000/nfc/cards/')
                self.stdout.write('')
                self.stdout.write('Or re-run with --link to link it directly:')
                self.stdout.write(f'  python manage.py read_nfc_uid --link --user <USER_ID>')
        else:
            self.stderr.write(self.style.ERROR(
                f'Failed to read UID. Status: {sw1:02X} {sw2:02X}'
            ))

    def _link_card(self, uid, user_id):
        from Rift_pay.models import User, Account, Card, NFCCard

        if NFCCard.objects.filter(card_uid=uid).exists():
            self.stdout.write(self.style.WARNING(f'Card {uid} is already linked.'))
            return

        if user_id:
            try:
                user = User.objects.get(user_id=user_id)
            except User.DoesNotExist:
                self.stderr.write(self.style.ERROR(f'User with id {user_id} not found.'))
                return
        else:
            user = User.objects.order_by('-user_id').first()
            if not user:
                self.stderr.write(self.style.ERROR('No users in database. Create one first.'))
                return
            self.stdout.write(f'  Using most recent user: {user.name} {user.prenom} (id={user.user_id})')

        account = Account.objects.filter(user=user).first()
        if not account:
            self.stderr.write(self.style.ERROR(f'User {user.user_id} has no bank account.'))
            return

        bank_card = Card.objects.filter(user=user).order_by('-expiration_date').first()

        nfc = NFCCard.objects.create(
            card_uid=uid,
            label=f'NFC-{uid[-4:]}',
            user=user,
            account=account,
            card=bank_card,
            status='ACTIVE',
        )

        self.stdout.write(self.style.SUCCESS(
            f'  Card {uid} linked to {user.name} {user.prenom} '
            f'(account {account.number})'
        ))
