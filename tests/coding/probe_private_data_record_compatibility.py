"""Frozen original record values, field order and malformed-input outcomes."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

_REFERENCE = json.loads(
    (
        Path(__file__).parent / "fixtures" / "private_data_record_contracts_v1.json"
    ).read_text()
)["records"]


@pytest.mark.parametrize("reference", _REFERENCE, ids=lambda row: row["class"])
def test_original_private_record_contracts(reference) -> None:
    constructor = getattr(
        importlib.import_module(reference["module"]), reference["class"]
    )
    for index, case in enumerate(reference["cases"]):
        expected = case["expected"]
        document = (
            case["document"]
            if "document" in case
            else {**reference["valid"], **case["changes"]}
        )
        if "value" in expected:
            value = constructor.from_dict(document).to_dict()
            assert value == expected["value"], index
            assert list(value) == expected["keys"], index
        else:
            with pytest.raises(Exception) as result:
                constructor.from_dict(document)
            error = result.value
            assert (
                type(error).__module__ + "." + type(error).__qualname__
                == expected["error_type"]
            ), index
            assert getattr(error, "code", None) == expected["code"], index
            assert str(error) == expected["message"], index
