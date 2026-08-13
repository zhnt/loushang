from __future__ import annotations

import asyncio
from pathlib import Path

from loushang.ai.model import ModelSelection
from loushang.harness.commands import CommandDescriptor
from loushang.harnesstui.completion.host import (
    CatalogCompletionProfile,
    PreparedCatalogCompletionHost,
    build_session_catalog_completion_host,
)
from loushang.tui import CompletionItem, CompletionProvider


def _profile() -> CatalogCompletionProfile:
    return CatalogCompletionProfile(
        model_command_value="/choose-model",
        model_argument_group="Prepared models",
    )


def _host() -> PreparedCatalogCompletionHost:
    async def commands() -> CompletionProvider:
        await asyncio.sleep(0)
        return CompletionProvider(
            (
                CompletionItem(
                    value="/choose-model",
                    label="/choose-model",
                    description="Choose a prepared model",
                ),
                CompletionItem(value="/quit", description="Quit"),
            )
        )

    return PreparedCatalogCompletionHost(
        command_provider_source=commands,
        model_provider_source=lambda: CompletionProvider(
            (CompletionItem(value="provider/model", label="A model"),)
        ),
        profile=_profile(),
    )


def test_prepared_completion_host_builds_model_command_arguments() -> None:
    provider = asyncio.run(_host().slash_provider())

    assert tuple(command.name for command in provider.commands) == (
        "/choose-model",
        "/quit",
    )
    assert provider.commands[0].argument_group == "Prepared models"
    assert [item.value for item in provider.complete("/choose-model pro")] == [
        "/choose-model provider/model"
    ]
    assert [item.value for item in provider.complete("/qui")] == ["/quit"]


def test_prepared_completion_host_limits_input_completion_to_slash_context() -> None:
    host = _host()

    assert asyncio.run(host.complete("plain prompt")) == ()
    assert asyncio.run(host.complete("/choose-model pro")) == (
        CompletionItem(
            value="/choose-model provider/model",
            label="A model",
        ),
    )


def test_prepared_completion_host_optionally_composes_recursive_path_source(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "example.py").write_text("", encoding="utf-8")

    slash_only = asyncio.run(_host().inline_provider())
    combined = asyncio.run(_host().inline_provider(base_path=tmp_path))

    assert [item.value for item in slash_only.complete("/qui")] == ["/quit"]
    suggestions = combined.get_suggestions(("@example",), 0, len("@example"))
    assert suggestions is not None
    assert [item.value for item in suggestions.items] == ["@src/example.py"]


def test_session_completion_host_binds_structural_product_catalogs() -> None:
    class Session:
        async def list_commands(self) -> list[CommandDescriptor[object]]:
            return [
                CommandDescriptor(
                    name="choose-model",
                    invocation_name="choose-model",
                    description="Choose a model",
                    source="research",
                ),
                CommandDescriptor(
                    name="inspect",
                    invocation_name="inspect",
                    description="Inspect a source",
                    source="research",
                ),
            ]

        async def get_available_models(self) -> list[ModelSelection]:
            return [
                ModelSelection(
                    provider="provider",
                    endpoint_id="test-endpoint",
                    model_id="research",
                )
            ]

    host = build_session_catalog_completion_host(Session(), profile=_profile())

    assert [item.value for item in asyncio.run(host.complete("/insp"))] == ["/inspect"]
    assert [item.value for item in asyncio.run(host.complete("/choose-model res"))] == [
        "/choose-model provider:test-endpoint:research"
    ]
    # Quit/exit are default local conversation commands, not session commands.
    assert {item.value for item in asyncio.run(host.complete("/qu"))} >= {"/quit"}
    assert {item.value for item in asyncio.run(host.complete("/ex"))} >= {"/exit"}
