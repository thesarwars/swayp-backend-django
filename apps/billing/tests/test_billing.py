"""Plans, allowances, fees, refunds and add-ons (E9-S1 … E9-S5)."""

import datetime as dt
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.billing.factories import SubscriptionFactory
from apps.billing.models import (
    ADDON_PRICES,
    FEE_AMOUNTS,
    AddOnKind,
    AllowanceKind,
    EnterpriseAddOn,
    FeeCharge,
    FeeKind,
    FeeState,
    Plan,
    PlanCode,
    Subscription,
    SubscriptionStatus,
)
from apps.billing.services.addon_service import AddOnService
from apps.billing.services.allowance_service import AllowanceService
from apps.billing.services.fee_service import FeeService
from apps.billing.services.subscription_service import (
    add_month,
    SubscriptionService,
)
from apps.common.dates import cutoff_datetime_et
from apps.common.enums import PaymentRail
from apps.common.exceptions import PlanLimitExceededException
from apps.payments.factories import PaymentFactory
from apps.vendors.factories import UserFactory

from zoneinfo import ZoneInfo

D = dt.date
EASTERN = ZoneInfo("America/New_York")


def plan(code):
    return Plan.objects.get(code=code)


class PlanSeedTests(TestCase):
    """The BRD numbers are fixed by the CEO; these pin them."""

    def test_the_three_plans_are_seeded(self):
        self.assertEqual(
            sorted(Plan.objects.values_list("code", flat=True)),
            ["ENTERPRISE", "FOUNDING", "STANDARD"],
        )

    def test_founding_matches_the_brd(self):
        p = plan(PlanCode.FOUNDING)

        self.assertEqual(p.monthly_price, Decimal("49.00"))
        self.assertEqual(p.seat_limit, 3)
        self.assertEqual(p.bank_limit, 1)
        self.assertEqual(p.free_checks_per_month, 2)
        self.assertTrue(p.price_locked)

    def test_standard_matches_the_brd(self):
        p = plan(PlanCode.STANDARD)

        self.assertEqual(p.monthly_price, Decimal("99.00"))
        self.assertEqual(p.seat_limit, 10)
        self.assertIsNone(p.bank_limit)
        self.assertEqual(p.free_checks_per_month, 5)

    def test_enterprise_is_unlimited_and_includes_three_entities(self):
        p = plan(PlanCode.ENTERPRISE)

        self.assertEqual(p.monthly_price, Decimal("299.00"))
        self.assertIsNone(p.seat_limit)
        self.assertIsNone(p.bank_limit)
        self.assertEqual(p.included_entities, 3)


class SubscriptionTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.service = SubscriptionService()

    def test_subscribing_starts_a_cycle(self):
        subscription = self.service.subscribe(
            account=self.user, plan_code=PlanCode.STANDARD,
            today=D(2026, 8, 1),
        )

        self.assertEqual(subscription.period_start, D(2026, 8, 1))
        self.assertEqual(subscription.period_end, D(2026, 9, 1))

    def test_only_one_active_subscription_per_account(self):
        self.service.subscribe(
            account=self.user, plan_code=PlanCode.STANDARD
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Subscription.objects.create(
                    account=self.user,
                    plan=plan(PlanCode.FOUNDING),
                    status=SubscriptionStatus.ACTIVE,
                    period_start=D(2026, 8, 1),
                    period_end=D(2026, 9, 1),
                )

    def test_a_cancelled_subscription_frees_the_slot(self):
        self.service.subscribe(
            account=self.user, plan_code=PlanCode.STANDARD
        )
        self.service.cancel(account=self.user)

        again = self.service.subscribe(
            account=self.user, plan_code=PlanCode.FOUNDING
        )

        self.assertTrue(again.is_active)
        self.assertEqual(Subscription.objects.count(), 2)

    def test_founding_locks_its_price(self):
        subscription = self.service.subscribe(
            account=self.user, plan_code=PlanCode.FOUNDING
        )

        self.assertEqual(subscription.locked_price, Decimal("49.00"))

    def test_the_lock_survives_a_list_price_rise(self):
        subscription = self.service.subscribe(
            account=self.user, plan_code=PlanCode.FOUNDING
        )

        founding = plan(PlanCode.FOUNDING)
        founding.monthly_price = Decimal("79.00")
        founding.save(update_fields=["monthly_price"])

        subscription.refresh_from_db()
        self.assertEqual(subscription.effective_price, Decimal("49.00"))

    def test_renewal_keeps_the_locked_price(self):
        subscription = self.service.subscribe(
            account=self.user, plan_code=PlanCode.FOUNDING,
            today=D(2026, 8, 1),
        )

        self.service.renew(subscription)

        self.assertEqual(subscription.period_start, D(2026, 9, 1))
        self.assertEqual(subscription.period_end, D(2026, 10, 1))
        self.assertEqual(subscription.effective_price, Decimal("49.00"))

    def test_an_unlocked_plan_follows_the_list_price(self):
        subscription = self.service.subscribe(
            account=self.user, plan_code=PlanCode.STANDARD
        )

        self.assertIsNone(subscription.locked_price)
        self.assertEqual(subscription.effective_price, Decimal("99.00"))

    def test_leaving_founding_gives_up_the_lock(self):
        self.service.subscribe(
            account=self.user, plan_code=PlanCode.FOUNDING
        )

        changed = self.service.change_plan(
            account=self.user, plan_code=PlanCode.STANDARD
        )

        self.assertIsNone(changed.locked_price)
        self.assertEqual(changed.effective_price, Decimal("99.00"))

    def test_a_month_end_anchor_clamps_into_february(self):
        self.assertEqual(add_month(D(2026, 1, 31)), D(2026, 2, 28))
        self.assertEqual(add_month(D(2024, 1, 31)), D(2024, 2, 29))
        self.assertEqual(add_month(D(2026, 12, 15)), D(2027, 1, 15))


class AllowanceTests(TestCase):

    def setUp(self):
        self.service = AllowanceService()
        self.subscription = SubscriptionFactory(
            plan=plan(PlanCode.FOUNDING)
        )

    def test_capacity_is_blocked_past_the_plan_limit(self):
        # Founding allows one bank.
        self.service.consume_capacity(
            subscription=self.subscription, kind=AllowanceKind.BANKS
        )

        with self.assertRaises(PlanLimitExceededException):
            self.service.consume_capacity(
                subscription=self.subscription, kind=AllowanceKind.BANKS
            )

    def test_the_limit_error_is_402_not_403(self):
        """Authorised, just needs a bigger plan — so the client can upsell."""
        self.service.consume_capacity(
            subscription=self.subscription, kind=AllowanceKind.BANKS
        )

        with self.assertRaises(PlanLimitExceededException) as ctx:
            self.service.check_capacity(
                subscription=self.subscription, kind=AllowanceKind.BANKS
            )

        self.assertEqual(ctx.exception.status_code, 402)

    def test_unlimited_capacity_never_blocks(self):
        subscription = SubscriptionFactory(plan=plan(PlanCode.ENTERPRISE))

        for _ in range(50):
            self.service.consume_capacity(
                subscription=subscription, kind=AllowanceKind.SEATS
            )

        self.assertTrue(
            self.service.check_capacity(
                subscription=subscription, kind=AllowanceKind.SEATS
            )
        )
        self.assertIsNone(
            self.service.remaining(subscription, AllowanceKind.SEATS)
        )

    def test_releasing_capacity_frees_the_slot(self):
        self.service.consume_capacity(
            subscription=self.subscription, kind=AllowanceKind.BANKS
        )
        self.service.release_capacity(
            subscription=self.subscription, kind=AllowanceKind.BANKS
        )

        self.assertTrue(
            self.service.check_capacity(
                subscription=self.subscription, kind=AllowanceKind.BANKS
            )
        )

    def test_metered_use_is_free_up_to_the_allotment(self):
        # Founding includes two checks.
        for expected in (False, False):
            _, is_overage = self.service.consume_metered(
                subscription=self.subscription
            )
            self.assertEqual(is_overage, expected)

    def test_the_next_check_after_the_allotment_is_an_overage(self):
        for _ in range(2):
            self.service.consume_metered(subscription=self.subscription)

        _, is_overage = self.service.consume_metered(
            subscription=self.subscription
        )

        self.assertTrue(is_overage)

    def test_metered_use_is_never_blocked(self):
        """Going over bills a fee; it does not refuse the send."""
        for _ in range(10):
            self.service.consume_metered(subscription=self.subscription)

        self.assertEqual(
            self.service.used(self.subscription, AllowanceKind.CHECKS), 10
        )

    def test_checks_reset_on_the_new_cycle(self):
        for _ in range(3):
            self.service.consume_metered(subscription=self.subscription)

        SubscriptionService().renew(self.subscription)
        self.service.reset_metered(self.subscription)

        self.assertEqual(
            self.service.used(self.subscription, AllowanceKind.CHECKS), 0
        )

    def test_capacity_does_not_reset_on_the_new_cycle(self):
        """A bank you had last month you still have this month."""
        self.service.consume_capacity(
            subscription=self.subscription, kind=AllowanceKind.BANKS
        )

        SubscriptionService().renew(self.subscription)
        self.service.reset_metered(self.subscription)

        self.assertEqual(
            self.service.used(self.subscription, AllowanceKind.BANKS), 1
        )

    def test_the_summary_reports_every_allowance(self):
        summary = self.service.summary(self.subscription)

        self.assertEqual(summary["BANKS"]["limit"], 1)
        self.assertEqual(summary["SEATS"]["limit"], 3)
        self.assertEqual(summary["CHECKS"]["limit"], 2)
        self.assertFalse(summary["BANKS"]["unlimited"])


class FeeTests(TestCase):

    def setUp(self):
        self.service = FeeService()
        self.subscription = SubscriptionFactory(
            plan=plan(PlanCode.FOUNDING)
        )
        self.user = self.subscription.account

    def payment(self, rail, initiated=D(2026, 8, 3)):
        return PaymentFactory(
            user=self.user, rail=rail, initiated_date=initiated
        )

    def before_cutoff(self, day=D(2026, 8, 3)):
        """9am Eastern on the send date."""
        return dt.datetime(
            day.year, day.month, day.day, 9, tzinfo=EASTERN
        )

    def after_cutoff(self, day=D(2026, 8, 3)):
        """One minute past the 11:59pm Eastern cutoff.

        Built in Eastern deliberately: constructing it in UTC makes "23:59"
        four hours *before* the real cutoff, which silently turns this into a
        before-cutoff test.
        """
        return cutoff_datetime_et(day) + dt.timedelta(minutes=1)

    def test_standard_ach_is_free(self):
        fee = self.service.charge_for_payment(
            subscription=self.subscription,
            payment=self.payment(PaymentRail.ACH_STANDARD),
        )

        self.assertIsNone(fee)
        self.assertEqual(FeeCharge.objects.count(), 0)

    def test_same_day_before_cutoff_charges_4_99(self):
        fee = self.service.charge_for_payment(
            subscription=self.subscription,
            payment=self.payment(PaymentRail.ACH_SAMEDAY),
            now=self.before_cutoff(),
        )

        self.assertEqual(fee.kind, FeeKind.SAME_DAY_ACH)
        self.assertEqual(fee.amount, Decimal("4.99"))

    def test_same_day_after_cutoff_creates_no_fee_row(self):
        """After cutoff same-day is not offered, so nothing is sold."""
        fee = self.service.charge_for_payment(
            subscription=self.subscription,
            payment=self.payment(PaymentRail.ACH_SAMEDAY),
            now=self.after_cutoff(),
        )

        self.assertIsNone(fee)
        self.assertEqual(FeeCharge.objects.count(), 0)

    def test_expedited_check_charges_8_99_on_any_plan(self):
        fee = self.service.charge_for_payment(
            subscription=self.subscription,
            payment=self.payment(PaymentRail.CHECK),
            expedited=True,
        )

        self.assertEqual(fee.kind, FeeKind.EXPEDITED_CHECK)
        self.assertEqual(fee.amount, Decimal("8.99"))

    def test_checks_inside_the_allotment_are_free(self):
        for _ in range(2):
            fee = self.service.charge_for_payment(
                subscription=self.subscription,
                payment=self.payment(PaymentRail.CHECK),
            )
            self.assertIsNone(fee)

    def test_the_check_past_the_allotment_charges_2_99(self):
        for _ in range(2):
            self.service.charge_for_payment(
                subscription=self.subscription,
                payment=self.payment(PaymentRail.CHECK),
            )

        fee = self.service.charge_for_payment(
            subscription=self.subscription,
            payment=self.payment(PaymentRail.CHECK),
        )

        self.assertEqual(fee.kind, FeeKind.CHECK_OVERAGE)
        self.assertEqual(fee.amount, Decimal("2.99"))

    def test_standard_gets_five_free_checks(self):
        subscription = SubscriptionFactory(plan=plan(PlanCode.STANDARD))

        for _ in range(5):
            self.assertIsNone(
                self.service.charge_for_payment(
                    subscription=subscription,
                    payment=self.payment(PaymentRail.CHECK),
                )
            )

        self.assertIsNotNone(
            self.service.charge_for_payment(
                subscription=subscription,
                payment=self.payment(PaymentRail.CHECK),
            )
        )

    def test_a_fee_links_to_its_payment(self):
        payment = self.payment(PaymentRail.ACH_SAMEDAY)

        fee = self.service.charge_for_payment(
            subscription=self.subscription,
            payment=payment,
            now=self.before_cutoff(),
        )

        self.assertEqual(fee.payment_id, payment.id)

    def test_a_retry_does_not_double_charge_one_payment(self):
        payment = self.payment(PaymentRail.ACH_SAMEDAY)

        first = self.service.charge_for_payment(
            subscription=self.subscription, payment=payment,
            now=self.before_cutoff(),
        )
        second = self.service.charge_for_payment(
            subscription=self.subscription, payment=payment,
            now=self.before_cutoff(),
        )

        self.assertEqual(first.id, second.id)
        self.assertEqual(FeeCharge.objects.filter(payment=payment).count(), 1)

    def test_the_amounts_are_exactly_the_brd_numbers(self):
        self.assertEqual(FEE_AMOUNTS[FeeKind.SAME_DAY_ACH], Decimal("4.99"))
        self.assertEqual(
            FEE_AMOUNTS[FeeKind.EXPEDITED_CHECK], Decimal("8.99")
        )
        self.assertEqual(FEE_AMOUNTS[FeeKind.CHECK_OVERAGE], Decimal("2.99"))


class GuaranteeRefundTests(TestCase):

    def setUp(self):
        self.service = FeeService()
        self.subscription = SubscriptionFactory(
            plan=plan(PlanCode.STANDARD)
        )
        self.user = self.subscription.account

    def charged(self, kind=FeeKind.SAME_DAY_ACH, guaranteed=D(2026, 8, 5)):
        payment = PaymentFactory(user=self.user, rail=PaymentRail.ACH_SAMEDAY)

        return FeeCharge.objects.create(
            subscription=self.subscription,
            payment=payment,
            kind=kind,
            amount=FEE_AMOUNTS[kind],
            guaranteed_arrival=guaranteed,
        )

    def test_a_missed_guarantee_is_refunded(self):
        fee = self.charged()

        refunded = self.service.settle_guarantee(
            payment=fee.payment, actual_arrival=D(2026, 8, 7)
        )

        fee.refresh_from_db()
        self.assertEqual(len(refunded), 1)
        self.assertEqual(fee.state, FeeState.REFUNDED)
        self.assertIsNotNone(fee.refunded_at)

    def test_a_met_guarantee_is_not_refunded(self):
        fee = self.charged()

        refunded = self.service.settle_guarantee(
            payment=fee.payment, actual_arrival=D(2026, 8, 5)
        )

        fee.refresh_from_db()
        self.assertEqual(refunded, [])
        self.assertEqual(fee.state, FeeState.PENDING)

    def test_arriving_early_is_not_a_miss(self):
        fee = self.charged()

        self.service.settle_guarantee(
            payment=fee.payment, actual_arrival=D(2026, 8, 4)
        )

        fee.refresh_from_db()
        self.assertEqual(fee.state, FeeState.PENDING)

    def test_a_refund_happens_at_most_once(self):
        fee = self.charged()

        self.service.refund(fee)
        first_at = FeeCharge.objects.get(pk=fee.pk).refunded_at

        self.service.refund(fee)
        second_at = FeeCharge.objects.get(pk=fee.pk).refunded_at

        self.assertEqual(first_at, second_at)

    def test_a_refund_notifies_the_customer(self):
        from apps.notifications.models import Notification

        fee = self.charged()

        self.service.settle_guarantee(
            payment=fee.payment, actual_arrival=D(2026, 8, 9)
        )

        self.assertTrue(
            Notification.objects.filter(title__icontains="refunded").exists()
        )

    def test_a_check_overage_is_never_refunded_for_slowness(self):
        """It buys no speed promise, so there is nothing to miss."""
        fee = self.charged(kind=FeeKind.CHECK_OVERAGE, guaranteed=None)

        refunded = self.service.settle_guarantee(
            payment=fee.payment, actual_arrival=D(2027, 1, 1)
        )

        fee.refresh_from_db()
        self.assertEqual(refunded, [])
        self.assertEqual(fee.state, FeeState.PENDING)

    def test_every_missed_guarantee_is_measurable_from_the_ledger(self):
        """The success metric is a query, not a spreadsheet (E9-S4 AC)."""
        missed = self.charged()
        met = self.charged()

        self.service.settle_guarantee(
            payment=missed.payment, actual_arrival=D(2026, 8, 9)
        )
        self.service.settle_guarantee(
            payment=met.payment, actual_arrival=D(2026, 8, 5)
        )

        self.assertEqual(
            FeeCharge.objects.filter(state=FeeState.REFUNDED).count(), 1
        )


class AddOnTests(TestCase):

    def setUp(self):
        self.service = AddOnService()
        self.subscription = SubscriptionFactory(
            plan=plan(PlanCode.ENTERPRISE)
        )

    def test_add_ons_require_the_enterprise_plan(self):
        from rest_framework.exceptions import ValidationError

        standard = SubscriptionFactory(plan=plan(PlanCode.STANDARD))

        with self.assertRaises(ValidationError):
            self.service.set_addon(
                subscription=standard, kind=AddOnKind.ERP_SYNC
            )

    def test_each_add_on_uses_its_brd_rate(self):
        for kind, price in ADDON_PRICES.items():
            with self.subTest(kind=kind):
                addon = self.service.set_addon(
                    subscription=self.subscription, kind=kind
                )
                self.assertEqual(addon.unit_price, price)

    def test_quantity_zero_removes_an_add_on(self):
        self.service.set_addon(
            subscription=self.subscription, kind=AddOnKind.ERP_SYNC
        )

        self.assertIsNone(
            self.service.set_addon(
                subscription=self.subscription,
                kind=AddOnKind.ERP_SYNC,
                quantity=0,
            )
        )
        self.assertEqual(EnterpriseAddOn.objects.count(), 0)

    def test_entity_add_on_counts_only_beyond_the_included_three(self):
        cases = [(1, 0), (3, 0), (4, 1), (7, 4)]

        for entities, expected in cases:
            with self.subTest(entities=entities):
                self.assertEqual(
                    self.service.entity_addon_quantity(
                        self.subscription, entities
                    ),
                    expected,
                )

    def test_syncing_entities_keeps_the_line_in_step(self):
        self.service.sync_entity_addon(
            subscription=self.subscription, entity_count=6
        )

        addon = EnterpriseAddOn.objects.get(kind=AddOnKind.EXTRA_ENTITY)
        self.assertEqual(addon.quantity, 3)
        self.assertEqual(addon.line_total, Decimal("237.00"))

    def test_dropping_back_to_three_entities_removes_the_line(self):
        self.service.sync_entity_addon(
            subscription=self.subscription, entity_count=6
        )
        self.service.sync_entity_addon(
            subscription=self.subscription, entity_count=3
        )

        self.assertEqual(EnterpriseAddOn.objects.count(), 0)

    def test_a_signed_rate_is_not_repriced_by_a_later_change(self):
        addon = self.service.set_addon(
            subscription=self.subscription, kind=AddOnKind.ERP_SYNC
        )

        self.assertEqual(addon.unit_price, Decimal("149.00"))


class InvoicePreviewTests(TestCase):

    def setUp(self):
        self.service = AddOnService()
        self.subscription = SubscriptionFactory(
            plan=plan(PlanCode.ENTERPRISE)
        )

    def test_the_base_plan_is_a_line(self):
        invoice = self.service.invoice_preview(self.subscription)

        self.assertEqual(invoice["lines"][0]["kind"], "SUBSCRIPTION")
        self.assertEqual(invoice["subtotal"], Decimal("299.00"))

    def test_each_add_on_is_its_own_line(self):
        self.service.set_addon(
            subscription=self.subscription, kind=AddOnKind.ERP_SYNC
        )
        self.service.set_addon(
            subscription=self.subscription, kind=AddOnKind.CUSTOM_SLA
        )

        invoice = self.service.invoice_preview(self.subscription)
        kinds = [line["kind"] for line in invoice["lines"]]

        self.assertIn(AddOnKind.ERP_SYNC, kinds)
        self.assertIn(AddOnKind.CUSTOM_SLA, kinds)
        # 299 + 149 + 199
        self.assertEqual(invoice["subtotal"], Decimal("647.00"))

    def test_toggling_an_add_on_changes_the_total_deterministically(self):
        before = self.service.invoice_preview(self.subscription)["subtotal"]

        self.service.set_addon(
            subscription=self.subscription,
            kind=AddOnKind.APPROVAL_WORKFLOW,
        )
        added = self.service.invoice_preview(self.subscription)["subtotal"]

        self.service.set_addon(
            subscription=self.subscription,
            kind=AddOnKind.APPROVAL_WORKFLOW,
            quantity=0,
        )
        removed = self.service.invoice_preview(self.subscription)["subtotal"]

        self.assertEqual(added - before, Decimal("99.00"))
        self.assertEqual(removed, before)

    def test_fees_appear_as_lines(self):
        payment = PaymentFactory(user=self.subscription.account)

        FeeCharge.objects.create(
            subscription=self.subscription,
            payment=payment,
            kind=FeeKind.SAME_DAY_ACH,
            amount=Decimal("4.99"),
        )

        invoice = self.service.invoice_preview(self.subscription)

        self.assertEqual(invoice["subtotal"], Decimal("303.99"))

    def test_a_refunded_fee_shows_at_zero_rather_than_vanishing(self):
        """The invoice should still show the guarantee was honoured."""
        payment = PaymentFactory(user=self.subscription.account)

        FeeCharge.objects.create(
            subscription=self.subscription,
            payment=payment,
            kind=FeeKind.SAME_DAY_ACH,
            amount=Decimal("4.99"),
            state=FeeState.REFUNDED,
        )

        invoice = self.service.invoice_preview(self.subscription)
        fee_line = [
            line for line in invoice["lines"]
            if line["kind"] == FeeKind.SAME_DAY_ACH
        ][0]

        self.assertEqual(fee_line["total"], Decimal("0.00"))
        self.assertIn("refunded", fee_line["description"])
        self.assertEqual(invoice["subtotal"], Decimal("299.00"))
