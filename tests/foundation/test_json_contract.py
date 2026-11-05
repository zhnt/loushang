from __future__ import annotations

import sys
from enum import IntEnum, StrEnum
from pathlib import Path

import pytest

from loushang.foundation.json import (
    JsonValueError,
    dump_json_value,
    require_json_mapping,
    require_json_value,
    validate_json_value,
)


def test_require_json_value_validates_and_copies_nested_values() -> None:
    source = {"items": [{"name": "alpha"}], "count": 1}

    projected = require_json_value(source, name="payload")

    assert projected == source
    assert projected is not source
    assert isinstance(projected, dict)
    assert projected["items"] is not source["items"]


@pytest.mark.parametrize(
    ("value", "value_type"),
    [
        ({"path": Path("notes.txt")}, type(Path("notes.txt")).__name__),
        ({"items": (1, 2)}, "tuple"),
        ({"items": {1, 2}}, "set"),
        ({"number": float("nan")}, "float"),
        ({"number": float("inf")}, "float"),
        ({"number": float("-inf")}, "float"),
    ],
)
def test_require_json_value_rejects_implicit_coercions(
    value: object,
    value_type: str,
) -> None:
    with pytest.raises(JsonValueError) as exc_info:
        require_json_value(value, name="payload")

    assert exc_info.value.value_type == value_type


def test_require_json_value_reports_nested_path_and_cycles() -> None:
    circular: list[object] = []
    circular.append(circular)

    with pytest.raises(JsonValueError) as nested_error:
        require_json_value({"outer": [{"path": Path("notes.txt")}]}, name="payload")
    with pytest.raises(JsonValueError, match="circular reference"):
        require_json_value(circular, name="payload")

    assert nested_error.value.path == "payload.outer[0].path"


def test_require_json_value_escapes_and_bounds_error_paths() -> None:
    with pytest.raises(JsonValueError) as escaped_error:
        require_json_value({"line\nbreak.with.dot": object()}, name="payload")

    assert escaped_error.value.path == 'payload["line\\nbreak.with.dot"]'
    assert "\n" not in escaped_error.value.path

    long_key = "x" * 10_000
    with pytest.raises(JsonValueError) as bounded_error:
        require_json_value({long_key: object()}, name="payload")

    assert len(bounded_error.value.path) <= 512
    assert long_key not in bounded_error.value.path


def test_json_mapping_and_dump_preserve_strict_json_contract() -> None:
    assert require_json_mapping({"ok": True}) == {"ok": True}
    assert dump_json_value({"message": "你好"}) == '{"message":"你好"}'

    with pytest.raises(JsonValueError, match="must be a JSON object"):
        require_json_mapping([1, 2])


def test_require_json_value_rejects_enum_and_non_string_keys() -> None:
    class Number(IntEnum):
        ONE = 1

    class Label(StrEnum):
        ONE = "one"

    for value in (Number.ONE, Label.ONE):
        with pytest.raises(JsonValueError) as exc_info:
            require_json_value({"value": value}, name="payload")
        assert exc_info.value.path == "payload.value"
        assert exc_info.value.value_type == type(value).__name__

    with pytest.raises(JsonValueError) as exc_info:
        require_json_value({1: "value"}, name="payload")
    assert exc_info.value.path == "payload"
    assert exc_info.value.value_type == "int"


def test_require_json_value_rejects_container_subclasses() -> None:
    class CustomList(list[object]):
        pass

    class CustomDict(dict[str, object]):
        pass

    for value in (CustomList(), CustomDict()):
        with pytest.raises(JsonValueError) as exc_info:
            require_json_value(value, name="payload")
        assert exc_info.value.path == "payload"
        assert exc_info.value.value_type == type(value).__name__


def test_require_json_value_rejects_unencodable_strings_and_integers() -> None:
    with pytest.raises(JsonValueError, match="valid UTF-8") as value_error:
        require_json_value({"value": "\ud800"}, name="payload")
    with pytest.raises(JsonValueError, match="valid UTF-8") as key_error:
        require_json_value({"\ud800": "value"}, name="payload")

    assert value_error.value.path == "payload.value"
    assert key_error.value.path == "payload"

    digit_limit = sys.get_int_max_str_digits()
    if digit_limit:
        with pytest.raises(JsonValueError, match="encoder limit"):
            require_json_value(10**digit_limit, name="payload")


def test_validate_json_value_accepts_strict_json_without_copying() -> None:
    source = {"items": [{"name": "alpha"}], "count": 1, "flag": True, "note": None}

    assert validate_json_value(source, name="payload") is None


def test_validate_json_value_allows_shared_noncyclic_containers() -> None:
    shared = {"items": [1, "hello"]}

    assert validate_json_value([shared, shared], name="payload") is None


def test_validate_json_value_preserves_first_error_in_mapping_order() -> None:
    source = {"first": object(), 1: "later"}

    with pytest.raises(JsonValueError) as exc_info:
        validate_json_value(source, name="payload")

    assert exc_info.value.path == "payload.first"
    assert exc_info.value.value_type == "object"


@pytest.mark.parametrize(
    ("value", "path", "value_type"),
    [
        ({"path": Path("notes.txt")}, "payload.path", "PosixPath"),
        ({"items": (1, 2)}, "payload.items", "tuple"),
        ({"items": {1, 2}}, "payload.items", "set"),
        ({"number": float("nan")}, "payload.number", "float"),
        ({"number": float("inf")}, "payload.number", "float"),
        ({"value": IntEnum("Number", "ONE").ONE}, "payload.value", "Number"),
        ({1: "value"}, "payload", "int"),
    ],
)
def test_validate_json_value_rejects_the_same_values_as_require(
    value: object,
    path: str,
    value_type: str,
) -> None:
    with pytest.raises(JsonValueError) as exc_info:
        validate_json_value(value, name="payload")
    assert exc_info.value.path == path
    assert exc_info.value.value_type == value_type


def test_validate_json_value_rejects_cycles_strings_integers_and_subclasses() -> None:
    class CustomList(list[object]):
        pass

    with pytest.raises(JsonValueError, match="circular"):
        cyclic: list[object] = []
        cyclic.append(cyclic)
        validate_json_value(cyclic, name="payload")

    with pytest.raises(JsonValueError, match="valid UTF-8"):
        validate_json_value({"value": "\ud800"}, name="payload")

    with pytest.raises(JsonValueError, match="valid UTF-8"):
        validate_json_value({"\ud800": "value"}, name="payload")

    with pytest.raises(JsonValueError) as subclass_error:
        validate_json_value(CustomList(), name="payload")
    assert subclass_error.value.value_type == "CustomList"

    digit_limit = sys.get_int_max_str_digits()
    if digit_limit:
        with pytest.raises(JsonValueError, match="encoder limit"):
            validate_json_value(10**digit_limit, name="payload")


def test_dump_json_value_still_rejects_non_strict_values() -> None:
    with pytest.raises(JsonValueError):
        dump_json_value({"number": float("nan")}, name="payload")
    with pytest.raises(JsonValueError):
        dump_json_value({"items": (1, 2)}, name="payload")
