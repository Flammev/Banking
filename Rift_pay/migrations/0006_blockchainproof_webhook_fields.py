from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Rift_pay', '0005_systemactivity'),
    ]

    operations = [
        migrations.AddField(
            model_name='blockchainproof',
            name='error_detail',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='blockchainproof',
            name='local_transaction_id',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='blockchainproof',
            name='status',
            field=models.CharField(choices=[('PENDING', 'Pending'), ('CONFIRMED', 'Confirmed'), ('FAILED', 'Failed')], default='PENDING', max_length=10),
        ),
        migrations.AddField(
            model_name='blockchainproof',
            name='synced_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
