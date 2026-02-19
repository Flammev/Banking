from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('Rift_pay', '0006_blockchainproof_webhook_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='MobileMoneyTransaction',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('operator', models.CharField(choices=[('ORANGE', 'Orange Money'), ('MTN', 'MTN Mobile Money')], max_length=10)),
                ('direction', models.CharField(choices=[('DEPOSIT', 'Deposit'), ('WITHDRAW', 'Withdraw')], max_length=10)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10)),
                ('currency', models.CharField(default='FCFA', max_length=10)),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('SUCCESS', 'Success'), ('FAILED', 'Failed')], default='PENDING', max_length=10)),
                ('external_reference', models.CharField(max_length=64, unique=True)),
                ('operator_reference', models.CharField(blank=True, max_length=100)),
                ('customer_phone_masked', models.CharField(max_length=25)),
                ('customer_phone_hash', models.CharField(max_length=128)),
                ('response_code', models.CharField(blank=True, max_length=30)),
                ('response_message', models.CharField(blank=True, max_length=255)),
                ('processed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mobile_money_transactions', to='Rift_pay.account')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mobile_money_transactions', to='Rift_pay.user')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
