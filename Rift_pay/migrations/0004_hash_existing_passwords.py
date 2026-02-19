from django.db import migrations
from django.contrib.auth.hashers import identify_hasher, make_password


def hash_existing_passwords(apps, schema_editor):
    User = apps.get_model('Rift_pay', 'User')

    for user in User.objects.all().iterator():
        current_password = user.password or ''

        try:
            identify_hasher(current_password)
            already_hashed = True
        except Exception:
            already_hashed = False

        if not already_hashed and current_password:
            user.password = make_password(current_password)
            user.save(update_fields=['password'])


class Migration(migrations.Migration):

    dependencies = [
        ('Rift_pay', '0003_alter_user_user_id'),
    ]

    operations = [
        migrations.RunPython(hash_existing_passwords, migrations.RunPython.noop),
    ]
