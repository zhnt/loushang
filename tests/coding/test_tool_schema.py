from __future__ import annotations

from dataclasses import dataclass
from typing import NotRequired, TypedDict

import pytest

from loushang.harness.tools.core import (
    apply_schema_overrides,
    infer_schema_from_signature,
    infer_schema_from_type,
)


class SearchArgs(TypedDict):
    pattern: str
    path: str
    ignore_case: NotRequired[bool]


@dataclass
class ReadArgs:
    path: str
    limit: int | None = None


def search(args: SearchArgs) -> None:
    del args


def read(args: ReadArgs) -> None:
    del args


def missing_annotation(path) -> None:
    del path


def variadic(*args: str) -> None:
    del args


def positional_only(path, /) -> None:
    del path


def test_infer_schema_for_typeddict() -> None:
    schema = infer_schema_from_signature(search)
    assert schema["properties"]["args"]["properties"]["pattern"]["type"] == "string"


def test_infer_schema_for_dataclass() -> None:
    schema = infer_schema_from_signature(read)
    assert schema["properties"]["args"]["properties"]["limit"]["anyOf"] == [
        {"type": "integer"},
        {"type": "null"},
    ]


def test_infer_schema_for_pydantic_model_when_installed() -> None:
    pydantic = pytest.importorskip("pydantic")

    class GrepArgs(pydantic.BaseModel):
        pattern: str
        path: str

    schema = infer_schema_from_type(GrepArgs)
    assert schema["type"] == "object"
    assert schema["properties"]["pattern"]["type"] == "string"


def test_infer_schema_for_nested_pydantic_model_rejects_unresolved_refs() -> None:
    pydantic = pytest.importorskip("pydantic")

    class InnerArgs(pydantic.BaseModel):
        pattern: str

    class OuterArgs(pydantic.BaseModel):
        nested: InnerArgs

    with pytest.raises(ValueError, match="unresolved pydantic refs"):
        infer_schema_from_type(OuterArgs)


def test_infer_schema_for_pydantic_field_named_definitions_is_allowed() -> None:
    pydantic = pytest.importorskip("pydantic")

    class DefinitionArgs(pydantic.BaseModel):
        definitions: str

    schema = infer_schema_from_type(DefinitionArgs)
    assert schema["properties"]["definitions"]["type"] == "string"


def test_infer_schema_for_unsupported_type_raises() -> None:
    class CustomArgs:
        pass

    with pytest.raises(TypeError, match="unsupported schema annotation"):
        infer_schema_from_type(CustomArgs)


def test_infer_schema_from_signature_rejects_unannotated_parameter() -> None:
    with pytest.raises(TypeError, match="must be annotated"):
        infer_schema_from_signature(missing_annotation)


def test_infer_schema_from_signature_rejects_variadic_parameter() -> None:
    with pytest.raises(TypeError, match="variadic parameters"):
        infer_schema_from_signature(variadic)


def test_infer_schema_from_signature_rejects_positional_only_parameter() -> None:
    with pytest.raises(TypeError, match="positional-only parameters"):
        infer_schema_from_signature(positional_only)


def test_apply_schema_overrides_deep_merges_nested_objects() -> None:
    base = {
        "type": "object",
        "properties": {
            "args": {
                "type": "object",
                "properties": {"pattern": {"type": "string"}},
                "required": ["pattern"],
                "additionalProperties": False,
            }
        },
        "required": ["args"],
        "additionalProperties": False,
    }
    overrides = {
        "properties": {
            "args": {
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            }
        }
    }

    merged = apply_schema_overrides(base, overrides)

    assert merged["properties"]["args"]["properties"] == {
        "pattern": {"type": "string"},
        "path": {"type": "string"},
    }
    assert merged["properties"]["args"]["required"] == ["path"]
