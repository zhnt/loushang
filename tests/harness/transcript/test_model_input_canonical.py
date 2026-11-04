"""Byte-equivalence regression for the single-pass canonical JSON encoder."""

from __future__ import annotations

import json
import random
from types import MappingProxyType

import pytest

from loushang.foundation.json import JsonValueError, dump_json_value
from loushang.harness.transcript.model_input_types import (
    canonical_model_input_json,
    freeze_model_input_json,
    thaw_model_input_json,
)


def _legacy_canonical(value: object, *, name: str) -> str:
    return dump_json_value(
        thaw_model_input_json(freeze_model_input_json(value, name=name)),
        name=name,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _random_value(rng: random.Random, depth: int) -> object:
    choices = ["none", "bool", "int", "float", "str"]
    if depth > 0:
        choices += ["list", "tuple", "dict", "proxy"]
    kind = rng.choice(choices)
    if kind == "none":
        return None
    if kind == "bool":
        return rng.choice([True, False])
    if kind == "int":
        return rng.randint(-(10**12), 10**12)
    if kind == "float":
        return rng.choice([0.0, -1.5, 3.141592653589793, 1e-300, 1e300, 2.0])
    if kind == "str":
        return rng.choice(
            [
                "",
                "plain",
                "中文内容",
                "emoji 🚀 and combining é",
                'quotes " and \\ and \n\t',
                "\u0000control",
            ]
        )
    if kind in {"list", "tuple"}:
        items = [_random_value(rng, depth - 1) for _ in range(rng.randint(0, 4))]
        return items if kind == "list" else tuple(items)
    mapping = {
        f"key_{index}_{rng.choice(['a', 'z', 'é', '中', '🚀'])}": _random_value(
            rng, depth - 1
        )
        for index in range(rng.randint(0, 4))
    }
    return MappingProxyType(mapping) if kind == "proxy" else mapping


def test_canonical_encoder_matches_freeze_thaw_dump_pipeline() -> None:
    rng = random.Random(20260819)
    samples = [_random_value(rng, depth=4) for _ in range(300)]
    samples += [
        {"nested": [[[{"deep": "value"}]]]},
        {"tuple": (1, "two", (3.0, None))},
        {"empty_list": [], "empty_dict": {}},
        {"floats": [0.1, 1e16, -0.0, 123456789.123456789]},
        {"unicode_keys": {"🚀": 1, "a": 2, "中": 3, "é": 4}},
    ]
    for value in samples:
        expected = _legacy_canonical(value, name="payload")
        assert canonical_model_input_json(value, name="payload") == expected
        assert (
            canonical_model_input_json(json.loads(expected), name="payload") == expected
        )


def test_native_canonical_keeps_shared_values_unicode_and_number_boundaries() -> None:
    shared = {"中文🚀": [-0.0, 5e-324, 1.7976931348623157e308, 2**1024]}
    value = {"first": shared, "second": shared, "\u0000": '"\\\n'}
    assert canonical_model_input_json(value, name="payload") == _legacy_canonical(
        value, name="payload"
    )


def test_canonical_encoder_rejects_the_same_values_with_the_same_errors() -> None:
    cyclic: list[object] = []
    cyclic.append(cyclic)
    with pytest.raises(TypeError, match="must not contain a cycle"):
        canonical_model_input_json(cyclic, name="payload")

    with pytest.raises(TypeError, match="keys must be strings"):
        canonical_model_input_json({1: "value"}, name="payload")

    with pytest.raises(TypeError, match="outside strict JSON"):
        canonical_model_input_json({"raw": b"bytes"}, name="payload")

    with pytest.raises(JsonValueError):
        canonical_model_input_json({"number": float("nan")}, name="payload")

    with pytest.raises(JsonValueError):
        canonical_model_input_json({"text": "\ud800"}, name="payload")


def test_canonical_encoder_rejects_non_exact_string_keys_like_the_pipeline() -> None:
    from enum import StrEnum

    class Label(StrEnum):
        ONE = "one"

    with pytest.raises(JsonValueError, match="keys must be strings"):
        canonical_model_input_json({Label.ONE: "value"}, name="payload")
