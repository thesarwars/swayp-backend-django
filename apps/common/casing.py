"""snake_case beside the shipped camelCase keys (API-5).

A few bodies shipped camelCase (notifications, payment history, the profile
summary, pagination) while everything else is snake_case. Renaming them
would break every client on the day it shipped, so instead both are sent:
the snake_case copy is the one to read, and the camelCase one stays until the
clients have moved, then goes. Query parameters accept both spellings.
"""

import re

_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def to_snake(name):
    return _BOUNDARY.sub("_", name).lower()


def with_snake_case(data):
    """A copy of a dict with a snake_case key beside each camelCase one.
    Shallow: the nested payloads a client sent or a provider returned are
    left as they are."""
    if not isinstance(data, dict):
        return data

    mirrored = dict(data)

    for key, value in data.items():
        snake = to_snake(key)

        if snake != key and snake not in mirrored:
            mirrored[snake] = value

    return mirrored


def snake_case_aliases(serializer_class):
    """Class decorator: each camelCase field gets a snake_case twin reading
    the same source, so the OpenAPI schema declares both."""
    declared = serializer_class._declared_fields

    for name, field in list(declared.items()):
        snake = to_snake(name)

        if snake == name or snake in declared:
            continue

        kwargs = dict(field._kwargs)
        kwargs.setdefault("source", name)

        # DRF refuses a source equal to the field's own name.
        if kwargs["source"] == snake:
            del kwargs["source"]

        declared[snake] = field.__class__(*field._args, **kwargs)

    return serializer_class


class SnakeCaseInputMixin:
    """Accepts ``page_size`` wherever ``pageSize`` is declared. The camelCase
    spelling wins if a request sends both."""

    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()

            for name in self.fields:
                snake = to_snake(name)

                if snake == name or snake not in data or name in data:
                    continue

                if hasattr(data, "getlist"):
                    data.setlist(name, data.getlist(snake))
                else:
                    data[name] = data[snake]

        return super().to_internal_value(data)


#: When the camelCase copies go (web C2). Announced on every answer that
#: still carries them, with the RFC 9745 Deprecation header and the RFC 8594
#: Sunset header, so clients can find what to move before it breaks.
CAMEL_CASE_DEPRECATED_AT = 1792022400   # 2026-10-14T00:00:00Z
CAMEL_CASE_SUNSET = "Sun, 15 Nov 2026 00:00:00 GMT"


def has_camel_case_keys(body):
    """Does a response body still carry camelCase copies? Checks the top
    level, pagination, and the first row of data (rows share a shape)."""
    def camel(mapping):
        return isinstance(mapping, dict) and any(
            to_snake(key) != key for key in mapping
        )

    if not isinstance(body, dict):
        return False

    data = body.get("data")
    first = data[0] if isinstance(data, list) and data else data

    return camel(body) or camel(body.get("pagination")) or camel(first)


def mark_camel_case_deprecated(response):
    response["Deprecation"] = f"@{CAMEL_CASE_DEPRECATED_AT}"
    response["Sunset"] = CAMEL_CASE_SUNSET

    return response
