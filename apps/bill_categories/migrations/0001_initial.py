from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="BillCategory",
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
                ("name", models.CharField(max_length=100, unique=True)),
                ("icon", models.URLField(max_length=500)),
                ("color", models.CharField(max_length=20)),
                ("display_order", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "bill_categories",
                "ordering": ["display_order", "name"],
            },
        ),
        migrations.AddIndex(
            model_name="billcategory",
            index=models.Index(
                fields=["display_order"],
                name="bill_cat_display_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="billcategory",
            index=models.Index(
                fields=["is_active"],
                name="bill_cat_active_idx",
            ),
        ),
    ]