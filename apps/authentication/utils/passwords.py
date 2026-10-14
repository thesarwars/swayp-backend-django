"""The password rules, in one place for registration and change-password.

Character classes only; no length minimum (a product decision, web S4).
"""

import re

RULES = (
    (r"[A-Z]", "Password must contain one uppercase letter."),
    (r"[a-z]", "Password must contain one lowercase letter."),
    (r"[0-9]", "Password must contain one digit."),
    (r"[!@#$%^&*(),.?\":{}|<>]", "Password must contain one special character."),
)


def password_problem(value):
    """The first rule the password breaks, as a message, or None."""
    for pattern, message in RULES:
        if not re.search(pattern, value or ""):
            return message

    return None
