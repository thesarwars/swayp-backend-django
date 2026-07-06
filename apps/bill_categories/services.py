from .repositories import BillCategoryRepository


class BillCategoryService:
    def __init__(self):
        self.repository = BillCategoryRepository()

    def get_dashboard_categories(self):
        categories = self.repository.get_active()

        return [
            {
                "id": str(category.id),
                "name": category.name,
                "icon": category.icon,
                "color": category.color,
                "displayOrder": category.display_order,
            }
            for category in categories
        ]