from django.db import models


class WalletStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    FROZEN = "FROZEN", "Frozen"
    SUSPENDED = "SUSPENDED", "Suspended"


class PaymentStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PROCESSING = "PROCESSING", "Processing"
    SUCCESSFUL = "SUCCESSFUL", "Successful"
    FAILED = "FAILED", "Failed"
    CANCELLED = "CANCELLED", "Cancelled"
    REFUNDED = "REFUNDED", "Refunded"


class NotificationType(models.TextChoices):
    SYSTEM = "SYSTEM", "System"
    PAYMENT = "PAYMENT", "Payment"
    PROMOTION = "PROMOTION", "Promotion"
    SECURITY = "SECURITY", "Security"


class ProviderStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"


class Currency(models.TextChoices):
    BDT = "BDT", "Bangladeshi Taka"
    USD = "USD", "US Dollar"
    EUR = "EUR", "Euro"