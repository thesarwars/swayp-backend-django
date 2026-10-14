"""One display name per user (web B4).

The profile, the dashboard, the greeting and the team list each built a name
their own way: profile.full_name (which fell back to the email address),
User.get_full_name(), the first name, and first+last again. The same account
showed four different names. Every endpoint now asks this.
"""


def display_name(user, profile=None):
    """The profile's full name, else first + last, else "". Never the email:
    an address is not a name, and showing it as one leaks it on screens the
    rest of a team can see. Pass ``profile`` when the caller holds a fresher
    copy than ``user.profile`` (e.g. just after saving it)."""
    if user is None:
        return ""

    if profile is None and _has_profile(user):
        profile = user.profile

    # False means "looked it up, there is none", so nothing is fetched.
    profile = profile or None
    name = (getattr(profile, "full_name", "") or "").strip()

    if name and name.lower() != (user.email or "").lower():
        return name

    return f"{user.first_name} {user.last_name}".strip()


def first_name(user, profile=None):
    """For "Welcome back, Jane": the first word of the display name."""
    name = display_name(user, profile)

    return name.split(" ", 1)[0] if name else ""


def _has_profile(user):
    from django.core.exceptions import ObjectDoesNotExist

    try:
        user.profile
    except ObjectDoesNotExist:
        return False

    return True
