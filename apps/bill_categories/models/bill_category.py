import uuid

from django.db import models
from apps.common.models import BaseModel

class BillCategory(BaseModel):
   
    name = models.CharField(max_length=100, unique=True)
    icon = models.URLField(max_length=500)
    color = models.CharField(max_length=20)
    # Unique (BILLS-9): clients identify and order categories by it — Home
    # shows the first four as badges — so a tie would let a rename reorder
    # them. 0 means "not set" and puts a new category at the end.
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
   
    class Meta:
        db_table = "bill_categories"
        ordering = ["display_order", "name"]
        indexes = [
            models.Index(fields=["is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["display_order"],
                name="uniq_bill_category_display_order",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.display_order:
            last = (
                BillCategory.objects.exclude(pk=self.pk)
                .aggregate(models.Max("display_order"))["display_order__max"]
            )
            self.display_order = (last or 0) + 1

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name