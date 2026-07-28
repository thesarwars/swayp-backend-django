from apps.bill_categories.selectors.bill_category_selector import (
    BillCategorySelector,
)


class BillCategoryService:

    def __init__(self):
        self.selector = BillCategorySelector()

    def get_dashboard_categories(self):
        return self.selector.get_dashboard_categories()
