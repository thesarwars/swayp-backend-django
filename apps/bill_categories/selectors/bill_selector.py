from apps.bill_categories.models.bill import Bill
from apps.bill_categories.repositories import BillRepository


class BillSelector:

    def __init__(self):
        self.repository = BillRepository()

    def get_user_bills(self, user):
        return self.repository.get_user_bills(user)
    
    def get_bill(self, bill_id, user):
        return (
            Bill.objects.filter(
                id=bill_id,
                user=user,
            )
            .select_related(
                "vendor",
                "category",
                "payment_method",
            )
            .first()
        )

class BillRepository:

    def get_user_bills(self, user):
        return (
            Bill.objects.filter(user=user)
            .select_related(
                "vendor",
                "category",
                "payment_method",
            )
            .order_by("-created_at")
        )