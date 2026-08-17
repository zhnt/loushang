"""Compatibility surface that adds WorkEvent identity to Work-owned facts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from loushang.harnesswork.integrations.agent_session import (
    AgentWorkFactProjectionContext,
    project_agent_event_to_work_facts,
)
from loushang.harnesswork.types import WorkEvent

AgentMessageSerializer = Callable[[object], Mapping[str, object]]


@dataclass(frozen=True)
class WorkEventProjectionContext:
    run_id: str
    session_id: str
    domain: str
    operation_id: str
    sequence: int
    created_at: datetime
    event_id_prefix: str = "work-event"
    source_event_ref: str | None = None
    message_serializer: AgentMessageSerializer | None = None


def project_agent_event_to_work_events(
    event: Mapping[str, object],
    *,
    context: WorkEventProjectionContext,
) -> list[WorkEvent]:
    facts = project_agent_event_to_work_facts(
        event,
        context=AgentWorkFactProjectionContext(
            source_event_ref=context.source_event_ref,
            message_serializer=context.message_serializer,
        ),
    )
    return [
        WorkEvent(
            event_id=f"{context.event_id_prefix}-{context.sequence + index}",
            kind=fact.kind,
            run_id=context.run_id,
            session_id=context.session_id,
            domain=context.domain,
            operation_id=context.operation_id,
            sequence=context.sequence + index,
            created_at=context.created_at,
            delivery_hint=fact.delivery_hint,
            payload=fact.payload,
            source_event_ref=fact.source_event_ref,
        )
        for index, fact in enumerate(facts)
    ]


__all__ = [
    "WorkEventProjectionContext",
    "project_agent_event_to_work_events",
]
