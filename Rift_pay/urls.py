from django.contrib import admin
from django.urls import path
from . import views

urlpatterns = [
    path('', views.register, name='register'),
    path('login/', views.login, name='login'),
    path('login/verify/', views.verify_otp, name='verify_otp'),
    path('logout/', views.logout, name='logout'),
    path('home/', views.home, name='home'),
    path('profile/update/', views.update_profile, name='update_profile'),
    path('deposit/', views.deposit, name='deposit'),
    path('withdraw/', views.withdraw, name='withdraw'),
    path('account/mobile-money/', views.process_mobile_money, name='process_mobile_money'),
    path('history/', views.history, name='history'),
    path('transfer/', views.transfer, name='transfer'),
    path('webhooks/blockchain/', views.blockchain_webhook, name='blockchain_webhook'),
    path('webhooks/mobile-money/', views.mobile_money_webhook, name='mobile_money_webhook'),
    path('api/recipient-name/', views.get_recipient_name, name='get_recipient_name'),
    path('api/recipient-info/', views.get_recipient_info, name='get_recipient_info'),
    path('transaction/<int:tx_id>/receipt/', views.transaction_receipt, name='transaction_receipt'),

    # NFC Card Payment routes
    path('nfc/cards/', views.nfc_cards, name='nfc_cards'),
    path('nfc/order/', views.order_nfc_card, name='order_nfc_card'),
    path('nfc/unlink/<int:nfc_id>/', views.unlink_nfc_card, name='unlink_nfc_card'),
    path('nfc/block/<int:nfc_id>/', views.block_nfc_card, name='block_nfc_card'),
    path('api/nfc/pay/', views.nfc_payment, name='nfc_payment'),
]
