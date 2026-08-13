from __future__ import annotations

import asyncio

from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, Usage


def _usage(*, input_tokens: int = 0, total_tokens: int = 0) -> Usage:
    return Usage(
        input=input_tokens,
        output=max(total_tokens - input_tokens, 0),
        cache_read=0,
        cache_write=0,
        total_tokens=total_tokens,
        cost={},
    )


def _model(*, context_window: int = 128000) -> Model:
    return Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=context_window,
            max_tokens=4096,
        ),
    )


def _assistant_error_message(
    error_message: str, *, usage: Usage | None = None
) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text="error")],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=usage or _usage(),
        stop_reason="error",
        error_message=error_message,
        timestamp=0.0,
    )


def _assistant_success_message(text: str = "ok") -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=_usage(total_tokens=12),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )


def test_agent_session_retryable_error_starts_retry_and_removes_error_message(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import AbortSignal, Agent
    from loushang.coding.control import ControlConfig, RetrySettings, SettingsManager
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
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
                retry=RetrySettings(enabled=True, max_retries=2, base_delay_ms=1)
            )
        ),
    )

    events: list[object] = []
    continued: list[str] = []
    error_message = _assistant_error_message("503 service unavailable")
    session.agent.state.messages.append(error_message)

    async def _instant_sleep(delay_ms, signal):
        del delay_ms, signal
        return None

    async def _fake_continue_run():
        continued.append("continued")

    monkeypatch.setattr(
        "loushang.coding.session.agent_session.sleep_for_retry", _instant_sleep
    )
    monkeypatch.setattr(
        session._composition.session_runtime,
        "schedule_continue_run",
        _fake_continue_run,
    )
    session.subscribe(events.append)

    async def scenario() -> None:
        await session._composition.session_runtime.handle_agent_event(
            {"type": "message_end", "message": error_message}, AbortSignal()
        )
        await session._composition.session_runtime.handle_agent_event(
            {"type": "agent_end", "messages": [error_message]}, AbortSignal()
        )
        await asyncio.sleep(0)

    asyncio.run(scenario())

    assert session.is_retrying is True
    assert session.agent.state.messages == []
    assert continued == ["continued"]
    assert events[-1] == {
        "type": "auto_retry_start",
        "attempt": 1,
        "max_attempts": 2,
        "delay_ms": 1,
        "error_message": "503 service unavailable",
    }


def test_agent_session_retry_success_emits_end_event_and_resolves_waiter(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import AbortSignal, Agent
    from loushang.coding.control import ControlConfig, RetrySettings, SettingsManager
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
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
                retry=RetrySettings(enabled=True, max_retries=2, base_delay_ms=1)
            )
        ),
    )

    events: list[object] = []
    error_message = _assistant_error_message("network error")
    success_message = _assistant_success_message()
    session.agent.state.messages.append(error_message)

    async def _instant_sleep(delay_ms, signal):
        del delay_ms, signal
        return None

    async def _fake_continue_run():
        return None

    monkeypatch.setattr(
        "loushang.coding.session.agent_session.sleep_for_retry", _instant_sleep
    )
    monkeypatch.setattr(
        session._composition.session_runtime,
        "schedule_continue_run",
        _fake_continue_run,
    )
    session.subscribe(events.append)

    async def scenario() -> None:
        await session._composition.session_runtime.handle_agent_event(
            {"type": "message_end", "message": error_message}, AbortSignal()
        )
        await session._composition.session_runtime.handle_agent_event(
            {"type": "agent_end", "messages": [error_message]}, AbortSignal()
        )
        await asyncio.sleep(0)
        await session._composition.session_runtime.handle_agent_event(
            {"type": "message_end", "message": success_message}, AbortSignal()
        )
        await session._composition.session_runtime.handle_agent_event(
            {"type": "agent_end", "messages": [success_message]}, AbortSignal()
        )
        await session.wait_for_retry()

    asyncio.run(scenario())

    assert session.is_retrying is False
    assert {
        "type": "auto_retry_end",
        "success": True,
        "attempt": 1,
    } in events


def test_agent_session_retry_preserves_queued_messages_until_retry_continues(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import AbortSignal, Agent
    from loushang.coding.control import ControlConfig, RetrySettings, SettingsManager
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
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
                retry=RetrySettings(enabled=True, max_retries=2, base_delay_ms=1)
            )
        ),
    )

    events: list[object] = []
    continued_states: list[tuple[list[str], list[str]]] = []
    error_message = _assistant_error_message("503 service unavailable")
    session.agent.state.messages.append(error_message)

    async def _instant_sleep(delay_ms, signal):
        del delay_ms, signal
        return None

    async def _fake_continue_run():
        continued_states.append(
            (session.get_steering_messages(), session.get_follow_up_messages())
        )

    monkeypatch.setattr(
        "loushang.coding.session.agent_session.sleep_for_retry", _instant_sleep
    )
    monkeypatch.setattr(
        session._composition.session_runtime,
        "schedule_continue_run",
        _fake_continue_run,
    )
    session.subscribe(events.append)

    async def scenario() -> None:
        await session._composition.session_runtime.handle_agent_event(
            {"type": "message_end", "message": error_message}, AbortSignal()
        )
        session.steer("queued steer")
        session.follow_up("queued follow")
        await session._composition.session_runtime.handle_agent_event(
            {"type": "agent_end", "messages": [error_message]}, AbortSignal()
        )
        await asyncio.sleep(0)

    asyncio.run(scenario())

    assert session.is_retrying is True
    assert continued_states == [(["queued steer"], ["queued follow"])]
    assert session.get_state().steering == ["queued steer"]
    assert session.get_state().follow_up == ["queued follow"]
    assert [event["type"] for event in events if event["type"] == "queue_update"] == [
        "queue_update",
        "queue_update",
    ]


def test_agent_session_abort_retry_ends_retry_with_failure(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import AbortSignal, Agent
    from loushang.coding.control import ControlConfig, RetrySettings, SettingsManager
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
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
                retry=RetrySettings(enabled=True, max_retries=2, base_delay_ms=1)
            )
        ),
    )

    events: list[object] = []
    error_message = _assistant_error_message("socket hang up")
    session.agent.state.messages.append(error_message)
    started = asyncio.Event()

    async def _blocking_sleep(delay_ms, signal):
        del delay_ms
        started.set()
        while not signal.aborted:
            await asyncio.sleep(0)
        raise asyncio.CancelledError

    async def _fake_continue_run():
        raise AssertionError("continue_run should not be called after retry abort")

    monkeypatch.setattr(
        "loushang.coding.session.agent_session.sleep_for_retry", _blocking_sleep
    )
    monkeypatch.setattr(
        session._composition.session_runtime,
        "schedule_continue_run",
        _fake_continue_run,
    )
    session.subscribe(events.append)

    async def scenario() -> None:
        await session._composition.session_runtime.handle_agent_event(
            {"type": "message_end", "message": error_message}, AbortSignal()
        )
        retry_task = asyncio.create_task(
            session._composition.session_runtime.handle_agent_event(
                {"type": "agent_end", "messages": [error_message]}, AbortSignal()
            )
        )
        await started.wait()
        session.abort_retry()
        await retry_task
        await session.wait_for_retry()

    asyncio.run(scenario())

    assert session.is_retrying is False
    assert events[-1] == {
        "type": "auto_retry_end",
        "success": False,
        "attempt": 1,
        "final_error": "Retry cancelled",
    }


def test_agent_session_retry_max_retries_emits_final_failure(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import AbortSignal, Agent
    from loushang.coding.control import ControlConfig, RetrySettings, SettingsManager
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsService

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
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
                retry=RetrySettings(enabled=True, max_retries=1, base_delay_ms=1)
            )
        ),
        diagnostics_service=DiagnosticsService(),
    )

    events: list[object] = []
    error_message = _assistant_error_message("provider returned error")
    session.subscribe(events.append)

    async def _instant_sleep(delay_ms, signal):
        del delay_ms, signal
        return None

    async def _fake_continue_run():
        return None

    monkeypatch.setattr(
        "loushang.coding.session.agent_session.sleep_for_retry", _instant_sleep
    )
    monkeypatch.setattr(
        session._composition.session_runtime,
        "schedule_continue_run",
        _fake_continue_run,
    )

    async def scenario() -> None:
        session.agent.state.messages.append(error_message)
        await session._composition.session_runtime.handle_agent_event(
            {"type": "message_end", "message": error_message}, AbortSignal()
        )
        await session._composition.session_runtime.handle_agent_event(
            {"type": "agent_end", "messages": [error_message]}, AbortSignal()
        )
        await asyncio.sleep(0)
        session.agent.state.messages.append(error_message)
        await session._composition.session_runtime.handle_agent_event(
            {"type": "message_end", "message": error_message}, AbortSignal()
        )
        await session._composition.session_runtime.handle_agent_event(
            {"type": "agent_end", "messages": [error_message]}, AbortSignal()
        )

    asyncio.run(scenario())

    assert session.is_retrying is False
    assert events[-1] == {
        "type": "auto_retry_end",
        "success": False,
        "attempt": 1,
        "final_error": "provider returned error",
    }
    report = session.diagnostics_service.get_last_error_report()
    assert report is not None
    assert report.primary.code == "retry_failed"
    assistant_errors = [
        record
        for record in session.get_last_diagnostics()
        if record.code == "assistant_response_error"
    ]
    assert len(assistant_errors) == 1
    assert assistant_errors[-1].source == "provider"
    assert assistant_errors[-1].message == "provider returned error"
    assert assistant_errors[-1].occurrence_count == 2
    assert assistant_errors[-1].details == {
        "provider": "faux",
        "model_id": "faux-model",
        "api": "anthropic-messages",
        "response_id": None,
        "stop_reason": "error",
    }


def test_agent_session_records_non_retryable_assistant_error_as_provider_diagnostic(
    tmp_path,
) -> None:
    from loushang.agent import AbortSignal, Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsService

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
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
        diagnostics_service=DiagnosticsService(),
    )
    error_message = _assistant_error_message("provider quota exhausted")

    async def scenario() -> None:
        await session._composition.session_runtime.handle_agent_event(
            {"type": "message_end", "message": error_message}, AbortSignal()
        )
        await session._composition.session_runtime.handle_agent_event(
            {"type": "agent_end", "messages": [error_message]}, AbortSignal()
        )

    asyncio.run(scenario())

    report = session.get_last_error_report()
    assert report is not None
    assert report.primary.code == "assistant_response_error"
    assert report.primary.source == "provider"
    assert report.primary.message == "provider quota exhausted"
    assert report.primary.details["provider"] == "faux"
    assert report.primary.details["model_id"] == "faux-model"


def test_agent_session_overflow_routes_to_compaction_instead_of_retry(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import AbortSignal, Agent
    from loushang.coding.control import ControlConfig, RetrySettings, SettingsManager
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(context_window=32),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        settings_manager=SettingsManager(
            ControlConfig(
                retry=RetrySettings(enabled=True, max_retries=2, base_delay_ms=1)
            )
        ),
    )

    events: list[object] = []
    compaction_calls: list[tuple[str, bool, bool]] = []
    overflow_message = _assistant_error_message(
        "token limit exceeded",
        usage=_usage(input_tokens=64, total_tokens=64),
    )

    async def _fake_compact_internal(*, reason, will_retry, raise_on_error):
        compaction_calls.append((reason, will_retry, raise_on_error))
        return None

    async def _fake_continue_run():
        raise AssertionError("overflow should not trigger retry continue_run")

    monkeypatch.setattr(
        session._composition.compaction_runtime,
        "compact",
        _fake_compact_internal,
    )
    monkeypatch.setattr(
        session._composition.session_runtime,
        "schedule_continue_run",
        _fake_continue_run,
    )
    session.subscribe(events.append)

    async def scenario() -> None:
        session.agent.state.messages.append(overflow_message)
        await session._composition.session_runtime.handle_agent_event(
            {"type": "message_end", "message": overflow_message}, AbortSignal()
        )
        await session._composition.session_runtime.handle_agent_event(
            {"type": "agent_end", "messages": [overflow_message]}, AbortSignal()
        )

    asyncio.run(scenario())

    assert compaction_calls == [("overflow", True, False)]
    assert not any(event["type"] == "auto_retry_start" for event in events)
