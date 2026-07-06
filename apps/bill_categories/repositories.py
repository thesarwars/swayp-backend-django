from .models import BillCategory


class BillCategoryRepository:

    @staticmethod
    def get_active():
        return (
            BillCategory.objects
            .filter(is_active=True)
            .only(
                "id",
                "name",
                "icon",
                "color",
                "display_order",
            )
            .order_by(
                "display_order",
                "name",
            )
        )

    @staticmethod
    def get_by_id(category_id):
        return (
            BillCategory.objects
            .filter(
                id=category_id,
                is_active=True,
            )
            .first()
        )