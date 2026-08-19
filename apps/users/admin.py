"""Admin for the users app.

``User`` goes through ``django.contrib.auth.admin.UserAdmin`` rather than a
plain ``ModelAdmin``, which is not a style preference. A plain ModelAdmin
renders ``password`` as an ordinary text field showing the stored hash, and
saving the form writes whatever is in that box back as the password in clear —
one visit to a user's page is enough to destroy the account. UserAdmin supplies
the read-only hash widget, the separate change-password form, and an add form
that hashes what it is given.

Its defaults are all keyed on ``username``, which this model does not have, so
every fieldset, the ordering and the search are restated against ``email``.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils import timezone

from apps.users.models import (
    AccountType,
    BusinessProfile,
    IndividualProfile,
    Profile,
    User,
)


class ProfileInline(admin.StackedInline):
    """The profile is created with the user and never separately."""

    model = Profile
    can_delete = False
    extra = 0

    fields = (
        "account_type",
        "full_name",
        "address",
        "terms_accepted_at",
        "signatory_confirmed_at",
        "marketing_opt_in",
        "onboarding_bank_skipped",
    )

    # Legal artifacts, not settings. When the terms were accepted has to stay
    # answerable later, and a timestamp an operator can retype answers nothing.
    readonly_fields = (
        "terms_accepted_at",
        "signatory_confirmed_at",
    )


@admin.register(User)
class UserAdmin(DjangoUserAdmin):

    list_display = (
        "email",
        "get_full_name",
        "phone_number",
        "is_active",
        "is_verified",
        "is_staff",
        "is_locked",
        "created_at",
    )

    list_filter = (
        "is_active",
        "is_verified",
        "is_staff",
        "is_superuser",
        "groups",
    )

    search_fields = (
        "email",
        "first_name",
        "last_name",
        "phone_number",
    )

    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    filter_horizontal = ("groups", "user_permissions")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Personal info",
            {"fields": ("first_name", "last_name", "phone_number")},
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_verified",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            # Left editable: clearing a lockout is the support request this
            # page exists to answer, and the alternative is waiting out the
            # window or a shell.
            "Login security",
            {"fields": ("failed_login_attempts", "locked_until", "last_login_ip")},
        ),
        (
            "Important dates",
            {"fields": ("last_login", "created_at", "updated_at")},
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "usable_password",
                    "password1",
                    "password2",
                ),
            },
        ),
    )

    readonly_fields = (
        "last_login",
        "created_at",
        "updated_at",
    )

    inlines = [ProfileInline]

    def get_inlines(self, request, obj=None):
        """No profile form on the add page.

        The profile is written by RegistrationService alongside the user, so a
        blank inline here would ask an operator to invent an account type and a
        full name for a row that does not exist yet.
        """
        if obj is None:
            return []

        return super().get_inlines(request, obj)

    @admin.display(description="Name", ordering="first_name")
    def get_full_name(self, obj):
        return obj.get_full_name() or "—"

    @admin.display(boolean=True, description="Locked")
    def is_locked(self, obj):
        return obj.locked_until is not None and obj.locked_until > timezone.now()


class BusinessProfileInline(admin.StackedInline):
    model = BusinessProfile
    can_delete = False
    extra = 0


class IndividualProfileInline(admin.StackedInline):
    model = IndividualProfile
    can_delete = False
    extra = 0


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):

    list_display = (
        "user",
        "account_type",
        "full_name",
        "marketing_opt_in",
        "onboarding_bank_skipped",
        "created_at",
    )

    list_filter = (
        "account_type",
        "marketing_opt_in",
        "onboarding_bank_skipped",
    )

    search_fields = (
        "full_name",
        "user__email",
    )

    ordering = ("-created_at",)
    list_select_related = ("user",)

    readonly_fields = (
        "terms_accepted_at",
        "signatory_confirmed_at",
        "created_at",
        "updated_at",
    )

    def get_inlines(self, request, obj=None):
        """Only the sub-profile the account type actually has.

        Showing both would offer an operator a blank business form on an
        individual account, and saving it creates a row the application never
        reads and the serializers do not expect.
        """
        if obj is None:
            return []

        if obj.account_type == AccountType.BUSINESS:
            return [BusinessProfileInline]

        return [IndividualProfileInline]


@admin.register(BusinessProfile)
class BusinessProfileAdmin(admin.ModelAdmin):

    list_display = (
        "business_name",
        "profile",
        "industry",
        "business_size",
        "ein",
        "created_at",
    )

    list_filter = (
        "industry",
        "business_size",
        "business_type",
    )

    search_fields = (
        "business_name",
        "trading_name",
        "ein",
        "profile__user__email",
    )

    ordering = ("-created_at",)
    list_select_related = ("profile__user",)

    readonly_fields = ("created_at", "updated_at")


@admin.register(IndividualProfile)
class IndividualProfileAdmin(admin.ModelAdmin):

    list_display = (
        "profile",
        "created_at",
    )

    search_fields = ("profile__user__email",)

    ordering = ("-created_at",)
    list_select_related = ("profile__user",)

    readonly_fields = ("created_at", "updated_at")
