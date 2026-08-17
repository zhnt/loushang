from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from loushang.agent.json_codec import serialize_tool_result
from loushang.agent.types import AgentToolResult
from loushang.ai.json_codec import serialize_assistant_message_event, serialize_message
from loushang.ai.types import AssistantMessageEvent, Message
from loushang.foundation.json import (
    JsonValueError,
    require_json_mapping,
    require_json_value,
)
from loushang.harness.events import RuntimeEvent, project_session_runtime_event
from loushang.harness.transcript import create_agent_transcript_message_codec
from loushang.harnesswork.event_log import EventLogBackend
from loushang.harnesswork.integrations.session import (
    SessionPromptPort,
    SessionWorkProfile,
    SessionWorkRuntime,
)
from loushang.harnesswork.types import DeliveryHint, WorkEventFact

AgentMessageSerializer = Callable[[object], Mapping[str, object]]


@dataclass(frozen=True)
class AgentWorkFactProjectionContext:
    source_event_ref: str | None = None
    message_serializer: AgentMessageSerializer | None = None


_TRANSCRIPT_MESSAGE_CODEC = create_agent_transcript_message_codec()


def project_agent_runtime_event_to_work_facts(
    event: object,
) -> Sequence[WorkEventFact]:
    """Project a shared Agent session runtime event into canonical Work facts."""

    if not isinstance(event, RuntimeEvent):
        return ()
    projected = project_session_runtime_event(event)
    if projected is None:
        return ()
    return project_agent_event_to_work_facts(
        projected,
        context=AgentWorkFactProjectionContext(
            source_event_ref=event.event_id,
            message_serializer=_TRANSCRIPT_MESSAGE_CODEC.serialize,
        ),
    )


def create_agent_session_work_runtime(
    *,
    session: SessionPromptPort,
    event_log: EventLogBackend,
    profile: SessionWorkProfile,
    session_id: Callable[[], str] = lambda: "",
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    cancellation_timeout: float | None = 30.0,
) -> SessionWorkRuntime:
    """Bind a Product profile to the existing session Work runtime."""

    return SessionWorkRuntime(
        session=session,
        event_log=event_log,
        profile=profile,
        project_event_facts=project_agent_runtime_event_to_work_facts,
        session_id=session_id,
        clock=clock,
        cancellation_timeout=cancellation_timeout,
    )


def project_agent_event_to_work_facts(
    event: Mapping[str, object],
    *,
    context: AgentWorkFactProjectionContext,
) -> list[WorkEventFact]:
    source_type = event.get("type")
    if not isinstance(source_type, str):
        raise ValueError("Agent event must include a string type")

    if source_type == "agent_start":
        return [
            _event(
                context,
                kind="AgentInvocationStarted",
                delivery_hint="coalesce",
                payload={"source_type": source_type},
            )
        ]
    if source_type == "agent_end":
        messages = event.get("messages", [])
        return [
            _event(
                context,
                kind="AgentInvocationCompleted",
                delivery_hint="coalesce",
                payload={
                    "source_type": source_type,
                    "messages": _serialize_messages(
                        messages,
                        name="agent_event.messages",
                        serializer=context.message_serializer,
                    ),
                },
            ),
        ]
    if source_type == "turn_start":
        return [
            _event(
                context,
                kind="TaskStarted",
                delivery_hint="immediate",
                payload={"source_type": source_type},
            )
        ]
    if source_type == "turn_end":
        payload = _payload(event)
        if "message" in event:
            payload["message"] = _serialize_message(
                event["message"],
                name="agent_event.message",
                serializer=context.message_serializer,
            )
        if "tool_results" in event:
            payload["tool_results"] = _serialize_messages(
                event["tool_results"],
                name="agent_event.tool_results",
                serializer=context.message_serializer,
            )
        return [
            _event(
                context,
                kind="TaskCompleted",
                delivery_hint="immediate",
                payload=payload,
            )
        ]
    if source_type in {"message_start", "message_update", "message_end"}:
        payload = _payload(event)
        if "message" in event:
            payload["message"] = _serialize_message(
                event["message"],
                name="agent_event.message",
                serializer=context.message_serializer,
            )
        if "assistant_message_event" in event:
            payload["assistant_message_event"] = _serialize_assistant_event(
                event["assistant_message_event"]
            )
        return [
            _event(
                context, kind="ContentDelta", delivery_hint="coalesce", payload=payload
            )
        ]
    if source_type == "tool_execution_start":
        payload = _payload(event, "tool_call_id", "tool_name")
        if "args" in event:
            payload["args"] = require_json_value(
                event["args"],
                name="agent_event.args",
            )
        return [
            _event(
                context,
                kind="ToolCallStarted",
                delivery_hint="coalesce",
                payload=payload,
            )
        ]
    if source_type == "tool_execution_update":
        payload = _payload(event, "tool_call_id", "tool_name")
        if "args" in event:
            payload["args"] = require_json_value(
                event["args"],
                name="agent_event.args",
            )
        if "partial_result" in event:
            payload["partial_result"] = _serialize_agent_tool_result(
                event["partial_result"],
                name="agent_event.partial_result",
            )
        return [
            _event(
                context,
                kind="ToolCallProgress",
                delivery_hint="coalesce",
                payload=payload,
            )
        ]
    if source_type == "tool_execution_end":
        payload = _payload(
            event,
            "tool_call_id",
            "tool_name",
            "is_error",
            "duration_ms",
        )
        if "result" in event:
            payload["result"] = _serialize_agent_tool_result(
                event["result"],
                name="agent_event.result",
            )
        delivery_hint: DeliveryHint = (
            "immediate" if event.get("is_error") is True else "coalesce"
        )
        return [
            _event(
                context,
                kind="ToolCallCompleted",
                delivery_hint=delivery_hint,
                payload=payload,
            )
        ]
    audit_identity_fields = (
        "tool_call_id",
        "tool_name",
        "action_fingerprint",
        "capability",
        "action_summary",
        "command_summary",
    )
    if source_type == "tool_action_frozen":
        return [
            _event(
                context,
                kind="ToolActionFrozen",
                delivery_hint="immediate",
                payload=_payload(event, *audit_identity_fields),
            )
        ]
    if source_type == "tool_policy_evaluated":
        payload = _payload(
            event,
            *audit_identity_fields,
            "policy_disposition",
            "policy_code",
            "approval_required",
        )
        return [
            _event(
                context,
                kind="ToolPolicyEvaluated",
                delivery_hint="immediate",
                payload=payload,
            )
        ]
    if source_type == "tool_approval_requested":
        payload = _payload(
            event,
            *audit_identity_fields,
            "action_id",
            "policy_code",
        )
        return [
            _event(
                context,
                kind="ToolApprovalRequested",
                delivery_hint="immediate",
                payload=payload,
            )
        ]
    if source_type == "tool_approval_resolved":
        payload = _payload(
            event,
            *audit_identity_fields,
            "action_id",
            "approval_decision",
            "policy_code",
        )
        return [
            _event(
                context,
                kind="ToolApprovalResolved",
                delivery_hint="immediate",
                payload=payload,
            )
        ]
    if source_type in {
        "tool_execution_started",
        "tool_execution_completed",
        "tool_execution_failed",
    }:
        kind = {
            "tool_execution_started": "ToolExecutionStarted",
            "tool_execution_completed": "ToolExecutionCompleted",
            "tool_execution_failed": "ToolExecutionFailed",
        }[source_type]
        payload = _payload(
            event,
            *audit_identity_fields,
            "policy_code",
            "approval_action_id",
            "execution_profile",
            "outcome",
            "phase",
        )
        return [
            _event(
                context,
                kind=kind,
                delivery_hint="immediate",
                payload=payload,
            )
        ]
    if source_type == "queue_update":
        payload = _payload(event, "steering", "follow_up")
        return [
            _event(
                context, kind="QueueUpdated", delivery_hint="coalesce", payload=payload
            )
        ]
    if source_type in {"auto_retry_start", "auto_retry_end"}:
        return [
            _event(
                context,
                kind="RetryDiagnostic",
                delivery_hint="immediate"
                if event.get("success") is False
                else "coalesce",
                payload=dict(event),
            ),
        ]
    if source_type in {"compaction_start", "compaction_end", "package_progress"}:
        return [
            _event(
                context,
                kind="MaintenanceProgress",
                delivery_hint="coalesce",
                payload=dict(event),
            )
        ]

    return [
        _event(context, kind="WorkEvent", delivery_hint="coalesce", payload=dict(event))
    ]


def _event(
    context: AgentWorkFactProjectionContext,
    *,
    kind: str,
    delivery_hint: DeliveryHint,
    payload: Mapping[str, object],
) -> WorkEventFact:
    return WorkEventFact(
        kind=kind,
        delivery_hint=delivery_hint,
        payload=cast(
            Mapping[str, object],
            require_json_mapping(
                dict(payload),
                name="work_event.payload",
            ),
        ),
        source_event_ref=context.source_event_ref,
    )


def _payload(event: Mapping[str, object], *keys: str) -> dict[str, object]:
    payload: dict[str, object] = {"source_type": event["type"]}
    for key in keys:
        if key in event:
            payload[key] = event[key]
    return payload


def _serialize_messages(
    value: object,
    *,
    name: str,
    serializer: AgentMessageSerializer | None,
) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list")
    return [
        _serialize_message(
            message,
            name=f"{name}[{index}]",
            serializer=serializer,
        )
        for index, message in enumerate(value)
    ]


def _serialize_message(
    value: object,
    *,
    name: str,
    serializer: AgentMessageSerializer | None,
) -> dict[str, object]:
    if isinstance(value, Mapping):
        return cast(
            dict[str, object],
            require_json_mapping(dict(value), name=name),
        )
    encoded = (
        serializer(value)
        if serializer is not None
        else serialize_message(cast(Message, value))
    )
    return cast(
        dict[str, object],
        require_json_mapping(encoded, name=name),
    )


def _serialize_assistant_event(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("agent_event.assistant_message_event must be a mapping")
    try:
        return cast(
            dict[str, object],
            require_json_mapping(
                dict(value),
                name="agent_event.assistant_message_event",
            ),
        )
    except JsonValueError:
        encoded = serialize_assistant_message_event(cast(AssistantMessageEvent, value))
        return cast(
            dict[str, object],
            require_json_mapping(
                encoded,
                name="agent_event.assistant_message_event",
            ),
        )


def _serialize_agent_tool_result(value: object, *, name: str) -> dict[str, object]:
    if isinstance(value, AgentToolResult):
        encoded = serialize_tool_result(value, target="event")
    elif isinstance(value, Mapping):
        encoded = dict(value)
    else:
        raise TypeError(f"{name} must be AgentToolResult or a projected JSON object")
    return cast(
        dict[str, object],
        require_json_mapping(encoded, name=name),
    )


__all__ = [
    "AgentWorkFactProjectionContext",
    "create_agent_session_work_runtime",
    "project_agent_event_to_work_facts",
    "project_agent_runtime_event_to_work_facts",
]
