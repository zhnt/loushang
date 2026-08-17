from __future__ import annotations

from dataclasses import dataclass

from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
from loushang.harnesstui.conversation.agent_binding import (
    agent_session_history_records,
)
from loushang.harnesstui.conversation.screen_state import ScreenConversationState
from loushang.harnesstui.conversation.source import (
    ActiveWindowTranscriptSource,
    MaterializedTranscriptSource,
)
from loushang.tui.transcript import (
    AssistantMessageRecord,
    ToolExecutionRecord,
    UserPromptRecord,
    WorkedDividerRecord,
)


@dataclass(slots=True)
class _Session:
    messages: list[object]


def _session_transcript_source(
    session: _Session,
    *,
    source_label: str = "Full transcript",
    active_window_state: ScreenConversationState | None = None,
) -> MaterializedTranscriptSource:
    return MaterializedTranscriptSource(
        materialize_records=lambda: agent_session_history_records(session.messages),
        source_label=source_label,
        active_window_state=active_window_state,
    )


def test_active_window_transcript_source_returns_snapshot_metadata() -> None:
    state = ScreenConversationState(
        model_label="model", cwd="/tmp/project", branch=None, session_label=None
    )
    state.replace_transcript_window(
        (
            UserPromptRecord("hello"),
            AssistantMessageRecord("answer"),
        ),
        evicted_prefix_record_count=3,
    )

    snapshot = ActiveWindowTranscriptSource(state).snapshot()

    assert snapshot.records == tuple(state.records)
    assert snapshot.evicted_prefix_record_count == 3
    assert snapshot.complete is False
    assert snapshot.source_label == "Transcript window"


def test_active_window_transcript_source_includes_live_assistant_draft() -> None:
    state = ScreenConversationState(
        model_label="model", cwd="/tmp/project", branch=None, session_label=None
    )
    state.replace_transcript_window(
        (
            UserPromptRecord("hello"),
            AssistantMessageRecord("answer"),
        ),
    )
    state.begin_run(started_at=1.0)
    state.append_assistant_chunk("streaming draft")

    snapshot = ActiveWindowTranscriptSource(state).snapshot()

    assert snapshot.records == (
        UserPromptRecord("hello"),
        AssistantMessageRecord("answer"),
        AssistantMessageRecord("streaming draft", stable=False),
    )
    assert snapshot.complete is False
    assert snapshot.source_label == "Transcript window"


def test_active_window_transcript_source_recent_assistant_texts_are_filtered_newest_first() -> (
    None
):
    state = ScreenConversationState(
        model_label="model", cwd="/tmp/project", branch=None, session_label=None
    )
    state.records.extend(
        [
            AssistantMessageRecord("first"),
            AssistantMessageRecord(""),
            ToolExecutionRecord(name="read", state="completed", elapsed_seconds=0.1),
            AssistantMessageRecord("second"),
        ]
    )

    assert ActiveWindowTranscriptSource(state).recent_assistant_texts() == (
        "second",
        "first",
    )


def test_session_transcript_source_returns_complete_session_snapshot() -> None:
    session = _Session(
        messages=[
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="full question")],
                timestamp=1.0,
            ),
            _assistant_message("full answer", timestamp=2.0),
        ]
    )

    snapshot = _session_transcript_source(session).snapshot()

    assert snapshot.complete is True
    assert snapshot.evicted_prefix_record_count == 0
    assert snapshot.source_label == "Full transcript"
    assert snapshot.records == (
        UserPromptRecord("full question"),
        AssistantMessageRecord("full answer", stable=True),
    )


def test_session_transcript_source_recent_assistant_texts_are_filtered_newest_first() -> (
    None
):
    session = _Session(
        messages=[
            _assistant_message("first", timestamp=1.0),
            _assistant_message("   ", timestamp=2.0),
            UserMessage(
                role="user", content=[TextPart(type="text", text="next")], timestamp=3.0
            ),
            _assistant_message("second", timestamp=4.0),
        ]
    )

    assert _session_transcript_source(session).recent_assistant_texts() == (
        "second",
        "first",
    )


def test_session_transcript_source_merges_live_active_window_records() -> None:
    session = _Session(
        messages=[
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="full question")],
                timestamp=1.0,
            ),
            _assistant_message("full answer", timestamp=2.0),
        ]
    )
    state = ScreenConversationState(
        model_label="model", cwd="/tmp/project", branch=None, session_label=None
    )
    state.replace_transcript_window(
        (
            UserPromptRecord("full question"),
            AssistantMessageRecord("full answer", stable=True),
            ToolExecutionRecord(
                name="bash run-tests",
                state="running",
                elapsed_seconds=0.1,
                output="live output",
            ),
        )
    )
    state.begin_run(started_at=3.0)

    snapshot = _session_transcript_source(session, active_window_state=state).snapshot()

    assert snapshot.complete is False
    assert snapshot.source_label == "Full transcript + live window"
    assert snapshot.records == (
        UserPromptRecord("full question"),
        AssistantMessageRecord("full answer", stable=True),
        ToolExecutionRecord(
            name="bash run-tests",
            state="running",
            elapsed_seconds=0.1,
            output="live output",
        ),
    )


def test_session_transcript_source_keeps_complete_metadata_for_identical_window() -> (
    None
):
    session = _Session(
        messages=[
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="full question")],
                timestamp=1.0,
            ),
            _assistant_message("full answer", timestamp=2.0),
        ]
    )
    state = ScreenConversationState(
        model_label="model", cwd="/tmp/project", branch=None, session_label=None
    )
    state.replace_transcript_window(
        (
            UserPromptRecord("full question"),
            AssistantMessageRecord("full answer", stable=True),
        )
    )

    snapshot = _session_transcript_source(
        session,
        source_label="Session history",
        active_window_state=state,
    ).snapshot()

    assert snapshot.complete is True
    assert snapshot.source_label == "Session history"
    assert snapshot.records == (
        UserPromptRecord("full question"),
        AssistantMessageRecord("full answer", stable=True),
    )


def test_session_transcript_source_deduplicates_decorated_active_window_history() -> (
    None
):
    session = _Session(
        messages=[
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="first question")],
                timestamp=1.0,
            ),
            _assistant_message("first answer", timestamp=2.0),
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="second question")],
                timestamp=3.0,
            ),
            _assistant_message("second answer", timestamp=4.0),
        ]
    )
    state = ScreenConversationState(
        model_label="model", cwd="/tmp/project", branch=None, session_label=None
    )
    state.replace_transcript_window(
        (
            UserPromptRecord("first question"),
            AssistantMessageRecord("first answer", stable=True),
            WorkedDividerRecord(1.0),
            UserPromptRecord("second question"),
            AssistantMessageRecord("second answer", stable=True),
            WorkedDividerRecord(2.0),
        )
    )

    snapshot = _session_transcript_source(session, active_window_state=state).snapshot()

    assert snapshot.records == (
        UserPromptRecord("first question"),
        AssistantMessageRecord("first answer", stable=True),
        WorkedDividerRecord(1.0),
        UserPromptRecord("second question"),
        AssistantMessageRecord("second answer", stable=True),
        WorkedDividerRecord(2.0),
    )


def test_session_transcript_source_merges_live_assistant_draft() -> None:
    session = _Session(
        messages=[
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="full question")],
                timestamp=1.0,
            ),
            _assistant_message("full answer", timestamp=2.0),
        ]
    )
    state = ScreenConversationState(
        model_label="model", cwd="/tmp/project", branch=None, session_label=None
    )
    state.replace_transcript_window(
        (
            UserPromptRecord("full question"),
            AssistantMessageRecord("full answer", stable=True),
        )
    )
    state.begin_run(started_at=3.0)
    state.append_assistant_chunk("streaming draft")

    snapshot = _session_transcript_source(session, active_window_state=state).snapshot()

    assert snapshot.complete is False
    assert snapshot.source_label == "Full transcript + live window"
    assert snapshot.records == (
        UserPromptRecord("full question"),
        AssistantMessageRecord("full answer", stable=True),
        AssistantMessageRecord("streaming draft", stable=False),
    )


def test_transcript_source_boundary_matrix() -> None:
    session = _Session(
        messages=[
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="full question")],
                timestamp=1.0,
            ),
            _assistant_message("full answer", timestamp=2.0),
        ]
    )
    active_state = ScreenConversationState(
        model_label="model", cwd="/tmp/project", branch=None, session_label=None
    )
    active_state.replace_transcript_window((AssistantMessageRecord("active answer"),))
    active_state.begin_run(started_at=3.0)
    active_state.append_assistant_chunk("active draft")

    running_tool_state = ScreenConversationState(
        model_label="model", cwd="/tmp/project", branch=None, session_label=None
    )
    running_tool_state.replace_transcript_window(
        (
            UserPromptRecord("full question"),
            AssistantMessageRecord("full answer", stable=True),
            ToolExecutionRecord(name="bash test", state="running", elapsed_seconds=0.1),
        )
    )

    draft_state = ScreenConversationState(
        model_label="model", cwd="/tmp/project", branch=None, session_label=None
    )
    draft_state.replace_transcript_window(
        (
            UserPromptRecord("full question"),
            AssistantMessageRecord("full answer", stable=True),
        )
    )
    draft_state.begin_run(started_at=4.0)
    draft_state.append_assistant_chunk("streaming draft")

    cases = (
        (
            "active",
            ActiveWindowTranscriptSource(active_state).snapshot(),
            False,
            "Transcript window",
            "active draft",
        ),
        (
            "session",
            _session_transcript_source(session).snapshot(),
            True,
            "Full transcript",
            "full answer",
        ),
        (
            "session+tool",
            _session_transcript_source(
                session, active_window_state=running_tool_state
            ).snapshot(),
            False,
            "Full transcript + live window",
            "bash test",
        ),
        (
            "session+draft",
            _session_transcript_source(
                session, active_window_state=draft_state
            ).snapshot(),
            False,
            "Full transcript + live window",
            "streaming draft",
        ),
    )

    for name, snapshot, complete, label, expected_text in cases:
        assert snapshot.complete is complete, name
        assert snapshot.source_label == label, name
        assert _snapshot_text(snapshot.records).find(expected_text) >= 0, name


def _assistant_message(text: str, *, timestamp: float) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="openai",
        provider="moonshot",
        model="kimi",
        response_id=None,
        usage=Usage(
            input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=timestamp,
    )


def _snapshot_text(records: tuple[object, ...]) -> str:
    parts: list[str] = []
    for record in records:
        text = getattr(record, "text", None)
        if isinstance(text, str):
            parts.append(text)
        name = getattr(record, "name", None)
        if isinstance(name, str):
            parts.append(name)
    return "\n".join(parts)
