"""Trial support: a per-plan free period, and the date it ends.

The schema change alone would leave every existing plan at the field default
of zero, Standard included — a database that had already run the seed would
silently offer no trial while PLAN_SPECS said fourteen days. The data step
re-applies the spec so the seed stays the single source of truth.
"""

from django.db import migrations, models


def apply_trial_days(apps, schema_editor):
    from apps.billing.models.plan import PLAN_SPECS

    Plan = apps.get_model("billing", "Plan")

    for code, spec in PLAN_SPECS.items():
        Plan.objects.filter(code=code).update(
            trial_days=spec.get("trial_days", 0)
        )


def clear_trial_days(apps, schema_editor):
    # Only resets the values; the column itself goes with the reverse of the
    # AddField below. Keeps a re-apply clean rather than leaving stale days.
    Plan = apps.get_model("billing", "Plan")
    Plan.objects.update(trial_days=0)


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0003_plan_provider_price_id_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="plan",
            name="trial_days",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="subscription",
            name="trial_end",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.RunPython(apply_trial_days, clear_trial_days),
    ]
