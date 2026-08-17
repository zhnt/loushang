from __future__ import annotations

import asyncio

from loushang.ai.model import Model, ModelSelection


class _Session:
    def __init__(
        self,
        *,
        current: object | None = None,
        selections: list[object] | None = None,
        details: list[object] | None = None,
    ) -> None:
        self.current = current
        self.selections = list(selections or [])
        self.details = list(details or [])
        self.set_model_calls: list[object] = []

    def get_model_selection(self) -> object | None:
        return self.current

    def get_available_models(self) -> list[object]:
        return self.selections

    def get_available_model_details(self) -> list[object]:
        return self.details

    async def set_model(self, selection: object) -> None:
        self.set_model_calls.append(selection)
        normalized = selection
        if isinstance(selection, Model):
            normalized = ModelSelection(
                endpoint_id="test-endpoint",
                provider=selection.provider_id,
                model_id=selection.id,
            )
        self.current = normalized


class _ScopedSession:
    def __init__(self, scoped_models: object) -> None:
        self.scopedModels = scoped_models


def test_model_label_from_selection_hides_unknown_model() -> None:
    from loushang.ai.model import model_label_from_selection

    assert (
        model_label_from_selection(
            ModelSelection(
                endpoint_id="test-endpoint", provider="unknown", model_id="unknown"
            )
        )
        is None
    )


def test_model_label_from_selection_formats_provider_and_model() -> None:
    from loushang.ai.model import model_label_from_selection

    assert (
        model_label_from_selection(
            ModelSelection(
                endpoint_id="test-endpoint",
                provider="kimi-code",
                model_id="kimi-for-coding",
            )
        )
        == "kimi-code:test-endpoint:kimi-for-coding"
    )


def test_model_selection_normalization_strips_external_identifiers() -> None:
    from loushang.ai.model import normalize_model_selection

    assert normalize_model_selection(
        {
            "provider": " kimi-code ",
            "model_id": " kimi-for-coding ",
            "endpoint_id": " anthropic ",
        }
    ) == ModelSelection(
        provider="kimi-code",
        model_id="kimi-for-coding",
        endpoint_id="anthropic",
    )


def test_current_model_first_preserves_relative_order() -> None:
    from loushang.ai.model import current_model_first

    items = ["provider/a", "provider/b", "provider/a"]

    assert current_model_first(
        items,
        current_label="provider/a",
        label_of=lambda item: item,
    ) == ["provider/a", "provider/a", "provider/b"]


def test_iter_scoped_model_selections_keeps_distinct_endpoints_and_dedupes() -> None:
    from loushang.harness.session.model_selection import iter_scoped_model_selections

    first = ModelSelection(provider="provider", endpoint_id="first", model_id="model")
    duplicate = {"model": first}
    second = ModelSelection(provider="provider", endpoint_id="second", model_id="model")
    session = _ScopedSession([{"model": first}, duplicate, {"model": second}])

    assert asyncio.run(iter_scoped_model_selections(session)) == [first, second]


def test_ensure_usable_session_model_keeps_existing_usable_model() -> None:
    from loushang.coding.model_selection import ensure_usable_session_model

    current = ModelSelection(
        endpoint_id="test-endpoint", provider="kimi-code", model_id="kimi-for-coding"
    )
    session = _Session(current=current)

    result = asyncio.run(ensure_usable_session_model(session))

    assert result == current
    assert session.set_model_calls == []


def test_ensure_usable_session_model_prefers_kimi_coding_anthropic_detail() -> None:
    from loushang.coding.model_selection import ensure_usable_session_model

    preferred = Model(
        id="kimi-for-coding", provider="kimi-code", endpoint="kimi-code-anthropic"
    )
    fallback = Model(
        id="kimi-for-coding",
        provider="kimi-code",
        endpoint="openai-completions:cn:coding",
    )
    session = _Session(
        current=ModelSelection(
            endpoint_id="test-endpoint", provider="unknown", model_id="unknown"
        ),
        details=[fallback, preferred],
    )

    result = asyncio.run(ensure_usable_session_model(session))

    assert result == ModelSelection(
        endpoint_id="test-endpoint", provider="kimi-code", model_id="kimi-for-coding"
    )
    assert session.set_model_calls == [preferred]


def test_ensure_usable_session_model_falls_back_to_available_selection() -> None:
    from loushang.coding.model_selection import ensure_usable_session_model

    fallback = ModelSelection(
        endpoint_id="test-endpoint", provider="kimi-code", model_id="kimi-for-coding"
    )
    session = _Session(
        current=ModelSelection(
            endpoint_id="test-endpoint", provider="unknown", model_id="unknown"
        ),
        selections=[fallback],
    )

    result = asyncio.run(ensure_usable_session_model(session))

    assert result == fallback
    assert session.set_model_calls == [fallback]
