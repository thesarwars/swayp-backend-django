"""Billing endpoints (E9-S1 … E9-S5)."""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError

from apps.billing.api.serializers.billing import (
    AddOnSerializer,
    FeeChargeSerializer,
    InvoicePreviewSerializer,
    PlanSerializer,
    SetAddOnSerializer,
    SetupIntentSerializer,
    SubscribeSerializer,
    SubscriptionSerializer,
)
from apps.billing.models import Plan
from apps.billing.services.addon_service import AddOnService
from apps.billing.services.allowance_service import AllowanceService
from apps.billing.services.provider_service import BillingProviderService
from apps.billing.services.subscription_service import SubscriptionService
from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse
from apps.teams.access import AccountScopedMixin, RequiresCapability
from apps.teams.permissions import MANAGE_BILLING


@extend_schema(
    tags=["Billing"],
    summary="List plans",
    description="The three tiers and what each includes.",
    responses={200: PlanSerializer(many=True)},
)
class PlanListAPIView(BaseAPIView):

    def get(self, request):
        plans = Plan.objects.filter(is_active=True).order_by("monthly_price")

        return ApiResponse.success(
            data=PlanSerializer(plans, many=True).data,
            message="Plans fetched successfully.",
        )


@extend_schema(
    tags=["Billing"],
    summary="Current subscription",
    description=(
        "The account's active subscription, or null when there is none. "
        "effective_price honours the Founding price lock."
    ),
    responses={200: SubscriptionSerializer},
)
class SubscriptionAPIView(AccountScopedMixin, BaseAPIView):

    service_class = SubscriptionService
    # Reading the plan is fine for anyone on the team; changing it is not,
    # because it changes what the owner is charged.
    permission_classes = BaseAPIView.permission_classes + [
        RequiresCapability
    ]
    required_capability = MANAGE_BILLING
    safe_methods = ("GET",)

    def get(self, request):
        subscription = self.service.current(self.account(request))

        return ApiResponse.success(
            data=(
                SubscriptionSerializer(subscription).data
                if subscription
                else None
            ),
            message="Subscription fetched successfully.",
        )

    def post(self, request):
        """Subscribe to a plan."""
        serializer = SubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        subscription = self.service.subscribe(
            account=self.account(request),
            plan_code=serializer.validated_data["plan"],
            payment_method_id=serializer.validated_data.get(
                "payment_method_id", ""
            ),
        )

        return ApiResponse.success(
            data=SubscriptionSerializer(subscription).data,
            message="Subscribed successfully.",
            status_code=status.HTTP_201_CREATED,
        )

    def patch(self, request):
        """Change plan, keeping the current cycle."""
        serializer = SubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        subscription = self.service.change_plan(
            account=self.account(request),
            plan_code=serializer.validated_data["plan"],
        )

        return ApiResponse.success(
            data=SubscriptionSerializer(subscription).data,
            message="Plan changed.",
        )

    def delete(self, request):
        subscription = self.service.cancel(account=self.account(request))

        return ApiResponse.success(
            data=SubscriptionSerializer(subscription).data,
            message="Subscription cancelled.",
        )


@extend_schema(
    tags=["Billing"],
    summary="Plan allowances",
    description=(
        "Usage against each allowance. limit null means unlimited. Seats and "
        "banks are standing capacity; checks reset each cycle."
    ),
)
class AllowanceAPIView(AccountScopedMixin, BaseAPIView):

    def get(self, request):
        subscription = SubscriptionService().current(self.account(request))

        if subscription is None:
            raise ValidationError(
                {"subscription": "No active subscription."}
            )

        return ApiResponse.success(
            data=AllowanceService().summary(subscription),
            message="Allowances fetched successfully.",
        )


@extend_schema(
    tags=["Billing"],
    summary="Enterprise add-ons",
    description=(
        "Each add-on is its own invoice line. Send quantity 0 to remove one."
    ),
    responses={200: AddOnSerializer(many=True)},
)
class AddOnAPIView(AccountScopedMixin, BaseAPIView):

    service_class = AddOnService
    # Adding an add-on adds an invoice line, so it is a billing change.
    permission_classes = BaseAPIView.permission_classes + [
        RequiresCapability
    ]
    required_capability = MANAGE_BILLING
    safe_methods = ("GET",)

    def _subscription(self, request):
        subscription = SubscriptionService().current(self.account(request))

        if subscription is None:
            raise ValidationError(
                {"subscription": "No active subscription."}
            )

        return subscription

    def get(self, request):
        subscription = self._subscription(request)

        return ApiResponse.success(
            data=AddOnSerializer(
                subscription.addons.order_by("kind"), many=True
            ).data,
            message="Add-ons fetched successfully.",
        )

    def post(self, request):
        subscription = self._subscription(request)

        serializer = SetAddOnSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        addon = self.service.set_addon(
            subscription=subscription,
            kind=serializer.validated_data["kind"],
            quantity=serializer.validated_data["quantity"],
        )

        return ApiResponse.success(
            data=AddOnSerializer(addon).data if addon else None,
            message="Add-on removed." if addon is None else "Add-on saved.",
        )


@extend_schema(
    tags=["Billing"],
    summary="Invoice preview",
    description=(
        "Every line for the current cycle: the plan, each add-on, and each "
        "unbilled fee. Refunded fees appear at zero rather than disappearing."
    ),
    responses={200: InvoicePreviewSerializer},
)
class InvoicePreviewAPIView(AccountScopedMixin, BaseAPIView):

    service_class = AddOnService

    def get(self, request):
        subscription = SubscriptionService().current(self.account(request))

        if subscription is None:
            raise ValidationError(
                {"subscription": "No active subscription."}
            )

        return ApiResponse.success(
            data=InvoicePreviewSerializer(
                self.service.invoice_preview(subscription)
            ).data,
            message="Invoice preview fetched successfully.",
        )


@extend_schema(
    tags=["Billing"],
    summary="Fee charges",
    description="The per-transaction fee ledger, newest first.",
    responses={200: FeeChargeSerializer(many=True)},
)
class FeeChargeListAPIView(AccountScopedMixin, BaseAPIView):

    def get(self, request):
        subscription = SubscriptionService().current(self.account(request))

        if subscription is None:
            raise ValidationError(
                {"subscription": "No active subscription."}
            )

        return ApiResponse.success(
            data=FeeChargeSerializer(
                subscription.fee_charges.select_related("payment"),
                many=True,
            ).data,
            message="Fee charges fetched successfully.",
        )


@extend_schema(
    tags=["Billing"],
    summary="Start card collection",
    description=(
        "Returns a SetupIntent client secret for the card form. The card is "
        "sent straight to the processor, never to Swayp; POST the resulting "
        "payment_method_id to /billing/subscription/. When collects_money is "
        "false no processor is configured and there is no card to collect."
    ),
    responses={200: SetupIntentSerializer},
)
class PaymentMethodSetupAPIView(AccountScopedMixin, BaseAPIView):

    service_class = SubscriptionService
    permission_classes = BaseAPIView.permission_classes + [
        RequiresCapability
    ]
    required_capability = MANAGE_BILLING

    def post(self, request):
        account = self.account(request)
        provider = BillingProviderService()

        if not provider.collects_money:
            # Not an error: the mock deployment genuinely has nothing to
            # collect, and the client needs to know that rather than wait for
            # a card form that will never work.
            return ApiResponse.success(
                data={
                    "client_secret": "",
                    "publishable_key": "",
                    "collects_money": False,
                },
                message="No payment processor is configured.",
            )

        subscription = self.service.current(account)

        if subscription is None:
            # A SetupIntent needs a customer, and a customer without a chosen
            # plan is an object nobody will ever bill. Subscribe first.
            raise ValidationError(
                {
                    "subscription": (
                        "Choose a plan before adding a payment method."
                    )
                }
            )

        intent = provider.setup_intent(subscription)

        return ApiResponse.success(
            data={
                "client_secret": intent.client_secret,
                "publishable_key": intent.publishable_key,
                "collects_money": True,
            },
            message="Setup intent created.",
        )
