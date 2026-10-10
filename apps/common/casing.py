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
