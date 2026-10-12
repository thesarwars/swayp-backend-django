"""Seed the bill categories (BILLS-9).

Nothing created these. They are reference data the client cannot work without
— ``POST /bills/create`` requires a category, ``GET /bill-categories`` feeds
Home's "Bill Types" row, and ``default_category()`` looks for one named
"Other" to file a vendor under when the add-vendor screen offers no category
step. On a freshly migrated database the table was empty, so Home's badges
rendered nothing and no bill could be created at all.

``display_order`` is the contract, not the name: the mobile app keys its four
hand-drawn badges to orders 1-4 (electricity, gas, water, internet), which is
why the column is unique and why renaming a category keeps its drawing. Keep
the first four where they are.
"""

from django.db import migrations

# name, color, display_order. ``icon`` stays empty: the client ships its own
# artwork for the first four and tints a plain badge for the rest, so a URL
# here would be downloaded and discarded.
CATEGORIES = [
    ("Electricity", "#F59E0B", 1),
    ("Gas", "#EF4444", 2),
    ("Water", "#0EA5E9", 3),
    ("Internet", "#6366F1", 4),
    ("Phone", "#8B5CF6", 5),
    ("Rent", "#10B981", 6),
    ("Insurance", "#14B8A6", 7),
    ("Credit Card", "#EC4899", 8),
    ("Subscription", "#F97316", 9),
    ("Waste", "#84CC16", 10),
    # The default for anything unclassified. default_category() looks for this
    # name first, so it has to exist and has to stay active.
    ("Other", "#64748B", 11),
]


def seed(apps, schema_editor):
    BillCategory = apps.get_model("bill_categories", "BillCategory")

    # A deployment that already has categories keeps exactly what it has.
    # Merging would mean guessing which display_order is free, and the column
    # is unique — a collision would fail the deploy rather than the row.
    if BillCategory.objects.exists():
        return

    BillCategory.objects.bulk_create(
        BillCategory(name=name, icon="", color=color, display_order=order,
                     is_active=True)
        for name, color, order in CATEGORIES
    )


def unseed(apps, schema_editor):
    """Remove only the untouched seed rows.

    A category with bills filed against it is not this migration's to delete,
    and the FK would refuse anyway.
    """
    BillCategory = apps.get_model("bill_categories", "BillCategory")
    BillCategory.objects.filter(
        name__in=[name for name, _, _ in CATEGORIES], bills__isnull=True
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("bill_categories", "0002_unique_display_order"),
        # unseed() filters on the reverse FK from Bill, so that table has to
        # exist in the migration state for the reverse to be runnable.
        ("bills", "0001_initial"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
