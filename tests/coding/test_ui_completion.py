from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from loushang.ai.model import ModelSelection


class _Session:
    def list_commands(self) -> list[object]:
        return [
            SimpleNamespace(name="model", description="Select model", source="builtin"),
            SimpleNamespace(name="models", description="List models", source="builtin"),
            SimpleNamespace(name="report", description="Show report", source="builtin"),
        ]

    def get_model_selection(self) -> ModelSelection:
        return ModelSelection(
            endpoint_id="test-endpoint", provider="moonshot", model_id="kimi-for-coding"
        )

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


class _SessionWithCwd(_Session):
    def __init__(self, cwd: Path) -> None:
        self.session_manager = SimpleNamespace(get_cwd=lambda: str(cwd))


class _AsyncSession(_Session):
    async def list_commands(self) -> list[object]:
        await asyncio.sleep(0)
        return [SimpleNamespace(name="inspect", description="Inspect asynchronously")]


def test_coding_completion_host_ignores_plain_prompts() -> None:
    from loushang.coding.ui.completion import coding_completion_host

    host = coding_completion_host(_Session())
    assert asyncio.run(host.complete("")) == ()
    assert asyncio.run(host.complete("hello")) == ()


def test_coding_completion_host_lists_matching_slash_commands() -> None:
    from loushang.coding.ui.completion import coding_completion_host
    from loushang.tui import CompletionItem

    completions = asyncio.run(coding_completion_host(_Session()).complete("/mo"))

    assert completions == (
        CompletionItem(
            value="/model", label="/model", description="Select model (builtin)"
        ),
        CompletionItem(
            value="/models", label="/models", description="List models (builtin)"
        ),
        CompletionItem(
            value="/permissions",
            label="/permissions",
            description="Manage pending approvals and session grants (local)",
        ),
    )


def test_coding_completion_host_awaits_session_command_source() -> None:
    from loushang.coding.ui.completion import coding_completion_host

    completions = asyncio.run(coding_completion_host(_AsyncSession()).complete("/ins"))

    assert "/inspect" in {item.value for item in completions}


def test_coding_completion_host_lists_local_commands_missing_from_session() -> None:
    from loushang.coding.ui.completion import coding_completion_host
    from loushang.tui import CompletionItem

    completions = asyncio.run(coding_completion_host(_Session()).complete("/set"))

    assert completions == (
        CompletionItem(
            value="/settings", label="/settings", description="Open settings (local)"
        ),
    )


def test_coding_completion_host_matches_current_input_context() -> None:
    from loushang.coding.ui.completion import coding_completion_host
    from loushang.tui import CompletionItem, CompletionProvider

    provider = asyncio.run(
        coding_completion_host(_Session()).input_provider("/model moon")
    )

    assert provider == CompletionProvider(
        (
            CompletionItem(
                value="/model moonshot:test-endpoint:kimi-for-coding",
                label="moonshot:test-endpoint:kimi-for-coding",
                description="current",
            ),
        )
    )


def test_coding_completion_host_completes_model_argument() -> None:
    from loushang.coding.ui.completion import coding_completion_host
    from loushang.tui import CompletionItem

    completions = asyncio.run(
        coding_completion_host(_Session()).complete("/model moon")
    )

    assert completions == (
        CompletionItem(
            value="/model moonshot:test-endpoint:kimi-for-coding",
            label="moonshot:test-endpoint:kimi-for-coding",
            description="current",
        ),
    )


def test_coding_completion_host_matches_model_argument_by_substring() -> None:
    from loushang.coding.ui.completion import coding_completion_host
    from loushang.tui import CompletionItem

    completions = asyncio.run(coding_completion_host(_Session()).complete("/model gpt"))

    assert completions == (
        CompletionItem(
            value="/model openai:test-endpoint:gpt-5.4",
            label="openai:test-endpoint:gpt-5.4",
        ),
    )


def test_coding_completion_host_does_not_treat_models_query_as_model_selection() -> (
    None
):
    from loushang.coding.ui.completion import coding_completion_host

    assert (
        asyncio.run(coding_completion_host(_Session()).complete("/models moon")) == ()
    )


def test_coding_inline_completion_provider_uses_slash_command_argument_provider() -> (
    None
):
    from loushang.coding.ui.completion import coding_inline_completion_provider

    provider = asyncio.run(
        coding_inline_completion_provider(_Session(), base_path=None)
    )

    assert [item.value for item in provider.complete("/mo")] == [
        "/model",
        "/models",
        "/permissions",
    ]
    assert [item.value for item in provider.complete("/model o")] == [
        "/model openai:test-endpoint:gpt-5.4"
    ]
    assert [item.value for item in provider.complete("/model gpt")] == [
        "/model openai:test-endpoint:gpt-5.4"
    ]


def test_coding_inline_completion_provider_renders_model_argument_group() -> None:
    from loushang.coding.ui.completion import coding_inline_completion_provider
    from loushang.tui import Composer, RenderConstraints, strip_control_sequences

    composer = Composer(prompt="> ")
    provider = asyncio.run(
        coding_inline_completion_provider(_Session(), base_path=None)
    )
    composer.set_completion_provider(provider)

    composer.insert_text("/model gpt")
    result = composer.render(RenderConstraints(width=40, max_height=4))

    assert tuple(strip_control_sequences(line.text) for line in result.lines) == (
        "> /model gpt",
        "",
        "  openai:test-endpoint:gpt",
    )


def test_coding_completion_host_limits_model_argument_context() -> None:
    from loushang.coding.ui.completion import coding_completion_host

    provider = asyncio.run(coding_completion_host(_Session()).input_provider("/model "))

    assert [item.value for item in provider.items] == [
        "/model moonshot:test-endpoint:kimi-for-coding",
        "/model openai:test-endpoint:gpt-5.4",
    ]


def test_coding_inline_completion_provider_uses_explicit_base_path_for_at_files(
    tmp_path: Path,
) -> None:
    from loushang.coding.ui.completion import coding_inline_completion_provider
    from loushang.tui import Composer, RenderConstraints, strip_control_sequences

    (tmp_path / "README.md").write_text("", encoding="utf-8")
    composer = Composer(prompt="> ")
    provider = asyncio.run(
        coding_inline_completion_provider(_SessionWithCwd(tmp_path), base_path=tmp_path)
    )
    composer.set_completion_provider(provider)

    composer.insert_text("@REA")
    composer.refresh_completions(force=True)
    result = composer.render(RenderConstraints(width=36, max_height=4))

    assert tuple(strip_control_sequences(line.text) for line in result.lines) == (
        "> @REA",
        "",
        "  README.md  README.md",
    )

    composer.apply_selected_completion()

    assert composer.value == "@README.md "


def test_coding_inline_completion_provider_recursively_completes_at_file_paths(
    tmp_path: Path,
) -> None:
    from loushang.coding.ui.completion import coding_inline_completion_provider
    from loushang.tui import Composer

    (tmp_path / "src" / "tests").mkdir(parents=True)
    (tmp_path / "src" / "tests" / "test_completion.py").write_text("", encoding="utf-8")
    composer = Composer(prompt="> ")
    provider = asyncio.run(
        coding_inline_completion_provider(_SessionWithCwd(tmp_path), base_path=tmp_path)
    )
    composer.set_completion_provider(provider)

    composer.insert_text("@test")
    composer.refresh_completions(force=True)
    composer.apply_selected_completion()

    assert composer.value == "@src/tests/test_completion.py "


def test_coding_inline_completion_provider_keeps_slash_commands_ahead_of_paths(
    tmp_path: Path,
) -> None:
    from loushang.coding.ui.completion import coding_inline_completion_provider
    from loushang.tui import Composer

    (tmp_path / "model").write_text("", encoding="utf-8")
    composer = Composer(prompt="> ")
    provider = asyncio.run(
        coding_inline_completion_provider(_SessionWithCwd(tmp_path), base_path=tmp_path)
    )
    composer.set_completion_provider(provider)

    composer.insert_text("/mo")
    composer.apply_selected_completion()

    assert composer.value == "/model "


def test_coding_completion_host_lists_quit_and_exit_local_commands() -> None:
    from loushang.coding.ui.completion import coding_completion_host

    host = coding_completion_host(_Session())
    quit_values = {item.value for item in asyncio.run(host.complete("/qu"))}
    exit_values = {item.value for item in asyncio.run(host.complete("/ex"))}

    assert "/quit" in quit_values
    assert "/exit" in exit_values


def test_coding_inline_completion_provider_completes_exit_without_file_fallback(
    tmp_path: Path,
) -> None:
    from loushang.coding.ui.completion import coding_inline_completion_provider
    from loushang.tui import Composer, RenderConstraints, strip_control_sequences

    (tmp_path / "exit").write_text("", encoding="utf-8")
    composer = Composer(prompt="> ")
    provider = asyncio.run(
        coding_inline_completion_provider(_SessionWithCwd(tmp_path), base_path=tmp_path)
    )
    composer.set_completion_provider(provider)

    composer.insert_text("/ex")
    result = composer.render(RenderConstraints(width=40, max_height=4))

    assert tuple(strip_control_sequences(line.text) for line in result.lines) == (
        "> /ex",
        "",
        "  /exit  Quit the conversation (local)",
    )
