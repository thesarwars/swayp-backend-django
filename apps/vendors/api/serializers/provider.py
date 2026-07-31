from rest_framework import serializers

from apps.common.enums import PaymentRail


class ProviderSearchSerializer(serializers.Serializer):
    """A configured-account directory hit (E3-S7).

    Shaped from the provider's ``DirectoryVendor`` DTO — carries the
    ``verified`` flag and the ``network`` badge the Add-Vendor screens show
    (792:16497 etc.). Every directory hit is reachable on the configured-account
    rail (BRD §5), hence a constant ``network``.

    That constant is the rail, never the processor behind it. It used to be the
    literal brand name, which put a vendor-lock detail on the wire and made the
    client's badge wrong the day the rail is re-sourced — the processor is an
    implementation choice (E1-S4), and swapping it must not be an API change.
    """

    external_id = serializers.CharField()
    name = serializers.CharField()
    category = serializers.CharField()
    verified = serializers.BooleanField()
    speed = serializers.CharField(allow_blank=True, default="")
    network = serializers.SerializerMethodField()

    def get_network(self, obj):
        return PaymentRail.NETWORK.value
