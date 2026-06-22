"""Small JSON type helpers for validated provider boundaries."""

from collections.abc import Mapping, Sequence
from typing import TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | Mapping[str, "JsonValue"] | Sequence["JsonValue"]
JsonObject: TypeAlias = Mapping[str, JsonValue]


def string_value(value: JsonValue | object, field_name: str) -> str:
    if isinstance(value, str):
        return value
    raise ValueError(f"{field_name} must be a string")


def optional_string_value(value: JsonValue | object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return None


def int_value(value: JsonValue | object, field_name: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ValueError(f"{field_name} must be an integer")


def object_value(value: JsonValue | object, field_name: str) -> JsonObject:
    if isinstance(value, Mapping):
        return value
    raise ValueError(f"{field_name} must be an object")


def sequence_value(value: JsonValue | object) -> Sequence[JsonValue]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return value
    return []
