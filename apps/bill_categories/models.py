import uuid

from django.db import models
from apps.common.models import BaseModel

class BillCategory(BaseModel):
   
    name = models.CharField(max_length=100, unique=True)
    icon = models.URLField(max_length=500)
    color = models.CharField(max_length=20)
    display_order = models.PositiveIntegerField(default=0)

    is_active = models.BooleanField(default=True)

   
    class Meta:
        db_table = "bill_categories"
        ordering = ["display_order", "name"]
        indexes = [
            models.Index(fields=["display_order"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return self.name