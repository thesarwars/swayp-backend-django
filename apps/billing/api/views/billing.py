"""Billing endpoints (E9-S1 … E9-S5)."""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny

from apps.billing.api.serializers.billing import (
    AddOnSerializer,
    FeeChargeQuerySerializer,
    FeeChargeSerializer,
    AllowancesSerializer,
    InvoicePreviewSerializer,
    BillingConfigSerializer,
    CardSerializer,
    InvoiceHistoryItemSerializer,
    InvoiceHistoryQuerySerializer,
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
from apps.common.pagination import PaginationService
from apps.common.responses import ApiResponse
from apps.payments.idempotency import IdempotencyMixin
from apps.teams.access import AccountScopedMixin
from apps.teams.permissions import MANAGE_BILLING


@extend_schema(
    tags=["Billing"],
    summary="List plans",
    auth=[],
    description=(
        "The tiers and what each includes, plus what subscribing now "
        "would get: trial_eligible, lock_available and "
        "founding_spots_remaining. Public: no token needed (for the pricing "
        "page). With a token, trial_eligible is this account's; without "
        "one it is true, as for a new account."
    ),
    responses={200: PlanOfferSerializer(many=True)},
)
class PlanListAPIView(AccountScopedMixin, BaseAPIView):

    # Public (web §4): the marketing pricing page shows the plans before
    # anyone signs up. A token still personalises trial_eligible; without
    # one it is true, which is what a new account would get.
    permission_classes = [AllowAny]

    def get(self, request):
        plans = Plan.objects.filter(is_active=True).order_by("monthly_price")
        service = SubscriptionService()
        signed_in = request.user and request.user.is_authenticated

        return ApiResponse.success(
            data=PlanOfferSerializer(
                plans,
                many=True,
                context={
                    "trial_eligible": (
                        service.trial_eligible(self.account(request))
                        if signed_in else True
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
class SubscriptionAPIView(AccountScopedMixin, IdempotencyMixin, BaseAPIView):

    service_class = SubscriptionService
    # Reading the plan is fine for anyone on the team; changing it is not,
    # because it changes what the owner is charged.
    required_capability = MANAGE_BILLING
    safe_methods = ("GET",)
    nullable_data = ("GET",)
    may_be_unavailable = True

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

    @extend_schema(
        summary="Subscribe",
        description=(
            "Starts the plan; with payment_method_id from a confirmed "
            "SetupIntent when money is collected. 201."
        ),
        request=SubscribeSerializer,
        responses={201: SubscriptionSerializer},
    )
    def post(self, request):
        """Subscribe to a plan."""
        # A retry must not start a second subscription or charge (API-2).
        return self.run_idempotent(request, lambda: self._subscribe(request))

    def _subscribe(self, request):
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

    @extend_schema(
        summary="Change plan",
        description=(
            "Keeps the current cycle. 402 if the account's usage would not "
            "fit the new plan."
        ),
        request=SubscribeSerializer,
        responses={200: SubscriptionSerializer},
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

    @extend_schema(
        summary="Cancel at period end",
        description=(
            "The plan stays live until cancels_on, then ends. Undo with "
            "POST subscription/resume."
        ),
        request=None,
        responses={200: SubscriptionSerializer},
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
    may_be_unavailable = True
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
    responses={200: AllowancesSerializer},
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
    required_capability = MANAGE_BILLING
    safe_methods = ("GET",)
    nullable_data = ("POST",)

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

    @extend_schema(
        summary="Add, update or remove an add-on",
        description="quantity 0 removes it, and data is then null.",
        request=SetAddOnSerializer,
        responses={200: AddOnSerializer},
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
    description=(
        "The per-transaction fee ledger, newest first, paged. Filter by "
        "state and by the day charged (from_date, to_date, inclusive); "
        "filters apply before paging. payment_id links to the receipt."
    ),
    parameters=[FeeChargeQuerySerializer],
    responses={200: FeeChargeSerializer(many=True)},
)
class FeeChargeListAPIView(AccountScopedMixin, BaseAPIView):

    # pagination beside data in the schema (apps/common/schema.py).
    paginated_response = True

    def get(self, request):
        query = FeeChargeQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data

        subscription = SubscriptionService().current(self.account(request))

        if subscription is None:
            raise ValidationError(
                {"subscription": "No active subscription."}
            )

        fees = subscription.fee_charges.select_related("payment")

        if params.get("state"):
            fees = fees.filter(state=params["state"])

        if params.get("from_date"):
            fees = fees.filter(created_at__date__gte=params["from_date"])

        if params.get("to_date"):
            fees = fees.filter(created_at__date__lte=params["to_date"])

        result = PaginationService.paginate(
            fees, page=params["page"], page_size=params["pageSize"]
        )

        return ApiResponse.success(
            data=FeeChargeSerializer(result["items"], many=True).data,
            message="Fee charges fetched successfully.",
            pagination=result["pagination"],
        )


@extend_schema(
    tags=["Billing"],
    summary="Start card collection",
    request=None,
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
    may_be_unavailable = True
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
    required_capability = MANAGE_BILLING
    safe_methods = ("GET",)
    nullable_data = ("GET",)
    may_be_unavailable = True

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
        "SetupIntent every time. Also the per-payment fee schedule, so no "
        "client hard-codes a price. Public: no token needed."
    ),
    auth=[],
    responses={200: BillingConfigSerializer},
)
class BillingConfigAPIView(BaseAPIView):

    # Public, like the plans: the pricing page shows the fees too, and a
    # publishable key is public by design.
    permission_classes = [AllowAny]

    def get(self, request):
        from decimal import Decimal

        from apps.billing.models.fee_charge import FEE_AMOUNTS, FeeKind

        provider = BillingProviderService()
        free = Decimal("0.00")

        return ApiResponse.success(
            data=BillingConfigSerializer({
                "collects_money": provider.collects_money,
                "publishable_key": provider.publishable_key,
                # From the same table the charges use, so the price shown
                # and the price charged cannot differ (web §4).
                "fees": {
                    "ach_standard": free,
                    "ach_same_day": FEE_AMOUNTS[FeeKind.SAME_DAY_ACH],
                    "network": free,
                    "check_standard": free,
                    "check_overage": FEE_AMOUNTS[FeeKind.CHECK_OVERAGE],
                    "check_expedited": FEE_AMOUNTS[FeeKind.EXPEDITED_CHECK],
                },
            }).data,
            message="Billing configuration fetched successfully.",
        )


@extend_schema(
    tags=["Billing"],
    summary="Invoice history",
    description=(
        "Past invoices from the payment processor, newest first, with "
        "pdf_url to download each. Cursor paged: pass next_cursor back as "
        "starting_after; next_cursor is null on the last page. Empty on a "
        "deployment that collects no money. The current cycle's running "
        "total is billing/invoice."
    ),
    parameters=[InvoiceHistoryQuerySerializer],
    responses={200: InvoiceHistoryItemSerializer(many=True)},
)
class InvoiceHistoryAPIView(AccountScopedMixin, BaseAPIView):

    may_be_unavailable = True
    response_extra = {
        "next_cursor": {
            "type": "string",
            "nullable": True,
            "description": "Send as starting_after for the next page.",
        },
    }

    def get(self, request):
        query = InvoiceHistoryQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        subscription = SubscriptionService().current(self.account(request))
        invoices, has_more = BillingProviderService().invoices(
            subscription,
            limit=query.validated_data["limit"],
            starting_after=query.validated_data["starting_after"],
        )

        return ApiResponse.success(
            data=InvoiceHistoryItemSerializer(invoices, many=True).data,
            message="Invoices fetched successfully.",
            extra={
                "next_cursor": invoices[-1].id if has_more and invoices else None,
            },
        )
