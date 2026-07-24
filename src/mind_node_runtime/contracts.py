from __future__ import annotations

from typing import Any

REQUIRED_CHAIN_ROLES = (
    "objective",
    "pattern",
    "vocabulary",
    "behavior",
    "algorithm",
    "code",
    "implementation",
    "justification",
    "validation",
    "observability_algorithm",
    "metric",
    "health",
)

OUTPUT_REQUIRED_KEYS = (
    "identity",
    "objective",
    "chainInventory",
    "causalChain",
    "debtsAndRisks",
    "nextVerticalIncrement",
    "honestFinalState",
)

INFORMATION_STATUSES = {
    "measured",
    "known_absent",
    "unknown",
    "not_measured",
    "measurement_failed",
}

CHAIN_STATUSES = {
    "present",
    "partial",
    "missing",
    "stale",
    "not_implemented",
    "not_measured",
}


def validate_against_schema(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Validate the small JSON-Schema subset used by the minimal runtime.

    Supported keywords: type, required, properties, enum, items.
    The graph remains authoritative for the schema; this function only interprets it.
    """
    errors: list[str] = []
    expected_type = schema.get("type")
    type_checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    if expected_type in type_checks and not type_checks[expected_type](value):
        return [f"{path}: expected {expected_type}, got {type(value).__name__}"]

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} is not in enum")

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required key {key!r}")
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, child_schema in properties.items():
                if key in value and isinstance(child_schema, dict):
                    errors.extend(validate_against_schema(value[key], child_schema, f"{path}.{key}"))

    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            errors.extend(validate_against_schema(item, schema["items"], f"{path}[{index}]"))

    return errors


def validate_output(value: object) -> list[str]:
    """Legacy semantic checks for the bundled Think-in-Loops fallback executor."""
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["output must be an object"]
    for key in OUTPUT_REQUIRED_KEYS:
        if key not in value:
            errors.append(f"missing output key: {key}")
    inventory = value.get("chainInventory")
    if inventory is not None and not isinstance(inventory, list):
        errors.append("chainInventory must be a list")
    if isinstance(inventory, list):
        for index, item in enumerate(inventory):
            if not isinstance(item, dict):
                errors.append(f"chainInventory[{index}] must be an object")
                continue
            status = item.get("status")
            if status not in CHAIN_STATUSES:
                errors.append(f"chainInventory[{index}].status invalid: {status!r}")
    return errors
