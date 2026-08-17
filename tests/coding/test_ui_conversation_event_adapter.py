from __future__ import annotations

import dis
from types import SimpleNamespace
from typing import Any, cast

import pytest

from loushang.agent import AgentToolResult
from loushang.ai import TextPart, ToolResultMessage
from loushang.harnesstui.conversation.tool_transcript import (
    ToolCallSnapshot,
    ToolCallView,
    ToolResultView,
)


class _RecordingProjector:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
        self.tool_calls: dict[str, ToolCallSnapshot] = {}
        self.rendered_tool_results: set[str] = set()

    def has_active_tool_call(self, tool_call_id: str) -> bool:
        return tool_call_id in self.tool_calls

    def tool_call_snapshot(self, tool_call_id: str) -> ToolCallSnapshot | None:
        return self.tool_calls.get(tool_call_id)

    def begin_tool_finish(self, tool_call_id: str) -> object:
        return SimpleNamespace(
            tool_call_id=tool_call_id,
            snapshot=self.tool_calls.get(tool_call_id),
            started_at=0.0,
        )

    def has_rendered_tool_result(self, tool_call_id: str) -> bool:
        return tool_call_id in self.rendered_tool_results

    def tool_started(self, view: ToolCallView) -> None:
        self.calls.append(("tool_started", (view,), {}))
        self.tool_calls[view.tool_call_id] = ToolCallSnapshot(
            tool_name=view.tool_name,
            args=view.args,
            rendered_call_text=view.rendered_text,
        )

    def tool_updated(self, view: ToolCallView) -> None:
        self.calls.append(("tool_updated", (view,), {}))
        self.tool_calls[view.tool_call_id] = ToolCallSnapshot(
            tool_name=view.tool_name,
            args=view.args,
            rendered_call_text=view.rendered_text,
        )

    def tool_finished(self, view: ToolResultView, *, context: object) -> None:
        self.calls.append(("tool_finished", (view,), {"context": context}))
        self.tool_calls.pop(view.tool_call_id, None)
        self.rendered_tool_results.add(view.tool_call_id)

    def tool_result_message(
        self,
        view: ToolResultView,
        *,
        deduplicate: bool,
    ) -> None:
        self.calls.append(
            ("tool_result_message", (view,), {"deduplicate": deduplicate})
        )
        if deduplicate:
            self.rendered_tool_results.add(view.tool_call_id)

    def __getattr__(self, name: str):
        def record(*args: object, **kwargs: object) -> None:
            self.calls.append((name, args, kwargs))

        return record


def _adapter(
    projector: _RecordingProjector,
    *,
    tool_projector: object | None = None,
    **kwargs: object,
):
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_tool_transcript_projection,
    )
    from loushang.harnesstui.conversation.projection import (
        SessionConversationEventAdapter,
    )

    return SessionConversationEventAdapter(
        projector=cast(Any, projector),
        tool_projection=cast(
            Any,
            tool_projector
            if tool_projector is not None
            else build_agent_tool_transcript_projection(),
        ),
        **kwargs,
    )


def test_coding_event_adapter_maps_message_and_queue_events_to_neutral_facts() -> None:
    projector = _RecordingProjector()
    adapter = _adapter(
        projector,
        read_pending_steers=lambda: ["steer"],
        read_pending_followups=lambda: ("follow",),
    )
    user = SimpleNamespace(
        role="user",
        content=[SimpleNamespace(text="hello "), SimpleNamespace(text="world")],
    )
    assistant = SimpleNamespace(
        role="assistant",
        content=[SimpleNamespace(text="answer")],
        stop_reason="stop",
        error_message=None,
    )
    delta = " streamed"

    adapter.handle({"type": "agent_start"})
    adapter.handle({"type": "queue_update"})
    adapter.handle({"type": "message_start", "message": user})
    adapter.handle({"type": "message_start", "message": assistant})
    adapter.handle(
        {
            "type": "message_update",
            "message": assistant,
            "assistant_message_event": {"type": "text_delta", "delta": delta},
        }
    )
    adapter.handle({"type": "message_end", "message": assistant})

    assert projector.calls[:4] == [
        ("run_started", (), {}),
        ("queues_updated", (), {"steers": ("steer",), "followups": ("follow",)}),
        ("user_message", ("hello world",), {}),
        ("assistant_started", (), {}),
    ]
    assert projector.calls[4][0] == "assistant_delta"
    assert projector.calls[4][1][0] is delta
    assert projector.calls[5] == (
        "assistant_finished",
        ("answer",),
        {"error_message": None, "show_error": False, "error_id": id(assistant)},
    )


def test_coding_event_adapter_applies_coding_assistant_error_policy() -> None:
    projector = _RecordingProjector()
    adapter = _adapter(projector)
    cancelled = SimpleNamespace(
        role="assistant",
        content=[],
        stop_reason="aborted",
        error_message="Request aborted by user",
    )
    failed = SimpleNamespace(
        role="assistant",
        content=[],
        stop_reason="error",
        error_message="provider failure",
    )

    adapter.handle({"type": "message_end", "message": cancelled})
    adapter.handle({"type": "agent_end", "messages": [cancelled, failed]})

    assert projector.calls == [
        (
            "assistant_finished",
            ("",),
            {
                "error_message": "Request aborted by user",
                "show_error": False,
                "error_id": id(cancelled),
            },
        ),
        (
            "assistant_error",
            ("provider failure",),
            {"show_error": True, "error_id": id(failed)},
        ),
    ]


def test_coding_event_adapter_maps_raw_tool_events_to_neutral_views() -> None:
    projector = _RecordingProjector()
    adapter = _adapter(projector)
    result = AgentToolResult(
        content=[TextPart(type="text", text="ok")],
        details={},
    )
    start = {
        "type": "tool_execution_start",
        "tool_call_id": "tc1",
        "tool_name": "read",
        "args": {"path": "README.md"},
    }

    adapter.handle(start)
    adapter.handle({**start, "type": "tool_execution_update"})
    adapter.handle(
        {
            "type": "tool_execution_end",
            "tool_call_id": "tc1",
            "tool_name": "read",
            "result": result,
            "is_error": False,
        }
    )
    adapter.handle(
        {
            "type": "message_end",
            "message": ToolResultMessage(
                role="toolResult",
                tool_call_id="tc2",
                tool_name="finish",
                content=result.content,
                details=result.details,
                is_error=False,
                terminate=True,
                timestamp=0.0,
            ),
        }
    )

    start_view = projector.calls[0][1][0]
    result_view = projector.calls[1][1][0]
    replay_view = projector.calls[2][1][0]
    assert isinstance(start_view, ToolCallView)
    assert start_view.tool_call_id == "tc1"
    assert start_view.args == {"path": "README.md"}
    assert isinstance(result_view, ToolResultView)
    assert result_view.tool_call_id == "tc1"
    assert result_view.status == "ok"
    assert isinstance(replay_view, ToolResultView)
    assert replay_view.tool_call_id == "tc2"
    assert replay_view.status == "terminate"


def test_coding_event_adapter_extracts_retry_and_compaction_values() -> None:
    projector = _RecordingProjector()
    adapter = _adapter(projector)

    adapter.handle(
        {
            "type": "auto_retry_start",
            "attempt": 2,
            "max_attempts": 3,
            "delay_ms": 1000,
            "error_message": "rate limit",
        }
    )
    adapter.handle({"type": "compaction_start", "reason": "threshold"})
    adapter.handle(
        {
            "type": "compaction_end",
            "result": {"summary": "  condensed  ", "tokens_before": 500_000},
        }
    )

    assert projector.calls == [
        (
            "retry_started",
            (),
            {
                "attempt": 2,
                "max_attempts": 3,
                "delay_ms": 1000,
                "error_message": "rate limit",
            },
        ),
        ("compaction_started", (), {"reason": "threshold"}),
        (
            "compaction_finished",
            (),
            {
                "error_message": None,
                "summary": "condensed",
                "tokens_before": 500_000,
            },
        ),
    ]


def test_coding_tool_adapter_exposes_read_only_neutral_views_and_projector() -> None:
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_tool_transcript_projection,
    )
    from loushang.harnesstui.conversation.tool_transcript import (
        ToolTranscriptProjector as NeutralToolTranscriptProjector,
    )

    projector = build_agent_tool_transcript_projection()
    call = projector.call_view(
        {
            "type": "tool_execution_start",
            "tool_call_id": "tc1",
            "tool_name": "bash",
            "args": {"command": "pytest -q"},
        }
    )
    result = projector.result_view(
        {
            "type": "tool_execution_end",
            "tool_call_id": "tc1",
            "tool_name": "bash",
            "result": AgentToolResult(
                content=[TextPart(type="text", text="1 passed")], details={}
            ),
        }
    )

    assert isinstance(projector.neutral_projector, NeutralToolTranscriptProjector)
    assert call.tool_call_id == result.tool_call_id == "tc1"
    assert call.tool_name == result.tool_name == "bash"
    assert result.result_text == "1 passed"


class _CountingRenderRuntime:
    def __init__(self) -> None:
        self.call_count = 0

    def render_event(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        self.call_count += 1


def _counting_tool_projector(runtime: _CountingRenderRuntime):
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_tool_transcript_projection,
    )

    return build_agent_tool_transcript_projection(
        tool_definition_resolver=lambda name: None,
        render_runtime=cast(Any, runtime),
    )


def test_tool_update_interest_short_circuits_expensive_call_projection() -> None:
    projector = _RecordingProjector()
    runtime = _CountingRenderRuntime()
    adapter = _adapter(
        projector,
        tool_projector=_counting_tool_projector(runtime),
        recover_tool_updates=True,
    )
    start = {
        "type": "tool_execution_start",
        "tool_call_id": "tc1",
        "tool_name": "bash",
        "args": {"command": "pytest -q"},
    }

    adapter.handle(start)
    assert runtime.call_count == 1
    projector.calls.clear()
    runtime.call_count = 0

    adapter.handle({**start, "type": "tool_execution_update"})

    assert runtime.call_count == 0
    assert projector.calls == []

    adapter.handle(
        {
            **start,
            "type": "tool_execution_update",
            "tool_call_id": "tc-missing",
        }
    )

    assert runtime.call_count == 1
    assert projector.calls[0][0] == "tool_updated"


def test_disabled_tool_update_recovery_skips_missing_call_projection() -> None:
    projector = _RecordingProjector()
    runtime = _CountingRenderRuntime()
    adapter = _adapter(
        projector,
        tool_projector=_counting_tool_projector(runtime),
        recover_tool_updates=False,
    )

    adapter.handle(
        {
            "type": "tool_execution_update",
            "tool_call_id": "tc-missing",
            "tool_name": "bash",
        }
    )

    assert runtime.call_count == 0
    assert projector.calls == []


def test_tool_result_message_interest_and_dedup_skip_result_projection() -> None:
    result = AgentToolResult(
        content=[TextPart(type="text", text="done")], details={}
    )
    rendered_message = ToolResultMessage(
        role="toolResult",
        tool_call_id="tc-rendered",
        tool_name="bash",
        content=result.content,
        details=result.details,
        is_error=False,
        timestamp=0.0,
    )
    fresh_message = ToolResultMessage(
        role="toolResult",
        tool_call_id="tc-fresh",
        tool_name="bash",
        content=result.content,
        details=result.details,
        is_error=False,
        timestamp=0.0,
    )
    projector = _RecordingProjector()
    projector.rendered_tool_results.add("tc-rendered")
    runtime = _CountingRenderRuntime()
    tool_projector = _counting_tool_projector(runtime)
    adapter = _adapter(
        projector,
        tool_projector=tool_projector,
        project_tool_result_messages=True,
    )

    adapter.handle({"type": "message_end", "message": rendered_message})
    assert runtime.call_count == 0
    assert projector.calls == []

    ignored_adapter = _adapter(
        projector,
        tool_projector=tool_projector,
        project_tool_result_messages=False,
    )
    ignored_adapter.handle({"type": "message_end", "message": fresh_message})
    assert runtime.call_count == 0
    assert projector.calls == []

    adapter.handle({"type": "message_end", "message": fresh_message})
    assert runtime.call_count == 1
    assert projector.calls[0][0] == "tool_result_message"


def test_delta_message_role_requirement_is_surface_configurable() -> None:
    delta_event = {
        "type": "message_update",
        "message": SimpleNamespace(role="user"),
        "assistant_message_event": {"type": "text_delta", "delta": "delta"},
    }
    strict_projector = _RecordingProjector()
    loose_projector = _RecordingProjector()

    _adapter(
        strict_projector, require_assistant_message_for_delta=True
    ).handle(delta_event)
    _adapter(
        loose_projector, require_assistant_message_for_delta=False
    ).handle(delta_event)

    assert strict_projector.calls == []
    assert loose_projector.calls == [("assistant_delta", ("delta",), {})]


def test_result_view_uses_started_tool_name_for_body_policy() -> None:
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_tool_transcript_projection,
    )

    tool_projector = build_agent_tool_transcript_projection(max_body_lines=4)
    snapshot = tool_projector.remember_call(
        {
            "type": "tool_execution_start",
            "tool_call_id": "tc1",
            "tool_name": "bash",
            "args": {"command": "pytest -q"},
        }
    )
    block = tool_projector.project_result(
        {
            "type": "tool_execution_end",
            "tool_call_id": "tc1",
            "result": AgentToolResult(
                content=[TextPart(type="text", text="1 passed")], details={}
            ),
            "is_error": False,
        },
        snapshot,
    )

    assert block.tool_name == "bash"
    assert block.body == "1 passed"


def test_tool_end_reads_active_snapshot_before_adapting_result() -> None:
    projector = _RecordingProjector()
    adapter = _adapter(projector)
    adapter.handle(
        {
            "type": "tool_execution_start",
            "tool_call_id": "tc1",
            "tool_name": "bash",
            "args": {"command": "pytest -q"},
        }
    )
    projector.calls.clear()

    adapter.handle(
        {
            "type": "tool_execution_end",
            "tool_call_id": "tc1",
            "result": AgentToolResult(
                content=[TextPart(type="text", text="1 passed")], details={}
            ),
            "is_error": False,
        }
    )

    result_view = projector.calls[0][1][0]
    assert isinstance(result_view, ToolResultView)
    assert result_view.result_text == "1 passed"


def test_tool_finish_timing_begins_before_result_projection() -> None:
    order: list[str] = []

    class OrderedProjector(_RecordingProjector):
        def begin_tool_finish(self, tool_call_id: str) -> object:
            order.append("begin")
            return super().begin_tool_finish(tool_call_id)

        def tool_finished(self, view: ToolResultView, *, context: object) -> None:
            order.append("finish")
            super().tool_finished(view, context=context)

    class OrderedRenderRuntime(_CountingRenderRuntime):
        def render_event(self, *args: object, **kwargs: object) -> None:
            order.append("project")
            super().render_event(*args, **kwargs)

    projector = OrderedProjector()
    runtime = OrderedRenderRuntime()
    adapter = _adapter(
        projector,
        tool_projector=_counting_tool_projector(runtime),
    )
    adapter.handle(
        {
            "type": "tool_execution_start",
            "tool_call_id": "tc1",
            "tool_name": "bash",
            "args": {"command": "pytest -q"},
        }
    )
    order.clear()

    adapter.handle(
        {
            "type": "tool_execution_end",
            "tool_call_id": "tc1",
            "tool_name": "bash",
            "result": AgentToolResult(
                content=[TextPart(type="text", text="1 passed")], details={}
            ),
            "is_error": False,
        }
    )

    assert order == ["begin", "project", "finish"]


def test_run_and_queue_interest_short_circuit_before_queue_reads() -> None:
    def poison_queue_reader() -> tuple[str, ...]:
        raise AssertionError("queue reader must not run")

    projector = _RecordingProjector()
    adapter = _adapter(
        projector,
        read_pending_steers=poison_queue_reader,
        read_pending_followups=poison_queue_reader,
        project_run_starts=False,
        project_queue_updates=False,
    )

    adapter.handle({"type": "agent_start"})
    adapter.handle({"type": "queue_update"})

    assert projector.calls == []


class _PoisonUserMessage:
    role = "user"

    @property
    def content(self) -> object:
        raise AssertionError("user content must not be read")


class _PoisonAssistantError:
    role = "assistant"
    stop_reason = "error"
    error_message = "provider failure"

    @property
    def content(self) -> object:
        raise AssertionError("errored assistant content must not be read")


def test_message_interest_short_circuits_before_text_extraction() -> None:
    projector = _RecordingProjector()
    adapter = _adapter(
        projector,
        project_user_messages=False,
        project_assistant_error_text=False,
    )
    assistant = _PoisonAssistantError()

    adapter.handle({"type": "message_start", "message": _PoisonUserMessage()})
    adapter.handle({"type": "message_end", "message": assistant})

    assert projector.calls == [
        (
            "assistant_finished",
            ("",),
            {
                "error_message": "provider failure",
                "show_error": True,
                "error_id": id(assistant),
            },
        )
    ]


class _PoisonCompactionResult(dict[str, object]):
    def get(self, key: str, default: object = None) -> object:
        del key, default
        raise AssertionError("compaction result must not be read")


def test_compaction_interest_and_error_short_circuit_detail_reads() -> None:
    projector = _RecordingProjector()
    adapter = _adapter(projector, project_compaction_details=False)
    poison_result = _PoisonCompactionResult()

    adapter.handle(
        {
            "type": "compaction_end",
            "error_message": 503,
            "result": poison_result,
        }
    )
    adapter.handle({"type": "compaction_end", "result": poison_result})

    assert projector.calls == [
        (
            "compaction_finished",
            (),
            {"error_message": "503", "summary": "", "tokens_before": None},
        ),
        (
            "compaction_finished",
            (),
            {"error_message": None, "summary": "", "tokens_before": None},
        ),
    ]


def test_anonymous_tool_result_messages_are_not_deduplicated() -> None:
    result = AgentToolResult(
        content=[TextPart(type="text", text="done")], details={}
    )
    message = SimpleNamespace(
        role="toolResult",
        tool_name="read",
        content=result.content,
        details=result.details,
        is_error=False,
        terminate=False,
    )
    projector = _RecordingProjector()
    adapter = _adapter(projector)

    adapter.handle({"type": "message_end", "message": message})
    adapter.handle({"type": "message_end", "message": message})

    assert len(projector.calls) == 2
    for name, args, kwargs in projector.calls:
        assert name == "tool_result_message"
        view = args[0]
        assert isinstance(view, ToolResultView)
        assert view.tool_call_id == "read"
        assert kwargs == {"deduplicate": False}


@pytest.mark.tui_render_contract
def test_delta_hot_path_preserves_identity_without_container_construction() -> None:
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_tool_transcript_projection,
    )
    from loushang.harnesstui.conversation.projection import (
        ConversationProjector,
        SessionConversationEventAdapter,
    )

    class DeltaTarget:
        delta: str | None = None

        def assistant_delta(self, delta: str) -> None:
            self.delta = delta

    target = DeltaTarget()
    adapter = SessionConversationEventAdapter(
        projector=ConversationProjector(target=cast(Any, target)),
        tool_projection=build_agent_tool_transcript_projection(),
        require_assistant_message_for_delta=False,
    )
    delta = "identity-sensitive delta"

    adapter.handle(
        {
            "type": "message_update",
            "assistant_message_event": {"type": "text_delta", "delta": delta},
        }
    )

    assert target.delta is delta
    forbidden = {
        "BUILD_LIST",
        "BUILD_TUPLE",
        "BUILD_MAP",
        "BUILD_CONST_KEY_MAP",
        "BUILD_SET",
        "LIST_APPEND",
        "MAP_ADD",
        "SET_ADD",
    }
    for hot_method in (
        SessionConversationEventAdapter._handle_message_update,
        ConversationProjector.assistant_delta,
    ):
        opnames = {
            instruction.opname for instruction in dis.get_instructions(hot_method)
        }
        assert opnames.isdisjoint(forbidden)
