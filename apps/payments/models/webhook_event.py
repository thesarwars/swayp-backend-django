from django.db import models

from apps.common.models import BaseModel


class WebhookEvent(BaseModel):
    """A processor callback, recorded once (E6-S1 / E6-S8).

    Processors redeliver and reorder. The unique constraint on
    (processor, event_id) is the dedupe: an insert that conflicts means the
    event was already accepted, so the redelivery is acknowledged and dropped
    rather than applied twice.
    """

    processor = models.CharField(max_length=20)
    event_id = models.CharField(max_length=100)

    event_type = models.CharField(max_length=100, blank=True)
    payload = models.JSONField(default=dict)

    processed_at = models.DateTimeField(null=True, blank=True)
    result = models.CharField(max_length=50, blank=True)

    class Meta:
        db_table = "webhook_events"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["processor", "event_id"],
                name="uniq_webhook_processor_event",
            ),
        ]
        indexes = [models.Index(fields=["processor", "processed_at"])]

    def __str__(self):
        return f"{self.processor}:{self.event_id}"
