"""Starting a plan through Stripe Checkout (Phase 1)."""

from drf_spectacular.utils import extend_schema
from rest_framework import status

from apps.billing.api.serializers.checkout import (
    CheckoutStartSerializer,
    CheckoutStatusSerializer,
    StartCheckoutSerializer,
)
from apps.billing.services.checkout_service import SUBSCRIBED, CheckoutService
from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse
from apps.payments.idempotency import IdempotencyMixin
from apps.teams.access import AccountScopedMixin
from apps.teams.permissions import MANAGE_BILLING


@extend_schema(tags=["Billing"])
class CheckoutSessionAPIView(AccountScopedMixin, IdempotencyMixin, BaseAPIView):

    requires_subscription = False
    required_capability = MANAGE_BILLING
    service_class = CheckoutService
    may_be_unavailable = True

    @extend_schema(
        summary="Start a plan",
        description=(
            "The one call behind every plan button. The backend picks the "
            "route: when a trial applies the plan starts now with no card "
            "and `action` is `subscribed`; otherwise `action` is `redirect` "
            "and the browser goes to `url`, Stripe's hosted payment page. "
            "Stripe sends the user back to /billing/success?session_id=…, "
            "which polls GET checkout-session/{id}. 400 already_subscribed "
            "when the account has a live plan: use PATCH subscription."
        ),
        request=StartCheckoutSerializer,
        responses={200: CheckoutStartSerializer, 201: CheckoutStartSerializer},
    )
    def post(self, request):
        return self.run_idempotent(request, lambda: self._start(request))

    def _start(self, request):
        serializer = StartCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        action, result = self.service.start(
            account=self.account(request),
            plan_code=serializer.validated_data["plan"],
        )

        if action == SUBSCRIBED:
            data = {
                "action": action,
                "url": None,
                "session_id": None,
                "subscription": result,
            }
            message = "Your trial has started."
            code = status.HTTP_201_CREATED
        else:
            data = {
                "action": action,
                "url": result.url,
                "session_id": result.provider_session_id,
                "subscription": result.subscription,
            }
            message = "Continue to payment."
            code = status.HTTP_200_OK

        return ApiResponse.success(
            data=CheckoutStartSerializer(data).data,
            message=message,
            status_code=code,
        )


@extend_schema(
    tags=["Billing"],
    summary="Checkout status",
    description=(
        "For the success page: poll every ~2 s until `status` is "
        "`complete` (then `subscription` is set) or `expired`. Asks Stripe "
        "directly when the webhook has not arrived yet."
    ),
    responses={200: CheckoutStatusSerializer},
)
class CheckoutSessionDetailAPIView(AccountScopedMixin, BaseAPIView):

    requires_subscription = False
    required_capability = MANAGE_BILLING
    service_class = CheckoutService
    may_be_unavailable = True

    def get(self, request, session_id):
        session = self.service.status(
            account=self.account(request), session_id=session_id
        )

        return ApiResponse.success(
            data=CheckoutStatusSerializer(session).data,
            message="Checkout fetched.",
        )
