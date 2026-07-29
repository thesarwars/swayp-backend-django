import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

TYPE_CHOICES = [
    ("SYSTEM", "System"),
    ("PAYMENT", "Payment"),
    ("PROMOTION", "Promotion"),
    ("SECURITY", "Security"),
    ("BILL_DUE", "Bill due"),
    ("PAYMENT_FAILED", "Payment failed"),
    ("PAYMENT_REVERSED", "Payment reversed"),
    ("AUTOPAY_EXECUTED", "Autopay executed"),
    ("PAYMENT_ARRIVED", "Payment arrived"),
    ("LATE_FEE_WARNING", "Late fee warning"),
]


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("notifications", "0002_notification_metadata"),
    ]

    operations = [
        migrations.AlterField(
            model_name="notification",
            name="type",
            field=models.CharField(
                choices=TYPE_CHOICES,
                default="SYSTEM",
                max_length=30,
            ),
        ),
        migrations.CreateModel(
            name="NotificationPreference",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "type",
                    models.CharField(choices=TYPE_CHOICES, max_length=30),
                ),
                ("in_app", models.BooleanField(default=True)),
                ("email", models.BooleanField(default=True)),
                ("sms", models.BooleanField(default=False)),
                ("push", models.BooleanField(default=False)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notification_preferences",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "notification_preferences",
            },
        ),
        migrations.AddConstraint(
            model_name="notificationpreference",
            constraint=models.UniqueConstraint(
                fields=("user", "type"), name="uniq_pref_per_type"
            ),
        ),
    ]
