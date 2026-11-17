"""Create the Stripe Customer Portal configuration, versioned here rather
than clicked together in the dashboard.

Card, invoices and cancel at period end; no plan changes, because the
portal cannot run Swayp's "does the account fit the smaller plan" check.
Prints the id to set as STRIPE_PORTAL_CONFIGURATION_ID.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create the Stripe Customer Portal configuration."

    def handle(self, *args, **options):
        if not settings.STRIPE_SECRET_KEY:
            raise CommandError("STRIPE_SECRET_KEY is not set.")

        import stripe

        client = stripe.StripeClient(settings.STRIPE_SECRET_KEY)
        frontend = settings.FRONTEND_URL.rstrip("/")

        configuration = client.v1.billing_portal.configurations.create(
            params={
                "business_profile": {
                    "headline": "Manage your Swayp plan",
                    "privacy_policy_url": f"{frontend}/privacy",
                    "terms_of_service_url": f"{frontend}/terms",
                },
                "default_return_url": f"{frontend}/settings/billing",
                "features": {
                    "payment_method_update": {"enabled": True},
                    "invoice_history": {"enabled": True},
                    "customer_update": {
                        "enabled": True,
                        "allowed_updates": ["email", "address", "tax_id"],
                    },
                    "subscription_cancel": {
                        "enabled": True,
                        "mode": "at_period_end",
                        "cancellation_reason": {
                            "enabled": True,
                            "options": [
                                "too_expensive",
                                "missing_features",
                                "switched_service",
                                "unused",
                                "other",
                            ],
                        },
                    },
                    "subscription_update": {"enabled": False},
                },
            }
        )

        self.stdout.write(
            f"STRIPE_PORTAL_CONFIGURATION_ID={configuration['id']}"
        )
