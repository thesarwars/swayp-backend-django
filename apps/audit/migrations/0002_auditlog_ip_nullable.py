from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="auditlog",
            name="ip",
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
    ]
