"""Hold a real response to the published OpenAPI schema (API-1).

``assert_matches_schema(testcase, response, method, path)`` validates the
body against the schema the server publishes for that operation and status,
strictly: a key the schema does not declare fails, as does a wrong type or a
null where the schema does not allow one. That strictness is the point — a
schema that omits a field the server sends is the drift API-1 is about.
"""

import copy
import functools

import jsonschema
from drf_spectacular.generators import SchemaGenerator


@functools.lru_cache(maxsize=1)
def published_schema():
    return SchemaGenerator().get_schema(request=None, public=True)


def _to_jsonschema(node):
    """OpenAPI 3.0 → JSON Schema: nullable becomes a null type, and objects
    that list their properties allow no others."""
    if isinstance(node, list):
        return [_to_jsonschema(item) for item in node]

    if not isinstance(node, dict):
        return node

    node = {key: _to_jsonschema(value) for key, value in node.items()}
    nullable = node.pop("nullable", False)

    for key in ("readOnly", "writeOnly", "example", "examples"):
        node.pop(key, None)

    if node.get("type") == "object" and "properties" in node:
        node.setdefault("additionalProperties", False)

    if nullable:
        if "type" in node:
            node["type"] = [node["type"], "null"]

            if "enum" in node and None not in node["enum"]:
                node["enum"] = [*node["enum"], None]
        else:
            node = {"anyOf": [node, {"type": "null"}]}

    return node


def response_schema(method, path, status):
    schema = published_schema()
    operation = schema["paths"][path][method.lower()]
    response = operation["responses"][str(status)]
    body = response["content"]["application/json"]["schema"]

    document = _to_jsonschema(copy.deepcopy(body))
    document["components"] = _to_jsonschema(
        copy.deepcopy(schema.get("components", {}))
    )

    return document


def assert_matches_schema(testcase, response, method, path):
    """``path`` is the template as published, e.g.
    ``/api/v1/billing/subscription`` or ``/api/v1/payments/{payment_id}``."""
    try:
        schema = response_schema(method, path, response.status_code)
    except KeyError as missing:
        testcase.fail(
            f"{method} {path}: no schema published for "
            f"{response.status_code} ({missing})"
        )

    errors = sorted(
        jsonschema.Draft7Validator(schema).iter_errors(response.json()),
        key=lambda e: list(e.absolute_path),
    )

    if errors:
        testcase.fail(
            f"{method} {path} {response.status_code} does not match its "
            "schema:\n"
            + "\n".join(
                f"  at {'/'.join(map(str, e.absolute_path)) or '<root>'}: "
                f"{e.message[:300]}"
                for e in errors[:15]
            )
        )
