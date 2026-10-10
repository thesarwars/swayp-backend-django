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
            return

        schema = media["schema"]

        if self._is_enveloped(schema):
            return

        if self.method in getattr(self.view, "nullable_data", ()):
            schema = {"allOf": [schema], "nullable": True}

        properties = {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": schema,
        }
        required = ["success", "message", "data"]

        for key, extra in getattr(self.view, "response_extra", {}).items():
            properties[key] = extra
            properties.setdefault(to_snake(key), extra)

        if getattr(self.view, "paginated_response", False):
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

        for code in codes:
            if code in responses:
                continue

            responses[code] = {
                "description": ERROR_DESCRIPTIONS[code],
                "content": {
                    "application/json": {
                        "schema": self._ref(ErrorResponseSerializer)
                    }
                },
            }

    def _requires_auth(self):
        from rest_framework.permissions import AllowAny

        permissions = self.view.get_permissions()

        return not (
            permissions and all(isinstance(p, AllowAny) for p in permissions)
        )

    def _capability_gated(self):
        return getattr(self.view, "required_capability", None) is not None

    def _ref(self, serializer_class):
        return self.resolve_serializer(serializer_class(), "response").ref
