from django.core.exceptions import ValidationError
from django.db import models
from apps.bill_categories.models.bill import Bill
from apps.common.enums import BillOccurrenceStatus
from apps.common.models import BaseModel


class BillOccurrence(BaseModel):
    """
    Represents a single billing cycle of a recurring Bill.
    """

    bill = models.ForeignKey(Bill,on_delete=models.CASCADE,related_name="occurrences")
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=18,decimal_places=2)
    status = models.CharField(max_length=20,choices=BillOccurrenceStatus.choices,default=BillOccurrenceStatus.UPCOMING)
    paid_at = models.DateTimeField(null=True,blank=True)
    payment_reference = models.CharField(max_length=255,blank=True)
    failure_reason = models.TextField(blank=True)
    class Meta:
        db_table = "bill_occurrences"
        ordering = ["due_date"]

        constraints = [
            models.UniqueConstraint(fields=["bill", "due_date"],name="uniq_occurrence_per_due_date"),
            models.CheckConstraint(
    condition=models.Q(amount__gt=0),
    name="occurrence_amount_positive",
)
        ]

        indexes = [
            models.Index(fields=["bill"]),
            models.Index(fields=["due_date"]),
            models.Index(fields=["status"]),
        ]

    def clean(self):
        super().clean()

        if self.amount <= 0:
            raise ValidationError(
                {"amount": "Occurrence amount must be greater than zero."}
            )

    def __str__(self):
        return f"{self.bill.vendor.name} - {self.due_date}"