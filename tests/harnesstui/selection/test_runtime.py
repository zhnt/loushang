from __future__ import annotations

import asyncio

from loushang.harnesstui.selection.catalog import ModelChoice
from loushang.harnesstui.selection.runtime import (
    available_model_completion_provider,
    format_available_models,
    select_available_model,
)
from loushang.tui import CompletionItem, CompletionProvider


class _Port:
    def __init__(self) -> None:
        self.choices = (
            ModelChoice(label="moonshot/kimi", value="moonshot/kimi", selection="kimi"),
            ModelChoice(label="openai/gpt-5", value="openai/gpt-5", selection="gpt"),
        )
        self.applied: list[object] = []

    async def available_choices(self) -> tuple[ModelChoice, ...]:
        return self.choices

    def current_value(self, choices: tuple[ModelChoice, ...]) -> str | None:
        return "moonshot/kimi" if choices else None

    async def apply_selection(self, selection: object) -> object:
        self.applied.append(selection)
        return selection


def test_runtime_formats_and_completes_normalized_choices() -> None:
    port = _Port()

    assert asyncio.run(format_available_models(port, query="gpt")) == (
        "Available models:\n  openai/gpt-5"
    )
    assert asyncio.run(available_model_completion_provider(port)) == CompletionProvider(
        (
            CompletionItem(
                value="moonshot/kimi",
                label="moonshot/kimi",
                description="current",
            ),
            CompletionItem(value="openai/gpt-5", label="openai/gpt-5"),
        )
    )


def test_runtime_applies_selected_value_through_explicit_port() -> None:
    port = _Port()

    result = asyncio.run(select_available_model(port, query="gpt"))

    assert result == "Model set: openai/gpt-5"
    assert port.applied == ["gpt"]


def test_runtime_uses_injected_persistence_warning() -> None:
    port = _Port()

    result = asyncio.run(
        select_available_model(
            port,
            query="gpt",
            persistence_warning=lambda _result: "could not persist",
        )
    )

    assert result == "Model set: openai/gpt-5, but could not persist"
