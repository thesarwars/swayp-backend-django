from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("bill_categories", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Provider",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        primary_key=True,
                        default=uuid.uuid4,
                        editable=False,
                        serialize=False,
                    ),
                ),
                ("provider_name", models.CharField(max_length=150)),
                ("provider_code", models.CharField(max_length=50, unique=True)),
                ("logo", models.URLField(max_length=500)),
                ("description", models.TextField(blank=True)),
                ("country", models.CharField(max_length=50)),
                (
                    "status",
                    models.CharField(
                        max_length=20,
                        default="ACTIVE",
                        choices=[
                            ("ACTIVE", "Active"),
                            ("INACTIVE", "Inactive"),
                        ],
                    ),
                ),
                ("supports_auto_pay", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="providers",
                        to="bill_categories.billcategory",
                    ),
                ),
            ],
            options={
                "db_table": "providers",
                "ordering": ["provider_name"],
            },
        ),
        migrations.AddIndex(
            model_name="provider",
            index=models.Index(fields=["category"], name="provider_cat_idx"),
        ),
        migrations.AddIndex(
            model_name="provider",
            index=models.Index(fields=["status"], name="provider_status_idx"),
        ),
        migrations.AddIndex(
            model_name="provider",
            index=models.Index(fields=["provider_name"], name="provider_name_idx"),
        ),
        migrations.AddIndex(
            model_name="provider",
            index=models.Index(fields=["provider_code"], name="provider_code_idx"),
        ),
    ]