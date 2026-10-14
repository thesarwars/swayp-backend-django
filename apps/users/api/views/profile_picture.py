from drf_spectacular.utils import extend_schema
from rest_framework.parsers import FormParser, MultiPartParser

from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse
from apps.users.api.serializers.profile_picture import (
    ProfilePictureSerializer,
    ProfilePictureUploadSerializer,
)
from apps.users.services.profile_picture_service import (
    ProfilePictureService,
    picture_url,
)


class ProfilePictureAPIView(BaseAPIView):
    """The signed-in person's photo. Personal, not the account's: a
    teammate's upload changes their own picture, never the owner's."""

    parser_classes = (MultiPartParser, FormParser)
    service_class = ProfilePictureService

    def _answer(self, request, message):
        return ApiResponse.success(
            data=ProfilePictureSerializer(
                {"profile_picture": picture_url(request.user, request)}
            ).data,
            message=message,
        )

    @extend_schema(
        tags=["Users"],
        summary="Upload a profile picture",
        description=(
            "multipart/form-data with a profile_picture file: JPEG, PNG or "
            "WebP, up to 5 MB. Replaces any previous picture. Answers its "
            "absolute URL, which dashboard/profile-summary returns too."
        ),
        request={"multipart/form-data": ProfilePictureUploadSerializer},
        responses={200: ProfilePictureSerializer},
    )
    def post(self, request):
        serializer = ProfilePictureUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        self.service.replace(
            request.user, serializer.validated_data["profile_picture"]
        )

        return self._answer(request, "Profile picture updated.")

    @extend_schema(
        tags=["Users"],
        summary="Remove the profile picture",
        request=None,
        responses={200: ProfilePictureSerializer},
    )
    def delete(self, request):
        self.service.remove(request.user)

        return self._answer(request, "Profile picture removed.")
