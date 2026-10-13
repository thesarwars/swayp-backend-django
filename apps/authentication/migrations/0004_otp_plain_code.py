"""OTP codes kept in plain text.

A rename, not a drop and add, so codes in flight survive the deploy: rows
written before hold a hash, which OTPService.verify_otp still accepts until
they expire a few minutes later.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0003_otp_phone_change"),
    ]

    operations = [
        migrations.RenameField(
            model_name="otp",
            old_name="code_hash",
            new_name="code",
        ),
    ]
