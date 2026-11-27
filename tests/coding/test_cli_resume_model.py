from __future__ import annotations

import asyncio
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from loushang.ai.model import ModelSelection, normalize_model_selection
from loushang.ai.types import ProviderCompactionWindow, UserMessage
from loushang.coding.cli.application import run_cli
from loushang.coding.composition.bootstrap import (
    create_agent_session_runtime,
    create_services,
)
from loushang.harness.transcript import build_agent_transcript_session_context
from loushang.harness.transcript.jsonl_file import load_agent_transcript_file


@pytest.fixture(autouse=True)
def isolated_coding_home(monkeypatch: pytest.MonkeyPatch):
    # Linux store admission isolates state from the transcript's parent, too.
    with TemporaryDirectory(prefix="loushang-resume-model-platform-") as platform_home:
        monkeypatch.setenv("LOUSHANG_HOME", platform_home)
        yield


async def _saved_history(
    tmp_path: Path,
    saved: ModelSelection,
    *,
    provider_checkpoint: bool = False,
) -> tuple[str, Path]:
    source = create_agent_session_runtime(
        session_dir=tmp_path / "sessions",
        services=create_services(),
    )
    try:
        original = await source.create_session(cwd=str(tmp_path))
        manager = original.session_manager
        await manager.append_model_change(
            saved.provider,
            saved.model_id,
            endpoint_id=saved.endpoint_id,
        )
        kept_id = await manager.append_message(
            UserMessage(role="user", content="Retain this history", timestamp=1.0)
        )
        if provider_checkpoint:
            await manager.append_compaction(
                "Provider checkpoint",
                kept_id,
                100,
                provider_window=ProviderCompactionWindow.from_items(
                    provider=saved.provider,
                    endpoint=saved.endpoint_id,
                    model=saved.model_id,
                    items=[{"type": "compaction", "encrypted_content": "opaque"}],
                ),
            )
        return manager.get_header().conversation_id, manager.session_file
    finally:
        await source.dispose_session_runtime()


@pytest.mark.parametrize("saved_model", ["removed-chat", "deepseek-v4-pro"])
@pytest.mark.parametrize("resume_flag", ["--resume", "--session", "--continue"])
def test_cli_restores_history_with_explicit_replacement_model(
    tmp_path: Path,
    saved_model: str,
    resume_flag: str,
) -> None:
    async def scenario() -> None:
        sessions = tmp_path / "sessions"
        session_id, session_file = await _saved_history(
            tmp_path,
            ModelSelection("deepseek", "openai-completions", saved_model),
        )
        replacement = ModelSelection("deepseek", "openai-completions", "deepseek-flash")
        seen = []

        async def print_runner(**kwargs):
            session = kwargs["session"]
            seen.append(session.session_id)
            assert session.session_id == session_id
            assert normalize_model_selection(session.agent.model) == replacement
            context = session.session_manager.build_session_context()
            assert context.model == {
                "provider": replacement.provider,
                "endpoint_id": replacement.endpoint_id,
                "model_id": replacement.model_id,
            }
            assert any(
                getattr(message, "content", None) == "Retain this history"
                for message in session.messages
            )
            return 0

        selection = [resume_flag]
        if resume_flag != "--continue":
            selection.append(session_id)
        stderr = StringIO()
        result = await run_cli(
            [
                "--mode",
                "json",
                "--session-dir",
                str(sessions),
                *selection,
                "--model",
                "deepseek:openai-completions:deepseek-flash",
                "hello",
            ],
            cwd=tmp_path,
            stdin=StringIO(),
            stdout=StringIO(),
            stderr=stderr,
            services=create_services(),
            print_runner=print_runner,
        )
        assert result == 0, stderr.getvalue()
        assert seen == [session_id]
        # Replay persisted bytes without opening another writer on an owned store.
        _, records = load_agent_transcript_file(
            session_file,
            read_only=True,
        )
        restored = build_agent_transcript_session_context(records)
        assert restored.model["model_id"] == replacement.model_id

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "replacement", [None, "deepseek:openai-completions:also-removed"]
)
def test_cli_requires_a_valid_explicit_replacement_for_missing_saved_model(
    tmp_path: Path,
    replacement: str | None,
) -> None:
    async def scenario() -> None:
        session_id, session_file = await _saved_history(
            tmp_path,
            ModelSelection("deepseek", "openai-completions", "removed-chat"),
        )
        before = session_file.read_bytes()
        stderr = StringIO()

        async def print_runner(**kwargs):
            pytest.fail("An unresolved model must not reach a model runner")

        result = await run_cli(
            [
                "--mode",
                "json",
                "--session-dir",
                str(tmp_path / "sessions"),
                "--resume",
                session_id,
                *(["--model", replacement] if replacement is not None else []),
                "hello",
            ],
            cwd=tmp_path,
            stdin=StringIO(),
            stdout=StringIO(),
            stderr=stderr,
            services=create_services(),
            print_runner=print_runner,
        )
        assert result == 1
        assert "removed" in stderr.getvalue()
        assert session_file.read_bytes() == before

    asyncio.run(scenario())


def test_cli_replacement_preserves_provider_checkpoint_route_guard(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        session_id, session_file = await _saved_history(
            tmp_path,
            ModelSelection("openai", "openai-responses", "gpt-6.2-sol"),
            provider_checkpoint=True,
        )
        before = session_file.read_bytes()
        stderr = StringIO()
        result = await run_cli(
            [
                "--mode",
                "json",
                "--session-dir",
                str(tmp_path / "sessions"),
                "--resume",
                session_id,
                "--model",
                "deepseek:openai-completions:deepseek-flash",
                "hello",
            ],
            cwd=tmp_path,
            stdin=StringIO(),
            stdout=StringIO(),
            stderr=stderr,
            services=create_services(),
        )
        assert result == 1
        assert "requires its original model route" in stderr.getvalue()
        assert session_file.read_bytes() == before

    asyncio.run(scenario())


def test_cli_keeps_available_saved_model_without_an_override(tmp_path: Path) -> None:
    async def scenario() -> None:
        saved = ModelSelection("deepseek", "openai-completions", "deepseek-v4-pro")
        session_id, _ = await _saved_history(tmp_path, saved)
        seen = []

        async def print_runner(**kwargs):
            selection = normalize_model_selection(kwargs["session"].agent.model)
            seen.append(selection)
            assert selection == saved
            return 0

        stderr = StringIO()
        result = await run_cli(
            [
                "--mode",
                "json",
                "--session-dir",
                str(tmp_path / "sessions"),
                "--resume",
                session_id,
                "hello",
            ],
            cwd=tmp_path,
            stdin=StringIO(),
            stdout=StringIO(),
            stderr=stderr,
            services=create_services(),
            print_runner=print_runner,
        )
        assert result == 0, stderr.getvalue()
        assert seen == [saved]

    asyncio.run(scenario())
