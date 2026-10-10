"""Reading and updating the account's own profile.

Registration collects a full name, address and — for a business — the trading
name, point of contact and billing address. Until now nothing could change any
of it, so a typo in a business name was permanent and a company that moved
office had no way to say so. That matters beyond tidiness: the billing address
is what appears on the invoice.

The profile shape depends on ``account_type``, and the branch rows are created
lazily rather than assumed. An account registered before the branch models
existed, or one whose registration half-failed, still has to be able to open
its own settings screen.
"""

from django.db import transaction

from apps.users.models.business_profile import BusinessProfile
from apps.users.models.individual_profile import IndividualProfile
from apps.users.models.profile import AccountType, Profile

#: Fields the account may change about itself. Deliberately excludes email and
#: phone: both are login identifiers and both are verified by OTP, so changing
#: one is an authentication flow rather than a profile edit.
PROFILE_FIELDS = ("full_name", "address")
BUSINESS_FIELDS = (
    "business_name",
    "poc_name",
    "billing_address",
    # Onboarding Step 1 and the Create Account screen. Registration no
    # longer demands these, so this is where they actually get set.
    "industry",
    "business_size",
    "trading_name",
    "business_type",
    "website",
    "ein",
)
INDIVIDUAL_FIELDS = ("billing_address",)


class ProfileService:

    def get_or_create_profile(self, user):
        profile, _ = Profile.objects.get_or_create(
            user=user,
            defaults={
                "account_type": AccountType.INDIVIDUAL,
                "full_name": (
                    f"{user.first_name} {user.last_name}".strip()
                    or user.email
                ),
            },
        )

        return profile

    def branch(self, profile):
        """The account-type-specific row, created if absent.

        Lazily, for the same reason the owner's team seat is: a data migration
        would have to invent values it does not have, and an account that
        cannot open its own settings screen is worse than an empty one.
        """
        if profile.account_type == AccountType.BUSINESS:
            branch, _ = BusinessProfile.objects.get_or_create(
                profile=profile,
                defaults={
                    "business_name": "",
                    "poc_name": "",
                    "billing_address": "",
                },
            )

            return branch

        branch, _ = IndividualProfile.objects.get_or_create(
            profile=profile, defaults={"billing_address": ""}
        )

        return branch

    def read(self, user):
        profile = self.get_or_create_profile(user)
        branch = self.branch(profile)

        data = {
            "id": user.id,
            "account_type": profile.account_type,
            "email": user.email,
            "phone_number": user.phone_number,
            "is_verified": user.is_verified,
            "full_name": profile.full_name,
            "address": profile.address or "",
            "billing_address": branch.billing_address or "",
            # Present but null for an individual, rather than absent: a client
            # rendering one form for both should not have to branch on the
            # existence of a key.
            "business_name": getattr(branch, "business_name", None),
            "poc_name": getattr(branch, "poc_name", None),
            "industry": getattr(branch, "industry", None),
            "business_size": getattr(branch, "business_size", None),
            "trading_name": getattr(branch, "trading_name", None),
            "business_type": getattr(branch, "business_type", None),
            "website": getattr(branch, "website", None),
            "ein": getattr(branch, "ein", None),
        }

        return data

    @transaction.atomic
    def update(self, user, data):
        """Apply a partial update. Unknown and unpermitted keys are ignored.

        Ignored rather than rejected because the serializer has already
        decided what is writable; anything else reaching here is a client
        sending extra keys, which is not worth failing a save over.
        """
        profile = self.get_or_create_profile(user)
        branch = self.branch(profile)

        changed = [f for f in PROFILE_FIELDS if f in data]

        for field in changed:
            setattr(profile, field, data[field])

        if changed:
            profile.save(update_fields=changed + ["updated_at"])

        allowed = (
            BUSINESS_FIELDS
            if profile.account_type == AccountType.BUSINESS
            else INDIVIDUAL_FIELDS
        )
        branch_changed = [f for f in allowed if f in data]

        for field in branch_changed:
            setattr(branch, field, data[field])

        if branch_changed:
            branch.save(update_fields=branch_changed + ["updated_at"])

        # Keep the User row in step so anything reading first_name/last_name —
        # the Stripe customer, the dashboard greeting — does not disagree with
        # the profile the customer just edited.
        if "full_name" in data:
            parts = (data["full_name"] or "").strip().split(" ", 1)
            user.first_name = parts[0][:150] if parts else ""
            user.last_name = parts[1][:150] if len(parts) > 1 else ""
            user.save(update_fields=["first_name", "last_name"])

        return self.read(user)
