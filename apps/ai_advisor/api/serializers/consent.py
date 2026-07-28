from rest_framework import serializers


class ConsentInputSerializer(serializers.Serializer):
    """The exact consent language shown to the user (E7-S1).

    Required, and not blank-tolerant. The column is annotated "exact language
    shown" — filing a server-side default in it records that the user saw text
    they may never have seen, which is the one thing a consent artifact must
    not do. E4's standing-authorization capture refuses blank text for the
    same reason.
    """

    consent_text = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )


class ConsentSerializer(serializers.Serializer):
    consented_at = serializers.DateTimeField()
    revoked_at = serializers.DateTimeField(allow_null=True)
    is_live = serializers.BooleanField()


class ConsentStateSerializer(serializers.Serializer):
    """Current consent state for the settings surface (E7-S1, PRD §10-Q12).

    Distinct from ConsentSerializer because a user who has never consented has
    no row at all, and the settings screen still has to render the toggle.
    """

    is_live = serializers.BooleanField()
    consented_at = serializers.DateTimeField(allow_null=True)
    revoked_at = serializers.DateTimeField(allow_null=True)
    consent_text = serializers.CharField(allow_null=True)
