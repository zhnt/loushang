from __future__ import annotations

import asyncio
from dataclasses import dataclass

from loushang.ai.model import ModelSelection
from loushang.harness.session.model_preferences import (
    PreferredModel,
    preferred_model_candidates,
    preferred_model_details,
    preferred_model_selection,
)


@dataclass
class _Detail:
    provider: str
    endpoint: str
    model_id: str


def test_preferred_model_details_preserves_preference_order() -> None:
    details = [
        _Detail("other", "default", "other-model"),
        _Detail("preferred", "endpoint", "model"),
    ]
    preferred = [PreferredModel("preferred", "endpoint", "model")]

    assert preferred_model_details(details, preferred) == [details[1]]


def test_preferred_model_selection_falls_back_to_matching_model() -> None:
    selection = ModelSelection(
        endpoint_id="test-endpoint", provider="preferred", model_id="model"
    )

    assert (
        preferred_model_selection(
            [selection], [PreferredModel("preferred", None, "model")]
        )
        == selection
    )


def test_preferred_model_selection_prioritizes_the_configured_endpoint() -> None:
    other = ModelSelection(provider="preferred", endpoint_id="other", model_id="model")
    preferred = ModelSelection(
        provider="preferred", endpoint_id="endpoint", model_id="model"
    )

    assert (
        preferred_model_selection(
            [other, preferred], [PreferredModel("preferred", "endpoint", "model")]
        )
        == preferred
    )


def test_preferred_model_details_accepts_mapping_values() -> None:
    detail = {
        "provider": "preferred",
        "endpoint_id": "endpoint",
        "model_id": "model",
    }

    assert preferred_model_details(
        [detail], [PreferredModel("preferred", "endpoint", "model")]
    ) == [detail]


def test_preferred_model_candidates_prefers_details_before_selections() -> None:
    detail = _Detail("preferred", "endpoint", "model")

    class Session:
        def get_available_model_details(self):
            return [detail]

        def get_available_models(self):
            raise AssertionError("details should be used first")

    result = asyncio.run(
        preferred_model_candidates(
            Session(), [PreferredModel("preferred", "endpoint", "model")]
        )
    )

    assert result == [detail]
