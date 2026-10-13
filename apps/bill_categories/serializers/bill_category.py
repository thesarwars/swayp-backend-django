from rest_framework import serializers

from apps.common.casing import snake_case_aliases


@snake_case_aliases
class BillCategorySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    icon = serializers.CharField(
        allow_blank=True,
        help_text="Image URL, or empty when the category has none.",
    )
    color = serializers.CharField()
    displayOrder = serializers.IntegerField(source="display_order")


class BillCategoryListResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = BillCategorySerializer(many=True)
