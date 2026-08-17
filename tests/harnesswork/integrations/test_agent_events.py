from __future__ import annotations

from datetime import UTC, datetime


def _context(sequence: int = 1):
    from loushang.harnesswork.integrations.agent_events import (
        WorkEventProjectionContext,
    )

    return WorkEventProjectionContext(
        run_id="run-1",
        session_id="session-1",
        domain="coding",
        operation_id="op-1",
        sequence=sequence,
        created_at=datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
        event_id_prefix="event",
        source_event_ref="agent-event-1",
    )


def test_project_agent_start_and_end_events() -> None:
    from loushang.harnesswork.integrations.agent_events import (
        project_agent_event_to_work_events,
    )

    started = project_agent_event_to_work_events(
        {"type": "agent_start"}, context=_context(1)
    )
    completed = project_agent_event_to_work_events(
        {"type": "agent_end", "messages": []}, context=_context(2)
    )

    assert [event.kind for event in started] == ["AgentInvocationStarted"]
    assert started[0].event_id == "event-1"
    assert started[0].delivery_hint == "coalesce"
    assert started[0].payload == {"source_type": "agent_start"}
    assert started[0].source_event_ref == "agent-event-1"

    assert [event.kind for event in completed] == ["AgentInvocationCompleted"]
    assert completed[0].event_id == "event-2"
    assert completed[0].delivery_hint == "coalesce"
    assert completed[0].payload == {"source_type": "agent_end", "messages": []}


def test_project_message_update_to_coalesced_content_delta() -> None:
    from loushang.harnesswork.integrations.agent_events import (
        project_agent_event_to_work_events,
    )

    events = project_agent_event_to_work_events(
        {
            "type": "message_update",
            "message": {"role": "assistant"},
            "assistant_message_event": {"type": "text_delta", "text": "hello"},
        },
        context=_context(3),
    )

    assert len(events) == 1
    event = events[0]
    assert event.kind == "ContentDelta"
    assert event.delivery_hint == "coalesce"
    assert event.sequence == 3
    assert event.payload == {
        "source_type": "message_update",
        "message": {"role": "assistant"},
        "assistant_message_event": {"type": "text_delta", "text": "hello"},
    }


def test_project_messages_with_existing_ai_codecs() -> None:
    from loushang.ai.types import AssistantMessage, TextPart, Usage
    from loushang.harnesswork.integrations.agent_events import (
        project_agent_event_to_work_events,
    )

    assistant = AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text="hello")],
        api="responses",
        provider="example",
        model="example-1",
        response_id="response-1",
        usage=Usage(
            input=1,
            output=2,
            cache_read=0,
            cache_write=0,
            total_tokens=3,
            cost=None,
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=1.0,
    )

    message_end = project_agent_event_to_work_events(
        {"type": "message_end", "message": assistant},
        context=_context(3),
    )[0]
    message_update = project_agent_event_to_work_events(
        {
            "type": "message_update",
            "message": assistant,
            "assistant_message_event": {
                "type": "text_delta",
                "content_index": 0,
                "delta": "hello",
                "partial": assistant,
            },
        },
        context=_context(4),
    )[0]

    assert message_end.payload["message"] == {
        "role": "assistant",
        "content": [
            {
                "type": "text",
                "text": "hello",
                "textSignature": None,
            }
        ],
        "api": "responses",
        "provider": "example",
        "endpoint": "test-endpoint",
        "model": "example-1",
        "responseId": "response-1",
        "usage": {
            "input": 1,
            "output": 2,
            "cacheRead": 0,
            "cacheWrite": 0,
            "totalTokens": 3,
            "cost": None,
        },
        "stopReason": "stop",
        "errorMessage": None,
        "timestamp": 1.0,
    }
    assert message_update.payload["assistant_message_event"] == {
        "type": "text_delta",
        "partial": message_end.payload["message"],
        "contentIndex": 0,
        "delta": "hello",
    }


def test_project_tool_events_to_tool_call_work_events() -> None:
    from loushang.harnesswork.integrations.agent_events import (
        project_agent_event_to_work_events,
    )

    started = project_agent_event_to_work_events(
        {
            "type": "tool_execution_start",
            "tool_call_id": "tool-1",
            "tool_name": "bash",
            "args": {"command": "pytest"},
        },
        context=_context(4),
    )
    completed = project_agent_event_to_work_events(
        {
            "type": "tool_execution_end",
            "tool_call_id": "tool-1",
            "tool_name": "bash",
            "result": {"output": "failed"},
            "is_error": True,
            "duration_ms": 50,
        },
        context=_context(5),
    )

    assert started[0].kind == "ToolCallStarted"
    assert started[0].delivery_hint == "coalesce"
    assert started[0].payload["tool_call_id"] == "tool-1"
    assert started[0].payload["tool_name"] == "bash"

    assert completed[0].kind == "ToolCallCompleted"
    assert completed[0].delivery_hint == "immediate"
    assert completed[0].payload["is_error"] is True
    assert completed[0].payload["duration_ms"] == 50


def test_project_tool_update_and_end_use_agent_event_projection() -> None:
    from dataclasses import dataclass
    from pathlib import Path

    from loushang.agent import AgentToolResult, FunctionalToolOutputProjector
    from loushang.ai.types import TextPart
    from loushang.harnesswork.integrations.agent_events import (
        project_agent_event_to_work_events,
    )

    @dataclass(frozen=True)
    class RichDetails:
        path: Path

    def result(text: str) -> AgentToolResult[RichDetails]:
        return AgentToolResult(
            content=[TextPart(type="text", text=text)],
            details=RichDetails(path=Path("notes.txt")),
            projector=FunctionalToolOutputProjector(
                transcript=lambda details: {
                    "path": str(details.path),
                    "surface": "transcript",
                },
                event=lambda details: {
                    "path": str(details.path),
                    "surface": "event",
                },
            ),
        )

    progress = project_agent_event_to_work_events(
        {
            "type": "tool_execution_update",
            "tool_call_id": "tool-1",
            "tool_name": "read",
            "args": {"path": "notes.txt"},
            "partial_result": result("partial"),
        },
        context=_context(5),
    )[0]
    completed = project_agent_event_to_work_events(
        {
            "type": "tool_execution_end",
            "tool_call_id": "tool-1",
            "tool_name": "read",
            "result": result("complete"),
            "is_error": False,
        },
        context=_context(6),
    )[0]

    assert progress.payload["partial_result"] == {
        "content": [
            {
                "type": "text",
                "text": "partial",
                "textSignature": None,
            }
        ],
        "details": {"path": "notes.txt", "surface": "event"},
        "terminate": False,
    }
    assert completed.payload["result"] == {
        "content": [
            {
                "type": "text",
                "text": "complete",
                "textSignature": None,
            }
        ],
        "details": {"path": "notes.txt", "surface": "event"},
        "terminate": False,
    }


def test_work_projection_rejects_malformed_tool_result_content() -> None:
    import pytest

    from loushang.agent import AgentToolResult, ToolOutputProjectionError
    from loushang.ai.types import TextPart
    from loushang.harnesswork.integrations.agent_events import (
        project_agent_event_to_work_events,
    )

    result = AgentToolResult(
        content=[TextPart(type="image", text="oops")],  # type: ignore[arg-type]
        details={},
    )

    with pytest.raises(ToolOutputProjectionError) as exc_info:
        project_agent_event_to_work_events(
            {
                "type": "tool_execution_update",
                "tool_call_id": "tool-1",
                "tool_name": "read",
                "partial_result": result,
            },
            context=_context(5),
        )
    assert exc_info.value.target == "event"
    assert exc_info.value.path == "tool_output.content[0].type"


def test_project_gateway_audit_sequence_to_safe_work_events() -> None:
    from loushang.harnesswork.integrations.agent_events import (
        project_agent_event_to_work_events,
    )

    common = {
        "tool_call_id": "tool-1",
        "tool_name": "write",
        "action_fingerprint": "f" * 64,
        "capability": "filesystem.write",
        "action_summary": {
            "argument_count": 2,
            "resource": {"kind": "file", "scope": "workspace"},
        },
    }
    frozen = project_agent_event_to_work_events(
        {
            "type": "tool_action_frozen",
            **common,
        },
        context=_context(5),
    )
    evaluated = project_agent_event_to_work_events(
        {
            "type": "tool_policy_evaluated",
            **common,
            "policy_disposition": "ask",
            "policy_code": "tool_requires_approval",
            "approval_required": True,
        },
        context=_context(6),
    )
    requested = project_agent_event_to_work_events(
        {
            "type": "tool_approval_requested",
            **common,
            "action_id": "approval-1",
            "policy_code": "tool_requires_approval",
        },
        context=_context(7),
    )
    resolved = project_agent_event_to_work_events(
        {
            "type": "tool_approval_resolved",
            **common,
            "action_id": "approval-1",
            "approval_decision": "allow",
            "policy_code": "tool_requires_approval",
        },
        context=_context(8),
    )
    started = project_agent_event_to_work_events(
        {
            "type": "tool_execution_started",
            **common,
            "execution_profile": {"configured": False},
            "outcome": "running",
            "phase": "execution",
        },
        context=_context(9),
    )
    completed = project_agent_event_to_work_events(
        {
            "type": "tool_execution_completed",
            **common,
            "execution_profile": {"configured": False},
            "outcome": "completed",
            "phase": "execution",
        },
        context=_context(10),
    )
    failed = project_agent_event_to_work_events(
        {
            "type": "tool_execution_failed",
            **common,
            "execution_profile": {"configured": False},
            "outcome": "error",
            "phase": "execution",
        },
        context=_context(11),
    )
    projected = [
        *frozen,
        *evaluated,
        *requested,
        *resolved,
        *started,
        *completed,
        *failed,
    ]

    assert [event.kind for event in projected] == [
        "ToolActionFrozen",
        "ToolPolicyEvaluated",
        "ToolApprovalRequested",
        "ToolApprovalResolved",
        "ToolExecutionStarted",
        "ToolExecutionCompleted",
        "ToolExecutionFailed",
    ]
    assert all(event.delivery_hint == "immediate" for event in projected)
    assert evaluated[0].payload == {
        "source_type": "tool_policy_evaluated",
        **common,
        "policy_disposition": "ask",
        "policy_code": "tool_requires_approval",
        "approval_required": True,
    }
    assert requested[0].payload["action_id"] == "approval-1"
    assert resolved[0].payload["approval_decision"] == "allow"
    assert completed[0].payload["outcome"] == "completed"


def test_project_queue_update_to_coalesced_queue_metadata_event() -> None:
    from loushang.harnesswork.integrations.agent_events import (
        project_agent_event_to_work_events,
    )

    events = project_agent_event_to_work_events(
        {"type": "queue_update", "steering": ["wait"], "follow_up": ["then test"]},
        context=_context(6),
    )

    assert len(events) == 1
    assert events[0].kind == "QueueUpdated"
    assert events[0].delivery_hint == "coalesce"
    assert events[0].payload == {
        "source_type": "queue_update",
        "steering": ["wait"],
        "follow_up": ["then test"],
    }


def test_work_event_bridge_rejects_non_json_payloads() -> None:
    from pathlib import Path

    import pytest

    from loushang.foundation.json import JsonValueError
    from loushang.harnesswork.integrations.agent_events import (
        project_agent_event_to_work_events,
    )

    cases = (
        (
            {
                "type": "queue_update",
                "steering": [Path("wait")],
                "follow_up": [],
            },
            "work_event.payload.steering[0]",
        ),
        (
            {
                "type": "tool_policy_evaluated",
                "tool_call_id": "call-1",
                "tool_name": "read",
                "action_summary": {"unsafe": Path("notes.txt")},
            },
            "work_event.payload.action_summary.unsafe",
        ),
        (
            {"type": "product_event", "unsafe": Path("notes.txt")},
            "work_event.payload.unsafe",
        ),
    )

    for source_event, expected_path in cases:
        with pytest.raises(JsonValueError) as exc_info:
            project_agent_event_to_work_events(source_event, context=_context())
        assert exc_info.value.path == expected_path


def test_work_event_bridge_snapshots_source_payloads() -> None:
    from loushang.harnesswork.integrations.agent_events import (
        project_agent_event_to_work_events,
    )

    steering = ["first"]
    source_event = {
        "type": "queue_update",
        "steering": steering,
        "follow_up": [],
    }

    projected = project_agent_event_to_work_events(source_event, context=_context())[0]
    steering.append("later")

    assert projected.payload["steering"] == ["first"]


def test_work_event_bridge_accepts_product_message_serializer() -> None:
    from dataclasses import dataclass, replace

    from loushang.agent import CustomAgentMessage
    from loushang.harnesswork.integrations.agent_events import (
        project_agent_event_to_work_events,
    )

    @dataclass(frozen=True)
    class ProductMessage(CustomAgentMessage):
        role: str
        text: str

    message = ProductMessage(role="product", text="hello")
    context = replace(
        _context(),
        message_serializer=lambda value: {
            "role": value.role,
            "text": value.text,
        },
    )

    projected = project_agent_event_to_work_events(
        {"type": "message_end", "message": message},
        context=context,
    )[0]

    assert projected.payload["message"] == {
        "role": "product",
        "text": "hello",
    }
