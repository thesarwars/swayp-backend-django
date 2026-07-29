"""factory_boy factories for the notifications domain (E8-S3)."""

import factory

from apps.common.enums import NotificationType
from apps.notifications.models import Notification, NotificationPreference
from apps.vendors.factories import UserFactory


class NotificationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Notification

    user = factory.SubFactory(UserFactory)
    title = "Verizon is due"
    message = "Verizon for 389.00 was due on 2026-08-01. Approve it to pay."
    type = NotificationType.BILL_DUE


class NotificationPreferenceFactory(factory.django.DjangoModelFactory):
    """The four channel columns are left at their model defaults, so a test
    that overrides one reads as the single thing it is changing."""

    class Meta:
        model = NotificationPreference

    user = factory.SubFactory(UserFactory)
    type = NotificationType.BILL_DUE
