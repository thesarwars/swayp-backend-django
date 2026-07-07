from apps.bill_categories.repositories import BillCategoryRepository


class BillCategorySelector:

    def __init__(self):
        self.repository = BillCategoryRepository()

    def get_dashboard_categories(self):
        return self.repository.get_active()

    def get_category(self, category_id):
        return self.repository.get_by_id(category_id)