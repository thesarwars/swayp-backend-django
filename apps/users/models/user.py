from django.contrib.auth.models import (
    AbstractBaseUser,
    PermissionsMixin,
)
from django.contrib.auth.base_user import BaseUserManager
from django.db import models
from django.db.models.functions import Lower

from apps.common.models import BaseModel


class UserManager(BaseUserManager):

    @classmethod
    def normalize_email(cls, email):
        """The whole address lowercased (SEC-5), not only the domain as
        Django does: Jane@acme.com and jane@acme.com are one inbox, so they
        must be one account."""
        return (email or "").strip().lower()

    def get_by_natural_key(self, username):
        # Sign-in matches whatever case was typed.
        return self.get(**{f"{self.model.USERNAME_FIELD}__iexact": username})

    def create_user(
        self,
        email,
        password=None,
        **extra_fields,
    ):

        if not email:
            raise ValueError("Email is required")

        email = self.normalize_email(email)

        user = self.model(
            email=email,
            **extra_fields,
        )

        user.set_password(password)

        user.save(using=self._db)

        return user

    def create_superuser(
        self,
        email,
        password,
        **extra_fields,
    ):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("is_verified", True)

        return self.create_user(
            email,
            password,
            **extra_fields,
        )


class User(
    AbstractBaseUser,
    PermissionsMixin,
    BaseModel,
):
    
    first_name = models.CharField(
        max_length=100,
        blank=True,
    )

    last_name = models.CharField(
        max_length=100,
        blank=True,
    )
    email = models.EmailField(
        unique=True,
        db_index=True,
    )

    phone_number = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
    )

    is_active = models.BooleanField(
        default=False,
    )

    is_staff = models.BooleanField(
        default=False,
    )

    is_verified = models.BooleanField(default=False,)
    failed_login_attempts = models.PositiveIntegerField(
        default=0,
    )

    locked_until = models.DateTimeField(
        null=True,
        blank=True,
    )

    last_login_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
    )

    # Google's stable id for the person ("sub"), set on the first Google
    # sign-in. Matched before the email, because a Google account's email can
    # change and the sub cannot. Null for anyone who never used Google.
    google_sub = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
    )

    USERNAME_FIELD = "email"

    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        db_table = "users"
        constraints = [
            # unique=True on the column compares exactly, so Jane@ and jane@
            # could both be stored (admin, a script). This compares them as
            # the same address.
            models.UniqueConstraint(
                Lower("email"), name="uniq_user_email_ci"
            ),
        ]

    def save(self, *args, **kwargs):
        # Every path that writes a user, the admin included, stores the
        # address lowercased.
        if self.email:
            self.email = UserManager.normalize_email(self.email)

        super().save(*args, **kwargs)

    def __str__(self):
        return self.email
    
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self):
        return self.first_name or self.email