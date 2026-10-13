"""Convert Pydantic models into strict JSON Schemas accepted by structured-output APIs."""

from typing import Any

from pydantic import BaseModel

# Keywords structured-output endpoints commonly reject; Pydantic validates them client-side.
_UNSUPPORTED_KEYWORDS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
        "default",
    }
)


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Every object closed (`additionalProperties: false`) with all properties required.

    Optional fields stay nullable through their `anyOf [..., null]` type, so the model must
    still emit them (as `null`), which is what strict mode expects.
    """
    result = _strictify(model.model_json_schema())
    assert isinstance(result, dict)  # noqa: S101 - a model schema is always an object
    return result


# Keys whose values map *names* (field or definition names) to schemas, not keywords.
_NAMED_SCHEMA_MAPS = frozenset({"properties", "$defs"})


def _strictify(node: Any) -> Any:
    if isinstance(node, list):
        return [_strictify(item) for item in node]
    if not isinstance(node, dict):
        return node
    cleaned: dict[str, Any] = {}
    for key, value in node.items():
        if key in _NAMED_SCHEMA_MAPS and isinstance(value, dict):
            cleaned[key] = {name: _strictify(schema) for name, schema in value.items()}
        elif key not in _UNSUPPORTED_KEYWORDS:
            cleaned[key] = _strictify(value)
    if cleaned.get("type") == "object" and "properties" in cleaned:
        cleaned["additionalProperties"] = False
        cleaned["required"] = list(cleaned["properties"])
    return cleaned
