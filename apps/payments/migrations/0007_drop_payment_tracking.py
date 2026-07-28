"""Drop payment_tracking (E6-S10).

PaymentStage replaces it. Tracking only ever held a single status per payment,
so it could not render the ordered checklist the processing drawer needs — the
two would have had to be kept in sync for no benefit.

Raw SQL because ``apps.payment_tracking`` has been removed from INSTALLED_APPS
and Django no longer has model state to delete.
"""

from django.db import migrations

#: See 0006 — Postgres syntax, and a no-op on a backend where the table never
#: existed.
_POSTGRES = "postgresql"


def _run(sql):
    def operation(apps, schema_editor):
        if schema_editor.connection.vendor != _POSTGRES:
            return

        schema_editor.execute(sql)

    return operation


DROP = """
DROP TABLE IF EXISTS payment_tracking CASCADE;
DELETE FROM django_migrations WHERE app = 'payment_tracking';
"""

RECREATE = """
CREATE TABLE IF NOT EXISTS payment_tracking (
    id uuid PRIMARY KEY,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    status varchar(20) NOT NULL,
    estimated_completion timestamptz,
    payment_id uuid NOT NULL UNIQUE REFERENCES payments(id) DEFERRABLE INITIALLY DEFERRED
);
"""


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0006_drop_wallet_tables"),
    ]

    operations = [
        migrations.RunPython(_run(DROP), _run(RECREATE)),
    ]
