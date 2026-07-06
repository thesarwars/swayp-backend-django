from .repositories import BillCategoryRepository


class BillCategoryService:

    def __init__(self):
        self.repository = BillCategoryRepository()

    def get_dashboard_categories(self):
        return self.repository.get_active()