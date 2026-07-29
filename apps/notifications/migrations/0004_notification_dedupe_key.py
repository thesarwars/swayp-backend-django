from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "notifications",
            "0003_notificationpreference_alter_notification_type",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="dedupe_key",
            field=models.CharField(
                blank=True, default=None, max_length=120, null=True
            ),
        ),
        migrations.AddConstraint(
            model_name="notification",
            constraint=models.UniqueConstraint(
                condition=models.Q(("dedupe_key__isnull", False)),
                fields=("dedupe_key",),
                name="uniq_notification_dedupe_key",
            ),
        ),
    ]
