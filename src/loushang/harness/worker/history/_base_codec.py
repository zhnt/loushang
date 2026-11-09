"""Canonical V2 base envelopes using the existing inert-record schema traversal.

Each stream retains its own semantic validation and fixed public value family.
Schemas are bound once to concrete dataclasses; there is no runtime registry.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import ClassVar, Self, cast

from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

_MAX_BASE_BYTES = 128 * 1024 * 1024
_BASE_ERRORS = (KeyError, TypeError, ValueError, UnicodeError)


def _unchanged(value: object) -> object:
    return value


class _BaseWireMethods:
    __slots__ = ()

    _wire_schema: ClassVar[RecordSchema]
    _wire_label: ClassVar[str]
    _wire_lists: ClassVar[tuple[str, ...]]
    _wire_errors: ClassVar[tuple[type[Exception], ...]] = _BASE_ERRORS
    _wire_max_bytes: ClassVar[int] = _MAX_BASE_BYTES
    _wire_bound_output: ClassVar[bool] = True
    _wire_invalid_bytes: ClassVar[str] = "bytes are invalid"
    _wire_invalid_fields: ClassVar[str] = "fields changed"
    _wire_invalid_encoding: ClassVar[str] = "encoding changed"
    _wire_capacity_label: ClassVar[str | None] = None
    _wire_nested_lists: ClassVar[tuple[str, ...]] = ()
    _wire_error_type: ClassVar[type[Exception]] = ValueError
    _wire_error_code: ClassVar[str | None] = None

    @classmethod
    def _wire_error(cls) -> Exception:
        return cls._wire_error_type(
            cls._wire_error_code or f"{cls._wire_label} {cls._wire_invalid_bytes}"
        )

    @classmethod
    def _wire_maximum(cls) -> int:
        return cls._wire_max_bytes

    def to_bytes(self) -> bytes:
        raw = canonical_json_bytes(self._wire_schema.encode(self))
        if self._wire_bound_output and len(raw) > self._wire_maximum():
            raise ValueError(
                f"{self._wire_capacity_label or self._wire_label} exceeds capacity"
            )
        return raw

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        if type(raw) is not bytes or not raw or len(raw) > cls._wire_maximum():
            raise cls._wire_error()
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value) != cls._wire_schema.keys
                or any(type(value[key]) is not list for key in cls._wire_lists)
                or any(
                    type(item) is not list
                    for key in cls._wire_nested_lists
                    for item in value[key]
                )
            ):
                raise ValueError(f"{cls._wire_label} {cls._wire_invalid_fields}")
            base = cls._wire_schema.decode(cast(Callable[..., Self], cls), value)
            if base.to_bytes() != raw:
                raise ValueError(f"{cls._wire_label} {cls._wire_invalid_encoding}")
            return base
        except cls._wire_errors as error:
            raise cls._wire_error() from error

    _from_wire_bytes = from_bytes


class _SourceBoundBaseWireMethods(_BaseWireMethods):
    """Digest bases share traversal; concrete records retain semantic admission."""

    __slots__ = ()
    _wire_invalid_bytes = _wire_invalid_fields = _wire_invalid_encoding = "is invalid"
    _wire_unsigned_schema: ClassVar[RecordSchema]

    @classmethod
    def _bind_wire_schema(cls, schema: RecordSchema) -> None:
        cls._wire_schema = schema
        cls._wire_unsigned_schema = RecordSchema(
            schema.text_decoder,
            tuple(
                field for field in schema.fields if field.attribute != "record_digest"
            ),
        )

    def _unsigned_dict(self) -> dict[str, object]:
        return self._wire_unsigned_schema.encode(self, sort_keys=True)
