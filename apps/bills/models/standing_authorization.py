from django.db import models

from apps.common.models import BaseModel
from apps.bills.models.bill import Bill


class StandingAuthorization(BaseModel):
    """
    Stores user's ACH/AutoPay authorization history.

    Each time a user enables AutoPay, a new authorization
    record is created for auditing purposes.
    """

    bill = models.ForeignKey(Bill,on_delete=models.CASCADE,related_name="standing_authorizations")
    authorization_text = models.TextField()
    accepted_at = models.DateTimeField()
    ip = models.GenericIPAddressField()
    user_agent = models.TextField()
    revoked_at = models.DateTimeField(null=True,blank=True)

    class Meta:
        db_table = "standing_authorizations"
        ordering = ["-accepted_at"]

    def __str__(self):
        return (
            f"{self.bill.vendor.name} - "
            f"{self.accepted_at.date()}"
        )