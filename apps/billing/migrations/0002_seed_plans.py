"""Seed the three plans with the BRD §6.2 numbers (E9-S1).

Pricing is fixed by the CEO, so it is seeded rather than left to be typed into
an admin form where a typo silently becomes revenue. The values are read from
``PLAN_SPECS`` so the model, the seed and the tests cannot disagree.

Forward is idempotent: it updates an existing plan rather than failing, so a
re-run after a partial deploy converges. Reverse deletes only untouched
plans — a plan with subscriptions attached is left alone rather than taking
live customers down with it.
"""

from django.db import migrations


def seed_plans(apps, schema_editor):
    from apps.billing.models.plan import PLAN_SPECS

    Plan = apps.get_model("billing", "Plan")

    # PLAN_SPECS is the live constant and it grows: trial_days was added
    # later, and passing it to this migration's historical model — which has
    # no such column — raised FieldError on every fresh database. Narrowing
    # to the fields that existed here keeps old migrations working as the
    # spec evolves, and the migration that adds a field backfills it.
    known = {f.name for f in Plan._meta.get_fields()}

    for code, spec in PLAN_SPECS.items():
        defaults = {k: v for k, v in spec.items() if k in known}
        Plan.objects.update_or_create(code=code, defaults=defaults)


def unseed_plans(apps, schema_editor):
    from apps.billing.models.plan import PLAN_SPECS

    Plan = apps.get_model("billing", "Plan")

    for code in PLAN_SPECS:
        plan = Plan.objects.filter(code=code).first()

        if plan is None:
            continue

        # PROTECT on Subscription.plan would raise anyway; skipping makes the
        # reverse migration usable on a database that has real customers.
        if plan.subscriptions.exists():
            continue

        plan.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_plans, unseed_plans),
    ]
