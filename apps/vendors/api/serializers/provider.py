from rest_framework import serializers


class ProviderSearchSerializer(serializers.Serializer):
    """A configured-account directory hit (E3-S7).

    Shaped from the provider's ``DirectoryVendor`` DTO — carries the
    ``verified`` flag and the ``network`` badge the Add-Vendor screens show
    (792:16497 etc.). Directory vendors are paid via the Stripe
    configured-account rail (BRD §5), hence a constant ``network``.
    """

    external_id = serializers.CharField()
    name = serializers.CharField()
    category = serializers.CharField()
    verified = serializers.BooleanField()
    speed = serializers.CharField(allow_blank=True, default="")
    network = serializers.SerializerMethodField()

    def get_network(self, obj):
        return "Stripe"
