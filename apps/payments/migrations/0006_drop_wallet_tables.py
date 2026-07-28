"""Drop the stored-balance subsystem (E6-S11).

BRD §4 is non-custodial: no code path may let funds rest in a Swayp-controlled
balance. The wallet did exactly that — ``payment_service`` debited
``Wallet.balance`` on create and credited it back on failure — so once
execution moved to the licensed providers the tables became both unused and
forbidden.

Raw SQL rather than DeleteModel because ``apps.wallet`` has been removed from
INSTALLED_APPS, so Django no longer has model state to delete. ``wallets`` is
dropped after ``wallet_transactions`` because the latter references it.

Reverse recreates the tables so the migration is testable both ways. It
restores the shape, not the data — the balances are gone by design.
"""

from django.db import migrations

#: ``CASCADE`` and the recreate body are Postgres syntax. On any other backend
#: — a sqlite test database, say — these tables never existed in the first
#: place, so the drop is a no-op by definition rather than something to
#: translate. The Postgres path is unchanged.
_POSTGRES = "postgresql"


def _run(sql):
    def operation(apps, schema_editor):
        if schema_editor.connection.vendor != _POSTGRES:
            return

        schema_editor.execute(sql)

    return operation


DROP = """
DROP TABLE IF EXISTS wallet_transactions CASCADE;
DROP TABLE IF EXISTS wallets CASCADE;
DELETE FROM django_migrations WHERE app = 'wallet';
"""

RECREATE = """
CREATE TABLE IF NOT EXISTS wallets (
    id uuid PRIMARY KEY,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    balance numeric(18, 2) NOT NULL,
    currency varchar(10) NOT NULL,
    reward_points integer NOT NULL,
    cashback numeric(18, 2) NOT NULL,
    status varchar(20) NOT NULL,
    is_balance_hidden boolean NOT NULL,
    user_id uuid NOT NULL UNIQUE REFERENCES users(id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE IF NOT EXISTS wallet_transactions (
    id uuid PRIMARY KEY,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    amount numeric(18, 2) NOT NULL,
    balance_before numeric(18, 2) NOT NULL,
    balance_after numeric(18, 2) NOT NULL,
    transaction_type varchar(30) NOT NULL,
    status varchar(20) NOT NULL,
    reference varchar(100) NOT NULL UNIQUE,
    description text NOT NULL,
    wallet_id uuid NOT NULL REFERENCES wallets(id) DEFERRABLE INITIALLY DEFERRED,
    payment_id uuid UNIQUE REFERENCES payments(id) DEFERRABLE INITIALLY DEFERRED
);
"""


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0005_paymentstage_webhookevent_and_more"),
    ]

    operations = [
        migrations.RunPython(_run(DROP), _run(RECREATE)),
    ]
