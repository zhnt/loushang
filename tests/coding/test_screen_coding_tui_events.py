from __future__ import annotations

from types import SimpleNamespace

import pytest

from loushang.agent import AgentToolResult
from loushang.ai import TextPart, UserMessage
from loushang.tui.transcript import (
    AssistantMessageRecord,
    ContextCompactionRecord,
    ErrorRecord,
    ToolExecutionRecord,
    UserPromptRecord,
)


def _assistant(
    text: str = "", *, stop_reason: str = "stop", error_message: str | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        role="assistant",
        content=[TextPart(type="text", text=text)] if text else [],
        stop_reason=stop_reason,
        error_message=error_message,
    )


def test_screen_event_projector_streams_assistant_to_draft_then_commits_once() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_screen_conversation_projection,
    )

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 1.0,
    )
    projector = build_agent_screen_conversation_projection(app)

    projector.handle({"type": "message_start", "message": _assistant()})
    projector.handle(
        {
            "type": "message_update",
            "message": _assistant("你好"),
            "assistant_message_event": {"type": "text_delta", "delta": "你好"},
        }
    )

    assert app.state.assistant_draft == AssistantMessageRecord("你好", stable=False)
    assert not any(
        isinstance(record, AssistantMessageRecord) for record in app.state.records
    )

    projector.handle({"type": "message_end", "message": _assistant("你好，世界")})

    assert app.state.assistant_draft is None
    assert [
        record
        for record in app.state.records
        if isinstance(record, AssistantMessageRecord)
    ] == [AssistantMessageRecord("你好，世界")]


@pytest.mark.tui_render_contract
def test_screen_event_projector_promotes_streaming_cache_through_shared_target() -> (
    None
):
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_screen_conversation_projection,
    )
    from loushang.tui import RenderConstraints

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 1.0,
    )
    projector = build_agent_screen_conversation_projection(app)
    text = "\n".join(f"- **Line {line}**: `code-{line}`" for line in range(100))

    projector.handle({"type": "message_start", "message": _assistant()})
    projector.handle(
        {
            "type": "message_update",
            "message": _assistant(text),
            "assistant_message_event": {"type": "text_delta", "delta": text},
        }
    )
    app.render(RenderConstraints(width=100, max_height=1_000, visible_height=1_000))
    transient_lines = tuple(
        line.text
        for segment in app._transcript_region._segmented_transient_content_segments
        for line in segment.lines
    )

    projector.handle({"type": "message_end", "message": _assistant(text)})

    assert transient_lines
    assert transient_lines in app._transcript_region._stable_line_cache.values()
    assert app._transcript_region._transient_line_cache_lines is None


def test_screen_event_projector_requires_assistant_message_for_delta() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_screen_conversation_projection,
    )

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 1.0,
    )
    projector = build_agent_screen_conversation_projection(app)

    projector.handle({"type": "message_start", "message": _assistant()})
    projector.handle(
        {
            "type": "message_update",
            "assistant_message_event": {"type": "text_delta", "delta": "ignored"},
        }
    )

    assert app.state.assistant_draft is None


def test_screen_event_projector_renders_assistant_error_from_agent_end() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_screen_conversation_projection,
    )

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 1.0,
    )
    projector = build_agent_screen_conversation_projection(app)

    projector.handle(
        {
            "type": "agent_end",
            "messages": [
                _assistant(stop_reason="error", error_message="provider failure")
            ],
        }
    )

    assert app.state.records == [ErrorRecord("provider failure")]


def test_screen_event_projector_commits_error_message_and_deduplicates_error() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_screen_conversation_projection,
    )

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 1.0,
    )
    projector = build_agent_screen_conversation_projection(app)
    message = _assistant(
        "partial answer",
        stop_reason="error",
        error_message="provider failure",
    )

    projector.handle({"type": "message_start", "message": message})
    projector.handle({"type": "message_end", "message": message})
    projector.handle({"type": "agent_end", "messages": [message]})

    assert app.state.records == [
        AssistantMessageRecord("partial answer"),
        ErrorRecord("provider failure"),
    ]


def test_screen_event_projector_commits_intentional_abort_without_error_record() -> (
    None
):
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_screen_conversation_projection,
    )

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 1.0,
    )
    projector = build_agent_screen_conversation_projection(app)
    message = _assistant(
        "partial answer",
        stop_reason="aborted",
        error_message="Request aborted by user",
    )

    projector.handle({"type": "message_start", "message": message})
    projector.handle({"type": "message_end", "message": message})

    assert app.state.records == [AssistantMessageRecord("partial answer")]


def test_screen_event_projector_renders_user_message_and_skips_optimistic_echo() -> (
    None
):
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_screen_conversation_projection,
    )

    message = UserMessage(
        role="user", content=[TextPart(type="text", text="你好")], timestamp=0.0
    )
    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 1.0,
    )

    build_agent_screen_conversation_projection(app).handle(
        {"type": "message_start", "message": message}
    )

    assert app.state.records == [UserPromptRecord("你好")]


def test_screen_event_projector_skips_user_message_when_matching_pending_echo() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_screen_conversation_projection,
    )

    message = UserMessage(
        role="user", content=[TextPart(type="text", text="你好")], timestamp=0.0
    )
    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 1.0,
    )
    app.start_prompt("你好", started_at=1.0)

    assert app.state.records == [UserPromptRecord("你好")]

    build_agent_screen_conversation_projection(app).handle(
        {"type": "message_start", "message": message}
    )

    # Should not duplicate the user message because it matches the pending echo
    assert app.state.records == [UserPromptRecord("你好")]


def test_screen_event_projector_drops_stale_pending_echo_on_mismatch() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_screen_conversation_projection,
    )

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 1.0,
    )
    app.start_prompt("same", started_at=1.0)
    projector = build_agent_screen_conversation_projection(app)

    projector.handle(
        {
            "type": "message_start",
            "message": UserMessage(
                role="user",
                content=[TextPart(type="text", text="different")],
                timestamp=0.0,
            ),
        }
    )
    projector.handle(
        {
            "type": "message_start",
            "message": UserMessage(
                role="user", content=[TextPart(type="text", text="same")], timestamp=0.0
            ),
        }
    )

    assert app.state.records == [
        UserPromptRecord("same"),
        UserPromptRecord("different"),
        UserPromptRecord("same"),
    ]


def test_screen_event_projector_updates_tool_record_in_place() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_screen_conversation_projection,
    )

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 5.0,
    )
    projector = build_agent_screen_conversation_projection(app, now=lambda: 5.0)
    result: AgentToolResult[dict[str, object]] = AgentToolResult(
        content=[TextPart(type="text", text="ok")], details={}
    )

    projector.handle(
        {
            "type": "tool_execution_start",
            "tool_call_id": "tc1",
            "tool_name": "read",
            "args": {"path": "README.md"},
        }
    )
    assert len(app.state.records) == 1
    assert isinstance(app.state.records[0], ToolExecutionRecord)
    assert app.state.records[0].state == "running"

    projector.handle(
        {
            "type": "tool_execution_end",
            "tool_call_id": "tc1",
            "tool_name": "read",
            "result": result,
            "is_error": False,
        }
    )

    assert len(app.state.records) == 1
    record = app.state.records[0]
    assert isinstance(record, ToolExecutionRecord)
    assert record.state == "completed"
    assert record.name == "read README.md"


def test_screen_event_projector_preserves_tool_elapsed_clock_boundaries() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_screen_conversation_projection,
    )

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 1.0,
    )
    clock = iter((10.0, 11.0, 15.0)).__next__
    projector = build_agent_screen_conversation_projection(app, now=clock)
    result: AgentToolResult[dict[str, object]] = AgentToolResult(
        content=[TextPart(type="text", text="ok")],
        details={},
    )

    projector.handle(
        {
            "type": "tool_execution_start",
            "tool_call_id": "tc1",
            "tool_name": "read",
        }
    )
    projector.handle(
        {
            "type": "tool_execution_end",
            "tool_call_id": "tc1",
            "tool_name": "read",
            "result": result,
            "is_error": False,
        }
    )

    record = app.state.records[0]
    assert isinstance(record, ToolExecutionRecord)
    assert record.elapsed_seconds == 5.0


def test_screen_agent_start_does_not_read_clock_while_run_is_active() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_screen_conversation_projection,
    )

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 1.0,
    )
    app.begin_run(started_at=1.0)
    clock_calls = 0

    def clock() -> float:
        nonlocal clock_calls
        clock_calls += 1
        return 2.0

    build_agent_screen_conversation_projection(app, now=clock).handle({"type": "agent_start"})

    assert clock_calls == 0


def test_screen_event_projector_recovers_tool_update_without_start() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_screen_conversation_projection,
    )

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 5.0,
    )
    projector = build_agent_screen_conversation_projection(app, now=lambda: 5.0)

    projector.handle(
        {
            "type": "tool_execution_update",
            "tool_call_id": "tc1",
            "tool_name": "read",
            "args": {"path": "README.md"},
        }
    )

    assert len(app.state.records) == 1
    assert isinstance(app.state.records[0], ToolExecutionRecord)
    assert app.state.records[0].state == "running"


def test_screen_event_projector_syncs_pending_queues() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_screen_conversation_projection,
    )

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 1.0,
    )
    projector = build_agent_screen_conversation_projection(
        app,
        read_pending_steers=lambda: ("马上回答中文",),
        read_pending_followups=lambda: ("继续",),
    )

    projector.handle({"type": "queue_update"})

    assert app.state.pending_steers == ["马上回答中文"]
    assert app.state.pending_followups == ["继续"]


def test_screen_event_projector_preserves_coding_status_copy() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_screen_conversation_projection,
    )

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 1.0,
    )
    projector = build_agent_screen_conversation_projection(app)

    projector.handle(
        {
            "type": "auto_retry_start",
            "attempt": 2,
            "max_attempts": 3,
            "delay_ms": 1000,
            "error_message": "rate limit",
        }
    )
    assert app.state.status_message == "retry 2/3 in 1000ms: rate limit"

    projector.handle({"type": "compaction_start", "reason": "threshold"})
    assert app.state.status_message == "compact start: threshold"

    projector.handle({"type": "compaction_end", "error_message": "failed"})
    assert app.state.status_message == "compact error: failed"

    projector.handle({"type": "compaction_end"})
    assert app.state.status_message == "compact done"


def test_screen_event_projector_renders_queued_steer_into_transcript() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_screen_conversation_projection,
    )

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 1.0,
    )
    app.start_prompt("初始问题", started_at=1.0)
    projector = build_agent_screen_conversation_projection(
        app, read_pending_steers=tuple, read_pending_followups=tuple
    )
    projector.handle(
        {
            "type": "message_start",
            "message": UserMessage(
                role="user",
                content=[TextPart(type="text", text="初始问题")],
                timestamp=0.0,
            ),
        }
    )

    app.queue_steer("steer 消息")
    assert app.state.pending_steers == ["steer 消息"]
    projector.handle({"type": "queue_update"})
    assert app.state.pending_steers == []

    steer_message = UserMessage(
        role="user", content=[TextPart(type="text", text="steer 消息")], timestamp=0.0
    )
    projector.handle({"type": "message_start", "message": steer_message})

    user_records = [
        record for record in app.state.records if isinstance(record, UserPromptRecord)
    ]
    assert len(user_records) == 2
    assert user_records[0].text == "初始问题"
    assert user_records[1].text == "steer 消息"


def test_screen_event_projector_renders_queued_followup_into_transcript() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_screen_conversation_projection,
    )

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 1.0,
    )
    app.start_prompt("初始问题", started_at=1.0)
    projector = build_agent_screen_conversation_projection(
        app, read_pending_steers=tuple, read_pending_followups=tuple
    )
    projector.handle(
        {
            "type": "message_start",
            "message": UserMessage(
                role="user",
                content=[TextPart(type="text", text="初始问题")],
                timestamp=0.0,
            ),
        }
    )

    app.queue_followup("followup 消息")
    assert app.state.pending_followups == ["followup 消息"]
    projector.handle({"type": "queue_update"})
    assert app.state.pending_followups == []

    followup_message = UserMessage(
        role="user",
        content=[TextPart(type="text", text="followup 消息")],
        timestamp=0.0,
    )
    projector.handle({"type": "message_start", "message": followup_message})

    user_records = [
        record for record in app.state.records if isinstance(record, UserPromptRecord)
    ]
    assert len(user_records) == 2
    assert user_records[0].text == "初始问题"
    assert user_records[1].text == "followup 消息"


def test_screen_event_projector_renders_same_text_queued_message_after_initial_echo() -> (
    None
):
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_screen_conversation_projection,
    )

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 1.0,
    )
    app.start_prompt("same", started_at=1.0)
    projector = build_agent_screen_conversation_projection(app)

    message = UserMessage(
        role="user", content=[TextPart(type="text", text="same")], timestamp=0.0
    )
    projector.handle({"type": "message_start", "message": message})
    projector.handle({"type": "message_start", "message": message})

    assert app.state.records == [UserPromptRecord("same"), UserPromptRecord("same")]


def test_screen_event_projector_appends_compaction_record_without_trimming_history() -> (
    None
):
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_screen_conversation_projection,
    )

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 1.0,
    )
    app.state.records.extend(
        UserPromptRecord(f"old prompt {index}")
        if index % 2 == 0
        else AssistantMessageRecord(f"old answer {index}")
        for index in range(120)
    )
    app.state.records.append(UserPromptRecord("recent prompt"))
    projector = build_agent_screen_conversation_projection(app)

    projector.handle(
        {
            "type": "compaction_end",
            "result": {
                "summary": "condensed summary",
                "first_kept_entry_id": "entry-100",
                "tokens_before": 500_000,
            },
        }
    )

    assert len(app.state.records) == 122
    assert app.state.evicted_prefix_record_count == 0
    assert isinstance(app.state.records[-1], ContextCompactionRecord)
    assert app.state.records[-1].summary == "condensed summary"
    assert app.state.records[-1].tokens_before == 500_000
    assert app.state.records[0] == UserPromptRecord("old prompt 0")
    assert UserPromptRecord("recent prompt") in app.state.records
    assert app.consume_render_baseline_reset_reason() is None


def test_screen_event_projector_does_not_reset_baseline_without_compaction_eviction() -> (
    None
):
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_screen_conversation_projection,
    )

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 1.0,
    )
    app.state.records.extend(UserPromptRecord(str(index)) for index in range(79))

    build_agent_screen_conversation_projection(app).handle(
        {
            "type": "compaction_end",
            "result": {"summary": "condensed", "tokens_before": 1_000},
        }
    )

    assert len(app.state.records) == 80
    assert app.state.evicted_prefix_record_count == 0
    assert app.consume_render_baseline_reset_reason() is None
