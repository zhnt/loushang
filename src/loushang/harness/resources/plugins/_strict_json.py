"""Single strict JSON primitive for inert Plugin package metadata."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from json import JSONDecodeError

_UTF8_BOM = b"\xef\xbb\xbf"
_DEFAULT_MAX_DEPTH = 64


class PluginJsonCodecError(ValueError):
    """Finite diagnostic emitted by the strict Plugin JSON boundary."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class _DuplicateJsonKeyError(ValueError):
    pass


class _InvalidJsonConstantError(ValueError):
    pass


class StrictPluginJsonCodec:
    """Decode and encode Plugin JSON without permissive peer paths."""

    @staticmethod
    def decode_bytes(
        encoded: bytes,
        *,
        max_depth: int = _DEFAULT_MAX_DEPTH,
    ) -> object:
        if not isinstance(encoded, bytes):
            raise TypeError("Strict Plugin JSON input must be bytes")
        if encoded.startswith(_UTF8_BOM):
            raise PluginJsonCodecError(
                "Plugin JSON must not contain a UTF-8 BOM",
                code="plugin_declaration_utf8_bom",
            )
        try:
            text = encoded.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PluginJsonCodecError(
                "Plugin JSON is not valid UTF-8",
                code="plugin_declaration_invalid_utf8",
            ) from exc
        try:
            value = json.loads(
                text,
                object_pairs_hook=_object_without_duplicate_keys,
                parse_constant=_reject_json_constant,
            )
        except _DuplicateJsonKeyError as exc:
            raise PluginJsonCodecError(
                str(exc),
                code="plugin_declaration_duplicate_json_key",
            ) from exc
        except _InvalidJsonConstantError as exc:
            raise PluginJsonCodecError(
                str(exc),
                code="plugin_declaration_invalid_json_constant",
            ) from exc
        except JSONDecodeError as exc:
            raise PluginJsonCodecError(
                f"Plugin JSON syntax is invalid: {exc.msg}",
                code="plugin_declaration_invalid_json",
            ) from exc
        _validate_json_tree(value, max_depth=max_depth)
        return value

    @staticmethod
    def encode(value: object, *, max_depth: int = _DEFAULT_MAX_DEPTH) -> bytes:
        normalized = _normalize_json_value(value)
        _validate_json_tree(normalized, max_depth=max_depth)
        try:
            return json.dumps(
                normalized,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise PluginJsonCodecError(
                "Plugin value cannot be encoded as strict canonical JSON",
                code="plugin_declaration_field_value_mismatch",
            ) from exc

    @classmethod
    def require_canonical_bytes(cls, encoded: bytes, value: object) -> None:
        if encoded != cls.encode(value):
            raise PluginJsonCodecError(
                "Plugin declaration document bytes are not canonical JSON",
                code="plugin_declaration_noncanonical_bytes",
            )


def _object_without_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise _DuplicateJsonKeyError(f"Plugin JSON repeats object key {key!r}")
        document[key] = value
    return document


def _reject_json_constant(value: str) -> object:
    raise _InvalidJsonConstantError(
        f"Plugin JSON contains unsupported numeric constant {value!r}"
    )


def _validate_json_tree(value: object, *, max_depth: int) -> None:
    if not isinstance(max_depth, int) or isinstance(max_depth, bool) or max_depth < 1:
        raise ValueError("Strict Plugin JSON max_depth must be a positive integer")

    def visit(item: object, *, depth: int) -> None:
        if isinstance(item, dict):
            if depth > max_depth:
                _raise_depth_exceeded(max_depth)
            for key, child in item.items():
                _require_unicode_scalars(key)
                visit(child, depth=depth + 1)
            return
        if isinstance(item, list):
            if depth > max_depth:
                _raise_depth_exceeded(max_depth)
            for child in item:
                visit(child, depth=depth + 1)
            return
        if isinstance(item, str):
            _require_unicode_scalars(item)

    visit(value, depth=1)


def _raise_depth_exceeded(max_depth: int) -> None:
    raise PluginJsonCodecError(
        f"Plugin JSON nesting exceeds the maximum depth of {max_depth}",
        code="plugin_declaration_json_depth_exceeded",
    )


def _require_unicode_scalars(value: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise PluginJsonCodecError(
            "Plugin JSON strings must contain only Unicode scalar values",
            code="plugin_declaration_field_value_mismatch",
        )


def _normalize_json_value(value: object) -> object:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PluginJsonCodecError(
                "Plugin JSON numbers must be finite",
                code="plugin_declaration_field_value_mismatch",
            )
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PluginJsonCodecError(
                    "Plugin JSON object keys must be strings",
                    code="plugin_declaration_field_type_mismatch",
                )
            normalized[key] = _normalize_json_value(item)
        return normalized
    if isinstance(value, list | tuple):
        return [_normalize_json_value(item) for item in value]
    raise PluginJsonCodecError(
        "Plugin values must contain only JSON data",
        code="plugin_declaration_field_type_mismatch",
    )


__all__: list[str] = []
