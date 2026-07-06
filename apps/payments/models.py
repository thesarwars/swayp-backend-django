# apps/payments/models.py

from django.db import models
from apps.common.models import BaseModel


class Payment(BaseModel):
    amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=0
    )

    reference = models.CharField(
        max_length=100,
        unique=True
    )

    status = models.CharField(
        max_length=30,
        default="PENDING"
    )

    def __str__(self):
        return self.reference