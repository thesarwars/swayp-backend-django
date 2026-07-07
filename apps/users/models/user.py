from django.contrib.auth.models import (
    AbstractBaseUser,
    PermissionsMixin,
)
from django.contrib.auth.base_user import BaseUserManager
from django.db import models

from apps.common.models import BaseModel


class UserManager(BaseUserManager):

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
        db_index=True,
    )

    is_active = models.BooleanField(
        default=False,
    )

    is_staff = models.BooleanField(
        default=False,
    )

    is_verified = models.BooleanField(
        default=False,
    )

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

    USERNAME_FIELD = "email"

    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        db_table = "users"

    def __str__(self):
        return self.email
    
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self):
        return self.first_name or self.email