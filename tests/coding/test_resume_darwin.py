from __future__ import annotations

import asyncio
import sys
from contextlib import contextmanager
from io import StringIO

import pytest

from loushang.ai.types import UserMessage
from loushang.coding.bootstrap import (
    create_agent_session_runtime,
    create_services,
)
from loushang.coding.composition_provenance import startup_composition_record
from loushang.harness.config.agent import ControlConfig, SettingsManager
from loushang.harness.transcript import load_agent_transcript_file


class _TTY(StringIO):
    def isatty(self) -> bool:
        return True


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="native macOS same-ID Resume evidence",
)
def test_darwin_resume_uses_current_resources_without_rewriting_history(
    tmp_path,
    monkeypatch,
    record_testsuite_property,
):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agents = workspace / "AGENTS.md"
    agents.write_text("Initial workspace instructions.\n", encoding="utf-8")
    skill = workspace / "skills" / "review" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: review\ndescription: Review code\n---\nReview carefully.\n",
        encoding="utf-8",
    )
    session_dir = tmp_path / "home/data/sessions"
    record_testsuite_property("native_platform", sys.platform)
    record_testsuite_property("resume_route", "session-lifecycle")

    async def scenario():
        original_runtime = create_agent_session_runtime(
            session_dir=session_dir,
            composition_set="coding-standard",
        )
        assert original_runtime._owned_transcript_factory is None
        try:
            original = await original_runtime.create_session(cwd=str(workspace))
            await original.session_manager.append_message(
                UserMessage(role="user", content="before resource change", timestamp=1.0)
            )
            session_file = original.session_manager.session_file
            assert session_file is not None
            session_id = original.session_id
            header = original.session_manager.header
            historical_receipt = startup_composition_record(
                original.session_manager.get_entries()
            )
            assert historical_receipt is not None
        finally:
            await original_runtime.dispose_session_runtime()

        agents.write_text("Updated workspace instructions.\n", encoding="utf-8")
        changed_services = create_services(
            settings_manager=SettingsManager(
                ControlConfig(disabled_skills=("review",))
            )
        )
        resumed_runtime = create_agent_session_runtime(
            session_dir=session_dir,
            composition_set="coding-standard",
            services=changed_services,
        )
        assert resumed_runtime._owned_transcript_factory is None
        try:
            resumed = await resumed_runtime.restore_session(session_file)
            assert resumed.session_id == session_id
            current_receipt = resumed._build_current_coding_composition_receipt()
            assert (
                current_receipt["catalogSelectionFingerprint"]
                != historical_receipt["catalogSelectionFingerprint"]
            )
            before_prepare = session_file.read_bytes()
            await resumed.prepare_model_call_runtime()
            assert session_file.read_bytes() == before_prepare
            await resumed.session_manager.append_message(
                UserMessage(role="user", content="after resource change", timestamp=2.0)
            )
        finally:
            await resumed_runtime.dispose_session_runtime()

        restored_header, records = load_agent_transcript_file(
            session_file,
            read_only=True,
        )
        assert restored_header == header
        assert [
            record.payload.content
            for record in records
            if isinstance(record.payload, UserMessage)
        ] == ["before resource change", "after resource change"]

    asyncio.run(scenario())


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="native macOS command-line Resume evidence",
)
def test_darwin_command_line_resume_uses_session_lifecycle(
    tmp_path,
    monkeypatch,
    record_testsuite_property,
):
    from loushang.coding.cli import screen_startup
    from loushang.coding.runtime.agent_session_runtime import AgentSessionRuntime
    from loushang.harnesstui.conversation.startup_host import (
        ScreenConversationStartup,
    )
    from loushang.tui.terminal import TerminalSize

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agents = workspace / "AGENTS.md"
    agents.write_text("Initial workspace instructions.\n", encoding="utf-8")
    session_dir = tmp_path / "home/data/sessions"
    record_testsuite_property("native_platform", sys.platform)
    record_testsuite_property("resume_route", "session-lifecycle")

    async def scenario():
        original_runtime = create_agent_session_runtime(
            session_dir=session_dir,
            composition_set="coding-minimal",
        )
        try:
            original = await original_runtime.create_session(cwd=str(workspace))
            await original.session_manager.append_message(
                UserMessage(role="user", content="before resource change", timestamp=1.0)
            )
            session_file = original.session_manager.session_file
            assert session_file is not None
            session_id = original.session_id
        finally:
            await original_runtime.dispose_session_runtime()

        agents.write_text("Updated workspace instructions.\n", encoding="utf-8")
        restore_calls = []
        original_restore = AgentSessionRuntime.restore_session_operation

        async def observe_restore(self, session_ref, **kwargs):
            result = await original_restore(self, session_ref, **kwargs)
            restore_calls.append(result.current)
            return result

        async def forbid_separate_history_protocol(self, session_ref):
            raise AssertionError(
                "macOS command-line Resume selected a separate history protocol "
                f"for {session_ref}"
            )

        @contextmanager
        def terminal(_stdin, _stdout):
            yield object()

        original_run = ScreenConversationStartup.run
        stdin, stdout, stderr = _TTY(), _TTY(), _TTY()

        async def exit_after_restore(_stdin):
            while not restore_calls:
                await asyncio.sleep(0.001)
            return "/quit\r"

        async def exit_screen(self, **kwargs):
            return await original_run(
                self,
                **kwargs,
                terminal_mode_factory=terminal,
                terminal_size_provider=lambda: TerminalSize(columns=100, rows=30),
                input_chunk_reader=exit_after_restore,
            )

        monkeypatch.setattr(
            AgentSessionRuntime, "restore_session_operation", observe_restore
        )
        monkeypatch.setattr(
            AgentSessionRuntime,
            "preview_resume_startup",
            forbid_separate_history_protocol,
        )
        monkeypatch.setattr(ScreenConversationStartup, "run", exit_screen)
        monkeypatch.setattr(sys, "stdin", stdin)
        monkeypatch.setattr(sys, "stdout", stdout)
        monkeypatch.setattr(sys, "stderr", stderr)
        result = await screen_startup.run_screen_first_cli(
            (
                "--resume",
                str(session_file),
                "--session-dir",
                str(session_dir),
                "--composition-set",
                "coding-minimal",
                "--no-tools",
            ),
            project_root=workspace,
            cwd=workspace,
            binding=None,
        )
        assert result == 0
        assert len(restore_calls) == 1
        assert restore_calls[0].session_id == session_id

    asyncio.run(asyncio.wait_for(scenario(), 30))
