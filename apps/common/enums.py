from django.db import models


class PaymentStatus(models.TextChoices):
    SCHEDULED = "SCHEDULED", "Scheduled"
    PENDING = "PENDING", "Pending"
    PROCESSING = "PROCESSING", "Processing"
    SUCCESSFUL = "SUCCESSFUL", "Successful"
    FAILED = "FAILED", "Failed"
    CANCELLED = "CANCELLED", "Cancelled"
    REFUNDED = "REFUNDED", "Refunded"
    RETURNED = "RETURNED", "Returned"


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


class TransactionType(models.TextChoices):
    DEPOSIT = "DEPOSIT", "Deposit"
    WITHDRAW = "WITHDRAW", "Withdraw"
    PAYMENT = "PAYMENT", "Payment"
    REFUND = "REFUND", "Refund"
    CASHBACK = "CASHBACK", "Cashback"
    REWARD = "REWARD", "Reward"


# --- Money-movement vocabulary (E1-S3) ---


class PaymentRail(models.TextChoices):
    ACH_STANDARD = "ACH_STANDARD", "ACH Standard"
    ACH_SAMEDAY = "ACH_SAMEDAY", "ACH Same-Day"
    NETWORK = "NETWORK", "Network"
    CHECK = "CHECK", "Check"


class PaymentProcessor(models.TextChoices):
    # STRIPE = configured-account vendors, MOOV = ACH, LOB = checks (BRD §5).
    # Dwolla / GoCardless / Stripe-Treasury are excluded on record.
    MOCK = "MOCK", "Mock"
    STRIPE = "STRIPE", "Stripe"
    MOOV = "MOOV", "Moov"
    LOB = "LOB", "Lob"


class BillFrequency(models.TextChoices):
    MONTHLY = "MONTHLY", "Monthly"
    QUARTERLY = "QUARTERLY", "Quarterly"
    WEEKLY = "WEEKLY", "Weekly"
    ONE_TIME = "ONE_TIME", "One-time"


class BillOccurrenceStatus(models.TextChoices):
    UPCOMING = "UPCOMING", "Upcoming"
    DUE = "DUE", "Due"
    OVERDUE = "OVERDUE", "Overdue"
    SCHEDULED = "SCHEDULED", "Scheduled"
    PAID = "PAID", "Paid"


class AutopayMode(models.TextChoices):
    AUTO = "AUTO", "Auto-pay"
    REMIND = "REMIND", "Remind me"


class VendorPaymentMethodType(models.TextChoices):
    NETWORK = "NETWORK", "Network"
    ACH = "ACH", "ACH"
    CHECK = "CHECK", "Check"


class VendorSource(models.TextChoices):
    DIRECTORY = "DIRECTORY", "Directory"
    QR = "QR", "QR"
    MANUAL = "MANUAL", "Manual"
    IMPORT = "IMPORT", "Import"


class BankAccountType(models.TextChoices):
    CHECKING = "CHECKING", "Checking"
    SAVINGS = "SAVINGS", "Savings"


class PaymentStageStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    RUNNING = "RUNNING", "Running"
    DONE = "DONE", "Done"
    FAILED = "FAILED", "Failed"


class ScanStatus(models.TextChoices):
    RUNNING = "RUNNING", "Running"
    DONE = "DONE", "Done"
    FAILED = "FAILED", "Failed"


class VendorStatus(models.TextChoices):
    ACTIVE="ACTIVE","Active"
    INACTIVE="INACTIVE","Inactive"
    # Soft delete (E3-S5). Vendors are never hard-deleted: payment history
    # references them, so the row survives and drops out of every list.
    DELETED="DELETED","Deleted"

# new added
class BillType(models.TextChoices):
    FIXED = "FIXED", "Fixed"
    VARIABLE = "VARIABLE", "Variable"


class BillSource(models.TextChoices):
    MANUAL = "MANUAL", "Manual"
    QR = "QR", "QR Scan"
    DETECTED = "DETECTED", "Detected"