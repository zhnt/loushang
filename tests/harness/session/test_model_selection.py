from __future__ import annotations

import asyncio
from types import SimpleNamespace

from loushang.ai.model import Model, ModelSelection
from loushang.harness.session.model_selection import (
    __all__ as model_selection_exports,
)
from loushang.harness.session.model_selection import (
    apply_session_model_selection,
    ensure_usable_session_model,
    format_model_metadata_table,
    iter_available_model_details,
    model_choice_data_from_details,
    model_identity_data,
    model_listing_matches_query,
    normalize_model_listing,
    unique_sorted_model_entries,
)


class _Session:
    def __init__(self) -> None:
        self.current: object | None = None
        self.applied: list[object] = []

    async def set_model(self, selection: object) -> None:
        self.applied.append(selection)
        self.current = selection

    def get_model_selection(self) -> object | None:
        return self.current


def test_apply_session_model_selection_uses_product_persistence_callback() -> None:
    session = _Session()
    persisted: list[ModelSelection] = []
    result = asyncio.run(
        apply_session_model_selection(
            session,
            {
                "provider": "example",
                "endpoint_id": "responses",
                "model_id": "model",
            },
            persist=persisted.append,
        )
    )

    assert result.persisted is True
    assert session.applied == [
        ModelSelection(endpoint_id="responses", provider="example", model_id="model")
    ]
    assert persisted == [
        ModelSelection(endpoint_id="responses", provider="example", model_id="model")
    ]


def test_ensure_usable_session_model_uses_product_candidate_policy() -> None:
    session = _Session()
    candidate = ModelSelection(
        endpoint_id="test-endpoint", provider="example", model_id="first"
    )

    result = asyncio.run(
        ensure_usable_session_model(session, candidates=lambda _: [candidate])
    )

    assert result == candidate
    assert session.applied == [candidate]


def test_model_listing_normalizes_dedupes_and_formats_shared_values() -> None:
    raw = [
        SimpleNamespace(
            provider="openai",
            endpoint_id="responses",
            model_id="gpt-5",
            context_window=1_000_000,
            max_tokens=4096,
            reasoning=True,
            supports_image_input=True,
        ),
        SimpleNamespace(provider="openai", endpoint_id="responses", model_id="gpt-5"),
        SimpleNamespace(
            provider="anthropic", endpoint_id="messages", model_id="claude-3"
        ),
    ]

    entries = normalize_model_listing(
        unique_sorted_model_entries(raw), include_metadata=True
    )

    assert [entry["id"] for entry in entries] == [
        "anthropic:messages:claude-3",
        "openai:responses:gpt-5",
    ]
    assert model_listing_matches_query(entries[1], "og5")
    assert format_model_metadata_table(entries).splitlines()[0].startswith("provider")


def test_model_listing_accepts_mapping_details() -> None:
    entries = normalize_model_listing(
        [
            {
                "provider": "openai",
                "endpoint_id": "responses",
                "model_id": "gpt-5",
                "context_window": 128_000,
                "supports_thinking": True,
            }
        ],
        include_metadata=True,
    )

    assert entries == [
        {
            "provider": "openai",
            "endpoint_id": "responses",
            "model_id": "gpt-5",
            "id": "openai:responses:gpt-5",
            "context_window": 128_000,
            "max_tokens": None,
            "supports_thinking": True,
            "supports_images": False,
        }
    ]


def test_available_model_details_accepts_one_shot_iterables() -> None:
    detail = SimpleNamespace(provider="openai", model_id="gpt-5")
    session = SimpleNamespace(get_available_model_details=lambda: iter([detail]))

    assert asyncio.run(iter_available_model_details(session)) == [detail]


def test_model_choice_data_projects_ai_details_without_tui_dependency() -> None:
    detail = Model(
        id="gpt-5",
        provider="openai",
        endpoint="responses",
        api="responses",
        preferred_endpoint=True,
        name="General model",
    )

    choices = model_choice_data_from_details([detail])

    assert choices[0].value == "openai:responses:gpt-5"
    assert choices[0].preferred_endpoint is True
    assert (
        model_identity_data(
            ModelSelection(provider="openai", endpoint_id="responses", model_id="gpt-5")
        ).value
        == "openai:responses:gpt-5"
    )


def test_model_selection_module_exports_all_public_selection_helpers() -> None:
    assert {
        "get_session_model_identity",
        "iter_available_model_details",
        "model_choice_data_from_selections",
    } <= set(model_selection_exports)
