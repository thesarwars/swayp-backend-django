"""Multi-entity accounts (E10-S3).

Entities are Enterprise-only, and the entity count drives E9-S5's extra-entity
add-on: the plan includes three, and every one beyond that is $79/mo. The
add-on is re-synced on every create and archive so the invoice cannot drift
from the real structure — nobody has to remember to update billing.
"""

import logging

from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from apps.billing.models import PlanCode
from apps.billing.services.addon_service import AddOnService
from apps.billing.services.subscription_service import SubscriptionService
from apps.teams.models import Entity, EntityStatus

logger = logging.getLogger(__name__)


class EntityService:

    def __init__(self):
        self.subscriptions = SubscriptionService()
        self.addons = AddOnService()

    def active(self, account):
        return Entity.objects.filter(
            account=account, status=EntityStatus.ACTIVE
        )

    def count(self, account):
        return self.active(account).count()

    # --- gating -----------------------------------------------------------

    def is_enterprise(self, account):
        subscription = self.subscriptions.current(account)

        return (
            subscription is not None
            and subscription.plan.code == PlanCode.ENTERPRISE
        )

    def assert_can_add(self, account):
        """A second entity is Enterprise-only.

        The first is free on every plan and is implicit — a single-entity
        account never has to think about entities at all, which is why the
        gate is on the *second* rather than on the feature.
        """
        if self.is_enterprise(account):
            return True

        if self.count(account) >= 1:
            raise ValidationError(
                {
                    "plan": (
                        "Multiple entities are available on the Enterprise "
                        "plan only."
                    )
                }
            )

        return True

    # --- CRUD -------------------------------------------------------------

    @transaction.atomic
    def create(self, *, account, legal_name, ein=""):
        legal_name = (legal_name or "").strip()

        if not legal_name:
            raise ValidationError(
                {"legal_name": "A legal name is required."}
            )

        self.assert_can_add(account)

        try:
            entity = Entity.objects.create(
                account=account, legal_name=legal_name, ein=ein.strip()
            )
        except IntegrityError:
            raise ValidationError(
                {"legal_name": "You already have an entity with this name."}
            )

        self.sync_billing(account)

        return entity

    @transaction.atomic
    def update(self, *, account, entity_id, legal_name=None, ein=None):
        entity = self.get(account, entity_id)

        if legal_name is not None:
            legal_name = legal_name.strip()

            if not legal_name:
                raise ValidationError(
                    {"legal_name": "A legal name is required."}
                )

            entity.legal_name = legal_name

        if ein is not None:
            entity.ein = ein.strip()

        try:
            entity.save(
                update_fields=["legal_name", "ein", "updated_at"]
            )
        except IntegrityError:
            raise ValidationError(
                {"legal_name": "You already have an entity with this name."}
            )

        return entity

    @transaction.atomic
    def archive(self, *, account, entity_id):
        """Archive rather than delete.

        Bills and payments point at entities, and deleting one would either
        cascade away financial history or orphan it. Archiving stops it being
        chosen while leaving every past record readable.
        """
        entity = self.get(account, entity_id)

        entity.status = EntityStatus.ARCHIVED
        entity.save(update_fields=["status", "updated_at"])

        self.sync_billing(account)

        return entity

    def get(self, account, entity_id):
        entity = Entity.objects.filter(
            account=account, id=entity_id
        ).first()

        if entity is None:
            # 404 rather than 403: the API does not confirm that an id it
            # does not own exists.
            from rest_framework.exceptions import NotFound

            raise NotFound("No such entity.")

        return entity

    # --- billing (E9-S5) --------------------------------------------------

    def sync_billing(self, account):
        """Keep the extra-entity add-on in step with the real count.

        Never allowed to break entity management: a billing hiccup must not
        stop a customer structuring their account. The count is derived, so a
        later sync corrects any line that was missed.
        """
        subscription = self.subscriptions.current(account)

        if subscription is None or subscription.plan.code != (
            PlanCode.ENTERPRISE
        ):
            return None

        try:
            return self.addons.sync_entity_addon(
                subscription=subscription,
                entity_count=self.count(account),
            )
        except Exception:
            logger.exception(
                "entity add-on sync failed for %s; count is still derivable",
                account.pk,
            )

            return None
