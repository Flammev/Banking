import json
import re
import uuid
import secrets
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.db import transaction as db_transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.urls import reverse
from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password
from django.core.mail import send_mail
from django.core.mail import BadHeaderError
from smtplib import SMTPException
from django.views.decorators.csrf import csrf_exempt
from decimal import Decimal
from datetime import date, timedelta
from urllib.parse import urlencode
import random
from .models import User, Transaction, Account, Card, SystemActivity, BlockchainProof, MobileMoneyTransaction, NFCCard, NFCTerminal, NFCPaymentTransaction, EmailOTP
from .services.blockchain_client import sync_transaction, BlockchainSyncError
from .services.mobile_money_client import initiate_mobile_money_transaction, MobileMoneyAPIError


def get_client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def log_activity(request, action, status='SUCCESS', user=None, detail=''):
    SystemActivity.objects.create(
        user=user,
        action=action,
        status=status,
        detail=detail,
        ip_address=get_client_ip(request),
        user_agent=(request.META.get('HTTP_USER_AGENT', '')[:255])
    )


def generate_account_number():
    while True:
        number = f"ACC{random.randint(10**9, (10**10)-1)}"
        if not Account.objects.filter(number=number).exists():
            return number


def generate_card_number():
    while True:
        raw = f"{random.randint(10**15, (10**16)-1)}"
        card_number = f"{raw[0:4]} {raw[4:8]} {raw[8:12]} {raw[12:16]}"
        if not Card.objects.filter(card_number=card_number).exists():
            return card_number


def generate_nfc_number():
    """Generate a unique NFC card number like 'NFC 4821 7390 5612'."""
    while True:
        digits = f"{random.randint(10**11, (10**12)-1)}"
        nfc_number = f"NFC {digits[0:4]} {digits[4:8]} {digits[8:12]}"
        if not NFCCard.objects.filter(nfc_number=nfc_number).exists():
            return nfc_number


def generate_cvv():
    return f"{random.randint(100, 999)}"


def generate_expiration_date():
    today = timezone.now().date()
    future_year = today.year + 3
    return date(future_year, today.month, 1)


def normalize_phone_number(phone):
    return re.sub(r'\D', '', phone or '')


def mask_phone_number(phone):
    raw = normalize_phone_number(phone)
    if len(raw) <= 4:
        return '••••'
    return f"{'•' * (len(raw) - 4)}{raw[-4:]}"


def hash_phone_number(phone):
    normalized = normalize_phone_number(phone)
    return salted_hmac('riftpay-mobile-money-phone', normalized).hexdigest()


def sanitize_error_message(message):
    text = str(message or '')
    if len(text) > 120:
        return text[:120]
    return text

def register(request):
    if request.method == 'POST':
        name = request.POST['name']
        prenom = request.POST['prenom']
        email = request.POST['email']
        password = request.POST['password']
        confirm_password = request.POST.get('confirm_password')
        phone = request.POST['phone']

        if password != confirm_password:
            log_activity(request, action='REGISTER', status='FAILED', detail=f"Password mismatch for email {email}")
            return render(request, 'register.html', {'message': 'Passwords do not match'})

        if User.objects.filter(email=email).exists():
            log_activity(request, action='REGISTER', status='FAILED', detail=f"Email already used: {email}")
            return render(request, 'register.html', {'message': 'Email already in use'})

        with db_transaction.atomic():
            user = User(
                name=name,
                prenom=prenom,
                email=email,
                password=make_password(password),
                phone=phone
            )
            user.save()

            account = Account(
                user=user,
                number=generate_account_number(),
                balance=0
            )
            account.save()

            # Auto-create a virtual NFC card for the new user
            NFCCard.objects.create(
                nfc_number=generate_nfc_number(),
                user=user,
                account=account,
                status='VIRTUAL',
                label=f"Carte de {user.prenom}",
            )

        log_activity(request, action='REGISTER', status='SUCCESS', user=user, detail='New user account created')

        return redirect('login')

    return render(request, 'register.html')

def login(request):
    if request.method == 'POST':
        email = request.POST['email']
        password = request.POST['password']

        try:
            user = User.objects.get(email=email)
            if check_password(password, user.password):
                # Credentials valid – generate and send OTP
                expiry_minutes = getattr(settings, 'OTP_EXPIRY_MINUTES', 10)
                code = f"{secrets.randbelow(1000000):06d}"
                EmailOTP.objects.create(
                    user=user,
                    code=code,
                    expires_at=timezone.now() + timedelta(minutes=expiry_minutes),
                )
                try:
                    send_mail(
                        subject='Your Rift Pay verification code',
                        message=(
                            f"Hello {user.prenom},\n\n"
                            f"Your verification code is: {code}\n\n"
                            f"This code expires in {expiry_minutes} minutes.\n\n"
                            "If you did not request this, please ignore this email."
                        ),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[user.email],
                        fail_silently=False,
                    )
                except (SMTPException, BadHeaderError, OSError):
                    log_activity(request, action='LOGIN', status='FAILED', user=user, detail='Failed to send OTP email')
                    return render(request, 'login.html', {'message': 'Unable to send verification email. Please try again.'})

                # Store user id in session (pending OTP verification)
                request.session['otp_user_id'] = user.user_id
                log_activity(request, action='LOGIN', status='SUCCESS', user=user, detail='OTP sent for 2FA')
                return redirect('verify_otp')
            log_activity(request, action='LOGIN', status='FAILED', user=user, detail='Invalid password')
            return render(request, 'login.html', {'message': 'Invalid email or password'})
        except User.DoesNotExist:
            log_activity(request, action='LOGIN', status='FAILED', detail=f'Unknown email: {email}')
            return render(request, 'login.html', {'message': 'Invalid email or password'})

    return render(request, 'login.html')


def verify_otp(request):
    user_id = request.session.get('otp_user_id')
    if not user_id:
        return redirect('login')

    try:
        user = User.objects.get(user_id=user_id)
    except User.DoesNotExist:
        del request.session['otp_user_id']
        return redirect('login')

    if request.method == 'POST':
        code = request.POST.get('otp_code', '').strip()
        otp = (
            EmailOTP.objects.filter(user=user, code=code, is_used=False, expires_at__gt=timezone.now())
            .order_by('-created_at')
            .first()
        )
        if otp:
            otp.is_used = True
            otp.save()
            del request.session['otp_user_id']
            request.session['user_id'] = user.user_id
            request.session['user_email'] = user.email
            log_activity(request, action='LOGIN', status='SUCCESS', user=user, detail='2FA verified, user logged in')
            return redirect('home')
        log_activity(request, action='LOGIN', status='FAILED', user=user, detail='Invalid or expired OTP')
        return render(request, 'verify_otp.html', {'message': 'Invalid or expired code. Please try again.'})

    return render(request, 'verify_otp.html')

def transfer(request):
    """Handle transfer data submission"""
    sender = None
    sender_account = None

    sender_id = request.session.get('user_id')
    if sender_id:
        sender = User.objects.filter(user_id=sender_id).first()
        if sender:
            sender_account = Account.objects.filter(user=sender).first()

    def build_context(**kwargs):
        context = {
            'available_balance': sender_account.balance if sender_account else Decimal('0.00')
        }
        context.update(kwargs)
        return context

    def wants_json():
        requested_with = request.headers.get('X-Requested-With', '')
        accept_header = request.headers.get('Accept', '')
        return requested_with == 'XMLHttpRequest' or 'application/json' in accept_header.lower()

    def respond_error(message, status=400):
        if wants_json():
            current_balance = sender_account.balance if sender_account else Decimal('0.00')
            return JsonResponse(
                {
                    'success': False,
                    'error': message,
                    'available_balance': float(current_balance),
                },
                status=status,
            )
        return render(request, 'transfer.html', build_context(error=message), status=status)

    if request.method == 'POST':
        try:
            lookup_type = request.POST.get('lookup_type', 'email')
            lookup_value = request.POST.get('recipient_lookup')
            receiver_id = request.POST.get('receiver_id')
            amount = request.POST.get('amount')
            description = request.POST.get('description', '')
            
            # Validate inputs
            if not lookup_value or not amount:
                log_activity(request, action='TRANSFER', status='FAILED', detail='Missing recipient or amount')
                return respond_error('Recipient and amount are required')
            
            # Convert amount to Decimal
            try:
                amount = Decimal(amount)
            except:
                log_activity(request, action='TRANSFER', status='FAILED', detail=f'Invalid amount format: {amount}')
                return respond_error('Invalid amount format')
            
            # Validate amount is positive
            if amount <= 0:
                log_activity(request, action='TRANSFER', status='FAILED', detail=f'Non-positive amount: {amount}')
                return respond_error('Amount must be greater than 0')
            
            # Get receiver user based on lookup type
            receiver = None
            if receiver_id:
                try:
                    receiver = User.objects.get(user_id=receiver_id)
                except User.DoesNotExist:
                    log_activity(request, action='TRANSFER', status='FAILED', detail=f'Recipient not found by id: {receiver_id}')
                    return respond_error('Recipient user not found')
            else:
                if lookup_type == 'email':
                    try:
                        receiver = User.objects.get(email=lookup_value)
                    except User.DoesNotExist:
                        log_activity(request, action='TRANSFER', status='FAILED', detail=f'Recipient not found by email: {lookup_value}')
                        return respond_error(f'No user found with email: {lookup_value}')
                elif lookup_type == 'phone':
                    try:
                        receiver = User.objects.get(phone=lookup_value)
                    except User.DoesNotExist:
                        log_activity(request, action='TRANSFER', status='FAILED', detail=f'Recipient not found by phone: {lookup_value}')
                        return respond_error(f'No user found with phone: {lookup_value}')
                elif lookup_type == 'account':
                    try:
                        account = Account.objects.get(number=lookup_value)
                        receiver = account.user
                    except Account.DoesNotExist:
                        log_activity(request, action='TRANSFER', status='FAILED', detail=f'Recipient not found by account: {lookup_value}')
                        return respond_error(f'No account found with number: {lookup_value}')
            
            # Get sender from session
            sender_id = request.session.get('user_id')
            if not sender_id:
                log_activity(request, action='TRANSFER', status='FAILED', detail='Anonymous transfer attempt')
                return respond_error('You must be logged in to make a transfer', status=401)
            
            try:
                sender = User.objects.get(user_id=sender_id)
            except User.DoesNotExist:
                log_activity(request, action='TRANSFER', status='FAILED', detail=f'Sender not found by id: {sender_id}')
                return respond_error('Sender user not found', status=404)
            
            # Check if sender has sufficient balance
            try:
                sender_account = Account.objects.get(user=sender)
                if sender_account.balance < amount:
                    log_activity(
                        request,
                        action='TRANSFER',
                        status='FAILED',
                        user=sender,
                        detail=f'Insufficient funds for transfer of {amount}'
                    )
                    return respond_error(f'Insufficient balance. Your balance: {sender_account.balance} FCFA')
            except Account.DoesNotExist:
                log_activity(request, action='TRANSFER', status='FAILED', user=sender, detail='Sender account not found')
                return respond_error('Sender account not found', status=404)
            
            with db_transaction.atomic():
                # Create local transaction
                transfer_tx = Transaction(
                    sender=sender,
                    receiver=receiver,
                    amount=amount
                )
                transfer_tx.save()

                # Update balances in local DB
                sender_account.balance -= amount
                sender_account.save()

                try:
                    receiver_account = Account.objects.get(user=receiver)
                    receiver_account.balance += amount
                    receiver_account.save()
                except Account.DoesNotExist:
                    receiver_account = Account(
                        user=receiver,
                        number=generate_account_number(),
                        balance=amount
                    )
                    receiver_account.save()

                # Sync transaction with Stellar backend
                sync_data = sync_transaction(transfer_tx)

                BlockchainProof.objects.update_or_create(
                    reference_id=sync_data['reference_id'],
                    defaults={
                        'stellar_transaction_hash': sync_data.get('stellar_transaction_hash') or f"pending-{transfer_tx.id}",
                        'proof_hash': sync_data.get('proof_hash') or f"pending-proof-{transfer_tx.id}",
                        'status': 'CONFIRMED' if sync_data.get('stellar_transaction_hash') else 'PENDING',
                        'local_transaction_id': transfer_tx.id,
                        'amount': float(sync_data.get('amount')),
                        'currency': sync_data.get('currency', 'FCFA'),
                        'synced_at': timezone.now() if sync_data.get('stellar_transaction_hash') else None,
                    }
                )

            log_activity(
                request,
                action='TRANSFER',
                status='SUCCESS',
                user=sender,
                detail=f'Transfer #{transfer_tx.id} sent to user {receiver.user_id} for {amount}'
            )
            
            # Success response
            context = {
                'success': f'Transfer of {amount} FCFA to {receiver.name} {receiver.prenom} completed successfully!',
                'transaction_id': transfer_tx.id,
                'available_balance': sender_account.balance
            }

            if wants_json():
                return JsonResponse(
                    {
                        'success': True,
                        'message': context['success'],
                        'transaction_id': transfer_tx.id,
                        'available_balance': float(sender_account.balance),
                    }
                )

            return render(request, 'transfer.html', context)

        except BlockchainSyncError as e:
            log_activity(
                request,
                action='TRANSFER',
                status='FAILED',
                user=sender if 'sender' in locals() else None,
                detail=f'Blockchain sync failed: {str(e)}'
            )
            return respond_error(f'Transfer cancelled: blockchain sync failed ({str(e)})', status=502)
        
        except Exception as e:
            log_activity(request, action='TRANSFER', status='FAILED', detail=f'Unhandled transfer error: {str(e)}')
            return respond_error('An internal error occurred while processing the transfer', status=500)
    
    # GET request - display transfer form
    return render(request, 'transfer.html', build_context())

def get_recipient_name(request):
    """AJAX endpoint to fetch recipient name by email"""
    if request.method == 'GET':
        email = request.GET.get('email', '')
        
        try:
            user = User.objects.get(email=email)
            return JsonResponse({
                'success': True,
                'name': f"{user.name} {user.prenom}"
            })
        except User.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'User not found'
            })
    
    return JsonResponse({'error': 'Invalid request'}, status=400)

def get_recipient_info(request):
    """AJAX endpoint to fetch recipient info by email, phone, or account number"""
    if request.method == 'GET':
        lookup_type = request.GET.get('type', 'email')
        lookup_value = request.GET.get('value', '')
        
        try:
            if lookup_type == 'email':
                user = User.objects.get(email=lookup_value)
            elif lookup_type == 'phone':
                user = User.objects.get(phone=lookup_value)
            elif lookup_type == 'account':
                account = Account.objects.get(number=lookup_value)
                user = account.user
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid lookup type'
                })
            
            return JsonResponse({
                'success': True,
                'name': f"{user.name} {user.prenom}",
                'user_id': user.user_id
            })
        except (User.DoesNotExist, Account.DoesNotExist):
            return JsonResponse({
                'success': False,
                'error': 'User not found'
            })
    
    return JsonResponse({'error': 'Invalid request'}, status=400)

def home(request):
    """Display home/dashboard page"""
    # Get user from session (implement proper authentication)
    user_id = request.session.get('user_id')
    
    context = {
        'user': None,
        'account': None,
        'nfc_card': None,
        'message': request.GET.get('message', ''),
        'error': request.GET.get('error', ''),
        'recent_operations': []
    }
    
    # If no user_id in session, try to get from all users (for development)
    if not user_id:
        # In production, should redirect to login
        # For now, get the most recent user (temporary solution)
        try:
            user = User.objects.latest('user_id')
            request.session['user_id'] = user.user_id
            request.session.save()
        except User.DoesNotExist:
            return redirect('login')
    else:
        try:
            user = User.objects.get(user_id=user_id)
        except User.DoesNotExist:
            return redirect('login')
    
    if user:
        try:
            account = Account.objects.get(user=user)
            nfc_card = NFCCard.objects.filter(user=user).first()

            # If user registered before NFC feature, create a virtual card now
            if not nfc_card and account:
                nfc_card = NFCCard.objects.create(
                    nfc_number=generate_nfc_number(),
                    user=user,
                    account=account,
                    status='VIRTUAL',
                    label=f"Carte de {user.prenom}",
                )

            # Compute today's NFC spending
            from django.db.models import Sum
            today = timezone.now().date()
            today_spent = Decimal('0.00')
            if nfc_card and nfc_card.status == 'ACTIVE':
                today_spent = NFCPaymentTransaction.objects.filter(
                    nfc_card=nfc_card,
                    status='SUCCESS',
                    created_at__date=today,
                ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

            sent_transactions = Transaction.objects.filter(
                sender=user
            ).order_by('-timestamp')[:5]

            received_transactions = Transaction.objects.filter(
                receiver=user
            ).exclude(sender=user).order_by('-timestamp')[:5]

            mm_transactions = MobileMoneyTransaction.objects.filter(
                user=user
            ).order_by('-created_at')[:8]

            nfc_transactions = NFCPaymentTransaction.objects.filter(
                user=user
            ).select_related('terminal').order_by('-created_at')[:8]

            recent_operations = []

            for transaction in sent_transactions:
                recent_operations.append({
                    'kind': 'TRANSFER_SENT',
                    'title': f"To: {transaction.receiver.name} {transaction.receiver.prenom}",
                    'amount_prefix': '-',
                    'amount': transaction.amount,
                    'timestamp': transaction.timestamp,
                    'status': 'SUCCESS',
                    'icon': '📤',
                })

            for transaction in received_transactions:
                recent_operations.append({
                    'kind': 'TRANSFER_RECEIVED',
                    'title': f"From: {transaction.sender.name} {transaction.sender.prenom}",
                    'amount_prefix': '+',
                    'amount': transaction.amount,
                    'timestamp': transaction.timestamp,
                    'status': 'SUCCESS',
                    'icon': '📥',
                })

            for operation in mm_transactions:
                recent_operations.append({
                    'kind': operation.direction,
                    'title': f"{operation.direction.title()} {operation.operator} ({operation.customer_phone_masked})",
                    'amount_prefix': '+' if operation.direction == 'DEPOSIT' else '-',
                    'amount': operation.amount,
                    'timestamp': operation.created_at,
                    'status': operation.status,
                    'icon': '➕' if operation.direction == 'DEPOSIT' else '➖',
                })

            for nfc_tx in nfc_transactions:
                merchant = nfc_tx.terminal.merchant_name if nfc_tx.terminal else 'NFC Payment'
                recent_operations.append({
                    'kind': 'NFC_PAYMENT',
                    'title': f"NFC: {merchant}",
                    'amount_prefix': '-',
                    'amount': nfc_tx.amount,
                    'timestamp': nfc_tx.created_at,
                    'status': nfc_tx.status,
                    'icon': '📶',
                })

            recent_operations.sort(key=lambda item: item['timestamp'], reverse=True)
            recent_operations = recent_operations[:8]
            
            context['user'] = user
            context['account'] = account
            context['nfc_card'] = nfc_card
            context['today_spent'] = today_spent
            context['recent_operations'] = recent_operations
        except Account.DoesNotExist:
            context['user'] = user
            context['account'] = None
    
    return render(request, 'home.html', context)


def update_profile(request):
    if request.method != 'POST':
        return redirect('home')

    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')

    try:
        user = User.objects.get(user_id=user_id)
    except User.DoesNotExist:
        return redirect('login')

    name = request.POST.get('name', '').strip()
    prenom = request.POST.get('prenom', '').strip()
    email = request.POST.get('email', '').strip()
    phone = request.POST.get('phone', '').strip()

    if not name or not prenom or not email or not phone:
        log_activity(request, action='PROFILE_UPDATE', status='FAILED', user=user, detail='Missing required profile fields')
        params = urlencode({'error': 'All profile fields are required'})
        return redirect(f"{reverse('home')}?{params}")

    email_owner = User.objects.filter(email=email).exclude(user_id=user.user_id).first()
    if email_owner:
        log_activity(request, action='PROFILE_UPDATE', status='FAILED', user=user, detail=f'Email already used: {email}')
        params = urlencode({'error': 'Email already used by another account'})
        return redirect(f"{reverse('home')}?{params}")

    user.name = name
    user.prenom = prenom
    user.email = email
    user.phone = phone
    user.save(update_fields=['name', 'prenom', 'email', 'phone'])
    log_activity(request, action='PROFILE_UPDATE', status='SUCCESS', user=user, detail='Profile updated')

    request.session['user_email'] = user.email
    params = urlencode({'message': 'Profile updated successfully'})
    return redirect(f"{reverse('home')}?{params}")


def deposit(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')

    user = User.objects.filter(user_id=user_id).first()
    if not user:
        return redirect('login')

    account = Account.objects.filter(user=user).first()
    context = {
        'operation': 'deposit',
        'title': 'Dépôt Mobile Money',
        'subtitle': 'Alimentez votre compte via Orange Money ou MTN MoMo',
        'submit_label': 'Effectuer le dépôt',
        'next_view': 'deposit',
        'available_balance': account.balance if account else Decimal('0.00'),
        'message': request.GET.get('message', ''),
        'error': request.GET.get('error', ''),
    }
    return render(request, 'mobile_money_form.html', context)


def withdraw(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')

    user = User.objects.filter(user_id=user_id).first()
    if not user:
        return redirect('login')

    account = Account.objects.filter(user=user).first()
    context = {
        'operation': 'withdraw',
        'title': 'Retrait Mobile Money',
        'subtitle': 'Retirez de votre compte vers Orange Money ou MTN MoMo',
        'submit_label': 'Effectuer le retrait',
        'next_view': 'withdraw',
        'available_balance': account.balance if account else Decimal('0.00'),
        'message': request.GET.get('message', ''),
        'error': request.GET.get('error', ''),
    }
    return render(request, 'mobile_money_form.html', context)


def process_mobile_money(request):
    if request.method != 'POST':
        return redirect('home')

    next_view = request.POST.get('next_view', 'home').strip().lower()
    if next_view not in {'home', 'deposit', 'withdraw'}:
        next_view = 'home'

    target_url = reverse(next_view)

    actor_id = request.session.get('user_id')
    if not actor_id:
        return redirect('login')

    try:
        actor = User.objects.get(user_id=actor_id)
    except User.DoesNotExist:
        return redirect('login')

    operation = request.POST.get('operation', 'deposit').strip().lower()
    operator = request.POST.get('operator', '').strip().upper()
    phone_number = request.POST.get('phone_number', '').strip()
    amount_raw = request.POST.get('amount', '').strip()

    if operator not in {'ORANGE', 'MTN'}:
        log_activity(request, action='PROFILE_UPDATE', status='FAILED', user=actor, detail='Invalid operator for mobile money')
        params = urlencode({'error': 'Operator must be Orange or MTN'})
        return redirect(f"{target_url}?{params}")

    normalized_phone = normalize_phone_number(phone_number)
    if len(normalized_phone) < 8 or len(normalized_phone) > 15:
        log_activity(request, action='PROFILE_UPDATE', status='FAILED', user=actor, detail='Invalid phone format for mobile money')
        params = urlencode({'error': 'Invalid phone number format'})
        return redirect(f"{target_url}?{params}")

    if not amount_raw:
        log_activity(request, action='PROFILE_UPDATE', status='FAILED', user=actor, detail='Mobile money amount missing')
        params = urlencode({'error': 'Amount is required'})
        return redirect(f"{target_url}?{params}")

    try:
        amount = Decimal(amount_raw)
    except Exception:
        params = urlencode({'error': 'Invalid amount format'})
        return redirect(f"{target_url}?{params}")

    if amount <= 0:
        params = urlencode({'error': 'Amount must be greater than zero'})
        return redirect(f"{target_url}?{params}")

    if amount > Decimal('5000000'):
        params = urlencode({'error': 'Amount exceeds the maximum allowed per operation'})
        return redirect(f"{target_url}?{params}")

    direction = 'DEPOSIT' if operation == 'deposit' else 'WITHDRAW'
    if operation not in {'deposit', 'withdraw'}:
        params = urlencode({'error': 'Invalid operation. Use deposit or withdraw'})
        return redirect(f"{target_url}?{params}")

    try:
        account = Account.objects.get(user=actor)
    except Account.DoesNotExist:
        params = urlencode({'error': 'Account not found'})
        return redirect(f"{target_url}?{params}")

    if direction == 'WITHDRAW' and account.balance < amount:
        log_activity(request, action='WITHDRAW', status='FAILED', user=actor, detail='Insufficient balance for withdrawal')
        params = urlencode({'error': f'Insufficient balance. Current: {account.balance} FCFA'})
        return redirect(f"{target_url}?{params}")

    external_reference = f"mm-{actor.user_id}-{uuid.uuid4().hex[:18]}"

    with db_transaction.atomic():
        account = Account.objects.select_for_update().get(user=actor)
        previous_balance = account.balance

        if direction == 'WITHDRAW' and previous_balance < amount:
            params = urlencode({'error': f'Insufficient balance. Current: {previous_balance} FCFA'})
            return redirect(f"{target_url}?{params}")

        mm_transaction = MobileMoneyTransaction.objects.create(
            user=actor,
            account=account,
            operator=operator,
            direction=direction,
            amount=amount,
            external_reference=external_reference,
            customer_phone_masked=mask_phone_number(normalized_phone),
            customer_phone_hash=hash_phone_number(normalized_phone),
            status='PENDING',
        )

    try:
        operator_response = initiate_mobile_money_transaction(
            operator=operator,
            direction=direction,
            phone_number=normalized_phone,
            amount=amount,
            external_reference=external_reference,
            customer_name=f"{actor.name} {actor.prenom}",
        )
    except MobileMoneyAPIError as error:
        mm_transaction.status = 'FAILED'
        mm_transaction.response_message = sanitize_error_message(error)
        mm_transaction.save(update_fields=['status', 'response_message', 'updated_at'])
        log_activity(request, action=direction, status='FAILED', user=actor, detail='Mobile money API error')
        params = urlencode({'error': 'Operator service unavailable. Please try again later.'})
        return redirect(f"{target_url}?{params}")

    status_value = operator_response.get('status', 'PENDING')
    if status_value not in {'PENDING', 'SUCCESS', 'FAILED'}:
        status_value = 'PENDING'

    with db_transaction.atomic():
        account = Account.objects.select_for_update().get(user=actor)
        mm_transaction = MobileMoneyTransaction.objects.select_for_update().get(id=mm_transaction.id)

        mm_transaction.status = status_value
        mm_transaction.operator_reference = operator_response.get('operator_reference', '')[:100]
        mm_transaction.response_code = operator_response.get('response_code', '')[:30]
        mm_transaction.response_message = sanitize_error_message(operator_response.get('message', ''))

        if status_value == 'SUCCESS':
            if direction == 'DEPOSIT':
                account.balance += amount
            else:
                if account.balance < amount:
                    mm_transaction.status = 'FAILED'
                    mm_transaction.response_message = 'Insufficient balance during settlement'
                else:
                    account.balance -= amount

        if mm_transaction.status in {'SUCCESS', 'FAILED'}:
            mm_transaction.processed_at = timezone.now()

        account.save(update_fields=['balance'])
        mm_transaction.save()

    final_action = 'DEPOSIT' if direction == 'DEPOSIT' else 'WITHDRAW'
    final_status = 'SUCCESS' if mm_transaction.status == 'SUCCESS' else 'FAILED' if mm_transaction.status == 'FAILED' else 'SUCCESS'
    log_activity(
        request,
        action=final_action,
        status=final_status,
        user=actor,
        detail=f'Mobile money {direction.lower()} via {operator}. Ref: {external_reference}'
    )

    if mm_transaction.status == 'SUCCESS':
        verb = 'Deposit' if direction == 'DEPOSIT' else 'Withdrawal'
        params = urlencode({'message': f'{verb} confirmed successfully. New balance: {account.balance} FCFA'})
    elif mm_transaction.status == 'PENDING':
        params = urlencode({'message': 'Operation initiated. Awaiting operator confirmation.'})
    else:
        params = urlencode({'error': 'Operation failed at operator level'})

    return redirect(f"{target_url}?{params}")

def history(request):
    """Display transfer and mobile money operation history"""
    user_id = request.session.get('user_id')
    
    context = {
        'user': None,
        'all_operations': [],
        'total_sent': 0,
        'total_received': 0,
        'total_deposit': 0,
        'total_withdraw': 0,
        'total_nfc': 0,
        'total_count': 0
    }
    
    if user_id:
        try:
            user = User.objects.get(user_id=user_id)
            
            sent_transactions = Transaction.objects.filter(
                sender=user
            ).order_by('-timestamp')
            
            received_transactions = Transaction.objects.filter(
                receiver=user
            ).order_by('-timestamp')

            mobile_money_transactions = MobileMoneyTransaction.objects.filter(
                user=user
            ).order_by('-created_at')

            nfc_payment_transactions = NFCPaymentTransaction.objects.filter(
                user=user
            ).select_related('terminal', 'nfc_card').order_by('-created_at')
            
            total_sent = sum(t.amount for t in sent_transactions)
            total_received = sum(t.amount for t in received_transactions)
            total_deposit = sum(t.amount for t in mobile_money_transactions if t.direction == 'DEPOSIT' and t.status == 'SUCCESS')
            total_withdraw = sum(t.amount for t in mobile_money_transactions if t.direction == 'WITHDRAW' and t.status == 'SUCCESS')
            total_nfc = sum(t.amount for t in nfc_payment_transactions if t.status == 'SUCCESS')

            all_operations = []

            for transfer in sent_transactions:
                all_operations.append({
                    'type': 'sent',
                    'title': 'Sent Money',
                    'counterparty_label': 'To',
                    'counterparty': f"{transfer.receiver.name} {transfer.receiver.prenom}",
                    'date_label': 'Date',
                    'date': transfer.timestamp,
                    'amount_prefix': '-',
                    'amount': transfer.amount,
                    'status': 'SUCCESS',
                })

            for transfer in received_transactions:
                all_operations.append({
                    'type': 'received',
                    'title': 'Received Money',
                    'counterparty_label': 'From',
                    'counterparty': f"{transfer.sender.name} {transfer.sender.prenom}",
                    'date_label': 'Date',
                    'date': transfer.timestamp,
                    'amount_prefix': '+',
                    'amount': transfer.amount,
                    'status': 'SUCCESS',
                })

            for mm in mobile_money_transactions:
                mm_type = 'deposit' if mm.direction == 'DEPOSIT' else 'withdraw'
                amount_prefix = '+' if mm.direction == 'DEPOSIT' else '-'
                all_operations.append({
                    'type': mm_type,
                    'title': 'Mobile Money Deposit' if mm.direction == 'DEPOSIT' else 'Mobile Money Withdrawal',
                    'counterparty_label': 'Operator',
                    'counterparty': f"{mm.operator} ({mm.customer_phone_masked})",
                    'date_label': 'Created',
                    'date': mm.created_at,
                    'amount_prefix': amount_prefix,
                    'amount': mm.amount,
                    'status': mm.status,
                })

            for nfc_tx in nfc_payment_transactions:
                merchant = nfc_tx.terminal.merchant_name if nfc_tx.terminal else 'NFC Payment'
                all_operations.append({
                    'type': 'nfc_payment',
                    'title': 'NFC Payment',
                    'counterparty_label': 'Merchant',
                    'counterparty': merchant,
                    'date_label': 'Date',
                    'date': nfc_tx.created_at,
                    'amount_prefix': '-',
                    'amount': nfc_tx.amount,
                    'status': nfc_tx.status,
                })
            
            all_operations.sort(
                key=lambda x: x['date'],
                reverse=True
            )
            
            context['user'] = user
            context['all_operations'] = all_operations
            context['total_sent'] = float(total_sent)
            context['total_received'] = float(total_received)
            context['total_deposit'] = float(total_deposit)
            context['total_withdraw'] = float(total_withdraw)
            context['total_nfc'] = float(total_nfc)
            context['total_count'] = len(all_operations)
        except User.DoesNotExist:
            pass
    
    return render(request, 'history.html', context)

def logout(request):
    """Logout user and clear session"""
    user = None
    user_id = request.session.get('user_id')
    if user_id:
        user = User.objects.filter(user_id=user_id).first()
    log_activity(request, action='LOGOUT', status='SUCCESS', user=user, detail='User logged out')
    request.session.flush()
    return redirect('login')


@csrf_exempt
def blockchain_webhook(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    expected_token = settings.BLOCKCHAIN_WEBHOOK_TOKEN.strip()
    provided_token = request.headers.get('X-Webhook-Token', '').strip()
    if expected_token and provided_token != expected_token:
        return JsonResponse({'error': 'Unauthorized webhook'}, status=401)

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    reference_id = payload.get('reference_id', '').strip()
    if not reference_id:
        return JsonResponse({'error': 'reference_id is required'}, status=400)

    status_value = str(payload.get('status', 'CONFIRMED')).upper()
    if status_value not in {'PENDING', 'CONFIRMED', 'FAILED'}:
        return JsonResponse({'error': 'Invalid status value'}, status=400)

    stellar_hash = str(payload.get('stellar_transaction_hash', '')).strip()
    proof_hash = str(payload.get('proof_hash', '')).strip()
    error_detail = str(payload.get('error_detail', '')).strip()

    proof, _created = BlockchainProof.objects.get_or_create(
        reference_id=reference_id,
        defaults={
            'stellar_transaction_hash': stellar_hash or f"pending-{reference_id}"[:100],
            'proof_hash': proof_hash or f"pending-proof-{reference_id}"[:64],
            'status': status_value,
            'amount': float(payload.get('amount')) if payload.get('amount') is not None else None,
            'currency': payload.get('currency', 'FCFA'),
            'local_transaction_id': payload.get('local_transaction_id'),
            'error_detail': error_detail,
            'synced_at': timezone.now(),
        }
    )

    if not _created:
        if stellar_hash:
            proof.stellar_transaction_hash = stellar_hash
        if proof_hash:
            proof.proof_hash = proof_hash
        if payload.get('amount') is not None:
            proof.amount = float(payload.get('amount'))
        if payload.get('currency'):
            proof.currency = payload.get('currency')
        if payload.get('local_transaction_id') is not None:
            proof.local_transaction_id = payload.get('local_transaction_id')

        proof.status = status_value
        proof.error_detail = error_detail
        proof.synced_at = timezone.now()
        proof.save()

    return JsonResponse({'success': True, 'reference_id': reference_id, 'status': status_value})


@csrf_exempt
def mobile_money_webhook(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    expected_token = settings.MOBILE_MONEY_WEBHOOK_TOKEN.strip()
    provided_token = request.headers.get('X-Webhook-Token', '').strip()
    if expected_token and provided_token != expected_token:
        return JsonResponse({'error': 'Unauthorized webhook'}, status=401)

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    external_reference = str(payload.get('reference', '')).strip()
    if not external_reference:
        return JsonResponse({'error': 'reference is required'}, status=400)

    status_value = str(payload.get('status', 'PENDING')).upper().strip()
    if status_value not in {'PENDING', 'SUCCESS', 'FAILED'}:
        return JsonResponse({'error': 'Invalid status value'}, status=400)

    mm_transaction = MobileMoneyTransaction.objects.filter(external_reference=external_reference).first()
    if not mm_transaction:
        return JsonResponse({'error': 'Transaction not found'}, status=404)

    with db_transaction.atomic():
        mm_transaction = MobileMoneyTransaction.objects.select_for_update().get(id=mm_transaction.id)
        account = Account.objects.select_for_update().get(id=mm_transaction.account_id)

        previous_status = mm_transaction.status
        mm_transaction.status = status_value
        mm_transaction.operator_reference = str(payload.get('operator_reference', '')).strip()[:100]
        mm_transaction.response_code = str(payload.get('code', '')).strip()[:30]
        mm_transaction.response_message = sanitize_error_message(payload.get('message', ''))

        if status_value in {'SUCCESS', 'FAILED'}:
            mm_transaction.processed_at = timezone.now()

        if previous_status != 'SUCCESS' and status_value == 'SUCCESS':
            if mm_transaction.direction == 'DEPOSIT':
                account.balance += mm_transaction.amount
                account.save(update_fields=['balance'])
            elif mm_transaction.direction == 'WITHDRAW' and account.balance >= mm_transaction.amount:
                account.balance -= mm_transaction.amount
                account.save(update_fields=['balance'])

        mm_transaction.save()

    log_activity(
        request,
        action='MM_WEBHOOK',
        status='SUCCESS',
        user=mm_transaction.user,
        detail=f'Mobile money webhook processed for ref {external_reference}'
    )

    return JsonResponse({'success': True, 'reference': external_reference, 'status': status_value})


# ──────────────────────────────────────────────
#  NFC Card Management & Payment Views
# ──────────────────────────────────────────────

def nfc_cards(request):
    """NFC card management is now merged into the dashboard. Redirect to home."""
    return redirect('home')


def order_nfc_card(request):
    """User requests a physical NFC card (changes status from VIRTUAL to ORDERED)."""
    if request.method != 'POST':
        return redirect('home')

    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')

    try:
        user = User.objects.get(user_id=user_id)
    except User.DoesNotExist:
        return redirect('login')

    nfc_card = NFCCard.objects.filter(user=user).first()
    if not nfc_card:
        params = urlencode({'error': 'No NFC card found on your account'})
        return redirect(f"{reverse('home')}?{params}")

    if nfc_card.status == 'ORDERED':
        params = urlencode({'error': 'You have already ordered a physical card. Please wait for delivery.'})
        return redirect(f"{reverse('home')}?{params}")

    if nfc_card.status == 'ACTIVE':
        params = urlencode({'error': 'Your physical card is already active.'})
        return redirect(f"{reverse('home')}?{params}")

    if nfc_card.status == 'BLOCKED':
        params = urlencode({'error': 'Your card is blocked. Contact support first.'})
        return redirect(f"{reverse('home')}?{params}")

    nfc_card.status = 'ORDERED'
    nfc_card.ordered_at = timezone.now()
    nfc_card.save(update_fields=['status', 'ordered_at', 'updated_at'])

    log_activity(request, action='NFC_ORDER', status='SUCCESS', user=user,
                 detail=f'Physical NFC card ordered (card {nfc_card.nfc_number})')

    params = urlencode({'message': 'Physical card ordered successfully! You will be notified when it is ready.'})
    return redirect(f"{reverse('home')}?{params}")


def unlink_nfc_card(request, nfc_id):
    """Permanently remove (unlink) the user's NFC card."""
    if request.method != 'POST':
        return redirect('home')

    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')

    try:
        nfc_card = NFCCard.objects.get(id=nfc_id, user__user_id=user_id)
    except NFCCard.DoesNotExist:
        params = urlencode({'error': 'NFC card not found'})
        return redirect(f"{reverse('home')}?{params}")

    nfc_number = nfc_card.nfc_number
    nfc_card.delete()

    log_activity(request, action='NFC_UNLINK', status='SUCCESS',
                 user=User.objects.filter(user_id=user_id).first(),
                 detail=f'NFC card {nfc_number} removed')

    params = urlencode({'message': 'NFC card removed'})
    return redirect(f"{reverse('home')}?{params}")


def block_nfc_card(request, nfc_id):
    """Block the NFC card (theft / loss). Only admins can reactivate."""
    if request.method != 'POST':
        return redirect('home')

    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')

    try:
        nfc_card = NFCCard.objects.get(id=nfc_id, user__user_id=user_id)
    except NFCCard.DoesNotExist:
        params = urlencode({'error': 'NFC card not found'})
        return redirect(f"{reverse('home')}?{params}")

    if nfc_card.status == 'BLOCKED':
        params = urlencode({'error': 'Card is already blocked'})
        return redirect(f"{reverse('home')}?{params}")

    nfc_card.status = 'BLOCKED'
    nfc_card.save(update_fields=['status', 'updated_at'])

    log_activity(request, action='NFC_BLOCK', status='SUCCESS',
                 user=nfc_card.user,
                 detail=f'NFC card {nfc_card.nfc_number} blocked by user (theft/loss)')

    params = urlencode({'message': 'Card blocked successfully. Contact support to reactivate it.'})
    return redirect(f"{reverse('home')}?{params}")


@csrf_exempt
def nfc_payment(request):
    """
    API endpoint called by an NFC terminal to process a contactless payment.

    Expected JSON body:
    {
        "terminal_id": "TERM-001",
        "card_uid": "04A3B2C1D0",
        "amount": 1500,
        "currency": "FCFA"         // optional, defaults to FCFA
    }

    Headers:
        X-Terminal-Key: <raw API key>

    Returns JSON with payment result.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    # ── Parse body ──
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    terminal_id = str(payload.get('terminal_id', '')).strip()
    card_uid = str(payload.get('card_uid', '')).strip().upper()
    amount_raw = payload.get('amount')
    currency = str(payload.get('currency', 'FCFA')).strip().upper()

    if not terminal_id or not card_uid or amount_raw is None:
        return JsonResponse({'error': 'terminal_id, card_uid, and amount are required'}, status=400)

    # ── Validate amount ──
    try:
        amount = Decimal(str(amount_raw))
    except Exception:
        return JsonResponse({'error': 'Invalid amount format'}, status=400)
    if amount <= 0:
        return JsonResponse({'error': 'Amount must be greater than zero'}, status=400)

    # ── Authenticate terminal ──
    terminal_key = request.headers.get('X-Terminal-Key', '').strip()
    try:
        terminal = NFCTerminal.objects.get(terminal_id=terminal_id, is_active=True)
    except NFCTerminal.DoesNotExist:
        return JsonResponse({'error': 'Unknown or inactive terminal'}, status=403)

    if not check_password(terminal_key, terminal.api_key_hash):
        return JsonResponse({'error': 'Invalid terminal credentials'}, status=403)

    # ── Locate NFC card ──
    try:
        nfc_card = NFCCard.objects.select_related('user', 'account').get(card_uid=card_uid)
    except NFCCard.DoesNotExist:
        return JsonResponse({'error': 'NFC card not recognised'}, status=404)

    if nfc_card.status != 'ACTIVE':
        return JsonResponse({'error': f'NFC card is {nfc_card.status.lower()}'}, status=403)

    user = nfc_card.user
    account = nfc_card.account
    reference = f"nfc-{user.user_id}-{uuid.uuid4().hex[:18]}"

    # ── Per-transaction limit ──
    if amount > nfc_card.per_transaction_limit:
        tx = NFCPaymentTransaction.objects.create(
            reference=reference, nfc_card=nfc_card, terminal=terminal,
            user=user, account=account, amount=amount, currency=currency,
            status='DECLINED', decline_reason='Per-transaction limit exceeded',
            processed_at=timezone.now(),
        )
        log_activity(request, action='NFC_PAY', status='FAILED', user=user,
                     detail=f'NFC payment declined: per-tx limit (ref {reference})')
        return JsonResponse({
            'success': False, 'reference': reference,
            'status': 'DECLINED', 'reason': 'Per-transaction limit exceeded',
        }, status=200)

    # ── Daily limit ──
    from django.db.models import Sum
    today = timezone.now().date()
    spent_today = NFCPaymentTransaction.objects.filter(
        nfc_card=nfc_card, status='SUCCESS', created_at__date=today,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    if spent_today + amount > nfc_card.daily_limit:
        tx = NFCPaymentTransaction.objects.create(
            reference=reference, nfc_card=nfc_card, terminal=terminal,
            user=user, account=account, amount=amount, currency=currency,
            status='DECLINED', decline_reason='Daily limit exceeded',
            processed_at=timezone.now(),
        )
        log_activity(request, action='NFC_PAY', status='FAILED', user=user,
                     detail=f'NFC payment declined: daily limit (ref {reference})')
        return JsonResponse({
            'success': False, 'reference': reference,
            'status': 'DECLINED', 'reason': 'Daily limit exceeded',
        }, status=200)

    # ── Balance check & debit (atomic) ──
    with db_transaction.atomic():
        account = Account.objects.select_for_update().get(number=account.number)

        if account.balance < amount:
            NFCPaymentTransaction.objects.create(
                reference=reference, nfc_card=nfc_card, terminal=terminal,
                user=user, account=account, amount=amount, currency=currency,
                status='DECLINED', decline_reason='Insufficient balance',
                processed_at=timezone.now(),
            )
            log_activity(request, action='NFC_PAY', status='FAILED', user=user,
                         detail=f'NFC payment declined: insufficient balance (ref {reference})')
            return JsonResponse({
                'success': False, 'reference': reference,
                'status': 'DECLINED', 'reason': 'Insufficient balance',
            }, status=200)

        # Debit account
        account.balance -= amount
        account.save(update_fields=['balance'])

        tx = NFCPaymentTransaction.objects.create(
            reference=reference, nfc_card=nfc_card, terminal=terminal,
            user=user, account=account, amount=amount, currency=currency,
            status='SUCCESS', processed_at=timezone.now(),
        )

    log_activity(request, action='NFC_PAY', status='SUCCESS', user=user,
                 detail=f'NFC payment of {amount} {currency} at {terminal.merchant_name} (ref {reference})')

    return JsonResponse({
        'success': True,
        'reference': reference,
        'status': 'SUCCESS',
        'amount': float(amount),
        'currency': currency,
        'merchant': terminal.merchant_name,
        'new_balance': float(account.balance),
    })
