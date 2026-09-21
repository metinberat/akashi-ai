"""Strict validation of the deliberately small tool-schema vocabulary.

Unknown input properties are rejected; nested arbitrary objects are allowed only
when a tool explicitly declares an open object (e.g. device arguments, validated
again by the agent). No coercion of strings, booleans or integers.
"""
import json
from typing import Any, Dict


def validate(value: Any, schema: Dict[str, Any], path: str = "arguments", strict: bool = True) -> None:
    kind = schema.get("type")
    checks = {"object": lambda: isinstance(value, dict), "array": lambda: isinstance(value, list),
              "string": lambda: isinstance(value, str), "integer": lambda: type(value) is int,
              "number": lambda: type(value) in (int, float), "boolean": lambda: type(value) is bool}
    if kind in checks and not checks[kind]():
        raise ValueError(f"{path} must be {kind}.")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} is not an allowed value.")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for required in schema.get("required", []):
            if required not in value:
                raise ValueError(f"{path}.{required} is required.")
        for name, item in value.items():
            if strict and "properties" in schema and name not in properties:
                raise ValueError(f"Unexpected field {path}.{name}.")
            if name in properties:
                validate(item, properties[name], f"{path}.{name}", strict)
    if isinstance(value, list):
        if len(value) > 100:
            raise ValueError(f"{path} has too many items.")
        for item in value:
            validate(item, schema.get("items", {}), path + "[]", strict)
    if isinstance(value, str) and len(value) > 50_000:
        raise ValueError(f"{path} is too long.")


def validate_arguments(arguments: Dict[str, Any], schema: Dict[str, Any]) -> None:
    if len(json.dumps(arguments)) > 64_000:
        raise ValueError("Tool arguments exceed the size limit.")
    validate(arguments, schema)
