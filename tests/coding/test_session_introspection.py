from __future__ import annotations

import asyncio

import loushang.coding as coding
import loushang.coding.session as coding_session
from loushang.agent import Agent
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import (
    AssistantMessage,
    TextPart,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from loushang.coding.session_manager import SessionManager
from loushang.coding.tool_pack import (
    register_coding_builtin_tools as register_builtin_tools,
)
from loushang.harness.diagnostics import DiagnosticRecord, DiagnosticsService
from loushang.harness.tools.workspace.registry import (
    WorkspaceToolRegistry as ToolRegistry,
)


def test_context_usage_shape_is_stable() -> None:
    usage_cls = getattr(coding_session, "ContextUsage")
    usage = usage_cls(
        message_count=5,
        assistant_message_count=2,
        user_message_count=2,
        tool_call_count=1,
        tool_result_count=1,
        custom_message_count=0,
        estimated_context_tokens=123,
        has_compaction=False,
        branch_depth=2,
        leaf_entry_id="e5",
    )
    assert usage.estimated_context_tokens == 123


def test_session_stats_shape_is_stable() -> None:
    stats_cls = getattr(coding_session, "SessionStats")
    stats = stats_cls(
        session_id="s1",
        session_name="demo",
        entry_count=3,
        message_count=2,
        custom_message_count=1,
        active_tool_count=2,
        is_retrying=False,
        is_compacting=False,
        has_diagnostics=False,
        branch_count=1,
        last_model_selection=None,
        context_usage=None,
    )
    assert stats.branch_count == 1


def test_context_usage_is_reexported_from_public_packages() -> None:
    assert getattr(coding, "ContextUsage") is getattr(coding_session, "ContextUsage")


def test_session_stats_is_reexported_from_public_packages() -> None:
    assert getattr(coding, "SessionStats") is getattr(coding_session, "SessionStats")


def _usage() -> Usage:
    return Usage(
        input=10,
        output=20,
        cache_read=0,
        cache_write=0,
        total_tokens=30,
        cost={},
    )


def _assistant_with_tool_call() -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[
            TextPart(type="text", text="Calling read"),
            ToolCall(
                type="toolCall",
                id="call-1",
                name="read",
                arguments={"path": "README.md"},
            ),
        ],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=_usage(),
        stop_reason="toolUse",
        error_message=None,
        timestamp=1.0,
    )


def _build_session_with_tool_turn(tmp_path):
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="read the readme")],
                timestamp=0.0,
            )
        )
    )
    asyncio.run(manager.append_message(_assistant_with_tool_call()))
    asyncio.run(
        manager.append_message(
            ToolResultMessage(
                role="toolResult",
                tool_call_id="call-1",
                tool_name="read",
                content=[TextPart(type="text", text="README content")],
                is_error=False,
                timestamp=2.0,
            )
        )
    )
    return coding_session.AgentSession(agent=Agent(), session_manager=manager)


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


def test_build_context_usage_counts_messages_and_tools(tmp_path) -> None:
    usage = _build_session_with_tool_turn(
        tmp_path
    )._composition.session_inspector.get_context_usage()
    assert usage is not None
    assert usage.message_count >= 3
    assert usage.tool_call_count == 1
    assert usage.tool_result_count == 1


def test_build_context_usage_uses_best_effort_token_estimate(tmp_path) -> None:
    usage = _build_session_with_tool_turn(
        tmp_path
    )._composition.session_inspector.get_context_usage()
    assert usage is not None
    assert usage.estimated_context_tokens is not None


def test_build_context_usage_uses_session_compaction_settings(tmp_path) -> None:
    from loushang.coding.control import (
        CompactionSettings,
        ControlConfig,
        SettingsManager,
    )

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="hello")],
                timestamp=0.0,
            )
        )
    )
    asyncio.run(manager.append_message(_assistant_with_tool_call()))
    session = coding_session.AgentSession(
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
                    compact_percent=80, reserve_tokens=8192, keep_recent_tokens=4096
                )
            )
        ),
    )

    usage = session._composition.session_inspector.get_context_usage()

    assert usage is not None
    assert usage.compact_percent == 80
    assert usage.reserve_tokens == 8192
    assert usage.keep_recent_tokens == 4096
    assert usage.percent_threshold_tokens == 102400
    assert usage.reserve_threshold_tokens == 119808
    assert usage.threshold_tokens == 102400
    assert usage.threshold_reason == "compact_percent"


def test_build_session_stats_includes_context_usage_and_session_metadata(
    tmp_path,
) -> None:
    session = _build_session_with_tool_turn(tmp_path)
    stats = session._composition.session_inspector.build_session_stats()
    assert stats.session_id == session.session_id
    assert stats.context_usage is not None


def test_build_session_stats_reports_token_totals_after_compaction(tmp_path) -> None:
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="first")],
                timestamp=0.0,
            )
        )
    )
    asyncio.run(
        manager.append_message(
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="first response")],
                api="anthropic-messages",
                provider="faux",
                model="faux-model",
                response_id=None,
                usage=Usage(
                    input=180_000,
                    output=0,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=180_000,
                    cost={},
                ),
                stop_reason="stop",
                error_message=None,
                timestamp=1.0,
            )
        )
    )
    kept_id = asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="second")],
                timestamp=2.0,
            )
        )
    )
    asyncio.run(
        manager.append_message(
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="second response")],
                api="anthropic-messages",
                provider="faux",
                model="faux-model",
                response_id=None,
                usage=Usage(
                    input=195_000,
                    output=0,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=195_000,
                    cost={},
                ),
                stop_reason="stop",
                error_message=None,
                timestamp=3.0,
            )
        )
    )
    asyncio.run(manager.append_compaction("summary", kept_id, 195_000))
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="third")],
                timestamp=4.0,
            )
        )
    )
    asyncio.run(
        manager.append_message(
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="third response")],
                api="anthropic-messages",
                provider="faux",
                model="faux-model",
                response_id=None,
                usage=Usage(
                    input=25_000,
                    output=0,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=25_000,
                    cost={},
                ),
                stop_reason="stop",
                error_message=None,
                timestamp=5.0,
            )
        )
    )
    agent = Agent(
        initial_state={
            "system_prompt": "",
            "model": _model(),
            "thinking_level": "off",
            "tools": [],
        }
    )
    agent.state.set_messages(manager.build_session_context().messages)
    session = coding_session.AgentSession(agent=agent, session_manager=manager)

    stats = session._composition.session_inspector.build_session_stats()

    assert stats.tokens.total == 220_000
    assert stats.tokens.input == 220_000
    assert stats.context_usage is not None
    assert stats.context_usage.tokens == 25_000


def test_build_session_stats_tracks_active_tools_and_diagnostics(tmp_path) -> None:
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    diagnostics = DiagnosticsService()
    diagnostics.record(
        DiagnosticRecord(
            type="warning",
            code="demo_warning",
            message="demo",
            phase="runtime",
            source="session",
            timestamp="2026-05-25T00:00:00Z",
        )
    )
    registry = ToolRegistry()
    register_builtin_tools(registry, diagnostics_service=diagnostics)
    agent = Agent(
        initial_state={
            "system_prompt": "",
            "model": _model(),
            "thinking_level": "off",
            "tools": [],
        },
        convert_to_llm=lambda messages: [],
    )
    session = coding_session.AgentSession(
        agent=agent,
        session_manager=manager,
        tool_registry=registry,
        active_tool_names=["bash", "read"],
        diagnostics_service=diagnostics,
    )

    stats = session._composition.session_inspector.build_session_stats()
    assert stats.active_tool_count == len(session.get_active_tool_names())
    assert stats.has_diagnostics is True
