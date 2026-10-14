"""OpenAPI that describes what the server actually sends (API-1).

Views document the payload they return (``responses={200: XSerializer}``),
but almost every view sends it wrapped by ApiResponse, so the published
schema described a body no client ever received. This AutoSchema adds the
wrapper at schema time, from the same facts the view acts on:

* ``{success, message, data}`` around every 2xx JSON body, unless the body
  is already declared enveloped (has ``success``) or the view opts out with
  ``response_envelope = False`` (the vendor endpoints, which are bare).
* ``pagination`` beside ``data`` on views with ``paginated_response = True``,
  which are the ones passing ``pagination=`` to ApiResponse.
* Top-level keys beside ``data`` from the view's ``response_extra``
  (``{"next_cursor": {...}}``), each also under its snake_case name.
* ``data`` nullable for the methods in the view's ``nullable_data`` (e.g.
  GET subscription answers null when there is none).
* The error envelope for the statuses the view can produce: 400, 401, 402
  and 403 for capability-gated views, 404 when the path carries an id, and
  503 on views with ``may_be_unavailable = True`` (an outside provider).

apps/common/tests/test_openapi_contract.py holds the schema to the server.
"""

from drf_spectacular.openapi import AutoSchema

from apps.common.casing import to_snake

from apps.common.serializers import (
    ErrorResponseSerializer,
    PaginationResponseSerializer,
)

ERROR_DESCRIPTIONS = {
    "400": "Validation failed: read `errors` and `code`.",
    "401": "Missing or expired token (`code`: not_authenticated, token_not_valid).",
    "402": "Plan limit (`code`: plan_limit, with `limit`).",
    "403": "Not allowed (`code`: forbidden, role_forbidden).",
    "404": "Not found, or not yours.",
    "503": "A provider is unreachable; nothing was charged or changed. Retry.",
}


class SwaypAutoSchema(AutoSchema):

    def get_description(self):
        """Only what a view declares with extend_schema(description=...).

        spectacular falls back to the class and method docstrings, which in
        this codebase are notes for maintainers ("Gives a view
        self.account(request). A mixin rather than a helper import…"), and
        16 operations published them as their documentation (web §6).
        """
        return ""

    def _map_basic_serializer(self, serializer, direction):
        """In a response, every field the serializer outputs is present.

        DRF marks a model field with a default or blank=True as not
        required, which is about input; spectacular carried that into the
        response schema, so always-present keys (status, provider, …) were
        published as optional. A field the serializer itself declares
        ``required=False`` is still optional: it is omitted when absent.
        """
        schema = super()._map_basic_serializer(serializer, direction)

        if direction != "response":
            return schema

        declared = getattr(serializer, "_declared_fields", {})
        required = set(schema.get("required", []))

        for name, field in serializer.fields.items():
            if field.write_only:
                continue

            if name in declared and field._kwargs.get("required") is False:
                continue

            required.add(field.field_name)

        properties = schema.get("properties", {})
        ordered = [name for name in properties if name in required]

        if ordered:
            schema["required"] = ordered

        return schema

    def _get_response_bodies(self, direction="response"):
        responses = super()._get_response_bodies(direction)

        if direction != "response":
            return responses

        for code, response in responses.items():
            if str(code).startswith("2"):
                self._envelope(response)

        self._add_errors(responses)

        return responses

    # --- success ------------------------------------------------------------

    def _envelope(self, response):
        if getattr(self.view, "response_envelope", True) is False:
            return

        content = response.get("content", {})
        media = content.get("application/json")

        if not media or "schema" not in media:
            if self.method not in getattr(self.view, "nullable_data", ()):
                return

            # Declared with no body (responses={200: None}) but enveloped
            # with data null.
            media = response.setdefault("content", {}).setdefault(
                "application/json", {}
            )
            media["schema"] = {
                "type": "object",
                "description": "Always null.",
                "properties": {},
            }

        schema = media["schema"]

        if self._is_enveloped(schema):
            return

        paged = None
        props = self._resolve(schema).get("properties") or {}

        if set(props) == {"items", "pagination"}:
            # A DRF-paged list (spectacular publishes it as a component),
            # enveloped by EnvelopeResponseMixin: the items become data and
            # pagination sits beside it (web C1).
            paged = props["pagination"]
            schema = props["items"]

        if self.method in getattr(self.view, "nullable_data", ()):
            schema = {"allOf": [schema], "nullable": True}

        properties = {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": schema,
        }
        required = ["success", "message", "data"]

        if paged is not None:
            properties["pagination"] = paged
            required.append("pagination")

        for key, extra in getattr(self.view, "response_extra", {}).items():
            properties[key] = extra
            properties.setdefault(to_snake(key), extra)

        if paged is None and getattr(self.view, "paginated_response", False):
            properties["pagination"] = self._ref(PaginationResponseSerializer)
            required.append("pagination")

        media["schema"] = {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    def _is_enveloped(self, schema):
        resolved = self._resolve(schema)

        return "success" in (resolved.get("properties") or {})

    def _resolve(self, schema):
        ref = schema.get("$ref") if isinstance(schema, dict) else None

        if not ref:
            return schema if isinstance(schema, dict) else {}

        name = ref.rsplit("/", 1)[-1]

        for (component_name, kind), component in self.registry._components.items():
            if component_name == name and kind == "schemas":
                return component.schema or {}

        return {}

    # --- errors -------------------------------------------------------------

    def _add_errors(self, responses):
        codes = ["400"]

        if self._requires_auth():
            codes.append("401")

        if self._capability_gated():
            codes += ["402", "403"]

        if "{" in self.path:
            codes.append("404")

        if getattr(self.view, "may_be_unavailable", False):
            codes.append("503")

        # Also every 4xx/5xx a view declared with a description only.
        codes += [
            str(c) for c in responses
            if str(c)[0] in "45" and str(c) not in codes
        ]

        for code in codes:
            existing = responses.get(code) or {}

            if existing.get("content"):
                continue

            responses[code] = {
                "description": (
                    existing.get("description")
                    or ERROR_DESCRIPTIONS.get(code, "Error.")
                ),
                "content": {
                    "application/json": {
                        "schema": self._ref(ErrorResponseSerializer)
                    }
                },
            }

    def _requires_auth(self):
        from rest_framework.permissions import AllowAny

        # Declared auth=[] (webhooks verify provider signatures; public
        # endpoints) means no token, so no 401 either.
        if not self.get_auth():
            return False

        permissions = self.view.get_permissions()

        return not (
            permissions and all(isinstance(p, AllowAny) for p in permissions)
        )

    def _capability_gated(self):
        return getattr(self.view, "required_capability", None) is not None

    def _ref(self, serializer_class):
        return self.resolve_serializer(serializer_class(), "response").ref



def drop_duplicate_routes(endpoints, **kwargs):
    """Preprocessing hook (web §6): the processor webhooks are mounted twice,
    at /webhooks/* (the URL registered with each processor) and again under
    /api/v1/webhooks/*. The schema lists each once, at the registered URL."""
    return [
        endpoint for endpoint in endpoints
        if not endpoint[0].startswith("/api/v1/webhooks")
    ]
