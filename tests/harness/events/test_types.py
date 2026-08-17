from __future__ import annotations

from datetime import datetime, timezone

import pytest

from loushang.harness.events import RuntimeEvent, TranscriptRecordCommitted


def test_runtime_event_preserves_typed_payload_and_source_references() -> None:
    occurred_at = datetime(2026, 7, 16, 12, 30, tzinfo=timezone.utc)
    payload = TranscriptRecordCommitted(
        conversation_id="conversation-1",
        record_id="record-4",
        revision=4,
        committed_at=occurred_at,
    )

    event = RuntimeEvent(
        event_id="event-1",
        kind="transcript_record_committed",
        stream_id="session:session-1",
        sequence=3,
        occurred_at=occurred_at,
        session_id="session-1",
        run_id="run-2",
        source_event_ref="agent-event-8",
        source_record_id="record-4",
        payload=payload,
    )

    assert event.payload is payload
    assert event.occurred_at is occurred_at
    assert event.source_record_id == "record-4"


@pytest.mark.parametrize("sequence", [True, 1.5, "1", None])
def test_runtime_event_rejects_non_integer_sequence(sequence: object) -> None:
    with pytest.raises(TypeError, match="sequence must be an integer"):
        RuntimeEvent(
            event_id="event-1",
            kind="test.event",
            stream_id="stream-1",
            sequence=sequence,  # type: ignore[arg-type]
            occurred_at=datetime.now(timezone.utc),
            payload=None,
        )


def test_runtime_event_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        RuntimeEvent(
            event_id="event-1",
            kind="test.event",
            stream_id="stream-1",
            sequence=1,
            occurred_at=datetime(2026, 7, 16),
            payload=None,
        )


@pytest.mark.parametrize("revision", [True, 1.5, "1", None])
def test_transcript_record_committed_rejects_non_integer_revision(
    revision: object,
) -> None:
    with pytest.raises(TypeError, match="revision must be an integer"):
        TranscriptRecordCommitted(
            conversation_id="conversation-1",
            record_id="record-1",
            revision=revision,  # type: ignore[arg-type]
            committed_at=datetime.now(timezone.utc),
        )


@pytest.mark.parametrize("revision", [-1, 0])
def test_transcript_record_committed_requires_positive_revision(revision: int) -> None:
    with pytest.raises(ValueError, match="revision must be positive"):
        TranscriptRecordCommitted(
            conversation_id="conversation-1",
            record_id="record-1",
            revision=revision,
            committed_at=datetime.now(timezone.utc),
        )


def test_transcript_record_committed_requires_conversation_identity() -> None:
    with pytest.raises(ValueError, match="conversation id"):
        TranscriptRecordCommitted(
            conversation_id=" ",
            record_id="record-1",
            revision=1,
            committed_at=datetime.now(timezone.utc),
        )


def test_transcript_record_committed_requires_aware_commit_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        TranscriptRecordCommitted(
            conversation_id="conversation-1",
            record_id="record-1",
            revision=1,
            committed_at=datetime(2026, 7, 16),
        )
