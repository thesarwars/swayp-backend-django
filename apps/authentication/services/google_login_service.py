from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.authentication.services.login_service import LoginService
from apps.users.models import (
    AccountType,
    BusinessProfile,
    IndividualProfile,
    Profile,
)
from apps.common.error_codes import ACCOUNT_INACTIVE

User = get_user_model()


class GoogleLoginService:
    """Sign in with a verified Google identity, creating the account if new.

    Matched by Google's sub first, then by email. An existing password
    account with the same email is linked rather than duplicated: Google has
    verified that the person holds the address, which is the same proof the
    registration code asks for. A new account has no usable password; forgot
    password sets one if they ever want it.
    """

    @staticmethod
    @transaction.atomic
    def login(
        *,
        claims,
        request,
        account_type=AccountType.BUSINESS,
        terms_accepted=False,
        marketing_opt_in=False,
        signatory_confirmed=False,
    ):
        sub = claims["sub"]
        email = claims["email"].lower().strip()

        user = User.objects.select_for_update().filter(google_sub=sub).first()

        if user is None:
            user = (
                User.objects.select_for_update()
                .filter(email__iexact=email)
                .first()
            )

            if user is not None and user.google_sub:
                # The email is someone's, already tied to another Google
                # account. Re-pointing it would hand that account over.
                raise ValidationError(
                    {
                        "id_token": (
                            "This email is linked to a different Google "
                            "account."
                        )
                    }
                )

        created = user is None

        if created:
            user = GoogleLoginService._create(
                claims=claims,
                email=email,
                account_type=account_type,
                terms_accepted=terms_accepted,
                marketing_opt_in=marketing_opt_in,
                signatory_confirmed=signatory_confirmed,
            )
        else:
            GoogleLoginService._link(user, sub)

        tokens = LoginService.sign_in(user, request)

        return {**tokens, "is_new_user": created}

    @staticmethod
    def _link(user, sub):
        if user.is_verified and not user.is_active:
            # Verified once and switched off since: deactivated, not pending.
            raise ValidationError(
                {"detail": "Account is inactive."}, code=ACCOUNT_INACTIVE
            )

        fields = []

        if user.google_sub != sub:
            user.google_sub = sub
            fields.append("google_sub")

        if not user.is_verified:
            # A signup that never entered its code. Google has just proved
            # the email, so the code has nothing left to prove.
            user.is_verified = True
            user.is_active = True
            fields += ["is_verified", "is_active"]

        if fields:
            user.save(update_fields=fields)

    @staticmethod
    def _create(*, claims, email, account_type, terms_accepted,
                marketing_opt_in, signatory_confirmed=False):
        first = (claims.get("given_name") or "")[:150]
        last = (claims.get("family_name") or "")[:150]
        full_name = (
            claims.get("name")
            or f"{first} {last}".strip()
            or email.split("@")[0]
        )

        user = User.objects.create_user(
            email=email,
            password=None,
            first_name=first,
            last_name=last,
            google_sub=claims["sub"],
            is_active=True,
            is_verified=True,
        )

        now = timezone.now()

        profile = Profile.objects.create(
            user=user,
            account_type=account_type,
            full_name=full_name,
            terms_accepted_at=now if terms_accepted else None,
            signatory_confirmed_at=now if signatory_confirmed else None,
            marketing_opt_in=marketing_opt_in,
        )

        # Empty on purpose: onboarding step 1 asks for the business name
        # when it is blank, so a Google signup lands there.
        if account_type == AccountType.BUSINESS:
            BusinessProfile.objects.create(profile=profile, poc_name=full_name)
        else:
            IndividualProfile.objects.create(profile=profile)

        return user
