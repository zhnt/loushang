"""Read model for product-neutral multi-agent facts."""

from __future__ import annotations

from dataclasses import dataclass, replace

from loushang.harness.multiagent import (
    AgentFact,
    AgentProgress,
    AgentRecord,
    AgentRef,
)


@dataclass(frozen=True, slots=True)
class AgentTreeRow:
    """Presentation-ready snapshot of one technical agent incarnation."""

    ref: AgentRef
    parent_ref: AgentRef | None
    agent_type: str
    status: str
    round_id: int
    progress: AgentProgress
    workspace_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()
    change_set_ref: str | None = None

    @classmethod
    def from_record(cls, record: AgentRecord) -> AgentTreeRow:
        return cls(
            ref=record.ref,
            parent_ref=record.parent_ref,
            agent_type=record.agent_type,
            status=record.status,
            round_id=record.round_id,
            progress=record.progress,
            workspace_ref=record.workspace_ref,
            artifact_refs=record.artifact_refs,
            change_set_ref=record.change_set_ref,
        )

    def apply(self, fact: AgentFact) -> AgentTreeRow:
        return replace(
            self,
            parent_ref=fact.parent_ref,
            agent_type=fact.agent_type,
            status=fact.status,
            round_id=fact.round_id,
            progress=fact.progress or self.progress,
            workspace_ref=fact.workspace_ref,
            artifact_refs=fact.artifact_refs,
            change_set_ref=fact.change_set_ref,
        )


class AgentTreeProjection:
    """Incrementally project ordered facts without mutating control state."""

    def __init__(self, records: tuple[AgentRecord, ...]) -> None:
        self._rows = {
            record.ref: AgentTreeRow.from_record(record) for record in records
        }

    def apply(self, fact: AgentFact) -> None:
        row = self._rows.get(fact.ref)
        if row is None:
            row = AgentTreeRow(
                ref=fact.ref,
                parent_ref=fact.parent_ref,
                agent_type=fact.agent_type,
                status=fact.status,
                round_id=fact.round_id,
                progress=fact.progress or AgentProgress(),
                workspace_ref=fact.workspace_ref,
                artifact_refs=fact.artifact_refs,
                change_set_ref=fact.change_set_ref,
            )
        else:
            row = row.apply(fact)
        self._rows[fact.ref] = row

    def rows(self) -> tuple[AgentTreeRow, ...]:
        return tuple(
            sorted(
                self._rows.values(),
                key=lambda row: (row.ref.path.parts, row.ref.incarnation),
            )
        )


__all__ = ["AgentTreeProjection", "AgentTreeRow"]
