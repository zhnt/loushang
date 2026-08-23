from __future__ import annotations

import pytest

from loushang.harness.resources.plugins._strict_json import (
    PluginJsonCodecError,
    StrictPluginJsonCodec,
)


@pytest.mark.parametrize(
    ("encoded", "code"),
    [
        (b"\xef\xbb\xbf{}", "plugin_declaration_utf8_bom"),
        (b'"\xff"', "plugin_declaration_invalid_utf8"),
        (b'{"value":NaN}', "plugin_declaration_invalid_json_constant"),
        (b'{"value":Infinity}', "plugin_declaration_invalid_json_constant"),
        (b'{"value":1,"value":2}', "plugin_declaration_duplicate_json_key"),
        (b'{"value":', "plugin_declaration_invalid_json"),
        (b'{"value":"\\ud800"}', "plugin_declaration_field_value_mismatch"),
    ],
)
def test_strict_plugin_json_rejects_ambiguous_or_invalid_bytes(
    encoded: bytes,
    code: str,
) -> None:
    with pytest.raises(PluginJsonCodecError) as caught:
        StrictPluginJsonCodec.decode_bytes(encoded)

    assert caught.value.code == code


def test_strict_plugin_json_enforces_the_frozen_depth_limit() -> None:
    accepted = b"[" * 63 + b"{}" + b"]" * 63
    rejected = b"[" * 64 + b"{}" + b"]" * 64

    assert StrictPluginJsonCodec.decode_bytes(accepted) is not None
    with pytest.raises(PluginJsonCodecError) as caught:
        StrictPluginJsonCodec.decode_bytes(rejected)

    assert caught.value.code == "plugin_declaration_json_depth_exceeded"


def test_strict_plugin_json_canonical_bytes_are_stable_and_ascii_escaped() -> None:
    composed = {"text": "\u00e9\u4e2d", "values": [2, 1]}
    decomposed = {"text": "e\u0301\u4e2d", "values": [2, 1]}

    assert StrictPluginJsonCodec.encode(composed) == (
        b'{"text":"\\u00e9\\u4e2d","values":[2,1]}'
    )
    assert StrictPluginJsonCodec.encode(decomposed) == (
        b'{"text":"e\\u0301\\u4e2d","values":[2,1]}'
    )
    assert StrictPluginJsonCodec.encode(composed) != StrictPluginJsonCodec.encode(
        decomposed
    )


def test_strict_plugin_json_checks_canonical_equality_on_request() -> None:
    canonical = b'{"a":1,"b":2}'

    StrictPluginJsonCodec.require_canonical_bytes(canonical, {"b": 2, "a": 1})
    with pytest.raises(PluginJsonCodecError) as caught:
        StrictPluginJsonCodec.require_canonical_bytes(
            b'{"b": 2, "a": 1}\n',
            {"b": 2, "a": 1},
        )

    assert caught.value.code == "plugin_declaration_noncanonical_bytes"
