"""Billing endpoints (E9-S1 … E9-S5)."""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError

from apps.billing.api.serializers.billing import (
    AddOnSerializer,
    FeeChargeSerializer,
    InvoicePreviewSerializer,
    BillingConfigSerializer,
    CardSerializer,
    PlanOfferSerializer,
    ReplaceCardSerializer,
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
    description=(
        "The three tiers and what each includes, plus what this account "
        "would get by subscribing now: trial_eligible, lock_available and "
        "founding_spots_remaining."
    ),
    responses={200: PlanOfferSerializer(many=True)},
)
class PlanListAPIView(AccountScopedMixin, BaseAPIView):

    def get(self, request):
        plans = Plan.objects.filter(is_active=True).order_by("monthly_price")
        service = SubscriptionService()

        return ApiResponse.success(
            data=PlanOfferSerializer(
                plans,
                many=True,
                context={
                    "trial_eligible": service.trial_eligible(
                        self.account(request)
                    ),
                    "spots_remaining": service.founding_spots_remaining(),
                },
            ).data,
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
        """Cancel at the end of the paid period (BILLING-5)."""
        subscription = self.service.cancel(account=self.account(request))

        return ApiResponse.success(
            data=SubscriptionSerializer(subscription).data,
            message=(
                f"Your plan stays active until {subscription.cancels_on}, "
                "then ends."
            ),
        )


@extend_schema(
    tags=["Billing"],
    summary="Undo a pending cancellation",
    description=(
        "Withdraws a cancellation before cancels_on; the plan continues as "
        "if it had never been cancelled. 400 when none is pending."
    ),
    request=None,
    responses={200: SubscriptionSerializer},
)
class SubscriptionResumeAPIView(AccountScopedMixin, BaseAPIView):

    service_class = SubscriptionService
    permission_classes = BaseAPIView.permission_classes + [
        RequiresCapability
    ]
    required_capability = MANAGE_BILLING

    def post(self, request):
        subscription = self.service.resume(account=self.account(request))

        return ApiResponse.success(
            data=SubscriptionSerializer(subscription).data,
            message="Cancellation withdrawn; your plan continues.",
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


@extend_schema(
    tags=["Billing"],
    summary="Card on file",
    description=(
        "GET: the default card (brand, last4, exp_month, exp_year), or null "
        "when there is none or no processor collects money. POST: replace it "
        "with a card collected against a SetupIntent (payment-method/setup). "
        "A past-due subscription is charged with the new card at once. A "
        "declined card is a 400 on payment_method_id."
    ),
    request=ReplaceCardSerializer,
    responses={200: CardSerializer},
)
class PaymentMethodAPIView(AccountScopedMixin, BaseAPIView):

    service_class = SubscriptionService
    permission_classes = BaseAPIView.permission_classes + [
        RequiresCapability
    ]
    required_capability = MANAGE_BILLING
    safe_methods = ("GET",)

    def get(self, request):
        subscription = self.service.current(self.account(request))
        card = BillingProviderService().card(subscription)

        return ApiResponse.success(
            data=CardSerializer(card).data if card else None,
            message="Card fetched successfully.",
        )

    def post(self, request):
        serializer = ReplaceCardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        subscription = self.service.current(self.account(request))

        if subscription is None:
            raise ValidationError(
                {"subscription": "Choose a plan before adding a card."}
            )

        card = BillingProviderService().replace_card(
            subscription, serializer.validated_data["payment_method_id"]
        )

        return ApiResponse.success(
            data=CardSerializer(card).data,
            message="Card updated.",
        )


@extend_schema(
    tags=["Billing"],
    summary="Billing configuration",
    description=(
        "Whether this deployment collects money, and the processor's "
        "publishable key for the card form. Creates nothing; call it before "
        "showing checkout instead of payment-method/setup, which opens a "
        "SetupIntent every time."
    ),
    responses={200: BillingConfigSerializer},
)
class BillingConfigAPIView(BaseAPIView):

    def get(self, request):
        provider = BillingProviderService()

        return ApiResponse.success(
            data={
                "collects_money": provider.collects_money,
                "publishable_key": provider.publishable_key,
            },
            message="Billing configuration fetched successfully.",
        )
