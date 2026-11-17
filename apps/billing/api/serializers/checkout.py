"""Starting a plan through the provider's hosted checkout."""

from rest_framework import serializers

from apps.billing.api.serializers.billing import SubscriptionSerializer
from apps.billing.models import CheckoutStatus, PlanCode


class StartCheckoutSerializer(serializers.Serializer):
    plan = serializers.ChoiceField(choices=PlanCode.choices)


class CheckoutStartSerializer(serializers.Serializer):
    """What to do next.

    ``subscribed``: a trial started, no payment needed; go to the dashboard.
    ``redirect``: send the browser to ``url`` (the provider's hosted payment page).
    """

    action = serializers.ChoiceField(choices=["subscribed", "redirect"])
    url = serializers.URLField(allow_null=True)
    session_id = serializers.CharField(allow_null=True)
    subscription = SubscriptionSerializer(allow_null=True)


class CheckoutStatusSerializer(serializers.Serializer):
    """Polled by the success page until ``status`` is ``complete``."""

    session_id = serializers.CharField(source="provider_session_id")
    status = serializers.ChoiceField(choices=CheckoutStatus.choices)
    plan = serializers.CharField(source="plan.code")
    subscription = SubscriptionSerializer(allow_null=True)
