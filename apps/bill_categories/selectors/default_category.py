"""The category to file something under when nobody chose one.

Shared by bank-scan import (a detected bill with no category guess) and
vendor create (VEND-7: the add-vendor design has no category step), so both
land in the same place.
"""

from apps.bill_categories.models import BillCategory

#: Preferred, in this order; the first that exists and is active wins.
DEFAULT_CATEGORY_NAMES = ("Other", "Uncategorized", "General")


def default_category():
    """The default category, or None when no active category exists."""
    for name in DEFAULT_CATEGORY_NAMES:
        category = BillCategory.objects.filter(
            name=name, is_active=True
        ).first()

        if category:
            return category

    return BillCategory.objects.filter(is_active=True).first()
