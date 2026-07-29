"""Multi-entity accounts (E10-S3, Enterprise).

An entity is a legal business under one Swayp account — the structure a
multi-entity customer already has in their accounting system. Bills, vendors
and payments carry a nullable FK to one, so a single-entity account is
unaffected: everything stays null and every existing query keeps working.
"""

from django.db import models

from apps.common.models import BaseModel


class EntityStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    ARCHIVED = "ARCHIVED", "Archived"


class Entity(BaseModel):

    account = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="entities",
    )

    legal_name = models.CharField(max_length=150)

    # Not encrypted and not validated as a tax identifier: it is a label the
    # customer types to tell their own entities apart, and E8's 1099 reporting
    # owns anything that has to be filed.
    ein = models.CharField(max_length=20, blank=True)

    status = models.CharField(
        max_length=10,
        choices=EntityStatus.choices,
        default=EntityStatus.ACTIVE,
    )

    class Meta:
        db_table = "entities"
        ordering = ["legal_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "legal_name"],
                name="uniq_entity_name_per_account",
            ),
        ]
        indexes = [
            models.Index(fields=["account", "status"]),
        ]

    def __str__(self):
        return self.legal_name
