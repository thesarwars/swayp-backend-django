from django.db import models


class VendorStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    DELETED = "DELETED", "Deleted"


class VendorSource(models.TextChoices):
    DIRECTORY = "DIRECTORY", "Directory Search"
    QR = "QR", "QR Scan"
    MANUAL = "MANUAL", "Manual"


class VendorPaymentMethodType(models.TextChoices):
    NETWORK = "NETWORK", "Network"
    ACH = "ACH", "ACH"
    CHECK = "CHECK", "Check"


class BankAccountType(models.TextChoices):
    CHECKING = "CHECKING", "Checking"
    SAVINGS = "SAVINGS", "Savings"