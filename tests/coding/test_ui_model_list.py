from __future__ import annotations

import asyncio
from types import SimpleNamespace

from loushang.ai.model import ModelSelection


class _Session:
    def __init__(self) -> None:
        self.set_model_calls: list[ModelSelection] = []
        self.default_model_calls: list[tuple[ModelSelection | None, str]] = []
        self.settings_manager = self
        self.selection = ModelSelection(
            endpoint_id="test-endpoint", provider="moonshot", model_id="kimi-for-coding"
        )

    def get_model_selection(self) -> ModelSelection:
        return self.selection

    def get_available_models(self) -> list[object]:
        return [
            ModelSelection(
                endpoint_id="test-endpoint",
                provider="moonshot",
                model_id="kimi-for-coding",
            ),
            ModelSelection(
                endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4"
            ),
        ]

    async def set_model(self, selection: ModelSelection) -> None:
        self.set_model_calls.append(selection)
        self.selection = selection

    def set_default_model(
        self,
        selection: ModelSelection | None,
        *,
        scope: str = "session",
    ) -> None:
        self.default_model_calls.append((selection, scope))


class _CurrentSecondSession(_Session):
    def __init__(self) -> None:
        super().__init__()
        self.selection = ModelSelection(
            endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4"
        )


class _AmbiguousSession(_Session):
    def get_available_models(self) -> list[object]:
        return [
            ModelSelection(
                endpoint_id="test-endpoint",
                provider="moonshot",
                model_id="kimi-for-coding",
            ),
            ModelSelection(
                endpoint_id="test-endpoint", provider="moonshot", model_id="kimi-latest"
            ),
            ModelSelection(
                endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4"
            ),
        ]


class _EmptySession(_Session):
    def get_available_models(self) -> list[object]:
        return []


class _SessionWithModelDetails(_Session):
    def get_available_model_details(self) -> list[object]:
        return [
            SimpleNamespace(
                provider_id="openai",
                endpoint_id="test-endpoint",
                id="gpt-5.4",
                name="Strong model for everyday coding.",
            )
        ]


class _DuplicateEndpointSession(_Session):
    def __init__(self) -> None:
        super().__init__()
        self.model_details = [
            SimpleNamespace(
                provider_id="dashscope",
                endpoint_id="openai-responses",
                id="qwen3.6-plus",
                api="openai-responses",
                region="cn",
                preferred_endpoint=True,
                name="Qwen 3.6 Plus",
            ),
            SimpleNamespace(
                provider_id="dashscope",
                endpoint_id="openai-completions:cn",
                id="qwen3.6-plus",
                api="openai-completions",
                region="cn",
                lane="coding",
                name="Qwen 3.6 Plus",
            ),
        ]

    def get_available_models(self) -> list[object]:
        return [
            ModelSelection(
                endpoint_id="openai-responses",
                provider="dashscope",
                model_id="qwen3.6-plus",
            ),
            ModelSelection(
                endpoint_id="openai-completions:cn",
                provider="dashscope",
                model_id="qwen3.6-plus",
            ),
        ]

    def get_available_model_details(self) -> list[object]:
        return self.model_details


class _DuplicateEndpointCurrentSession(_DuplicateEndpointSession):
    def __init__(self) -> None:
        super().__init__()
        self.selection = self.model_details[1]


class _DuplicateEndpointAgentModelSession(_DuplicateEndpointSession):
    def __init__(self) -> None:
        super().__init__()
        self.selection = ModelSelection(
            endpoint_id="openai-responses",
            provider="dashscope",
            model_id="qwen3.6-plus",
        )
        self.agent = SimpleNamespace(model=self.model_details[1])


class _AmbiguousDuplicateEndpointSession(_DuplicateEndpointSession):
    def __init__(self) -> None:
        super().__init__()
        for detail in self.model_details:
            detail.preferred_endpoint = False


def test_model_choice_is_the_shared_harnesstui_view_model() -> None:
    from loushang.harnesstui.selection.catalog import ModelChoice
    from loushang.harnesstui.selection.catalog import ModelChoice as CodingModelChoice

    assert CodingModelChoice is ModelChoice


def test_format_available_models_marks_current_model() -> None:
    from loushang.harnesstui.selection.binding import (
        format_available_session_models as format_available_models,
    )

    text = asyncio.run(format_available_models(_Session()))

    assert text == (
        "Available models:\n"
        "* moonshot:test-endpoint:kimi-for-coding (current)\n"
        "  openai:test-endpoint:gpt-5.4"
    )


def test_format_available_models_filters_by_query() -> None:
    from loushang.harnesstui.selection.binding import (
        format_available_session_models as format_available_models,
    )

    text = asyncio.run(format_available_models(_Session(), query="gpt"))

    assert text == "Available models:\n  openai:test-endpoint:gpt-5.4"


def test_format_available_models_lists_current_model_first() -> None:
    from loushang.harnesstui.selection.binding import (
        format_available_session_models as format_available_models,
    )

    text = asyncio.run(format_available_models(_CurrentSecondSession()))

    assert text == (
        "Available models:\n"
        "* openai:test-endpoint:gpt-5.4 (current)\n"
        "  moonshot:test-endpoint:kimi-for-coding"
    )


def test_format_available_models_reports_empty_matches() -> None:
    from loushang.harnesstui.selection.binding import (
        format_available_session_models as format_available_models,
    )

    text = asyncio.run(format_available_models(_Session(), query="missing"))

    assert text == "No models match: missing"


def test_format_available_models_keeps_longer_substring_with_exact_label() -> None:
    from loushang.harnesstui.selection.binding import (
        format_available_session_models as format_available_models,
    )

    class _FormattingSession(_Session):
        def get_available_models(self) -> list[object]:
            return [
                ModelSelection(
                    endpoint_id="test-endpoint", provider="provider", model_id="model"
                ),
                ModelSelection(
                    endpoint_id="test-endpoint",
                    provider="provider",
                    model_id="model-plus",
                ),
            ]

    text = asyncio.run(
        format_available_models(_FormattingSession(), query="provider:model")
    )

    assert text == (
        "Available models:\n"
        "  provider:test-endpoint:model\n"
        "  provider:test-endpoint:model-plus"
    )


def test_available_model_completion_provider_exposes_structured_items() -> None:
    from loushang.harnesstui.selection.binding import (
        available_session_model_completion_provider as available_model_completion_provider,
    )
    from loushang.tui import CompletionItem, CompletionProvider

    provider = asyncio.run(available_model_completion_provider(_Session()))

    assert provider == CompletionProvider(
        (
            CompletionItem(
                value="moonshot:test-endpoint:kimi-for-coding",
                label="moonshot:test-endpoint:kimi-for-coding",
                description="current",
            ),
            CompletionItem(
                value="openai:test-endpoint:gpt-5.4",
                label="openai:test-endpoint:gpt-5.4",
            ),
        )
    )


def test_available_model_completion_provider_uses_model_detail_descriptions() -> None:
    from loushang.harnesstui.selection.binding import (
        available_session_model_completion_provider as available_model_completion_provider,
    )
    from loushang.tui import CompletionItem, CompletionProvider

    provider = asyncio.run(
        available_model_completion_provider(_SessionWithModelDetails())
    )

    assert provider == CompletionProvider(
        (
            CompletionItem(
                value="moonshot:test-endpoint:kimi-for-coding",
                label="moonshot:test-endpoint:kimi-for-coding",
                description="current",
            ),
            CompletionItem(
                value="openai:test-endpoint:gpt-5.4",
                label="openai:test-endpoint:gpt-5.4",
                description="Strong model for everyday coding.",
            ),
        )
    )


def test_available_model_completion_provider_lists_current_model_first() -> None:
    from loushang.harnesstui.selection.binding import (
        available_session_model_completion_provider as available_model_completion_provider,
    )

    provider = asyncio.run(available_model_completion_provider(_CurrentSecondSession()))

    assert [item.value for item in provider.items] == [
        "openai:test-endpoint:gpt-5.4",
        "moonshot:test-endpoint:kimi-for-coding",
    ]
    assert provider.items[0].description == "current"


def test_select_available_model_sets_unique_match() -> None:
    from loushang.coding.model_selection_tui import select_available_model

    session = _Session()
    text = asyncio.run(select_available_model(session, query="gpt"))

    assert text == "Model set: openai:test-endpoint:gpt-5.4"
    selection = ModelSelection(
        endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4"
    )
    assert session.set_model_calls == [selection]
    assert session.default_model_calls == [(selection, "global")]


def test_select_available_model_lists_models_when_query_is_empty() -> None:
    from loushang.coding.model_selection_tui import select_available_model

    session = _Session()
    text = asyncio.run(select_available_model(session, query=""))

    assert text == (
        "Available models:\n"
        "* moonshot:test-endpoint:kimi-for-coding (current)\n"
        "  openai:test-endpoint:gpt-5.4"
    )
    assert session.set_model_calls == []


def test_select_available_model_uses_injected_palette_chooser() -> None:
    from loushang.coding.model_selection_tui import select_available_model
    from loushang.tui import CommandPalette

    session = _Session()
    seen: list[CommandPalette] = []

    async def choose(palette: CommandPalette) -> str:
        seen.append(palette)
        return "openai:test-endpoint:gpt-5.4"

    text = asyncio.run(select_available_model(session, query="", choose=choose))

    assert text == "Model set: openai:test-endpoint:gpt-5.4"
    assert session.set_model_calls == [
        ModelSelection(
            endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4"
        )
    ]
    assert seen
    assert [item.value for item in seen[0].items] == [
        "moonshot:test-endpoint:kimi-for-coding",
        "openai:test-endpoint:gpt-5.4",
    ]


def test_select_available_model_reports_cancelled_palette_choice() -> None:
    from loushang.coding.model_selection_tui import select_available_model

    session = _Session()

    text = asyncio.run(
        select_available_model(session, query="", choose=lambda _palette: None)
    )

    assert text == "Model selection cancelled."
    assert session.set_model_calls == []


def test_select_available_model_passes_empty_palette_to_chooser() -> None:
    from loushang.coding.model_selection_tui import select_available_model
    from loushang.tui import CommandPalette

    session = _EmptySession()
    seen: list[CommandPalette] = []

    def choose(palette: CommandPalette) -> None:
        seen.append(palette)

    text = asyncio.run(select_available_model(session, choose=choose))

    assert text == "Model selection cancelled."
    assert len(seen) == 1
    assert seen[0].items == ()
    assert session.set_model_calls == []


def test_select_available_model_reports_ambiguous_matches_with_hint() -> None:
    from loushang.coding.model_selection_tui import select_available_model

    session = _AmbiguousSession()
    text = asyncio.run(select_available_model(session, query="moonshot"))

    assert text == (
        "Multiple models match:\n"
        "  moonshot:test-endpoint:kimi-for-coding\n"
        "  moonshot:test-endpoint:kimi-latest\n"
        "Use /model <provider:endpoint:model> or choose one from the model list."
    )
    assert session.set_model_calls == []


def test_select_available_model_uses_full_identity_for_duplicate_endpoint_choice() -> (
    None
):
    from loushang.coding.model_selection_tui import select_available_model

    session = _DuplicateEndpointSession()
    text = asyncio.run(
        select_available_model(
            session,
            query="dashscope:openai-responses:qwen3.6-plus",
        )
    )

    assert text == "Model set: dashscope:openai-responses:qwen3.6-plus"
    selection = ModelSelection(
        provider="dashscope",
        endpoint_id="openai-responses",
        model_id="qwen3.6-plus",
    )
    assert session.set_model_calls == [selection]
    assert session.default_model_calls == [(selection, "global")]


def test_select_available_model_does_not_guess_preferred_endpoint_for_shorthand() -> (
    None
):
    from loushang.coding.model_selection_tui import select_available_model

    session = _DuplicateEndpointSession()
    text = asyncio.run(select_available_model(session, query="dashscope:qwen3.6-plus"))

    assert text == (
        "Multiple models match:\n"
        "  dashscope:openai-responses:qwen3.6-plus\n"
        "  dashscope:openai-completions:cn:qwen3.6-plus\n"
        "Use /model <provider:endpoint:model> or choose one from the model list."
    )
    assert session.set_model_calls == []


def test_select_available_model_reports_duplicate_endpoint_label_as_ambiguous_without_preferred() -> (
    None
):
    from loushang.coding.model_selection_tui import select_available_model

    session = _AmbiguousDuplicateEndpointSession()
    text = asyncio.run(select_available_model(session, query="dashscope:qwen3.6-plus"))

    assert text == (
        "Multiple models match:\n"
        "  dashscope:openai-responses:qwen3.6-plus\n"
        "  dashscope:openai-completions:cn:qwen3.6-plus\n"
        "Use /model <provider:endpoint:model> or choose one from the model list."
    )
    assert session.set_model_calls == []


def test_available_model_completion_provider_marks_only_current_endpoint() -> None:
    from loushang.harnesstui.selection.binding import (
        available_session_model_completion_provider as available_model_completion_provider,
    )

    provider = asyncio.run(
        available_model_completion_provider(_DuplicateEndpointCurrentSession())
    )

    assert [item.value for item in provider.items] == [
        "dashscope:openai-completions:cn:qwen3.6-plus",
        "dashscope:openai-responses:qwen3.6-plus",
    ]
    assert (
        provider.items[0].description
        == "current - region: cn - lane: coding - protocol: openai-completions - Qwen 3.6 Plus"
    )
    assert (
        provider.items[1].description
        == "region: cn - protocol: openai-responses - Qwen 3.6 Plus"
    )


def test_available_model_completion_provider_uses_agent_model_endpoint_for_current() -> (
    None
):
    from loushang.harnesstui.selection.binding import (
        available_session_model_completion_provider as available_model_completion_provider,
    )

    provider = asyncio.run(
        available_model_completion_provider(_DuplicateEndpointAgentModelSession())
    )

    assert [item.value for item in provider.items] == [
        "dashscope:openai-completions:cn:qwen3.6-plus",
        "dashscope:openai-responses:qwen3.6-plus",
    ]
    assert (
        provider.items[0].description
        == "current - region: cn - lane: coding - protocol: openai-completions - Qwen 3.6 Plus"
    )
    assert (
        provider.items[1].description
        == "region: cn - protocol: openai-responses - Qwen 3.6 Plus"
    )


def test_available_model_completion_provider_keeps_every_endpoint() -> None:
    from loushang.harnesstui.selection.binding import (
        available_session_model_completion_provider as available_model_completion_provider,
    )

    provider = asyncio.run(
        available_model_completion_provider(_DuplicateEndpointSession())
    )

    assert [item.value for item in provider.items] == [
        "dashscope:openai-responses:qwen3.6-plus",
        "dashscope:openai-completions:cn:qwen3.6-plus",
    ]
    assert (
        provider.items[0].description
        == "region: cn - protocol: openai-responses - Qwen 3.6 Plus"
    )
    assert (
        provider.items[1].description
        == "region: cn - lane: coding - protocol: openai-completions - Qwen 3.6 Plus"
    )
