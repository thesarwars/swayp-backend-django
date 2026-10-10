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
    # E8-S3 typed events, appended so the generated choices list — and
    # therefore every migration that stores it — stays append-only. Both
    # columns that hold this vocabulary (notifications.type,
    # notification_preferences.type) are max_length=30, so they can never
    # disagree about what is storable.
    BILL_DUE = "BILL_DUE", "Bill due"
    PAYMENT_FAILED = "PAYMENT_FAILED", "Payment failed"
    PAYMENT_REVERSED = "PAYMENT_REVERSED", "Payment reversed"
    AUTOPAY_EXECUTED = "AUTOPAY_EXECUTED", "Autopay executed"
    PAYMENT_ARRIVED = "PAYMENT_ARRIVED", "Payment arrived"
    LATE_FEE_WARNING = "LATE_FEE_WARNING", "Late fee warning"


class NotificationCategory(models.TextChoices):
    """The chips on the notifications screen. A grouping of types, not a
    stored column — see NOTIFICATION_CATEGORY_TYPES."""

    TRANSACTIONS = "transactions", "Transactions"
    PROMOTION = "promotion", "Promotion"


#: Which types each chip shows. SYSTEM and SECURITY belong to neither chip and
#: only appear under "All". A new NotificationType must be placed here (or
#: deliberately left out), or it will silently never show under a chip.
NOTIFICATION_CATEGORY_TYPES = {
    NotificationCategory.TRANSACTIONS: (
        NotificationType.PAYMENT,
        NotificationType.BILL_DUE,
        NotificationType.PAYMENT_FAILED,
        NotificationType.PAYMENT_REVERSED,
        NotificationType.AUTOPAY_EXECUTED,
        NotificationType.PAYMENT_ARRIVED,
        NotificationType.LATE_FEE_WARNING,
    ),
    NotificationCategory.PROMOTION: (NotificationType.PROMOTION,),
}


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


# --- Commercial plans (BRD §6.2). E9 owns the Plan table; this enum is the
# vocabulary both sides agree on, so the E8-S2 entitlement gate can exist
# before the table does. Order matters and lives in apps/common/plans.py.


class PlanCode(models.TextChoices):
    FOUNDING = "FOUNDING", "Founding"
    STANDARD = "STANDARD", "Standard"
    ENTERPRISE = "ENTERPRISE", "Enterprise"