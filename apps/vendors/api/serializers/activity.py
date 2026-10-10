"""The vendor activity feed (VEND-5)."""

from rest_framework import serializers

from apps.vendors.models import VendorActivity, VendorActivityAction


class VendorActivitySerializer(serializers.ModelSerializer):
    action = serializers.ChoiceField(choices=VendorActivityAction.choices)
    label = serializers.CharField(
        source="get_action_display",
        help_text='Display text, e.g. "Payment method added".',
    )
    vendor_id = serializers.UUIDField(
        allow_null=True, help_text="Null if the vendor no longer exists."
    )
    actor_name = serializers.SerializerMethodField(
        help_text="Who did it; null for system actions such as bank imports."
    )

    class Meta:
        model = VendorActivity
        fields = (
            "id",
            "action",
            "label",
            "vendor_id",
            "vendor_name",
            "actor_name",
            "created_at",
        )

    def get_actor_name(self, obj):
        actor = obj.actor

        if actor is None:
            return None

        return actor.get_full_name() or actor.email
