from __future__ import annotations

import dis
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from loushang.harnesstui.conversation.projection import (
    ConversationProjectionBinding,
    ConversationProjector,
    SessionConversationEventAdapter,
)
from loushang.harnesstui.conversation.tool_transcript import (
    ToolCallSnapshot,
    ToolCallView,
    ToolResultView,
    ToolTranscriptBlock,
    ToolTranscriptProjectionBinding,
    ToolTranscriptProjector,
)


@dataclass
class RecordingTarget:
    events: list[tuple[object, ...]] = field(default_factory=list)
    last_delta: str | None = None

    def run_started(self, *, start_time: Callable[[], float]) -> None:
        self.events.append(("run_started", start_time()))

    def queues_updated(
        self,
        *,
        steers: tuple[str, ...],
        followups: tuple[str, ...],
    ) -> None:
        self.events.append(("queues_updated", steers, followups))

    def user_message(self, text: str) -> None:
        self.events.append(("user_message", text))

    def assistant_started(self) -> None:
        self.events.append(("assistant_started",))

    def assistant_delta(self, delta: str) -> None:
        self.last_delta = delta

    def assistant_finished(
        self,
        final_text: str,
        *,
        error_message: str | None,
        show_error: bool,
    ) -> None:
        self.events.append(
            ("assistant_finished", final_text, error_message, show_error)
        )

    def assistant_error(self, error_message: str) -> None:
        self.events.append(("assistant_error", error_message))

    def tool_started(
        self,
        tool_call_id: str,
        snapshot: ToolCallSnapshot,
    ) -> None:
        self.events.append(("tool_started", tool_call_id, snapshot))

    def tool_finished(
        self,
        block: ToolTranscriptBlock,
        *,
        elapsed_seconds: float,
    ) -> None:
        self.events.append(("tool_finished", block, elapsed_seconds))

    def tool_result_message(self, block: ToolTranscriptBlock) -> None:
        self.events.append(("tool_result_message", block))

    def retry_started(
        self,
        *,
        attempt: int | None,
        max_attempts: int | None,
        delay_ms: int | float | None,
        error_message: str | None,
    ) -> None:
        self.events.append(
            (
                "retry_started",
                attempt,
                max_attempts,
                delay_ms,
                error_message,
            )
        )

    def compaction_started(self, *, reason: str | None) -> None:
        self.events.append(("compaction_started", reason))

    def compaction_finished(
        self,
        *,
        error_message: str | None,
        summary: str,
        tokens_before: int | None,
    ) -> None:
        self.events.append(
            ("compaction_finished", error_message, summary, tokens_before)
        )


def test_projection_binding_forwards_product_events_and_exposes_shared_state() -> None:
    target = RecordingTarget()
    projector = ConversationProjector(target)
    seen: list[object] = []
    binding = ConversationProjectionBinding[object](projector, seen.append)
    event = object()
    tool_calls = {"call-1": ToolCallSnapshot(tool_name="read")}
    rendered_tool_results = {"call-0"}
    rendered_assistant_errors: set[int | str] = {"message-1"}

    binding.tool_calls = tool_calls
    binding.rendered_tool_results = rendered_tool_results
    binding.rendered_assistant_errors = rendered_assistant_errors
    binding.last_error_message = "old error"
    binding.handle(event)

    assert seen == [event]
    assert seen[0] is event
    assert binding.tool_calls is tool_calls
    assert binding.rendered_tool_results is rendered_tool_results
    assert binding.rendered_assistant_errors is rendered_assistant_errors
    assert binding.last_error_message == "old error"
    assert binding.projector is projector


def test_assistant_delta_forwards_the_same_object_without_building_containers() -> None:
    target = RecordingTarget()
    projector = ConversationProjector(target)
    delta = "".join(("streamed", " ", "text"))

    projector.assistant_delta(delta)

    assert target.last_delta is delta
    opnames = {
        instruction.opname
        for instruction in dis.get_instructions(ConversationProjector.assistant_delta)
    }
    assert opnames.isdisjoint(
        {
            "BUILD_LIST",
            "BUILD_TUPLE",
            "BUILD_MAP",
            "BUILD_CONST_KEY_MAP",
            "BUILD_SET",
            "BUILD_STRING",
            "MAKE_FUNCTION",
            "RETURN_GENERATOR",
        }
    )


def test_session_event_adapter_routes_structural_events_without_product_types() -> None:
    target = RecordingTarget()
    projector = ConversationProjector(target, now=lambda: 2.0)
    tool_projection = ToolTranscriptProjectionBinding[dict[str, object], object](
        neutral_projector=ToolTranscriptProjector(),
        call_id=lambda event: str(event["tool_call_id"]),
        message_id=lambda message: str(getattr(message, "tool_call_id", "")),
        call_view=lambda event: ToolCallView(
            tool_call_id=str(event["tool_call_id"]),
            tool_name=str(event["tool_name"]),
        ),
        result_view=lambda event, _snapshot, _tool_call_id: ToolResultView(
            tool_call_id=str(event["tool_call_id"]),
            tool_name=str(event["tool_name"]),
            status="ok",
        ),
        tool_result_message_view=lambda message: ToolResultView(
            tool_call_id=str(getattr(message, "tool_call_id", "")),
            tool_name=str(getattr(message, "tool_name", "tool")),
            status="ok",
        ),
    )
    adapter = SessionConversationEventAdapter(
        projector,
        tool_projection,
        read_pending_steers=lambda: ["adjust"],
        read_pending_followups=lambda: ["next"],
    )

    adapter.handle({"type": "agent_start"})
    adapter.handle({"type": "queue_update"})
    adapter.handle(
        {
            "type": "message_start",
            "message": SimpleNamespace(role="user", content="hello"),
        }
    )
    adapter.handle(
        {
            "type": "message_update",
            "message": SimpleNamespace(role="assistant"),
            "assistant_message_event": {"type": "text_delta", "delta": "part"},
        }
    )
    adapter.handle(
        {
            "type": "compaction_end",
            "result": {"summary": "condensed", "tokens_before": 120},
        }
    )

    assert target.events == [
        ("run_started", 2.0),
        ("queues_updated", ("adjust",), ("next",)),
        ("user_message", "hello"),
        ("compaction_finished", None, "condensed", 120),
    ]
    assert target.last_delta == "part"


def test_session_event_adapter_notifies_session_info_changes() -> None:
    target = RecordingTarget()
    changed: list[str] = []
    adapter = SessionConversationEventAdapter(
        ConversationProjector(target),
        ToolTranscriptProjectionBinding[dict[str, object], object](
            neutral_projector=ToolTranscriptProjector(),
            call_id=lambda _event: "",
            message_id=lambda _message: "",
            call_view=lambda _event: ToolCallView(tool_call_id="", tool_name=""),
            result_view=lambda _event, _snapshot, _tool_call_id: ToolResultView(
                tool_call_id="",
                tool_name="",
                status="ok",
            ),
            tool_result_message_view=lambda _message: ToolResultView(
                tool_call_id="",
                tool_name="",
                status="ok",
            ),
        ),
        on_session_info_changed=lambda: changed.append("changed"),
    )

    adapter.handle({"type": "session_info_changed", "name": "Project Alpha"})

    assert changed == ["changed"]


def test_tool_call_snapshot_and_elapsed_time_are_shared_with_target() -> None:
    target = RecordingTarget()
    clock = iter((10.0, 11.0, 12.5)).__next__
    projector = ConversationProjector(
        target,
        tool_projector=ToolTranscriptProjector(
            verb_resolver=lambda tool_name, args: "Ran",
        ),
        now=clock,
    )

    projector.tool_started(
        ToolCallView(
            tool_call_id="call-1",
            tool_name="bash",
            args={"command": "pytest"},
            rendered_text="$ pytest",
        )
    )
    projector.tool_finished(
        ToolResultView(
            tool_call_id="call-1",
            tool_name="ignored-after-snapshot",
            status="ok",
        )
    )

    assert target.events == [
        (
            "tool_started",
            "call-1",
            ToolCallSnapshot(
                tool_name="bash",
                args={"command": "pytest"},
                rendered_call_text="$ pytest",
            ),
        ),
        (
            "tool_finished",
            ToolTranscriptBlock(
                tool_call_id="call-1",
                tool_name="bash",
                status="ok",
                verb="Ran",
                title="bash pytest",
            ),
            2.5,
        ),
    ]


def test_tool_elapsed_clock_wraps_neutral_result_projection() -> None:
    order: list[str] = []
    values = iter((10.0, 11.0, 14.0))

    def clock() -> float:
        order.append("clock")
        return next(values)

    class OrderedToolProjector(ToolTranscriptProjector):
        def project_result(
            self,
            view: ToolResultView,
            snapshot: ToolCallSnapshot | None = None,
        ) -> ToolTranscriptBlock:
            order.append("project")
            return super().project_result(view, snapshot)

    target = RecordingTarget()
    projector = ConversationProjector(
        target,
        tool_projector=OrderedToolProjector(),
        now=clock,
    )
    projector.tool_started(ToolCallView(tool_call_id="call-1", tool_name="bash"))

    context = projector.begin_tool_finish("call-1")
    projector.tool_finished(
        ToolResultView(tool_call_id="call-1", tool_name="bash", status="ok"),
        context=context,
    )

    assert order == ["clock", "clock", "project", "clock"]
    assert target.events[-1][2] == 4.0


def test_tool_finish_cleanup_policy_preserves_surface_exception_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = ToolCallView(tool_call_id="call-1", tool_name="bash")
    result = ToolResultView(tool_call_id="call-1", tool_name="bash", status="ok")

    def fail_projection(*args: object, **kwargs: object) -> ToolTranscriptBlock:
        del args, kwargs
        raise RuntimeError("projection failed")

    after_projector = ToolTranscriptProjector()
    monkeypatch.setattr(after_projector, "project_result", fail_projection)
    after = ConversationProjector(
        RecordingTarget(),
        tool_projector=after_projector,
        now=lambda: 1.0,
        tool_finish_cleanup="after_target",
    )
    after.tool_started(view)
    after_context = after.begin_tool_finish("call-1")

    with pytest.raises(RuntimeError, match="projection failed"):
        after.tool_finished(result, context=after_context)

    assert after.has_active_tool_call("call-1")

    before_projector = ToolTranscriptProjector()
    monkeypatch.setattr(before_projector, "project_result", fail_projection)
    before = ConversationProjector(
        RecordingTarget(),
        tool_projector=before_projector,
        measure_tool_elapsed=False,
        tool_finish_cleanup="before_projection",
    )
    before.tool_started(view)
    before_context = before.begin_tool_finish("call-1")

    with pytest.raises(RuntimeError, match="projection failed"):
        before.tool_finished(result, context=before_context)

    assert not before.has_active_tool_call("call-1")


def test_tool_update_without_start_creates_running_snapshot() -> None:
    target = RecordingTarget()
    clock = iter((4.0, 4.5, 5.0)).__next__
    projector = ConversationProjector(target, now=clock)
    view = ToolCallView(tool_call_id="call-1", tool_name="search")

    projector.tool_updated(view)
    projector.tool_finished(
        ToolResultView(tool_call_id="call-1", tool_name="search", status="ok")
    )

    assert target.events[0] == (
        "tool_started",
        "call-1",
        ToolCallSnapshot(tool_name="search"),
    )
    assert target.events[1][0] == "tool_finished"
    assert target.events[1][2] == 1.0


def test_tool_state_can_be_queried_without_projecting_an_event() -> None:
    target = RecordingTarget()
    projector = ConversationProjector(target, now=lambda: 1.0)
    view = ToolCallView(tool_call_id="call-1", tool_name="search")

    assert not projector.has_active_tool_call("call-1")
    assert projector.tool_call_snapshot("call-1") is None

    projector.tool_started(view)

    assert projector.has_active_tool_call("call-1")
    assert projector.tool_call_snapshot("call-1") == ToolCallSnapshot(
        tool_name="search"
    )


def test_tool_result_message_is_deduplicated_after_execution_end() -> None:
    target = RecordingTarget()
    projector = ConversationProjector(target, now=lambda: 1.0)
    result = ToolResultView(
        tool_call_id="call-1",
        tool_name="search",
        status="ok",
    )

    projector.tool_finished(result)
    projector.tool_result_message(result)
    projector.tool_result_message(result)

    assert [event[0] for event in target.events] == ["tool_finished"]


def test_target_without_tool_result_messages_does_not_retain_finished_ids() -> None:
    target = RecordingTarget()
    projector = ConversationProjector(
        target,
        now=lambda: 1.0,
        track_rendered_tool_results=False,
    )
    result = ToolResultView(
        tool_call_id="call-1",
        tool_name="search",
        status="ok",
    )

    projector.tool_finished(result)

    assert not projector.has_rendered_tool_result("call-1")
    assert projector.rendered_tool_results == set()


def test_visible_assistant_error_is_recorded_and_deduplicated_by_id() -> None:
    target = RecordingTarget()
    projector = ConversationProjector(target)

    projector.assistant_finished(
        "partial",
        error_message="provider failed",
        show_error=True,
        error_id=17,
    )
    projector.assistant_finished(
        "partial",
        error_message="provider failed",
        show_error=True,
        error_id=17,
    )
    projector.assistant_error(
        "provider failed",
        show_error=True,
        error_id=17,
    )

    assert projector.last_error_message == "provider failed"
    assert target.events == [
        ("assistant_finished", "partial", "provider failed", True),
        ("assistant_finished", "partial", "provider failed", False),
    ]


def test_hidden_assistant_error_updates_last_error_without_rendering() -> None:
    target = RecordingTarget()
    projector = ConversationProjector(target)

    projector.assistant_finished(
        "partial",
        error_message="request cancelled",
        show_error=False,
        error_id=23,
    )
    projector.assistant_error(
        "request cancelled",
        show_error=False,
        error_id=23,
    )

    assert projector.last_error_message == "request cancelled"
    assert target.events == [
        ("assistant_finished", "partial", "request cancelled", False),
    ]


def test_run_start_clears_pending_tool_timing() -> None:
    target = RecordingTarget()
    clock = iter((10.0, 20.0, 30.0, 40.0)).__next__
    projector = ConversationProjector(target, now=clock)
    projector.tool_started(ToolCallView(tool_call_id="call-1", tool_name="bash"))

    projector.run_started()
    projector.tool_finished(
        ToolResultView(tool_call_id="call-1", tool_name="bash", status="ok")
    )

    assert target.events[1] == ("run_started", 20.0)
    assert target.events[2][0] == "tool_finished"
    assert target.events[2][2] == 10.0


def test_run_start_time_is_lazy_for_targets_that_do_not_need_it() -> None:
    clock_calls = 0

    def clock() -> float:
        nonlocal clock_calls
        clock_calls += 1
        return 1.0

    @dataclass
    class LazyRunTarget(RecordingTarget):
        def run_started(self, *, start_time: Callable[[], float]) -> None:
            self.events.append(("run_started", start_time))

    target = LazyRunTarget()
    projector = ConversationProjector(target, now=clock)

    projector.run_started()

    assert clock_calls == 0
    assert target.events[0][0] == "run_started"


def test_neutral_lifecycle_facts_are_forwarded_without_product_policy() -> None:
    target = RecordingTarget()
    projector = ConversationProjector(target)

    projector.queues_updated(steers=("correct it",), followups=("then test",))
    projector.user_message("hello")
    projector.assistant_started()
    projector.retry_started(
        attempt=2,
        max_attempts=3,
        delay_ms=250.0,
        error_message="rate limited",
    )
    projector.compaction_started(reason="token budget")
    projector.compaction_finished(
        error_message=None,
        summary="Earlier context",
        tokens_before=8192,
    )

    assert target.events == [
        ("queues_updated", ("correct it",), ("then test",)),
        ("user_message", "hello"),
        ("assistant_started",),
        ("retry_started", 2, 3, 250.0, "rate limited"),
        ("compaction_started", "token budget"),
        ("compaction_finished", None, "Earlier context", 8192),
    ]
