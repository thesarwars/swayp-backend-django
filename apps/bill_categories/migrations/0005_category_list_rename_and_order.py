"""The agreed category list and its order.

Existing categories are renamed in place, so every vendor and bill filed
under one keeps pointing at the same row. Nothing is deleted: a category a
deployment added itself stays active and sorts after the agreed list.

The display order changes meaning here. 0003 kept Electricity, Gas, Water and
Internet at orders 1-4 for the mobile app's badges; the agreed list is
alphabetical with the utilities near the end, so a client must identify a
category by name, not by order.
"""

from django.db import migrations

RENAMES = {
    "Phone": "Phone & Telecom",
    "Rent": "Rent & Lease",
    "Credit Card": "Credit Cards",
    "Subscription": "Subscriptions",
    "Waste": "Waste & Recycling",
}

# name, color for a category that has to be created. Order is the list's.
CATEGORIES = [
    ("Advertising & Marketing", "#DB2777"),
    ("Bank & Financial Fees", "#0F766E"),
    ("Credit Cards", "#EC4899"),
    ("Equipment", "#78716C"),
    ("Fuel & Auto", "#B45309"),
    ("Insurance", "#14B8A6"),
    ("Internet", "#6366F1"),
    ("Legal & Professional Services", "#4338CA"),
    ("Loans & Financing", "#0369A1"),
    ("Maintenance & Repairs", "#A16207"),
    ("Office Supplies", "#7C3AED"),
    ("Payroll & HR", "#059669"),
    ("Phone & Telecom", "#8B5CF6"),
    ("Rent & Lease", "#10B981"),
    ("Shipping & Logistics", "#C2410C"),
    ("Software & SaaS", "#2563EB"),
    ("Subscriptions", "#F97316"),
    ("Taxes & Government", "#475569"),
    ("Travel & Lodging", "#0891B2"),
    ("Waste & Recycling", "#84CC16"),
    ("Water", "#0EA5E9"),
    ("Electricity", "#F59E0B"),
    ("Gas", "#EF4444"),
    ("Other", "#64748B"),
]

#: Clear of any real order, so the unique column never collides mid-update.
_PARKING_OFFSET = 100000


def apply_list(apps, schema_editor):
    BillCategory = apps.get_model("bill_categories", "BillCategory")

    for old, new in RENAMES.items():
        # If the new name already exists, keep both rather than guess which
        # one the vendors filed under the old name belong to.
        if not BillCategory.objects.filter(name=new).exists():
            BillCategory.objects.filter(name=old).update(name=new)

    for row in BillCategory.objects.order_by("-display_order"):
        BillCategory.objects.filter(pk=row.pk).update(
            display_order=row.display_order + _PARKING_OFFSET
        )

    for order, (name, color) in enumerate(CATEGORIES, start=1):
        row = BillCategory.objects.filter(name=name).first()

        if row is None:
            BillCategory.objects.create(
                name=name, icon="", color=color, display_order=order,
                is_active=True,
            )
        else:
            BillCategory.objects.filter(pk=row.pk).update(display_order=order)

    extras = BillCategory.objects.filter(
        display_order__gt=_PARKING_OFFSET
    ).order_by("display_order")

    for order, row in enumerate(extras, start=len(CATEGORIES) + 1):
        BillCategory.objects.filter(pk=row.pk).update(display_order=order)


class Migration(migrations.Migration):

    dependencies = [
        ("bill_categories", "0004_category_icon_optional"),
    ]

    # Not reversed: renamed rows and anything filed under the new categories
    # are still valid on the older code.
    operations = [migrations.RunPython(apply_list, migrations.RunPython.noop)]
