"""Independent in-memory adapters for facts and projection snapshots."""

from __future__ import annotations

from threading import RLock
from uuid import UUID

from loushang.ontology.facts.commit import (
    CommittedFactBatch,
    PreparedFactCommit,
    prepare_fact_commit,
    prepare_guarded_fact_commit,
    require_sequence,
    select_facts_as_of,
)
from loushang.ontology.facts.model import FactBatch
from loushang.ontology.facts.ports import FactCommit, FactSelection, StoredFact
from loushang.ontology.projection import (
    ProjectedObject,
    ProjectionSnapshot,
    ProjectionState,
    ProjectionUnavailableError,
)
from loushang.ontology.schema import CompiledOntologySchema


class MemoryFactStore:
    """Deterministic in-memory reference adapter for the FactStore port."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._facts: list[StoredFact] = []
        self._by_id: dict[UUID, StoredFact] = {}
        self._batches: dict[str, CommittedFactBatch] = {}

    @property
    def fact_watermark(self) -> int:
        with self._lock:
            return len(self._facts)

    def get_fact(self, fact_id: UUID) -> StoredFact:
        with self._lock:
            try:
                return self._by_id[fact_id]
            except KeyError as exc:
                raise KeyError(f"Unknown ontology fact {fact_id}") from exc

    def read_facts(self, *, after_sequence: int = 0) -> tuple[StoredFact, ...]:
        after_sequence = require_sequence("after_sequence", after_sequence)
        with self._lock:
            return tuple(item for item in self._facts if item.sequence > after_sequence)

    def select_facts(
        self,
        *,
        valid_at: float,
        recorded_at: float,
    ) -> FactSelection:
        with self._lock:
            selected = select_facts_as_of(
                self._facts,
                valid_at=valid_at,
                recorded_at=recorded_at,
            )
            return FactSelection(
                facts=selected,
                fact_watermark=len(self._facts),
                valid_at=valid_at,
                recorded_at=recorded_at,
            )

    def commit_fact_batch(self, batch: FactBatch) -> FactCommit:
        with self._lock:
            plan = prepare_fact_commit(
                batch,
                current_facts=self._facts,
                committed_batches=self._batches,
            )
            return self._apply_fact_commit(plan)

    def commit_fact_batch_guarded(
        self,
        batch: FactBatch,
        *,
        expected_watermark: int,
    ) -> FactCommit:
        with self._lock:
            plan = prepare_guarded_fact_commit(
                batch,
                expected_watermark=expected_watermark,
                current_facts=self._facts,
                committed_batches=self._batches,
            )
            return self._apply_fact_commit(plan)

    def _apply_fact_commit(self, plan: PreparedFactCommit) -> FactCommit:
        if plan.commit.replayed:
            return plan.commit
        self._facts.extend(plan.entries)
        self._by_id.update((entry.fact.fact_id, entry) for entry in plan.entries)
        self._batches[plan.batch.batch_id] = CommittedFactBatch(
            digest=plan.digest,
            commit=plan.commit,
        )
        return plan.commit


class MemoryProjectionStore:
    """Atomic in-memory holder for a complete immutable snapshot."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._snapshot: ProjectionSnapshot | None = None

    @property
    def snapshot(self) -> ProjectionSnapshot | None:
        with self._lock:
            return self._snapshot

    @property
    def schema(self) -> CompiledOntologySchema:
        return self._require_snapshot().schema

    @property
    def projection_state(self) -> ProjectionState:
        return self._require_snapshot().state

    def read_snapshot(self) -> ProjectionSnapshot:
        return self._require_snapshot()

    def replace(self, snapshot: ProjectionSnapshot) -> ProjectionState:
        if not isinstance(snapshot, ProjectionSnapshot):
            raise TypeError("replace requires a ProjectionSnapshot")
        with self._lock:
            expected_version = (
                1
                if self._snapshot is None
                else self._snapshot.state.projection_version + 1
            )
            if self._snapshot is not None and self._snapshot.schema != snapshot.schema:
                raise ValueError("projection schema cannot change within one store")
            if snapshot.state.projection_version != expected_version:
                raise ValueError(
                    f"projection_version must be {expected_version} for this replacement"
                )
            self._snapshot = snapshot
            return snapshot.state

    def get(self, object_id: UUID) -> ProjectedObject | None:
        return self._require_snapshot().get(object_id)

    def get_by_type(self, object_type: str) -> tuple[ProjectedObject, ...]:
        return self._require_snapshot().get_by_type(object_type)

    def find_neighbors(
        self,
        object_id: UUID,
        link_type: str,
        direction: str = "outgoing",
    ) -> tuple[ProjectedObject, ...]:
        return self._require_snapshot().find_neighbors(
            object_id,
            link_type,
            direction,
        )

    def all_objects(self) -> tuple[ProjectedObject, ...]:
        return self._require_snapshot().all_objects()

    def _require_snapshot(self) -> ProjectionSnapshot:
        with self._lock:
            if self._snapshot is None:
                raise ProjectionUnavailableError("no ontology projection is installed")
            return self._snapshot


__all__ = ["MemoryFactStore", "MemoryProjectionStore"]
