"""Validate every keyword used by the committed evidence schema without dependencies.

This is a deliberately bounded schema vocabulary. New unsupported keywords fail
closed and require extending the validator or adopting a full schema library.
"""

import json
import re
from datetime import datetime

SUPPORTED = {
    "$schema", "$id", "title", "description", "$defs", "$ref", "type", "const", "enum",
    "properties", "required", "additionalProperties", "minProperties", "maxProperties",
    "items", "minItems", "maxItems", "uniqueItems", "pattern", "minLength", "maxLength",
    "minimum", "maximum", "format",
}


def ensure(condition, message):
    if not condition:
        raise ValueError(message)


def type_matches(value, name):
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool, "null": type(None)}
    ensure(name in types or name == "number", f"Unsupported schema type: {name}")
    if name == "number":
        return type(value) in {int, float}
    return type(value) is types[name]


def object_check(value, rule, schema, path, depth):
    properties = rule.get("properties", {})
    ensure(set(rule.get("required", [])) <= set(value), f"{path}: missing required field")
    extra = set(value) - set(properties)
    additional = rule.get("additionalProperties", True)
    ensure(additional is not False or not extra, f"{path}: unknown fields {sorted(extra)}")
    ensure(rule.get("minProperties", 0) <= len(value) <= rule.get("maxProperties", float("inf")), f"{path}: object size outside bounds")
    for key, child in value.items():
        child_rule = properties.get(key, additional)
        if isinstance(child_rule, dict):
            check(child, child_rule, schema, f"{path}.{key}", depth+1)


def array_check(value, rule, schema, path, depth):
    ensure(rule.get("minItems", 0) <= len(value) <= rule.get("maxItems", float("inf")), f"{path}: array size outside bounds")
    if rule.get("uniqueItems"):
        ensure(len({json.dumps(item, sort_keys=True) for item in value}) == len(value), f"{path}: duplicate array items")
    for index, child in enumerate(value):
        check(child, rule.get("items", {}), schema, f"{path}[{index}]", depth+1)


def string_check(value, rule, path):
    ensure(rule.get("minLength", 0) <= len(value) <= rule.get("maxLength", float("inf")), f"{path}: string length outside bounds")
    if "pattern" in rule:
        ensure(re.search(rule["pattern"], value) is not None, f"{path}: pattern mismatch")
    if "format" in rule:
        ensure(rule["format"] == "date-time", f"Unsupported format: {rule['format']}")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        ensure(parsed.tzinfo is not None, f"{path}: timestamp requires timezone")


def constraints(value, rule, path):
    if "const" in rule:
        ensure(value == rule["const"] and type(value) is type(rule["const"]), f"{path}: constant mismatch")
    if "enum" in rule:
        ensure(any(value == item and type(value) is type(item) for item in rule["enum"]), f"{path}: invalid enum value")
    if type(value) in {int, float}:
        ensure(rule.get("minimum", -float("inf")) <= value <= rule.get("maximum", float("inf")), f"{path}: numeric value outside bounds")
    if isinstance(value, str):
        string_check(value, rule, path)


def check(value, rule, schema, path="$", depth=0):
    ensure(depth <= 16, f"{path}: schema nesting exceeds bound")
    ensure(set(rule) <= SUPPORTED, f"{path}: unsupported schema keywords {sorted(set(rule)-SUPPORTED)}")
    if "$ref" in rule:
        ensure(set(rule) <= {"$ref", "description", "title"}, f"{path}: validation siblings of $ref are unsupported")
        ref = rule["$ref"]
        ensure(ref.startswith("#/$defs/"), f"Unsupported schema reference: {ref}")
        return check(value, schema["$defs"][ref.split("/")[-1]], schema, path, depth+1)
    names = rule.get("type", [])
    names = [names] if isinstance(names, str) else names
    ensure(not names or any(type_matches(value, name) for name in names), f"{path}: wrong value type")
    constraints(value, rule, path)
    if isinstance(value, dict):
        object_check(value, rule, schema, path, depth)
    if isinstance(value, list):
        array_check(value, rule, schema, path, depth)


def validate(value, schema):
    check(value, schema, schema)
