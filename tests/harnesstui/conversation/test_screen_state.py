from __future__ import annotations

from loushang.harnesstui.conversation.screen_state import (
    ActiveTranscriptWindow,
    ScreenConversationState,
)
from loushang.tui.transcript import (
    AssistantMessageRecord,
    ToolExecutionRecord,
    UserPromptRecord,
    WorkedDividerRecord,
)


def test_screen_conversation_state_tracks_bounded_transcript_generation() -> None:
    state = ScreenConversationState(cwd="/repo")
    records = (
        UserPromptRecord("question"),
        AssistantMessageRecord("answer"),
    )

    state.replace_transcript_window(
        ActiveTranscriptWindow(records, evicted_prefix_record_count=4)
    )

    assert state.records == list(records)
    assert state.records_revision == 1
    assert state.transcript_window_generation == 1
    assert state.evicted_prefix_record_count == 4

    assert state.trim_transcript_prefix(max_records=1) == 1
    assert state.records == [AssistantMessageRecord("answer")]
    assert state.records_revision == 2
    assert state.transcript_window_generation == 2
    assert state.evicted_prefix_record_count == 5


def test_screen_conversation_state_tracks_live_run_records() -> None:
    state = ScreenConversationState(cwd="/repo")

    state.start_prompt(" question ", started_at=10.0)
    state.append_assistant_chunk("partial ")
    state.append_assistant_chunk("answer")

    assert state.running is True
    assert state.assistant_draft == AssistantMessageRecord(
        "partial answer", stable=False
    )

    state.complete_run(elapsed_seconds=2.5)

    assert state.records == [
        UserPromptRecord("question"),
        AssistantMessageRecord("partial answer", stable=True),
        WorkedDividerRecord(2.5),
    ]
    assert state.running is False
    assert state.assistant_draft is None


def test_screen_conversation_state_updates_tools_and_restores_queues() -> None:
    state = ScreenConversationState(cwd="/repo")
    running = ToolExecutionRecord(name="read", state="running", elapsed_seconds=0.1)
    completed = ToolExecutionRecord(name="read", state="completed", elapsed_seconds=0.2)

    state.upsert_tool_record("tool-1", running)
    state.upsert_tool_record("tool-1", completed)
    state.queue_steer(" steer ")
    state.queue_followup(" follow up ")

    assert state.records == [completed]
    assert state.records_revision == 2
    assert state.restore_queued_to_text() == "steer\nfollow up"
    assert state.pending_steers == []
    assert state.pending_followups == []
