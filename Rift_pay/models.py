from django.db import models
from django.utils import timezone

# Create your models here.
#create user model
class User(models.Model):
    user_id = models.AutoField(primary_key=True, editable=False, unique=True)
    name = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=128)
    phone = models.CharField(max_length=20)

    def __str__(self):
        return f"{self.name} {self.prenom}"

class Transaction(models.Model):
    id = models.AutoField(primary_key=True)
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_transactions')
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_transactions')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    timestamp = models.DateTimeField(auto_now_add=True)

class Account(models.Model):
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    number = models.CharField(max_length=20, unique=True, primary_key=True)

    def __str__(self):
        return f"{self.number}"

class Card(models.Model):
    card_number = models.CharField(max_length=19, unique=True, primary_key=True)
    expiration_date = models.DateField()
    cvv = models.CharField(max_length=4)
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    @property
    def masked_number(self):
        raw = self.card_number.replace(" ", "")
        if len(raw) < 4:
            return "••••"
        return f"•••• •••• •••• {raw[-4:]}"

class BlockchainProof(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('CONFIRMED', 'Confirmed'),
        ('FAILED', 'Failed'),
    ]

    id = models.AutoField(primary_key=True)
    reference_id = models.CharField(max_length=255, unique=True)
    stellar_transaction_hash = models.CharField(max_length=100, unique=True)
    proof_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    local_transaction_id = models.IntegerField(null=True, blank=True)
    error_detail = models.CharField(max_length=255, blank=True)
    amount = models.FloatField(null=True, blank=True)
    currency = models.CharField(max_length=10, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    synced_at = models.DateTimeField(null=True, blank=True)


class SystemActivity(models.Model):
    ACTION_CHOICES = [
        ('REGISTER', 'User registration'),
        ('LOGIN', 'User login'),
        ('LOGOUT', 'User logout'),
        ('TRANSFER', 'Money transfer'),
        ('DEPOSIT', 'Mobile money deposit'),
        ('WITHDRAW', 'Mobile money withdrawal'),
        ('MM_WEBHOOK', 'Mobile money webhook'),
        ('PROFILE_UPDATE', 'Profile update'),
        ('NFC_LINK', 'NFC card linked'),
        ('NFC_UNLINK', 'NFC card unlinked'),
        ('NFC_ORDER', 'NFC physical card ordered'),
        ('NFC_BLOCK', 'NFC card blocked'),
        ('NFC_PAY', 'NFC payment'),
    ]

    STATUS_CHOICES = [
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
    ]

    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='activities')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='SUCCESS')
    detail = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        username = f"{self.user.name} {self.user.prenom}" if self.user else "Unknown user"
        return f"[{self.status}] {self.action} - {username}"


class MobileMoneyTransaction(models.Model):
    OPERATOR_CHOICES = [
        ('ORANGE', 'Orange Money'),
        ('MTN', 'MTN Mobile Money'),
    ]

    DIRECTION_CHOICES = [
        ('DEPOSIT', 'Deposit'),
        ('WITHDRAW', 'Withdraw'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
    ]

    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='mobile_money_transactions')
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='mobile_money_transactions')
    operator = models.CharField(max_length=10, choices=OPERATOR_CHOICES)
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default='FCFA')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    external_reference = models.CharField(max_length=64, unique=True)
    operator_reference = models.CharField(max_length=100, blank=True)
    customer_phone_masked = models.CharField(max_length=25)
    customer_phone_hash = models.CharField(max_length=128)
    response_code = models.CharField(max_length=30, blank=True)
    response_message = models.CharField(max_length=255, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.direction} {self.amount} {self.currency} - {self.operator} ({self.status})"


# ──────────────────────────────────────────────
#  NFC Card Payment Models
# ──────────────────────────────────────────────

class NFCCard(models.Model):
    """An NFC card linked to a user's bank account for contactless payments."""

    STATUS_CHOICES = [
        ('VIRTUAL', 'Virtual'),       # Card number assigned, no physical card yet
        ('ORDERED', 'Ordered'),       # User requested a physical card
        ('ACTIVE', 'Active'),         # Physical card linked by admin, ready to use
        ('BLOCKED', 'Blocked'),       # Blocked by user (theft/loss), admin must reactivate
    ]

    id = models.AutoField(primary_key=True)
    nfc_number = models.CharField(max_length=19, unique=True,
                                  help_text="System-generated card number (e.g. 'NFC 4821 7390 5612')")
    card_uid = models.CharField(max_length=32, unique=True, null=True, blank=True,
                                help_text="Physical NFC chip UID – set by admin when linking the card")
    label = models.CharField(max_length=100, blank=True, help_text="Friendly name, e.g. 'My blue card'")
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='nfc_card')
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='nfc_cards')
    card = models.ForeignKey(Card, on_delete=models.SET_NULL, null=True, blank=True, related_name='nfc_cards',
                             help_text="Optional link to the user's bank card")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='VIRTUAL')
    daily_limit = models.DecimalField(max_digits=10, decimal_places=2, default=50000,
                                      help_text="Maximum amount authorised per day (FCFA)")
    per_transaction_limit = models.DecimalField(max_digits=10, decimal_places=2, default=10000,
                                                help_text="Maximum amount per single tap (FCFA)")
    ordered_at = models.DateTimeField(null=True, blank=True, help_text="When the user requested a physical card")
    linked_at = models.DateTimeField(null=True, blank=True, help_text="When admin linked the physical UID")
    created_at = models.DateTimeField(default=timezone.now, help_text="Card creation date")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def masked_nfc_number(self):
        raw = self.nfc_number.replace(' ', '')
        if len(raw) < 4:
            return '•••• •••• ••••'
        return f"•••• •••• •••• {raw[-4:]}"

    @property
    def is_physical(self):
        return bool(self.card_uid)

    def __str__(self):
        tag = self.label or self.nfc_number
        return f"NFC {tag} – {self.user.name} {self.user.prenom} ({self.status})"


class NFCTerminal(models.Model):
    """A merchant NFC payment terminal."""

    id = models.AutoField(primary_key=True)
    terminal_id = models.CharField(max_length=64, unique=True, help_text="Unique terminal identifier")
    merchant_name = models.CharField(max_length=150)
    location = models.CharField(max_length=255, blank=True)
    api_key_hash = models.CharField(max_length=128, help_text="Hashed API key for terminal authentication")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.merchant_name} ({self.terminal_id})"


class NFCPaymentTransaction(models.Model):
    """Records every NFC tap-to-pay transaction."""

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SUCCESS', 'Success'),
        ('DECLINED', 'Declined'),
        ('FAILED', 'Failed'),
    ]

    id = models.AutoField(primary_key=True)
    reference = models.CharField(max_length=64, unique=True)
    nfc_card = models.ForeignKey(NFCCard, on_delete=models.CASCADE, related_name='payments')
    terminal = models.ForeignKey(NFCTerminal, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='nfc_payments')
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='nfc_payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default='FCFA')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    decline_reason = models.CharField(max_length=255, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"NFC PAY {self.reference} – {self.amount} {self.currency} ({self.status})"

