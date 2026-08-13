from __future__ import annotations

import asyncio

from loushang.agent import Agent
from loushang.ai.model import Capabilities, Model, ModelSelection
from loushang.ai.types import (
    AssistantMessage,
    TextPart,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.conversation import CommandExecutionRecord
from loushang.harness.runtime.types import RunState
from loushang.harness.session import AgentSessionInspector
from loushang.harness.session.inspection_projection import (
    project_fork_candidates,
    project_session_stats,
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


def _usage(total_tokens: int = 17) -> Usage:
    return Usage(
        input=2,
        output=3,
        cache_read=5,
        cache_write=7,
        total_tokens=total_tokens,
        cost={"total": 0.25},
    )


def _user_message(text: str) -> UserMessage:
    return UserMessage(
        role="user", content=[TextPart(type="text", text=text)], timestamp=0.0
    )


def _assistant_message(
    text: str = "answer", *, total_tokens: int = 17, stop_reason: str = "toolUse"
) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[
            TextPart(type="text", text=text),
            ToolCall(
                type="toolCall",
                id="tool-1",
                name="read",
                arguments={"path": "README.md"},
            ),
        ],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=_usage(total_tokens),
        stop_reason=stop_reason,
        error_message=None,
        timestamp=1.0,
    )


def _tool_only_assistant_message() -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[
            ToolCall(
                type="toolCall",
                id="tool-1",
                name="read",
                arguments={"path": "README.md"},
            )
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


def _inspector(
    *,
    agent: Agent,
    session_manager: SessionManager,
    active_tool_names: list[str],
    is_retrying: bool,
    is_compacting: bool,
    model_selection: ModelSelection | None,
) -> AgentSessionInspector:
    return AgentSessionInspector(
        agent=agent,
        session=session_manager,
        get_session_id=lambda: session_manager.get_session_record().session_id,
        get_session_name=lambda: session_manager.get_session_record().metadata.name,
        get_active_tool_names=lambda: active_tool_names,
        is_retrying=lambda: is_retrying,
        is_compacting=lambda: is_compacting,
        get_last_diagnostics=lambda limit=50: [],
        get_model_selection=lambda: model_selection,
    )


def test_session_view_controller_builds_usage_and_pi_stats(tmp_path) -> None:
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(manager.append_message(_user_message("hello")))
    asyncio.run(manager.append_message(_assistant_message()))
    asyncio.run(
        manager.append_message(
            ToolResultMessage(
                role="toolResult",
                tool_call_id="tool-1",
                tool_name="read",
                content=[TextPart(type="text", text="ok")],
                is_error=False,
                timestamp=2.0,
            )
        )
    )
    agent = Agent(
        initial_state={"system_prompt": "", "model": _model(), "thinking_level": "off"}
    )
    agent.state.set_messages(manager.build_session_context().messages)
    controller = _inspector(
        agent=agent,
        session_manager=manager,
        active_tool_names=["read", "bash"],
        is_retrying=True,
        is_compacting=False,
        model_selection=ModelSelection(
            endpoint_id="test-endpoint", provider="faux", model_id="faux-model"
        ),
    )

    usage = controller.get_context_usage()
    stats = controller.build_session_stats()

    assert usage is not None
    assert usage.message_count == 3
    assert usage.user_message_count == 1
    assert usage.assistant_message_count == 1
    assert usage.tool_call_count == 1
    assert usage.tool_result_count == 1
    assert usage.tokens == usage.estimated_context_tokens
    assert usage.context_window == 128000
    assert usage.percent == (usage.estimated_context_tokens / 128000) * 100
    assert stats.session_id == manager.get_session_record().session_id
    assert stats.active_tool_count == 2
    assert stats.is_retrying is True
    assert stats.last_model_selection == ModelSelection(
        endpoint_id="test-endpoint", provider="faux", model_id="faux-model"
    )
    pi_stats = project_session_stats(
        agent=agent,
        session_manager=manager,
        context_usage=usage,
    )
    pi_usage = pi_stats["context_usage"]
    assert pi_stats | {"context_usage": None} == {
        "session_file": None,
        "session_id": manager.get_session_record().session_id,
        "user_messages": 1,
        "assistant_messages": 1,
        "tool_calls": 1,
        "tool_results": 1,
        "total_messages": 3,
        "tokens": {
            "input": 2,
            "output": 3,
            "cache_read": 5,
            "cache_write": 7,
            "total": 17,
        },
        "cost": 0.25,
        "context_usage": None,
        "latest_compaction": None,
    }
    assert isinstance(pi_usage, dict)
    assert pi_usage["messageCount"] == usage.message_count
    assert pi_usage["estimatedContextTokens"] == usage.estimated_context_tokens
    assert pi_usage["contextWindow"] == usage.context_window
    assert pi_usage["compactPercent"] == usage.compact_percent
    assert pi_usage["thresholdReason"] == usage.threshold_reason
    assert "message_count" not in pi_usage


def test_session_view_controller_reports_unknown_current_context_after_compaction(
    tmp_path,
) -> None:
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(manager.append_message(_user_message("first")))
    asyncio.run(manager.append_message(_assistant_message("before", total_tokens=180)))
    kept_user_id = asyncio.run(manager.append_message(_user_message("second")))
    asyncio.run(
        manager.append_message(_assistant_message("kept stale", total_tokens=195))
    )
    compaction_id = asyncio.run(
        manager.append_compaction(
            "summary",
            kept_user_id,
            195,
            details={
                "compactionPlan": {
                    "firstKeptEntryId": kept_user_id,
                    "summarizedEntryIds": [
                        manager.get_entries()[0].record_id,
                        manager.get_entries()[1].record_id,
                    ],
                    "turnPrefixEntryIds": [],
                    "keptEntryIds": [kept_user_id, manager.get_entries()[3].record_id],
                    "isSplitTurn": False,
                    "tokensBefore": 195,
                    "keepRecentTokens": 32,
                }
            },
        )
    )
    asyncio.run(manager.append_message(_user_message("third")))
    agent = Agent(
        initial_state={"system_prompt": "", "model": _model(), "thinking_level": "off"}
    )
    agent.state.set_messages(manager.build_session_context().messages)
    controller = _inspector(
        agent=agent,
        session_manager=manager,
        active_tool_names=[],
        is_retrying=False,
        is_compacting=False,
        model_selection=None,
    )

    usage = controller.get_context_usage()

    assert usage is not None
    assert usage.has_compaction is True
    assert usage.tokens is None
    assert usage.context_window == 128000
    assert usage.percent is None

    pi_stats = project_session_stats(
        agent=agent,
        session_manager=manager,
        context_usage=usage,
    )
    assert pi_stats["latest_compaction"] == {
        "entry_id": compaction_id,
        "first_kept_entry_id": kept_user_id,
        "tokens_before": 195,
        "from_hook": None,
        "plan": {
            "firstKeptEntryId": kept_user_id,
            "summarizedEntryIds": [
                manager.get_entries()[0].record_id,
                manager.get_entries()[1].record_id,
            ],
            "turnPrefixEntryIds": [],
            "keptEntryIds": [kept_user_id, manager.get_entries()[3].record_id],
            "isSplitTurn": False,
            "tokensBefore": 195,
            "keepRecentTokens": 32,
        },
    }


def test_session_view_controller_uses_post_compaction_usage_for_current_context(
    tmp_path,
) -> None:
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(manager.append_message(_user_message("first")))
    asyncio.run(manager.append_message(_assistant_message("before", total_tokens=180)))
    kept_user_id = asyncio.run(manager.append_message(_user_message("second")))
    asyncio.run(
        manager.append_message(_assistant_message("kept stale", total_tokens=195))
    )
    asyncio.run(manager.append_compaction("summary", kept_user_id, 195))
    asyncio.run(manager.append_message(_user_message("third")))
    asyncio.run(manager.append_message(_assistant_message("after", total_tokens=25)))
    agent = Agent(
        initial_state={"system_prompt": "", "model": _model(), "thinking_level": "off"}
    )
    agent.state.set_messages(manager.build_session_context().messages)
    controller = _inspector(
        agent=agent,
        session_manager=manager,
        active_tool_names=[],
        is_retrying=False,
        is_compacting=False,
        model_selection=None,
    )

    usage = controller.get_context_usage()

    assert usage is not None
    assert usage.tokens == 25
    assert usage.context_window == 128000
    assert usage.percent == (25 / 128000) * 100


def test_session_view_controller_reads_forking_entries_and_last_assistant_text(
    tmp_path,
) -> None:
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    first_id = asyncio.run(manager.append_message(_user_message("first")))
    asyncio.run(manager.append_message(_assistant_message("assistant")))
    asyncio.run(
        manager.append_message(
            CommandExecutionRecord(
                command="printf hi",
                output="hi\n",
                exit_code=0,
                cancelled=False,
                truncated=False,
                full_output_path=None,
            )
        )
    )
    second_id = asyncio.run(manager.append_message(_user_message("second")))
    agent = Agent(
        initial_state={"system_prompt": "", "model": _model(), "thinking_level": "off"}
    )
    agent.state.set_messages(manager.build_session_context().messages)
    controller = _inspector(
        agent=agent,
        session_manager=manager,
        active_tool_names=[],
        is_retrying=False,
        is_compacting=False,
        model_selection=None,
    )

    assert controller.get_user_messages_for_forking() == [
        {"entry_id": first_id, "text": "first"},
        {"entry_id": second_id, "text": "second"},
    ]
    assert project_fork_candidates(controller) == [
        {"entry_id": first_id, "text": "first"},
        {"entry_id": second_id, "text": "second"},
    ]
    assert controller.get_entry_text(second_id) == "second"
    assert controller.get_last_assistant_text() == "assistant"


def test_session_view_controller_returns_recent_assistant_texts_newest_first(
    tmp_path,
) -> None:
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(manager.append_message(_assistant_message("first")))
    asyncio.run(manager.append_message(_assistant_message("")))
    asyncio.run(manager.append_message(_tool_only_assistant_message()))
    asyncio.run(manager.append_message(_assistant_message("second")))
    agent = Agent(
        initial_state={"system_prompt": "", "model": _model(), "thinking_level": "off"}
    )
    agent.state.set_messages(manager.build_session_context().messages)
    controller = _inspector(
        agent=agent,
        session_manager=manager,
        active_tool_names=[],
        is_retrying=False,
        is_compacting=False,
        model_selection=None,
    )

    assert controller.get_recent_assistant_texts() == ("second", "first")
    assert controller.get_last_assistant_text() == "second"


def test_session_view_controller_builds_state_snapshot(tmp_path) -> None:
    agent = Agent(
        initial_state={"system_prompt": "", "model": _model(), "thinking_level": "high"}
    )
    controller = _inspector(
        agent=agent,
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        active_tool_names=["read"],
        is_retrying=True,
        is_compacting=False,
        model_selection=ModelSelection(
            endpoint_id="test-endpoint", provider="faux", model_id="faux-model"
        ),
    )

    state = controller.get_state(steering=["steer"], follow_up=["follow"])

    assert state.run == RunState(status="idle")
    assert state.active_tool_names == ["read"]
    assert state.is_retrying is True
    assert state.thinking_level == "high"
