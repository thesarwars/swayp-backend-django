"""Connection and funding-account management (E5-S3)."""

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.banking.models import (
    BankAccount,
    BankConnection,
    BankConnectionStatus,
)
from apps.common.enums import PaymentStatus

#: A payment in one of these states still needs its funding source.
IN_FLIGHT_STATUSES = (
    PaymentStatus.SCHEDULED,
    PaymentStatus.PENDING,
    PaymentStatus.PROCESSING,
)


class ConnectionService:

    def list_connections(self, user):
        return (
            BankConnection.objects.filter(user=user)
            .prefetch_related("accounts")
            .order_by("-created_at")
        )

    def list_accounts(self, user, connection_id=None):
        queryset = BankAccount.objects.filter(
            connection__user=user,
            connection__status=BankConnectionStatus.ACTIVE,
        ).select_related("connection")

        if connection_id:
            queryset = queryset.filter(connection_id=connection_id)

        return queryset

    def get_connection(self, user, connection_id):
        connection = BankConnection.objects.filter(
            id=connection_id, user=user
        ).first()

        if connection is None:
            raise ValidationError({"connection": "Connection not found."})

        return connection

    def payments_in_flight(self, connection):
        """Payments that would be orphaned by disconnecting."""
        from apps.payments.models import Payment

        return Payment.objects.filter(
            user=connection.user,
            status__in=IN_FLIGHT_STATUSES,
        )

    @transaction.atomic
    def disconnect(self, *, user, connection_id):
        """Revoke at the provider and mark the connection disconnected.

        Blocked while payments are in flight — pulling the funding source out
        from under a payment that is already moving would strand it.
        """
        connection = self.get_connection(user, connection_id)

        in_flight = self.payments_in_flight(connection).count()

        if in_flight:
            raise ValidationError(
                {
                    "connection": (
                        f"Cannot disconnect while {in_flight} payment(s) are "
                        "in flight. Cancel or wait for them to settle first."
                    )
                }
            )

        if connection.status == BankConnectionStatus.DISCONNECTED:
            return connection

        # Revoke at the provider first so the link is actually dead upstream,
        # not merely flagged locally. If revocation fails the atomic block
        # rolls back and the connection stays ACTIVE for a clean retry.
        from integrations.factory import get_bank_data_provider

        get_bank_data_provider().remove_item(
            access_token=connection.access_token
        )

        connection.status = BankConnectionStatus.DISCONNECTED
        connection.save(update_fields=["status", "updated_at"])

        # Funding-source flags go with it; nothing may draw on a dead link.
        BankAccount.objects.filter(connection=connection).update(
            is_default_funding_source=False
        )

        return connection

    @transaction.atomic
    def set_default_funding_source(self, *, user, account_id):
        account = BankAccount.objects.filter(
            id=account_id,
            connection__user=user,
            connection__status=BankConnectionStatus.ACTIVE,
        ).first()

        if account is None:
            raise ValidationError({"account": "Account not found."})

        BankAccount.objects.filter(connection__user=user).update(
            is_default_funding_source=False
        )

        account.is_default_funding_source = True
        account.save(update_fields=["is_default_funding_source", "updated_at"])

        return account
