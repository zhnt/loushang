from __future__ import annotations

import dis
from dataclasses import dataclass, field

import pytest

from loushang.harnesstui.conversation.projection import ConversationProjector
from loushang.harnesstui.conversation.screen_state import ScreenConversationState
from loushang.harnesstui.conversation.screen_target import (
    ScreenConversationProjectionTarget,
    build_screen_conversation_projection,
)
from loushang.harnesstui.conversation.tool_transcript import (
    ToolCallSnapshot,
    ToolTranscriptBlock,
    ToolTranscriptProjector,
)
from loushang.tui.transcript import (
    ContextCompactionRecord,
    ErrorRecord,
    ToolExecutionRecord,
    UserPromptRecord,
)


@dataclass
class _RecordingApp:
    state: ScreenConversationState = field(default_factory=ScreenConversationState)
    events: list[tuple[object, ...]] = field(default_factory=list)

    def begin_run(self, *, started_at: float | None = None) -> None:
        self.events.append(("begin_run", started_at))
        assert started_at is not None
        self.state.begin_run(started_at=started_at)

    def sync_queues(
        self,
        *,
        steers: tuple[str, ...],
        followups: tuple[str, ...],
    ) -> None:
        self.events.append(("sync_queues", steers, followups))
        self.state.sync_queues(steers=steers, followups=followups)

    def begin_assistant(self) -> None:
        self.events.append(("begin_assistant",))
        self.state.begin_assistant()

    def append_assistant_chunk(self, chunk: str) -> None:
        self.events.append(("append_assistant_chunk", chunk))
        self.state.append_assistant_chunk(chunk)

    def end_assistant(self, final_text: str | None = None) -> None:
        self.events.append(("end_assistant", final_text))
        self.state.end_assistant(final_text)

    def add_error(self, summary: str, diagnostics: str = "") -> None:
        self.events.append(("add_error", summary, diagnostics))
        self.state.add_error(summary, diagnostics)

    def set_status(self, message: str | None) -> None:
        self.events.append(("set_status", message))
        self.state.set_status(message)

    def append_context_compaction_record(
        self,
        *,
        summary: str = "",
        tokens_before: int | None = None,
    ) -> None:
        self.events.append(("append_context_compaction_record", summary, tokens_before))
        self.state.records.append(
            ContextCompactionRecord(
                summary=summary,
                tokens_before=tokens_before,
            )
        )
        self.state.mark_records_changed()


@dataclass
class _RecordingCopy:
    events: list[tuple[object, ...]] = field(default_factory=list)

    def retry_status(
        self,
        *,
        attempt: int | None,
        max_attempts: int | None,
        delay_ms: int | float | None,
        error_message: str | None,
    ) -> str:
        self.events.append(("retry", attempt, max_attempts, delay_ms, error_message))
        return "custom retry"

    def compaction_started_status(self, *, reason: str | None) -> str:
        self.events.append(("compaction_started", reason))
        return "custom compaction start"

    def compaction_finished_status(
        self,
        *,
        error_message: str | None,
    ) -> str:
        self.events.append(("compaction_finished", error_message))
        return "custom compaction error" if error_message else "custom compaction done"


def _tool_title(snapshot: ToolCallSnapshot) -> str:
    return f"running {snapshot.tool_name}"


def _tool_record(
    block: ToolTranscriptBlock,
    *,
    elapsed_seconds: float = 0.0,
) -> ToolExecutionRecord:
    return ToolExecutionRecord(
        name=f"finished {block.title}",
        state="completed",
        elapsed_seconds=elapsed_seconds,
    )


def _target(
    app: _RecordingApp | None = None,
    copy: _RecordingCopy | None = None,
) -> tuple[ScreenConversationProjectionTarget, _RecordingApp, _RecordingCopy]:
    app = app or _RecordingApp()
    copy = copy or _RecordingCopy()
    return (
        ScreenConversationProjectionTarget(
            app,
            tool_title_resolver=_tool_title,
            tool_record_projector=_tool_record,
            status_copy=copy,
        ),
        app,
        copy,
    )


def test_screen_target_reads_run_clock_only_when_starting_a_run() -> None:
    target, app, _ = _target()
    clock_calls = 0

    def clock() -> float:
        nonlocal clock_calls
        clock_calls += 1
        return 2.0

    target.run_started(start_time=clock)
    target.run_started(start_time=clock)

    assert clock_calls == 1
    assert app.events == [("begin_run", 2.0)]


def test_screen_target_syncs_queues_and_filters_user_echoes() -> None:
    target, app, _ = _target()
    app.state.start_prompt("same", started_at=1.0)

    target.queues_updated(steers=("steer",), followups=("followup",))
    target.user_message("  same  ")
    target.user_message("  different  ")
    target.user_message("same")
    target.user_message("   ")

    assert app.state.pending_steers == ["steer"]
    assert app.state.pending_followups == ["followup"]
    assert app.state.records == [
        UserPromptRecord("same"),
        UserPromptRecord("different"),
        UserPromptRecord("same"),
    ]
    assert app.events == [
        ("sync_queues", ("steer",), ("followup",)),
    ]


def test_screen_target_uses_app_assistant_lifecycle_and_error_methods() -> None:
    target, app, _ = _target()
    delta = "".join(("streamed", " text"))
    final_text = "".join(("final", " text"))

    target.assistant_started()
    target.assistant_delta(delta)
    target.assistant_finished(
        final_text,
        error_message="provider failed",
        show_error=True,
    )
    target.assistant_error("agent failed")

    assert app.events[0] == ("begin_assistant",)
    assert app.events[1][0] == "append_assistant_chunk"
    assert app.events[1][1] is delta
    assert app.events[2][0] == "end_assistant"
    assert app.events[2][1] is final_text
    assert app.events[3:] == [
        ("add_error", "provider failed", ""),
        ("add_error", "agent failed", ""),
    ]
    assert app.state.records[-2:] == [
        ErrorRecord("provider failed"),
        ErrorRecord("agent failed"),
    ]


@pytest.mark.tui_render_contract
def test_screen_target_delta_preserves_identity_without_building_containers() -> None:
    target, app, _ = _target()
    delta = "".join(("identity", "-sensitive", " delta"))

    target.assistant_delta(delta)

    assert app.events[0][1] is delta
    opnames = {
        instruction.opname
        for instruction in dis.get_instructions(
            ScreenConversationProjectionTarget.assistant_delta
        )
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


def test_screen_target_uses_injected_tool_title_and_record_projectors() -> None:
    app = _RecordingApp()
    copy = _RecordingCopy()
    seen_titles: list[ToolCallSnapshot] = []
    seen_records: list[tuple[ToolTranscriptBlock, float]] = []

    def title(snapshot: ToolCallSnapshot) -> str:
        seen_titles.append(snapshot)
        return "custom running label"

    def record(
        block: ToolTranscriptBlock,
        *,
        elapsed_seconds: float = 0.0,
    ) -> ToolExecutionRecord:
        seen_records.append((block, elapsed_seconds))
        return ToolExecutionRecord(
            name="custom finished label",
            state="failed",
            elapsed_seconds=elapsed_seconds,
        )

    target = ScreenConversationProjectionTarget(
        app,
        tool_title_resolver=title,
        tool_record_projector=record,
        status_copy=copy,
    )
    snapshot = ToolCallSnapshot(tool_name="neutral-tool")
    block = ToolTranscriptBlock(
        tool_call_id="tc1",
        tool_name="neutral-tool",
        status="error",
        verb="Used",
        title="neutral title",
    )

    target.tool_started("tc1", snapshot)
    target.tool_finished(block, elapsed_seconds=3.5)
    target.tool_result_message(block)

    assert seen_titles == [snapshot]
    assert seen_titles[0] is snapshot
    assert seen_records == [(block, 3.5)]
    assert seen_records[0][0] is block
    assert app.state.records == [
        ToolExecutionRecord(
            name="custom finished label",
            state="failed",
            elapsed_seconds=3.5,
        )
    ]


def test_screen_target_delegates_status_copy_and_compaction_recording() -> None:
    target, app, copy = _target()

    target.retry_started(
        attempt=2,
        max_attempts=3,
        delay_ms=1000,
        error_message="rate limit",
    )
    target.compaction_started(reason="threshold")
    target.compaction_finished(
        error_message="failed",
        summary="must not append",
        tokens_before=10,
    )
    target.compaction_finished(
        error_message=None,
        summary="",
        tokens_before=20,
    )
    target.compaction_finished(
        error_message=None,
        summary="condensed",
        tokens_before=30,
    )

    assert copy.events == [
        ("retry", 2, 3, 1000, "rate limit"),
        ("compaction_started", "threshold"),
        ("compaction_finished", "failed"),
        ("compaction_finished", None),
        ("compaction_finished", None),
    ]
    assert [event for event in app.events if event[0] == "set_status"] == [
        ("set_status", "custom retry"),
        ("set_status", "custom compaction start"),
        ("set_status", "custom compaction error"),
        ("set_status", "custom compaction done"),
        ("set_status", "custom compaction done"),
    ]
    assert [
        event for event in app.events if event[0] == "append_context_compaction_record"
    ] == [("append_context_compaction_record", "condensed", 30)]
    assert app.state.records == [
        ContextCompactionRecord(summary="condensed", tokens_before=30)
    ]


def test_screen_projection_builder_owns_target_projector_and_event_binding() -> None:
    app = _RecordingApp()
    copy = _RecordingCopy()
    events: list[str] = []
    seen_projectors: list[ConversationProjector] = []

    def event_handler_factory(
        projector: ConversationProjector,
    ) -> object:
        seen_projectors.append(projector)
        return events.append

    binding = build_screen_conversation_projection(
        app,
        tool_projector=ToolTranscriptProjector(),
        tool_title_resolver=_tool_title,
        tool_record_projector=_tool_record,
        status_copy=copy,
        event_handler_factory=event_handler_factory,  # type: ignore[arg-type]
        now=lambda: 7.0,
    )
    binding.handle("event")

    assert seen_projectors == [binding.projector]
    assert isinstance(binding.projector.target, ScreenConversationProjectionTarget)
    assert binding.projector.target.app is app
    assert binding.projector.target.status_copy is copy
    assert binding.projector.track_rendered_tool_results is False
    assert binding.projector.now() == 7.0
    assert events == ["event"]
