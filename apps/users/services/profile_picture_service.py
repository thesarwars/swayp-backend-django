class ProfilePictureService:
    """The signed-in person's own photo (web §4)."""

    @staticmethod
    def replace(user, image):
        old = user.profile_picture.name if user.profile_picture else None

        user.profile_picture = image
        user.save(update_fields=["profile_picture"])

        if old:
            user.profile_picture.storage.delete(old)

        return user

    @staticmethod
    def remove(user):
        if user.profile_picture:
            user.profile_picture.delete(save=False)

        user.profile_picture = None
        user.save(update_fields=["profile_picture"])

        return user


def picture_url(user, request=None):
    """Absolute URL of the user's picture, or None."""
    if not getattr(user, "profile_picture", None):
        return None

    url = user.profile_picture.url

    return request.build_absolute_uri(url) if request is not None else url
