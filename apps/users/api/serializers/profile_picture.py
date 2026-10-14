from rest_framework import serializers

#: 5 MB, and the formats every browser and phone renders.
MAX_PICTURE_BYTES = 5 * 1024 * 1024
PICTURE_FORMATS = {"JPEG", "PNG", "WEBP"}


class ProfilePictureUploadSerializer(serializers.Serializer):
    profile_picture = serializers.ImageField(
        help_text="JPEG, PNG or WebP, up to 5 MB."
    )

    def validate_profile_picture(self, image):
        if image.size > MAX_PICTURE_BYTES:
            raise serializers.ValidationError("The picture is over 5 MB.")

        fmt = getattr(getattr(image, "image", None), "format", None)

        if fmt and fmt.upper() not in PICTURE_FORMATS:
            raise serializers.ValidationError("Use a JPEG, PNG or WebP picture.")

        return image


class ProfilePictureSerializer(serializers.Serializer):
    profile_picture = serializers.CharField(
        allow_null=True, help_text="Absolute URL of the picture, or null."
    )
