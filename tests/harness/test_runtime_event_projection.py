from __future__ import annotations

from datetime import UTC, datetime

from loushang.ai.types import AssistantMessage, Usage
from loushang.harness.events import (
    BranchSummaryCompleted,
    ContextCompactionCompleted,
    ContextCompactionStarted,
    PackageProgressChanged,
    QueueChanged,
    RetryCompleted,
    RuntimeEvent,
    ToolPolicyAuditEvent,
    TranscriptRecordCommitted,
    project_session_runtime_event,
)
from loushang.harness.events.session import (
    QueuedMessageSnapshot,
    QueueSnapshot,
    RetryOutcome,
)
from loushang.harness.session import (
    project_runtime_event_to_json_views,
    shape_runtime_event_view,
)


def _event(kind: str, payload: object) -> RuntimeEvent[object]:
    return RuntimeEvent(
        event_id="event-1",
        kind=kind,
        stream_id="session:s1",
        sequence=1,
        occurred_at=datetime(2026, 7, 16, tzinfo=UTC),
        session_id="s1",
        payload=payload,
    )


def test_runtime_projection_preserves_agent_owned_event() -> None:
    payload = {"type": "agent_start"}

    projected = project_session_runtime_event(_event("agent.agent_start", payload))

    assert projected is payload


def test_runtime_projection_converts_common_session_payloads() -> None:
    queue = QueueChanged(
        QueueSnapshot(
            steering=(QueuedMessageSnapshot("q1", "steering", "adjust"),),
            follow_up=(QueuedMessageSnapshot("q2", "follow_up", "continue"),),
        )
    )
    assert project_session_runtime_event(_event("session.queue_update", queue)) == {
        "type": "queue_update",
        "steering": ["adjust"],
        "follow_up": ["continue"],
    }
    assert project_session_runtime_event(
        _event(
            "session.compaction_start",
            ContextCompactionStarted("threshold", usage={"tokens": 90}),
        )
    ) == {
        "type": "compaction_start",
        "reason": "threshold",
        "usage": {"tokens": 90},
    }
    assert project_session_runtime_event(
        _event(
            "session.compaction_end",
            ContextCompactionCompleted(
                "manual",
                {"summary": "done"},
                False,
                False,
                usage_before={"tokens": 90},
                usage_after={"tokens": 30},
                stage="committed",
                product_id="research",
                session_id="s1",
                duration_ms=12.5,
                tokens_before=90,
                tokens_after=30,
                checkpoint_record_id="checkpoint-1",
            ),
        )
    ) == {
        "type": "compaction_end",
        "reason": "manual",
        "result": {"summary": "done"},
        "aborted": False,
        "will_retry": False,
        "usage_before": {"tokens": 90},
        "usage_after": {"tokens": 30},
        "stage": "committed",
        "product_id": "research",
        "session_id": "s1",
        "duration_ms": 12.5,
        "tokens_before": 90,
        "tokens_after": 30,
        "checkpoint_record_id": "checkpoint-1",
    }
    assert project_session_runtime_event(
        _event(
            "session.auto_retry_end",
            RetryCompleted(RetryOutcome(False, 2, error="unavailable")),
        )
    ) == {
        "type": "auto_retry_end",
        "success": False,
        "attempt": 2,
        "final_error": "unavailable",
    }
    assert project_session_runtime_event(
        _event(
            "session.auto_retry_end",
            RetryCompleted(RetryOutcome(True, 2, error="stale error")),
        )
    ) == {
        "type": "auto_retry_end",
        "success": True,
        "attempt": 2,
    }
    assert project_session_runtime_event(
        _event(
            "session.branch_summary_end",
            BranchSummaryCompleted("target", "old", "new", "summary", False, False),
        )
    ) == {
        "type": "branch_summary_end",
        "target_id": "target",
        "old_leaf_id": "old",
        "new_leaf_id": "new",
        "summary_entry_id": "summary",
        "cancelled": False,
        "aborted": False,
    }
    assert project_session_runtime_event(
        _event(
            "session.package_progress",
            PackageProgressChanged(
                progress_type="complete",
                action="install",
                source="pack",
                message="done",
                target_path="/tmp/pack",
            ),
        )
    ) == {
        "type": "package_progress",
        "progress_type": "complete",
        "action": "install",
        "source": "pack",
        "message": "done",
        "target_path": "/tmp/pack",
    }


def test_runtime_projection_hides_non_product_runtime_facts() -> None:
    committed_at = datetime(2026, 7, 16, tzinfo=UTC)
    event = _event(
        "transcript.record_committed",
        TranscriptRecordCommitted("s1", "r1", 1, committed_at),
    )

    assert project_session_runtime_event(event) is None


def test_runtime_projection_converts_tool_policy_audit_event() -> None:
    event = _event(
        "session.tool_approval_resolved",
        ToolPolicyAuditEvent(
            "tool_approval_resolved",
            {"tool_name": "write", "approval_decision": "allow"},
        ),
    )

    assert project_session_runtime_event(event) == {
        "type": "tool_approval_resolved",
        "tool_name": "write",
        "approval_decision": "allow",
    }


def test_runtime_projection_creates_transport_view_with_source_identity() -> None:
    message = AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[],
        api="test",
        provider="test",
        model="test",
        response_id=None,
        usage=Usage(
            input=0,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost={},
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )
    event = _event(
        "agent.message_update",
        {
            "type": "message_update",
            "message": message,
            "assistant_message_event": {
                "type": "text_delta",
                "content_index": 0,
                "delta": "hello",
                "partial": message,
            },
        },
    )

    views = project_runtime_event_to_json_views(event, event_view="assistant_stream")

    assert len(views) == 1
    view = views[0]
    assert view.event_id == event.event_id
    assert view.stream_id == event.stream_id
    assert view.sequence == event.sequence
    assert view.event_type == "assistant_delta"
    assert view.delivery_hint == "coalesce"
    assert view.payload == {
        "type": "assistant_delta",
        "event_type": "text_delta",
        "content_index": 0,
        "delta": "hello",
    }
    assert shape_runtime_event_view(view) == {
        "type": "assistant_delta",
        "event_type": "text_delta",
        "content_index": 0,
        "delta": "hello",
        "stream": {"kind": "session_event", "view": "assistant_stream"},
    }
