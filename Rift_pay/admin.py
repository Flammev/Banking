from django.contrib import admin
from django.db.models import Sum, Q
from django.utils import timezone
from .models import (
    User, Transaction, Account, Card, BlockchainProof, SystemActivity,
    NFCCard, NFCTerminal, NFCPaymentTransaction,
)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
	list_display = ('user_id', 'name', 'prenom', 'email', 'phone')
	search_fields = ('name', 'prenom', 'email', 'phone')
	list_per_page = 25


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
	list_display = ('number', 'user', 'balance')
	search_fields = ('number', 'user__name', 'user__prenom', 'user__email')
	list_per_page = 25


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
	list_display = ('card_number', 'user', 'account', 'expiration_date')
	search_fields = ('card_number', 'user__name', 'user__prenom', 'user__email', 'account__number')
	list_filter = ('expiration_date',)
	list_per_page = 25


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
	change_list_template = 'admin/Rift_pay/transaction/change_list.html'
	list_display = ('id', 'sender', 'receiver', 'amount', 'timestamp')
	search_fields = (
		'sender__name',
		'sender__prenom',
		'sender__email',
		'receiver__name',
		'receiver__prenom',
		'receiver__email',
	)
	list_filter = ('timestamp',)
	date_hierarchy = 'timestamp'
	list_select_related = ('sender', 'receiver')
	list_per_page = 30

	def changelist_view(self, request, extra_context=None):
		queryset = self.get_queryset(request)
		today = timezone.now().date()

		summary = {
			'total_transactions': queryset.count(),
			'today_transactions': queryset.filter(timestamp__date=today).count(),
			'total_volume': queryset.aggregate(total=Sum('amount'))['total'] or 0,
			'active_users_count': User.objects.filter(
				Q(sent_transactions__isnull=False) | Q(received_transactions__isnull=False)
			).distinct().count(),
		}

		extra_context = extra_context or {}
		extra_context['summary'] = summary
		extra_context['summary_title'] = 'Transactions Summary'
		return super().changelist_view(request, extra_context=extra_context)


@admin.register(SystemActivity)
class SystemActivityAdmin(admin.ModelAdmin):
	change_list_template = 'admin/Rift_pay/systemactivity/change_list.html'
	list_display = ('created_at', 'action', 'status', 'user', 'ip_address', 'detail')
	search_fields = ('user__name', 'user__prenom', 'user__email', 'detail', 'ip_address')
	list_filter = ('action', 'status', 'created_at')
	date_hierarchy = 'created_at'
	list_select_related = ('user',)
	readonly_fields = ('created_at',)
	list_per_page = 40

	def changelist_view(self, request, extra_context=None):
		queryset = self.get_queryset(request)
		today = timezone.now().date()

		summary = {
			'total_events': queryset.count(),
			'today_events': queryset.filter(created_at__date=today).count(),
			'failed_events': queryset.filter(status='FAILED').count(),
			'successful_events': queryset.filter(status='SUCCESS').count(),
		}

		extra_context = extra_context or {}
		extra_context['summary'] = summary
		extra_context['summary_title'] = 'System Activity Summary'
		return super().changelist_view(request, extra_context=extra_context)


@admin.register(BlockchainProof)
class BlockchainProofAdmin(admin.ModelAdmin):
	list_display = ('reference_id', 'status', 'stellar_transaction_hash', 'amount', 'currency', 'timestamp', 'synced_at')
	search_fields = ('reference_id', 'stellar_transaction_hash', 'currency', 'status')
	list_filter = ('status', 'currency', 'timestamp', 'synced_at')
	date_hierarchy = 'timestamp'
	list_per_page = 25


# ──────────────────────────────────────────────
#  NFC Card Payment Admin
# ──────────────────────────────────────────────

@admin.register(NFCCard)
class NFCCardAdmin(admin.ModelAdmin):
	list_display = ('nfc_number', 'card_uid_display', 'label', 'user', 'account', 'status', 'daily_limit', 'ordered_at', 'linked_at', 'created_at')
	search_fields = ('nfc_number', 'card_uid', 'label', 'user__name', 'user__prenom', 'user__email', 'account__number')
	list_filter = ('status', 'created_at', 'ordered_at', 'linked_at')
	list_select_related = ('user', 'account')
	list_per_page = 25
	readonly_fields = ('nfc_number', 'user', 'account', 'card', 'created_at', 'updated_at', 'ordered_at')
	fieldsets = (
		('Card Info', {
			'fields': ('nfc_number', 'label', 'status', 'user', 'account', 'card'),
		}),
		('Physical Card Linking (admin only)', {
			'fields': ('card_uid',),
			'description': 'Enter the physical NFC chip UID here to link it to this virtual card, then set status to ACTIVE.',
		}),
		('Limits', {
			'fields': ('daily_limit', 'per_transaction_limit'),
		}),
		('Dates', {
			'fields': ('ordered_at', 'linked_at', 'created_at', 'updated_at'),
		}),
	)
	actions = ['reactivate_cards', 'link_and_activate']

	def card_uid_display(self, obj):
		return obj.card_uid or '—'
	card_uid_display.short_description = 'Physical UID'

	def save_model(self, request, obj, form, change):
		"""When admin sets a card_uid, automatically update linked_at and status."""
		if change and 'card_uid' in form.changed_data and obj.card_uid:
			obj.linked_at = timezone.now()
			if obj.status in ('VIRTUAL', 'ORDERED'):
				obj.status = 'ACTIVE'
		super().save_model(request, obj, form, change)

	@admin.action(description='Reactivate selected blocked cards')
	def reactivate_cards(self, request, queryset):
		blocked = queryset.filter(status='BLOCKED')
		count = blocked.update(status='ACTIVE')
		if count:
			self.message_user(request, f'{count} NFC card(s) reactivated.')
		else:
			self.message_user(request, 'No blocked cards in selection.', level='warning')

	@admin.action(description='Mark selected cards as ACTIVE (after linking physical UID)')
	def link_and_activate(self, request, queryset):
		"""Activate ordered cards that already have a card_uid set."""
		eligible = queryset.filter(status__in=['VIRTUAL', 'ORDERED']).exclude(card_uid__isnull=True).exclude(card_uid='')
		count = eligible.update(status='ACTIVE', linked_at=timezone.now())
		if count:
			self.message_user(request, f'{count} card(s) activated.')
		else:
			self.message_user(request, 'No eligible cards (must have a UID and be VIRTUAL or ORDERED).', level='warning')


@admin.register(NFCTerminal)
class NFCTerminalAdmin(admin.ModelAdmin):
	list_display = ('terminal_id', 'merchant_name', 'location', 'is_active', 'created_at')
	search_fields = ('terminal_id', 'merchant_name', 'location')
	list_filter = ('is_active', 'created_at')
	list_per_page = 25


@admin.register(NFCPaymentTransaction)
class NFCPaymentTransactionAdmin(admin.ModelAdmin):
	list_display = ('reference', 'user', 'amount', 'currency', 'status', 'terminal', 'nfc_card', 'created_at')
	search_fields = ('reference', 'user__name', 'user__prenom', 'user__email', 'nfc_card__nfc_number', 'terminal__terminal_id')
	list_filter = ('status', 'currency', 'created_at')
	date_hierarchy = 'created_at'
	list_select_related = ('user', 'nfc_card', 'terminal', 'account')
	list_per_page = 30
