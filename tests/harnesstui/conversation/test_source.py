from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass

import pytest

from loushang.harnesstui.conversation.screen_state import ScreenConversationState
from loushang.harnesstui.conversation.source import (
    ActiveWindowTranscriptSource,
    MaterializedTranscriptSource,
    TranscriptSnapshot,
    TranscriptSource,
    active_window_records,
    merge_history_and_active_records,
    recent_assistant_texts,
)
from loushang.tui.transcript import (
    AssistantMessageRecord,
    ContextCompactionRecord,
    DisplayRecord,
    StatusRecord,
    ToolExecutionRecord,
    UserPromptRecord,
    WorkedDividerRecord,
)


@dataclass(slots=True)
class _Source:
    records: tuple[DisplayRecord, ...]

    def snapshot(self) -> TranscriptSnapshot:
        return TranscriptSnapshot(records=self.records)

    def recent_assistant_texts(self) -> tuple[str, ...]:
        return tuple(
            record.text
            for record in reversed(self.records)
            if isinstance(record, AssistantMessageRecord) and record.text.strip()
        )


def _read_source(
    source: TranscriptSource,
) -> tuple[TranscriptSnapshot, tuple[str, ...]]:
    return source.snapshot(), source.recent_assistant_texts()


def test_transcript_snapshot_has_product_neutral_defaults() -> None:
    records: tuple[DisplayRecord, ...] = (
        UserPromptRecord("question"),
        AssistantMessageRecord("answer"),
    )

    snapshot = TranscriptSnapshot(records=records)

    assert snapshot.records is records
    assert snapshot.evicted_prefix_record_count == 0
    assert snapshot.complete is False
    assert snapshot.source_label == "Transcript window"


def test_transcript_snapshot_is_immutable() -> None:
    snapshot = TranscriptSnapshot(records=())

    with pytest.raises(FrozenInstanceError):
        snapshot.complete = True  # type: ignore[misc]


def test_transcript_source_is_a_structural_contract() -> None:
    source = _Source(
        (
            AssistantMessageRecord("first"),
            UserPromptRecord("next"),
            AssistantMessageRecord("second"),
        )
    )

    snapshot, recent_assistant_texts = _read_source(source)

    assert snapshot.records == source.records
    assert recent_assistant_texts == ("second", "first")


def test_recent_assistant_texts_filters_blank_messages_newest_first() -> None:
    records: tuple[DisplayRecord, ...] = (
        AssistantMessageRecord("  first  "),
        AssistantMessageRecord("   "),
        ToolExecutionRecord(name="read", state="completed", elapsed_seconds=0.1),
        AssistantMessageRecord("second", stable=False),
    )

    assert recent_assistant_texts(iter(records)) == ("second", "  first  ")


def test_active_window_records_appends_live_assistant_draft() -> None:
    state = ScreenConversationState(
        records=[UserPromptRecord("question")],
        evicted_prefix_record_count=3,
    )
    state.begin_run(started_at=1.0)
    state.append_assistant_chunk("draft")

    assert active_window_records(state) == (
        UserPromptRecord("question"),
        AssistantMessageRecord("draft", stable=False),
    )


def test_active_window_transcript_source_exposes_bounded_snapshot() -> None:
    state = ScreenConversationState(
        records=[AssistantMessageRecord("answer")],
        evicted_prefix_record_count=3,
    )

    source = ActiveWindowTranscriptSource(state)

    assert source.snapshot() == TranscriptSnapshot(
        records=(AssistantMessageRecord("answer"),),
        evicted_prefix_record_count=3,
        complete=False,
        source_label="Transcript window",
    )
    assert source.recent_assistant_texts() == ("answer",)


def test_materialized_transcript_source_exposes_complete_history() -> None:
    records = (
        UserPromptRecord("question"),
        AssistantMessageRecord("answer"),
    )
    source = MaterializedTranscriptSource(
        materialize_records=lambda: records,
        source_label="Conversation history",
    )

    assert source.snapshot() == TranscriptSnapshot(
        records=records,
        evicted_prefix_record_count=0,
        complete=True,
        source_label="Conversation history",
    )
    assert source.recent_assistant_texts() == ("answer",)


def test_materialized_transcript_source_merges_decorated_live_window() -> None:
    question = UserPromptRecord("question")
    answer = AssistantMessageRecord("answer")
    state = ScreenConversationState(
        records=[question, WorkedDividerRecord(1.0), answer],
    )
    state.begin_run(started_at=2.0)
    state.append_assistant_chunk("draft")
    source = MaterializedTranscriptSource(
        materialize_records=lambda: (question, answer),
        source_label="Conversation history",
        active_window_state=state,
    )

    assert source.snapshot() == TranscriptSnapshot(
        records=(
            question,
            WorkedDividerRecord(1.0),
            answer,
            AssistantMessageRecord("draft", stable=False),
        ),
        evicted_prefix_record_count=0,
        complete=False,
        source_label="Conversation history + live window",
    )


@pytest.mark.parametrize(
    ("record", "projected"),
    (
        (UserPromptRecord("question"), True),
        (AssistantMessageRecord("answer", stable=True), True),
        (AssistantMessageRecord("draft", stable=False), False),
        (
            ToolExecutionRecord(name="read", state="completed", elapsed_seconds=0.1),
            True,
        ),
        (ContextCompactionRecord("summary"), True),
        (WorkedDividerRecord(1.0), False),
        (StatusRecord("working"), False),
    ),
)
def test_merge_history_and_active_records_uses_only_projected_history_records(
    record: DisplayRecord, projected: bool
) -> None:
    decoration = StatusRecord("working")

    merged = merge_history_and_active_records(
        (record,),
        (record, decoration),
    )

    expected = (record, decoration) if projected else (record, record, decoration)
    assert merged == expected


def test_merge_history_and_active_records_returns_history_when_active_window_is_empty() -> (
    None
):
    history: tuple[DisplayRecord, ...] = (UserPromptRecord("question"),)

    merged = merge_history_and_active_records(history, ())

    assert merged is history


def test_merge_history_and_active_records_appends_unmatched_window() -> None:
    history: tuple[DisplayRecord, ...] = (UserPromptRecord("history"),)
    active: tuple[DisplayRecord, ...] = (UserPromptRecord("active"),)

    assert merge_history_and_active_records(history, active) == (*history, *active)


def test_merge_history_and_active_records_appends_ui_only_window() -> None:
    history: tuple[DisplayRecord, ...] = (UserPromptRecord("history"),)
    active: tuple[DisplayRecord, ...] = (
        WorkedDividerRecord(1.0),
        StatusRecord("working"),
        AssistantMessageRecord("draft", stable=False),
    )

    assert merge_history_and_active_records(history, active) == (*history, *active)


def test_merge_history_and_active_records_replaces_maximal_overlap_with_decorated_window() -> (
    None
):
    first_question = UserPromptRecord("first question")
    first_answer = AssistantMessageRecord("first answer")
    second_question = UserPromptRecord("second question")
    second_answer = AssistantMessageRecord("second answer")
    history: tuple[DisplayRecord, ...] = (
        first_question,
        first_answer,
        second_question,
        second_answer,
    )
    active: tuple[DisplayRecord, ...] = (
        second_question,
        WorkedDividerRecord(1.0),
        second_answer,
        AssistantMessageRecord("streaming draft", stable=False),
    )

    assert merge_history_and_active_records(history, active) == (
        first_question,
        first_answer,
        *active,
    )
