from __future__ import annotations

import asyncio

import pytest

from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage


def _usage() -> Usage:
    return Usage(
        input=0,
        output=0,
        cache_read=0,
        cache_write=0,
        total_tokens=0,
        cost={},
    )


def _model() -> Model:
    return Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )


def _assistant_text_message(text: str) -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=_usage(),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )


def _assistant_message(
    text: str,
    *,
    usage: Usage | None = None,
    stop_reason: str = "stop",
    error_message: str | None = None,
    timestamp: float = 0.0,
) -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=usage if usage is not None else _usage(),
        stop_reason=stop_reason,
        error_message=error_message,
        timestamp=timestamp,
    )


def test_agent_session_compact_appends_compaction_and_rebuilds_context(
    tmp_path, monkeypatch
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.control import (
        CompactionSettings,
        ControlConfig,
        SettingsManager,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.transcript import CompactionResult

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[
                    TextPart(type="text", text="older context that should be compacted")
                ],
                timestamp=0.0,
            )
        )
    )
    assistant_id = asyncio.run(
        manager.append_message(_assistant_text_message("recent reply"))
    )

    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        settings_manager=SettingsManager(
            ControlConfig(
                compaction=CompactionSettings(
                    enabled=True, reserve_tokens=8192, keep_recent_tokens=1
                )
            )
        ),
    )

    events: list[object] = []
    extension_events: list[tuple[str, str, bool]] = []

    def _session_compact(event, ctx):
        del ctx
        extension_events.append(
            (event.type, event.compaction_entry.kind, event.from_extension)
        )

    session._extension_runner = ExtensionRunner(
        [
            LoadedExtension(
                name="compact-ext",
                source_path=Path("/tmp/project/extensions/compact-ext.py"),
                hooks={"session_compact": [_session_compact]},
            )
        ]
    )

    async def _fake_compact(**kwargs):
        preparation = kwargs["preparation"]
        assert preparation.first_kept_entry_id == assistant_id
        return CompactionResult(
            summary="condensed summary",
            first_kept_entry_id=preparation.first_kept_entry_id,
            tokens_before=preparation.tokens_before,
            details={"source": "test"},
        )

    monkeypatch.setattr(
        "loushang.coding.session.agent_session._execute_coding_compaction",
        _fake_compact,
    )
    session.subscribe(events.append)

    result = asyncio.run(session.compact())

    assert result.summary == "condensed summary"
    assert [entry.kind for entry in manager.get_entries()] == [
        "agent.message",
        "agent.message",
        "context.compaction_checkpoint",
    ]
    assert [
        getattr(message, "role", None) for message in session.agent.state.messages
    ] == [
        "user",
        "assistant",
    ]
    assert [
        getattr(message, "role", None)
        for message in session.get_session_context().messages
    ] == [
        "user",
        "assistant",
    ]
    assert (
        "condensed summary" in session.get_session_context().messages[0].content[0].text
    )
    assert extension_events == [
        ("session_compact", "context.compaction_checkpoint", False)
    ]
    compaction_entry = manager.get_entries()[-1]
    assert isinstance(compaction_entry.payload.details, dict)
    assert compaction_entry.payload.details["source"] == "test"
    assert (
        compaction_entry.payload.details["compactionPlan"]["firstKeptEntryId"]
        == assistant_id
    )

    assert events[0]["type"] == "compaction_start"
    assert events[0]["reason"] == "manual"
    assert events[0]["stage"] == "started"
    assert events[0]["product_id"] == "coding"
    assert events[0]["session_id"] == session.session_id
    assert events[0]["usage"]["reserve_tokens"] == 8192
    assert events[0]["usage"]["keep_recent_tokens"] == 1
    assert events[-1]["type"] == "compaction_end"
    assert events[-1]["reason"] == "manual"
    assert events[-1]["result"] == {
        "summary": "condensed summary",
        "first_kept_entry_id": assistant_id,
        "tokens_before": result.tokens_before,
        "details": compaction_entry.payload.details,
    }
    assert events[-1]["aborted"] is False
    assert events[-1]["will_retry"] is False
    assert events[-1]["stage"] == "committed"
    assert events[-1]["product_id"] == "coding"
    assert events[-1]["session_id"] == session.session_id
    assert events[-1]["duration_ms"] >= 0
    assert events[-1]["checkpoint_record_id"] == compaction_entry.record_id
    assert events[-1]["usage_before"] == events[0]["usage"]
    assert events[-1]["usage_after"]["stale_after_compaction"] is True


def test_agent_session_exposes_compaction_service_surface(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import Agent
    from loushang.coding.control import (
        CompactionSettings,
        ControlConfig,
        SettingsManager,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import CompactionResult

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[
                    TextPart(type="text", text="older context that should be compacted")
                ],
                timestamp=0.0,
            )
        )
    )
    assistant_id = asyncio.run(
        manager.append_message(_assistant_text_message("recent reply"))
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        settings_manager=SettingsManager(
            ControlConfig(
                compaction=CompactionSettings(
                    enabled=True, reserve_tokens=8192, keep_recent_tokens=1
                )
            )
        ),
    )

    async def _fake_compact(**kwargs):
        preparation = kwargs["preparation"]
        return CompactionResult(
            summary="public surface summary",
            first_kept_entry_id=preparation.first_kept_entry_id,
            tokens_before=preparation.tokens_before,
        )

    monkeypatch.setattr(
        "loushang.coding.session.agent_session._execute_coding_compaction",
        _fake_compact,
    )

    assert session.get_compaction_status().is_compacting is False
    result = asyncio.run(session.compact(custom_instructions="preserve tasks"))

    assert result.summary == "public surface summary"
    assert result.first_kept_entry_id == assistant_id
    assert session.get_compaction_status().is_compacting is False


def test_agent_session_abort_compaction_cancels_public_manual_operation(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import Agent
    from loushang.coding.control import (
        CompactionSettings,
        ControlConfig,
        SettingsManager,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(role="user", content="older context", timestamp=0.0)
        )
    )
    asyncio.run(manager.append_message(_assistant_text_message("recent reply")))
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        settings_manager=SettingsManager(
            ControlConfig(
                compaction=CompactionSettings(
                    enabled=True,
                    reserve_tokens=8_192,
                    keep_recent_tokens=1,
                )
            )
        ),
    )
    started = asyncio.Event()
    events: list[object] = []

    async def _blocking_compact(**kwargs):
        del kwargs
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(
        "loushang.coding.session.agent_session._execute_coding_compaction",
        _blocking_compact,
    )
    session.subscribe(events.append)

    async def scenario() -> None:
        task = asyncio.create_task(session.compact())
        await started.wait()
        session.abort_compaction()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert all(
        entry.kind != "context.compaction_checkpoint"
        for entry in manager.get_entries()
    )
    assert session.get_compaction_status().is_compacting is False
    compaction_end = next(
        event for event in events if event["type"] == "compaction_end"
    )
    assert compaction_end["aborted"] is True
    assert compaction_end["result"] is None


def test_agent_session_compact_emits_error_event_on_failure(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import Agent
    from loushang.coding.control import (
        CompactionSettings,
        ControlConfig,
        SettingsManager,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsService
    from loushang.harness.transcript import CompactionPreparation

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="older context")],
                timestamp=0.0,
            )
        )
    )
    assistant_id = asyncio.run(
        manager.append_message(_assistant_text_message("recent reply"))
    )

    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        settings_manager=SettingsManager(
            ControlConfig(
                compaction=CompactionSettings(
                    enabled=True, reserve_tokens=8192, keep_recent_tokens=1
                )
            )
        ),
        diagnostics_service=DiagnosticsService(),
    )

    events: list[object] = []

    def _fake_prepare(entries, keep_recent_tokens):
        del entries, keep_recent_tokens
        return CompactionPreparation(
            first_kept_entry_id=assistant_id,
            messages_to_summarize=[session.agent.state.messages[0]],
            turn_prefix_messages=[],
            is_split_turn=False,
            tokens_before=42,
        )

    async def _failing_compact(**kwargs):
        del kwargs
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "loushang.harness.transcript.compaction.prepare_turn_aware_compaction",
        _fake_prepare,
    )
    monkeypatch.setattr(
        "loushang.coding.session.agent_session._execute_coding_compaction",
        _failing_compact,
    )
    session.subscribe(events.append)

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(session.compact())

    assert [entry.kind for entry in manager.get_entries()] == [
        "agent.message",
        "agent.message",
    ]
    assert events[0]["type"] == "compaction_start"
    assert events[0]["reason"] == "manual"
    assert events[0]["stage"] == "started"
    assert events[0]["product_id"] == "coding"
    assert events[0]["session_id"] == session.session_id
    assert events[0]["usage"]["reserve_tokens"] == 8192
    assert events[-1]["type"] == "compaction_end"
    assert events[-1]["reason"] == "manual"
    assert events[-1]["result"] is None
    assert events[-1]["aborted"] is False
    assert events[-1]["will_retry"] is False
    assert events[-1]["stage"] == "failed"
    assert events[-1]["product_id"] == "coding"
    assert events[-1]["session_id"] == session.session_id
    assert events[-1]["duration_ms"] >= 0
    assert events[-1]["usage_before"] == events[0]["usage"]
    assert events[-1]["usage_after"]["tokens"] == events[0]["usage"]["tokens"]
    assert events[-1]["error_message"] == "Compaction failed: boom"
    report = session.diagnostics_service.get_last_error_report()
    assert report is not None
    assert report.primary.code == "compaction_failed"


def test_agent_session_compact_respects_extension_before_compact_cancellation(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.control import (
        CompactionSettings,
        ControlConfig,
        SettingsManager,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsService
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        SessionActionDecision,
    )

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[
                    TextPart(type="text", text="older context that should be compacted")
                ],
                timestamp=0.0,
            )
        )
    )
    asyncio.run(manager.append_message(_assistant_text_message("recent reply")))
    diagnostics = DiagnosticsService()
    events: list[object] = []

    def _before_compact(event, ctx):
        del ctx
        assert event.reason == "manual"
        assert event.cwd == "/tmp/project"
        return SessionActionDecision(cancel=True)

    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        settings_manager=SettingsManager(
            ControlConfig(
                compaction=CompactionSettings(
                    enabled=True, reserve_tokens=8192, keep_recent_tokens=1
                )
            )
        ),
        diagnostics_service=diagnostics,
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="compaction-guard",
                    source_path=tmp_path / "compaction_guard.py",
                    hooks={"session_before_compact": [_before_compact]},
                )
            ]
        ),
    )
    session.subscribe(events.append)

    from loushang.harness.transcript import CompactionAborted

    with pytest.raises(CompactionAborted, match="Compaction cancelled"):
        asyncio.run(session.compact())

    assert [entry.kind for entry in manager.get_entries()] == [
        "agent.message",
        "agent.message",
    ]
    assert events[0]["type"] == "compaction_start"
    assert events[0]["reason"] == "manual"
    assert events[0]["usage"]["reserve_tokens"] == 8192
    assert events[-1]["type"] == "compaction_end"
    assert events[-1]["reason"] == "manual"
    assert events[-1]["result"] is None
    assert events[-1]["aborted"] is True
    assert events[-1]["will_retry"] is False
    assert events[-1]["usage_before"] == events[0]["usage"]
    assert events[-1]["usage_after"]["tokens"] == events[0]["usage"]["tokens"]
    assert diagnostics.get_last_error_report() is None


def test_agent_session_compact_respects_extension_before_compact_result_override(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import Agent
    from loushang.coding.control import (
        CompactionSettings,
        ControlConfig,
        SettingsManager,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        SessionBeforeCompactResult,
    )
    from loushang.harness.transcript import CompactionResult

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[
                    TextPart(type="text", text="older context that should be compacted")
                ],
                timestamp=0.0,
            )
        )
    )
    asyncio.run(manager.append_message(_assistant_text_message("recent reply")))

    called = False

    def _before_compact(event, ctx):
        del event, ctx
        nonlocal called
        called = True
        return SessionBeforeCompactResult(
            compaction=CompactionResult(
                summary="extension summary",
                first_kept_entry_id=manager.get_entries()[0].record_id,
                tokens_before=123,
                details={"source": "extension"},
            )
        )

    compacted = False

    async def _failing_compact(**kwargs):
        nonlocal compacted
        compacted = True
        raise RuntimeError("should not run")

    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        settings_manager=SettingsManager(
            ControlConfig(
                compaction=CompactionSettings(
                    enabled=True, reserve_tokens=8192, keep_recent_tokens=1
                )
            )
        ),
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="compact-hook",
                    source_path=tmp_path / "compact_hook.py",
                    hooks={"session_before_compact": [_before_compact]},
                )
            ]
        ),
    )

    monkeypatch.setattr(
        "loushang.coding.session.agent_session._execute_coding_compaction",
        _failing_compact,
    )
    result = asyncio.run(session.compact())

    assert called
    assert compacted is False
    assert result.summary == "extension summary"
    assert result.first_kept_entry_id == manager.get_entries()[0].record_id
    assert result.tokens_before == 123
    assert [entry.kind for entry in manager.get_entries()] == [
        "agent.message",
        "agent.message",
        "context.compaction_checkpoint",
    ]
    compaction_entry = manager.get_entries()[-1]
    assert compaction_entry.payload.from_hook is True
    assert compaction_entry.payload.details == {
        "source": "extension",
        "compactionPlan": {
            "previousCompactionId": None,
            "previousFirstKeptEntryId": None,
            "firstKeptEntryId": manager.get_entries()[1].record_id,
            "summarizedEntryIds": [],
            "turnPrefixEntryIds": [manager.get_entries()[0].record_id],
            "keptEntryIds": [manager.get_entries()[1].record_id],
            "isSplitTurn": True,
            "tokensBefore": 0,
            "keepRecentTokens": 1,
        },
    }


def test_agent_session_auto_compacts_after_agent_end_when_threshold_exceeded(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import AbortSignal, Agent
    from loushang.coding.control import (
        CompactionSettings,
        ControlConfig,
        SettingsManager,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import CompactionResult

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="older context")],
                timestamp=0.0,
            )
        )
    )

    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": Model(
                    id="tiny-model",
                    name="Tiny",
                    provider="faux",
                    endpoint="anthropic-messages",
                    capabilities=Capabilities(
                        reasoning=True,
                        input=("text",),
                        context_window=100,
                        max_tokens=64,
                    ),
                ),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        settings_manager=SettingsManager(
            ControlConfig(
                compaction=CompactionSettings(
                    enabled=True, reserve_tokens=10, keep_recent_tokens=1
                )
            )
        ),
    )

    events: list[object] = []
    assistant = AssistantMessage(
        role="assistant",
        content=[TextPart(type="text", text="recent reply")],
        api="anthropic-messages",
        provider="faux",
        model="tiny-model",
        response_id=None,
        usage=Usage(
            input=90,
            output=5,
            cache_read=0,
            cache_write=0,
            total_tokens=95,
            cost={},
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=1.0,
    )

    async def _fake_compact(**kwargs):
        preparation = kwargs["preparation"]
        return CompactionResult(
            summary="threshold summary",
            first_kept_entry_id=preparation.first_kept_entry_id,
            tokens_before=preparation.tokens_before,
        )

    monkeypatch.setattr(
        "loushang.coding.session.agent_session._execute_coding_compaction",
        _fake_compact,
    )
    session.subscribe(events.append)

    async def scenario() -> None:
        await session._composition.session_runtime.handle_agent_event(
            {"type": "message_end", "message": assistant}, AbortSignal()
        )
        await session._composition.session_runtime.handle_agent_event(
            {"type": "agent_end", "messages": [assistant]}, AbortSignal()
        )
        await asyncio.sleep(0)

    asyncio.run(scenario())

    assert any(
        entry.kind == "context.compaction_checkpoint" for entry in manager.get_entries()
    )
    compaction_end = next(
        event for event in events if event["type"] == "compaction_end"
    )
    assert compaction_end["reason"] == "threshold"
    assert compaction_end["will_retry"] is False


def test_agent_session_auto_compaction_uses_default_streaming_summarizer(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import AbortSignal, Agent
    from loushang.coding.control import (
        CompactionSettings,
        ControlConfig,
        SettingsManager,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import summarization as summary_module

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="older context")],
                timestamp=0.0,
            )
        )
    )
    model = Model(
        id="tiny-stream-model",
        name="Tiny Stream",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            stream=True,
            input=("text",),
            context_window=100,
            max_tokens=64,
        ),
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": model,
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        settings_manager=SettingsManager(
            ControlConfig(
                compaction=CompactionSettings(
                    enabled=True, reserve_tokens=10, keep_recent_tokens=1
                )
            )
        ),
    )
    events: list[object] = []
    session.subscribe(events.append)
    stream_calls: list[tuple[object, object, object | None]] = []
    summary_message = _assistant_message("threshold stream summary")

    class FakeEventStream:
        async def result(self):
            return summary_message

    async def fake_stream(model, context, options=None):
        stream_calls.append((model, context, options))
        return FakeEventStream()

    monkeypatch.setattr(summary_module, "stream", fake_stream)
    assistant = _assistant_message(
        "recent reply",
        usage=Usage(
            input=90,
            output=5,
            cache_read=0,
            cache_write=0,
            total_tokens=95,
            cost={},
        ),
        timestamp=1.0,
    )

    async def scenario() -> None:
        await session._composition.session_runtime.handle_agent_event(
            {"type": "message_end", "message": assistant}, AbortSignal()
        )
        await session._composition.session_runtime.handle_agent_event(
            {"type": "agent_end", "messages": [assistant]}, AbortSignal()
        )

    asyncio.run(scenario())

    assert len(stream_calls) == 1
    assert all(call[0] is model for call in stream_calls)
    checkpoint = next(
        entry
        for entry in manager.get_entries()
        if entry.kind == "context.compaction_checkpoint"
    )
    assert "threshold stream summary" in checkpoint.payload.summary
    compaction_end = next(
        event for event in events if event["type"] == "compaction_end"
    )
    assert compaction_end["reason"] == "threshold"
    assert compaction_end["stage"] == "committed"


def test_agent_session_auto_compaction_uses_compact_percent_threshold(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import AbortSignal, Agent
    from loushang.coding.control import (
        CompactionSettings,
        ControlConfig,
        SettingsManager,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import CompactionResult

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="older context")],
                timestamp=0.0,
            )
        )
    )

    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": Model(
                    id="tiny-model",
                    name="Tiny",
                    provider="faux",
                    endpoint="anthropic-messages",
                    capabilities=Capabilities(
                        reasoning=True,
                        input=("text",),
                        context_window=100,
                        max_tokens=64,
                    ),
                ),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        settings_manager=SettingsManager(
            ControlConfig(
                compaction=CompactionSettings(
                    enabled=True,
                    compact_percent=80,
                    reserve_tokens=10,
                    keep_recent_tokens=1,
                )
            )
        ),
    )

    events: list[object] = []
    assistant = AssistantMessage(
        role="assistant",
        content=[TextPart(type="text", text="recent reply")],
        api="anthropic-messages",
        provider="faux",
        model="tiny-model",
        response_id=None,
        usage=Usage(
            input=80,
            output=5,
            cache_read=0,
            cache_write=0,
            total_tokens=85,
            cost={},
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=1.0,
    )

    async def _fake_compact(**kwargs):
        preparation = kwargs["preparation"]
        return CompactionResult(
            summary="percent threshold summary",
            first_kept_entry_id=preparation.first_kept_entry_id,
            tokens_before=preparation.tokens_before,
        )

    monkeypatch.setattr(
        "loushang.coding.session.agent_session._execute_coding_compaction",
        _fake_compact,
    )
    session.subscribe(events.append)

    async def scenario() -> None:
        await session._composition.session_runtime.handle_agent_event(
            {"type": "message_end", "message": assistant}, AbortSignal()
        )
        await session._composition.session_runtime.handle_agent_event(
            {"type": "agent_end", "messages": [assistant]}, AbortSignal()
        )
        await asyncio.sleep(0)

    asyncio.run(scenario())

    assert any(
        entry.kind == "context.compaction_checkpoint" for entry in manager.get_entries()
    )
    compaction_end = next(
        event for event in events if event["type"] == "compaction_end"
    )
    assert compaction_end["reason"] == "threshold"


def test_agent_session_auto_compaction_ignores_stale_assistant_usage_before_latest_compaction(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import Agent
    from loushang.ai import AssistantMessage, TextPart, Usage
    from loushang.coding.control import (
        CompactionSettings,
        ControlConfig,
        SettingsManager,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    stale_assistant = AssistantMessage(
        role="assistant",
        content=[TextPart(type="text", text="stale usage before compaction")],
        api="test",
        provider="test",
        model="test",
        response_id=None,
        usage=Usage(
            input=95, output=5, cache_read=0, cache_write=0, total_tokens=100, cost={}
        ),
        stop_reason="end_turn",
        error_message=None,
        timestamp=1.0,
    )
    asyncio.run(manager.append_message(stale_assistant))
    asyncio.run(
        manager.append_compaction(
            summary="summary",
            first_kept_entry_id=manager.get_entries()[0].record_id,
            tokens_before=100,
        )
    )
    events = []
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": Model(
                    id="small-model",
                    name="Small",
                    provider="faux",
                    endpoint="anthropic-messages",
                    capabilities=Capabilities(context_window=100, max_tokens=64),
                ),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        settings_manager=SettingsManager(
            ControlConfig(
                compaction=CompactionSettings(
                    enabled=True, reserve_tokens=10, keep_recent_tokens=1
                )
            )
        ),
    )
    session.subscribe(events.append)

    async def _unexpected_compact(**kwargs):
        raise AssertionError("stale assistant usage should not trigger compaction")

    monkeypatch.setattr(
        "loushang.coding.session.agent_session._execute_coding_compaction",
        _unexpected_compact,
    )

    result = asyncio.run(session.maybe_compact_after_turn(stale_assistant))

    assert result is None
    assert events == []


def test_agent_session_auto_compacts_error_message_using_last_successful_usage(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import Agent
    from loushang.coding.control import (
        CompactionSettings,
        ControlConfig,
        SettingsManager,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import CompactionResult

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    user = UserMessage(
        role="user", content=[TextPart(type="text", text="hello")], timestamp=1.0
    )
    successful = _assistant_message(
        "large successful response",
        usage=Usage(
            input=90, output=5, cache_read=0, cache_write=0, total_tokens=95, cost={}
        ),
        timestamp=2.0,
    )
    next_user = UserMessage(
        role="user", content=[TextPart(type="text", text="next")], timestamp=3.0
    )
    error = _assistant_message(
        "",
        stop_reason="error",
        error_message="529 overloaded",
        usage=_usage(),
        timestamp=4.0,
    )
    for message in (user, successful, next_user, error):
        asyncio.run(manager.append_message(message))

    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": Model(
                    id="faux-model",
                    name="Tiny",
                    provider="faux",
                    endpoint="anthropic-messages",
                    capabilities=Capabilities(context_window=100, max_tokens=64),
                ),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        settings_manager=SettingsManager(
            ControlConfig(
                compaction=CompactionSettings(
                    enabled=True, reserve_tokens=10, keep_recent_tokens=1
                )
            )
        ),
    )
    session.agent.state.set_messages([user, successful, next_user, error])
    events: list[object] = []

    async def _fake_compact(**kwargs):
        preparation = kwargs["preparation"]
        return CompactionResult(
            summary="threshold summary",
            first_kept_entry_id=preparation.first_kept_entry_id,
            tokens_before=preparation.tokens_before,
        )

    monkeypatch.setattr(
        "loushang.coding.session.agent_session._execute_coding_compaction",
        _fake_compact,
    )
    session.subscribe(events.append)

    result = asyncio.run(session.maybe_compact_after_turn(error))

    assert result is not None
    compaction_end = next(
        event for event in events if event["type"] == "compaction_end"
    )
    assert compaction_end["reason"] == "threshold"
    assert compaction_end["will_retry"] is False


def test_agent_session_compacts_before_prompt_when_previous_usage_crossed_threshold(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import Agent
    from loushang.coding.control import (
        CompactionSettings,
        ControlConfig,
        SettingsManager,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import CompactionResult

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="older context")],
                timestamp=0.0,
            )
        )
    )
    asyncio.run(
        manager.append_message(
            _assistant_message(
                "large reply",
                usage=Usage(
                    input=90,
                    output=5,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=95,
                    cost={},
                ),
                timestamp=1.0,
            )
        )
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": Model(
                    id="faux-model",
                    name="Tiny",
                    provider="faux",
                    endpoint="anthropic-messages",
                    capabilities=Capabilities(context_window=100, max_tokens=64),
                ),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        settings_manager=SettingsManager(
            ControlConfig(
                compaction=CompactionSettings(
                    enabled=True, reserve_tokens=10, keep_recent_tokens=1
                )
            )
        ),
    )
    calls: list[str] = []

    async def _fake_compact(**kwargs):
        calls.append("compact")
        preparation = kwargs["preparation"]
        return CompactionResult(
            summary="threshold summary",
            first_kept_entry_id=preparation.first_kept_entry_id,
            tokens_before=preparation.tokens_before,
        )

    async def _fake_prompt(messages) -> None:
        calls.append("prompt")
        assert any(getattr(message, "role", None) == "user" for message in messages)

    monkeypatch.setattr(
        "loushang.coding.session.agent_session._execute_coding_compaction",
        _fake_compact,
    )
    monkeypatch.setattr(session.agent, "prompt", _fake_prompt)

    asyncio.run(session.prompt("next request"))

    assert calls == ["compact", "prompt"]
    assert any(
        entry.kind == "context.compaction_checkpoint" for entry in manager.get_entries()
    )


@pytest.mark.parametrize(
    ("streaming_behavior", "expected_steering", "expected_follow_up"),
    [
        ("steer", ["queued control"], []),
        ("followUp", [], ["queued control"]),
    ],
)
def test_agent_session_streaming_control_does_not_pre_prompt_compact(
    tmp_path,
    monkeypatch,
    streaming_behavior,
    expected_steering,
    expected_follow_up,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.control import (
        CompactionSettings,
        ControlConfig,
        SettingsManager,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="older context")],
                timestamp=0.0,
            )
        )
    )
    asyncio.run(
        manager.append_message(
            _assistant_message(
                "large reply",
                usage=Usage(
                    input=90,
                    output=5,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=95,
                    cost={},
                ),
                timestamp=1.0,
            )
        )
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": Model(
                    id="faux-model",
                    name="Tiny",
                    provider="faux",
                    endpoint="anthropic-messages",
                    capabilities=Capabilities(context_window=100, max_tokens=64),
                ),
                "thinking_level": "off",
                "is_streaming": True,
            }
        ),
        session_manager=manager,
        settings_manager=SettingsManager(
            ControlConfig(
                compaction=CompactionSettings(
                    enabled=True, reserve_tokens=10, keep_recent_tokens=1
                )
            )
        ),
    )

    async def _unexpected_compact(**kwargs):
        del kwargs
        raise AssertionError(
            "streaming control input must not trigger pre-prompt compaction"
        )

    monkeypatch.setattr(
        "loushang.coding.session.agent_session._execute_coding_compaction",
        _unexpected_compact,
    )

    asyncio.run(session.prompt("queued control", streaming_behavior=streaming_behavior))

    assert [entry.kind for entry in manager.get_entries()] == [
        "agent.message",
        "agent.message",
    ]
    assert session.get_steering_messages() == expected_steering
    assert session.get_follow_up_messages() == expected_follow_up


def test_agent_session_threshold_auto_compaction_resumes_agent_level_queue(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import Agent
    from loushang.coding.control import (
        CompactionSettings,
        ControlConfig,
        SettingsManager,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import CompactionResult

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="older context")],
                timestamp=0.0,
            )
        )
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": Model(
                    id="faux-model",
                    name="Tiny",
                    provider="faux",
                    endpoint="anthropic-messages",
                    capabilities=Capabilities(context_window=100, max_tokens=64),
                ),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        settings_manager=SettingsManager(
            ControlConfig(
                compaction=CompactionSettings(
                    enabled=True, reserve_tokens=10, keep_recent_tokens=1
                )
            )
        ),
    )
    queued = UserMessage(
        role="user",
        content=[TextPart(type="text", text="queued custom")],
        timestamp=2.0,
    )
    session.agent.follow_up(queued)
    assistant = _assistant_message(
        "recent reply",
        usage=Usage(
            input=90, output=5, cache_read=0, cache_write=0, total_tokens=95, cost={}
        ),
        timestamp=1.0,
    )
    continue_runs = 0

    async def _fake_compact(**kwargs):
        preparation = kwargs["preparation"]
        return CompactionResult(
            summary="threshold summary",
            first_kept_entry_id=preparation.first_kept_entry_id,
            tokens_before=preparation.tokens_before,
        )

    def _continue_run() -> asyncio.Task[None]:
        nonlocal continue_runs
        continue_runs += 1
        return asyncio.create_task(asyncio.sleep(0))

    monkeypatch.setattr(
        "loushang.coding.session.agent_session._execute_coding_compaction",
        _fake_compact,
    )
    monkeypatch.setattr(session.agent, "continue_run", _continue_run)

    async def scenario() -> None:
        await session._composition.session_runtime.handle_agent_event(
            {"type": "message_end", "message": assistant}, session.agent.signal
        )
        await session._composition.session_runtime.handle_agent_event(
            {"type": "agent_end", "messages": [assistant]}, session.agent.signal
        )
        await asyncio.sleep(0)

    asyncio.run(scenario())

    assert continue_runs == 1


def test_agent_session_overflow_recovery_emits_compaction_with_retry_flag(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import AbortSignal, Agent
    from loushang.coding.control import (
        CompactionSettings,
        ControlConfig,
        SettingsManager,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import CompactionResult

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="older context")],
                timestamp=0.0,
            )
        )
    )

    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": Model(
                    id="tiny-model",
                    name="Tiny",
                    provider="faux",
                    endpoint="anthropic-messages",
                    capabilities=Capabilities(
                        reasoning=True,
                        input=("text",),
                        context_window=100,
                        max_tokens=64,
                    ),
                ),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        settings_manager=SettingsManager(
            ControlConfig(
                compaction=CompactionSettings(
                    enabled=True, reserve_tokens=10, keep_recent_tokens=1
                )
            )
        ),
    )

    events: list[object] = []
    assistant = AssistantMessage(
        role="assistant",
        content=[TextPart(type="text", text="overflow error")],
        api="anthropic-messages",
        provider="faux",
        model="tiny-model",
        response_id=None,
        usage=_usage(),
        stop_reason="error",
        error_message="input token count exceeds the maximum context window",
        timestamp=1.0,
    )

    async def _fake_compact(**kwargs):
        preparation = kwargs["preparation"]
        return CompactionResult(
            summary="overflow summary",
            first_kept_entry_id=preparation.first_kept_entry_id,
            tokens_before=preparation.tokens_before,
        )

    monkeypatch.setattr(
        "loushang.coding.session.agent_session._execute_coding_compaction",
        _fake_compact,
    )
    continue_runs = 0

    def _continue_run() -> asyncio.Task[None]:
        nonlocal continue_runs
        continue_runs += 1
        return asyncio.create_task(asyncio.sleep(0))

    monkeypatch.setattr(
        session._composition.session_runtime, "schedule_continue_run", _continue_run
    )
    session.subscribe(events.append)

    async def scenario() -> None:
        await session._composition.session_runtime.handle_agent_event(
            {"type": "message_end", "message": assistant}, AbortSignal()
        )
        await session._composition.session_runtime.handle_agent_event(
            {"type": "agent_end", "messages": [assistant]}, AbortSignal()
        )
        await asyncio.sleep(0)

    asyncio.run(scenario())

    compaction_end = next(
        event for event in events if event["type"] == "compaction_end"
    )
    assert compaction_end["reason"] == "overflow"
    assert compaction_end["will_retry"] is True
    assert continue_runs == 1


def test_agent_session_overflow_recovery_is_limited_to_one_attempt(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import AbortSignal, Agent
    from loushang.coding.control import (
        CompactionSettings,
        ControlConfig,
        SettingsManager,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import CompactionResult

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="older context")],
                timestamp=0.0,
            )
        )
    )

    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": Model(
                    id="tiny-model",
                    name="Tiny",
                    provider="faux",
                    endpoint="anthropic-messages",
                    capabilities=Capabilities(
                        reasoning=True,
                        input=("text",),
                        context_window=100,
                        max_tokens=64,
                    ),
                ),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        settings_manager=SettingsManager(
            ControlConfig(
                compaction=CompactionSettings(
                    enabled=True, reserve_tokens=10, keep_recent_tokens=1
                )
            )
        ),
    )

    events: list[object] = []
    assistant = AssistantMessage(
        role="assistant",
        content=[TextPart(type="text", text="overflow error")],
        api="anthropic-messages",
        provider="faux",
        model="tiny-model",
        response_id=None,
        usage=_usage(),
        stop_reason="error",
        error_message="input token count exceeds the maximum context window",
        timestamp=1.0,
    )

    compact_calls = 0

    async def _fake_compact(**kwargs):
        nonlocal compact_calls
        compact_calls += 1
        preparation = kwargs["preparation"]
        return CompactionResult(
            summary="overflow summary",
            first_kept_entry_id=preparation.first_kept_entry_id,
            tokens_before=preparation.tokens_before,
        )

    continue_runs = 0

    def _continue_run() -> asyncio.Task[None]:
        nonlocal continue_runs
        continue_runs += 1
        return asyncio.create_task(asyncio.sleep(0))

    monkeypatch.setattr(
        "loushang.coding.session.agent_session._execute_coding_compaction",
        _fake_compact,
    )
    monkeypatch.setattr(
        session._composition.session_runtime, "schedule_continue_run", _continue_run
    )
    session.subscribe(events.append)

    async def scenario() -> None:
        await session._composition.session_runtime.handle_agent_event(
            {"type": "message_end", "message": assistant}, AbortSignal()
        )
        await session._composition.session_runtime.handle_agent_event(
            {"type": "agent_end", "messages": [assistant]}, AbortSignal()
        )
        await asyncio.sleep(0)
        await session._composition.session_runtime.handle_agent_event(
            {"type": "agent_end", "messages": [assistant]}, AbortSignal()
        )

    asyncio.run(scenario())

    compaction_ends = [event for event in events if event["type"] == "compaction_end"]
    assert compact_calls == 1
    assert continue_runs == 1
    assert [event["reason"] for event in compaction_ends] == ["overflow"]
    assert compaction_ends[-1]["result"] is not None
