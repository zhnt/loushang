from __future__ import annotations

from dataclasses import dataclass, field
from io import StringIO

from loushang.harnesstui.conversation.plain_target import (
    PlainConversationProjectionTarget,
    build_plain_conversation_projection,
)
from loushang.harnesstui.conversation.projection import ConversationProjector
from loushang.harnesstui.conversation.tool_transcript import (
    ToolCallSnapshot,
    ToolTranscriptBlock,
    ToolTranscriptProjector,
)
from loushang.harnesstui.plain.renderer import PlainConversationRenderer
from loushang.tui import TranscriptBuffer


@dataclass
class _RecordingRenderer:
    events: list[tuple[object, ...]] = field(default_factory=list)

    def render_user(self, text: str) -> None:
        self.events.append(("user", text))

    def begin_assistant(self) -> None:
        self.events.append(("assistant_started",))

    def write_assistant_delta(self, text: str) -> None:
        self.events.append(("assistant_delta", text))

    def end_assistant(self, final_text: str) -> None:
        self.events.append(("assistant_finished", final_text))

    def render_error(self, text: str) -> None:
        self.events.append(("error", text))

    def render_tool_block(self, block: ToolTranscriptBlock) -> None:
        self.events.append(("tool", block))

    def render_status(self, text: str) -> None:
        self.events.append(("status", text))


def _target() -> tuple[PlainConversationProjectionTarget, _RecordingRenderer]:
    renderer = _RecordingRenderer()
    return PlainConversationProjectionTarget(renderer), renderer


def test_plain_target_maps_conversation_content_directly() -> None:
    target, renderer = _target()

    target.run_started(start_time=lambda: 1.0)
    target.queues_updated(steers=("steer",), followups=("followup",))
    target.user_message("question")
    target.assistant_started()
    target.assistant_delta("first")
    target.assistant_delta(" second")
    target.assistant_finished(
        "first second",
        error_message=None,
        show_error=False,
    )

    assert renderer.events == [
        ("user", "question"),
        ("assistant_started",),
        ("assistant_delta", "first"),
        ("assistant_delta", " second"),
        ("assistant_finished", "first second"),
    ]


def test_plain_target_does_not_commit_errored_assistant_draft() -> None:
    target, renderer = _target()

    target.assistant_finished(
        "partial",
        error_message="provider failed",
        show_error=False,
    )
    target.assistant_finished(
        "partial",
        error_message="visible failure",
        show_error=True,
    )
    target.assistant_error("agent failure")

    assert renderer.events == [
        ("error", "visible failure"),
        ("error", "agent failure"),
    ]


def test_plain_target_clears_errored_buffer_draft_when_next_assistant_starts() -> None:
    buffer = TranscriptBuffer()
    renderer = PlainConversationRenderer(
        stdout=StringIO(),
        transcript_buffer=buffer,
    )
    target = PlainConversationProjectionTarget(renderer)

    target.assistant_started()
    target.assistant_delta("partial")
    target.assistant_finished(
        "partial",
        error_message="aborted",
        show_error=False,
    )

    assert buffer.assistant_draft is not None
    assert buffer.assistant_draft.text == "partial"
    assert buffer.records == ()

    target.assistant_started()

    assert buffer.assistant_draft is None


def test_plain_target_maps_completed_tools_and_ignores_start_metadata() -> None:
    target, renderer = _target()
    snapshot = ToolCallSnapshot(tool_name="read")
    block = ToolTranscriptBlock(
        tool_call_id="tc1",
        tool_name="read",
        status="ok",
        verb="Explored",
        title="README.md",
    )

    target.tool_started("tc1", snapshot)
    target.tool_finished(block, elapsed_seconds=3.5)
    target.tool_result_message(block)

    assert renderer.events == [("tool", block), ("tool", block)]


def test_plain_target_preserves_retry_and_compaction_status_text() -> None:
    target, renderer = _target()

    target.retry_started(
        attempt=2,
        max_attempts=3,
        delay_ms=1000,
        error_message="rate limit",
    )
    target.compaction_started(reason="threshold")
    target.compaction_finished(
        error_message="compact failed",
        summary="ignored",
        tokens_before=8192,
    )
    target.compaction_finished(
        error_message=None,
        summary="ignored",
        tokens_before=None,
    )

    assert renderer.events == [
        ("status", "[retry] attempt 2/3 in 1000ms: rate limit"),
        ("status", "[compact] start: threshold"),
        ("status", "[compact] error: compact failed"),
        ("status", "[compact] done"),
    ]


def test_plain_projection_builder_owns_target_projector_and_event_binding() -> None:
    renderer = _RecordingRenderer()
    tool_calls = {"tc1": ToolCallSnapshot(tool_name="read")}
    events: list[str] = []
    seen_projectors: list[ConversationProjector] = []

    def event_handler_factory(
        projector: ConversationProjector,
    ) -> object:
        seen_projectors.append(projector)
        return events.append

    binding = build_plain_conversation_projection(
        renderer,
        tool_projector=ToolTranscriptProjector(),
        event_handler_factory=event_handler_factory,  # type: ignore[arg-type]
        tool_calls=tool_calls,
        last_error_message="previous",
    )
    binding.handle("event")

    assert seen_projectors == [binding.projector]
    assert isinstance(binding.projector.target, PlainConversationProjectionTarget)
    assert binding.projector.target.renderer is renderer
    assert binding.projector.tool_calls is tool_calls
    assert binding.projector.measure_tool_elapsed is False
    assert binding.projector.tool_finish_cleanup == "before_projection"
    assert binding.last_error_message == "previous"
    assert events == ["event"]
