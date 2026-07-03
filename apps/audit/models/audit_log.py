from django.db import models

from apps.common.models import BaseModel


class AuditLog(BaseModel):

    user = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
    )

    action = models.CharField(
        max_length=255,
    )

    ip = models.GenericIPAddressField()

    user_agent = models.TextField()

    metadata = models.JSONField(
        default=dict,
    )

    class Meta:
        db_table = "audit_logs"