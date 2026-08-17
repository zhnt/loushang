"""Incarnation-safe in-memory tree registry for multi-agent control."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from threading import RLock

from .types import (
    AgentPath,
    AgentProgress,
    AgentRecord,
    AgentRef,
    AgentStatus,
    MultiAgentError,
    require_agent_name,
)

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AgentReservation:
    """Single-use proof that one child path has been reserved."""

    def __init__(
        self,
        registry: AgentRegistry,
        *,
        token: int,
        ref: AgentRef,
        parent_ref: AgentRef,
        agent_type: str,
    ) -> None:
        self._registry = registry
        self._token = token
        self.ref = ref
        self.parent_ref = parent_ref
        self.agent_type = agent_type
        self._active = True

    @property
    def active(self) -> bool:
        return self._active

    def commit(self) -> AgentRecord:
        if not self._active:
            raise MultiAgentError(
                "reservation_stale",
                f"agent reservation is no longer active: {self.ref.path}",
            )
        try:
            return self._registry._commit(self)
        finally:
            self._active = False

    def rollback(self) -> None:
        if not self._active:
            return
        self._registry._rollback(self)
        self._active = False

    def __enter__(self) -> AgentReservation:
        return self

    def __exit__(self, *_args: object) -> None:
        self.rollback()


class AgentRegistry:
    """Pure data owner for paths, incarnations, reservations, and topology."""

    def __init__(self, *, clock: Clock = _utc_now) -> None:
        self._clock = clock
        self._lock = RLock()
        self._records: dict[AgentPath, AgentRecord] = {}
        self._incarnations: dict[AgentPath, int] = {}
        self._reservations: dict[AgentPath, int] = {}
        self._next_token = 1

        now = self._clock()
        root_ref = AgentRef(AgentPath.root(), 1)
        self._incarnations[root_ref.path] = root_ref.incarnation
        self._records[root_ref.path] = AgentRecord(
            ref=root_ref,
            parent_ref=None,
            agent_type="root",
            status="idle",
            round_id=0,
            created_at=now,
            updated_at=now,
        )

    @property
    def root_ref(self) -> AgentRef:
        with self._lock:
            return self._records[AgentPath.root()].ref

    @property
    def reserved_count(self) -> int:
        with self._lock:
            return len(self._reservations)

    @property
    def open_count(self) -> int:
        with self._lock:
            return sum(record.is_open for record in self._records.values())

    def reserve(
        self,
        *,
        parent_ref: AgentRef,
        name: str,
        agent_type: str,
    ) -> AgentReservation:
        name = require_agent_name(name)
        require_agent_name(agent_type, field_name="agent type")
        with self._lock:
            parent = self._require_current(parent_ref)
            if not parent.is_open:
                raise MultiAgentError(
                    "parent_not_open",
                    f"parent agent is closed: {parent_ref.path}",
                )
            path = parent_ref.path.child(name)
            current = self._records.get(path)
            if path in self._reservations or (current is not None and current.is_open):
                raise MultiAgentError(
                    "agent_name_conflict",
                    f"an open agent already uses {path}",
                    details={"path": str(path)},
                )

            incarnation = self._incarnations.get(path, 0) + 1
            self._incarnations[path] = incarnation
            token = self._next_token
            self._next_token += 1
            self._reservations[path] = token
            return AgentReservation(
                self,
                token=token,
                ref=AgentRef(path, incarnation),
                parent_ref=parent_ref,
                agent_type=agent_type,
            )

    def current(
        self,
        path: AgentPath,
        *,
        include_closed: bool = False,
    ) -> AgentRecord | None:
        with self._lock:
            record = self._records.get(path)
            if record is None or (not include_closed and not record.is_open):
                return None
            return record

    def get(
        self,
        ref: AgentRef,
        *,
        include_closed: bool = False,
    ) -> AgentRecord | None:
        with self._lock:
            record = self._records.get(ref.path)
            if record is None or record.ref != ref:
                return None
            if not include_closed and not record.is_open:
                return None
            return record

    def records(
        self,
        *,
        prefix: AgentPath | None = None,
        include_closed: bool = False,
    ) -> tuple[AgentRecord, ...]:
        with self._lock:
            records = tuple(
                record
                for record in self._records.values()
                if (include_closed or record.is_open)
                and (
                    prefix is None
                    or record.path.is_descendant_of(prefix, include_self=True)
                )
            )
        return tuple(sorted(records, key=lambda record: record.path.parts))

    def children(self, parent_ref: AgentRef) -> tuple[AgentRecord, ...]:
        with self._lock:
            self._require_current(parent_ref)
            return tuple(
                record for record in self.records() if record.parent_ref == parent_ref
            )

    def subtree(self, ref: AgentRef) -> tuple[AgentRecord, ...]:
        current = self.get(ref)
        if current is None:
            return ()
        return self.records(prefix=current.path)

    def resolve(
        self,
        *,
        caller_ref: AgentRef,
        target: str | AgentPath,
    ) -> AgentRecord:
        caller = self._require_current(caller_ref)
        if not caller.is_open:
            raise MultiAgentError(
                "agent_not_addressable", f"caller is closed: {caller.path}"
            )
        if isinstance(target, AgentPath):
            return self._require_addressable(target)
        if not isinstance(target, str) or not target:
            raise MultiAgentError("agent_not_found", "agent target must be non-empty")
        if target.startswith("/"):
            try:
                return self._require_addressable(AgentPath.parse(target))
            except ValueError as error:
                raise MultiAgentError(
                    "agent_not_found", f"invalid agent path: {target}"
                ) from error
        if target == "parent":
            if caller.parent_ref is None:
                raise MultiAgentError("agent_not_found", "the root agent has no parent")
            parent = self.get(caller.parent_ref)
            if parent is None:
                raise MultiAgentError(
                    "agent_not_found", f"parent is not addressable: {target}"
                )
            return parent

        try:
            require_agent_name(target, field_name="relative agent target")
        except ValueError as error:
            raise MultiAgentError(
                "agent_not_found", f"invalid relative agent target: {target}"
            ) from error
        direct = tuple(
            record for record in self.children(caller_ref) if record.path.name == target
        )
        if direct:
            return direct[0]
        candidates = tuple(
            record
            for record in self.records(prefix=caller.path)
            if record.path != caller.path and record.path.name == target
        )
        if not candidates:
            raise MultiAgentError(
                "agent_not_found",
                f"agent target was not found below {caller.path}: {target}",
            )
        if len(candidates) > 1:
            paths = tuple(str(record.path) for record in candidates)
            raise MultiAgentError(
                "agent_reference_ambiguous",
                f"agent target is ambiguous below {caller.path}: {target}",
                details={"candidates": paths},
            )
        return candidates[0]

    def update(
        self,
        ref: AgentRef,
        *,
        status: AgentStatus | None = None,
        round_id: int | None = None,
        progress: AgentProgress | None = None,
        workspace_ref: str | None = None,
        artifact_refs: tuple[str, ...] | None = None,
        change_set_ref: str | None = None,
        update_workspace: bool = False,
    ) -> AgentRecord:
        with self._lock:
            current = self._require_current(ref)
            if not current.is_open:
                raise MultiAgentError(
                    "agent_not_addressable", f"agent is closed: {ref.path}"
                )
            updated = replace(
                current,
                status=current.status if status is None else status,
                round_id=current.round_id if round_id is None else round_id,
                progress=current.progress if progress is None else progress,
                workspace_ref=(
                    current.workspace_ref if not update_workspace else workspace_ref
                ),
                artifact_refs=(
                    current.artifact_refs
                    if artifact_refs is None
                    else tuple(artifact_refs)
                ),
                change_set_ref=(
                    current.change_set_ref if not update_workspace else change_set_ref
                ),
                updated_at=self._clock(),
            )
            self._records[ref.path] = updated
            return updated

    def close(self, ref: AgentRef) -> AgentRecord:
        with self._lock:
            current = self._require_current(ref)
            if current.status == "closed":
                return current
            closed = replace(current, status="closed", updated_at=self._clock())
            self._records[ref.path] = closed
            return closed

    def _commit(self, reservation: AgentReservation) -> AgentRecord:
        with self._lock:
            token = self._reservations.get(reservation.ref.path)
            if token != reservation._token:
                raise MultiAgentError(
                    "reservation_stale",
                    f"agent reservation is stale: {reservation.ref.path}",
                )
            parent = self.get(reservation.parent_ref)
            if parent is None:
                self._reservations.pop(reservation.ref.path, None)
                raise MultiAgentError(
                    "parent_not_open",
                    f"parent agent is no longer open: {reservation.parent_ref.path}",
                )
            now = self._clock()
            record = AgentRecord(
                ref=reservation.ref,
                parent_ref=reservation.parent_ref,
                agent_type=reservation.agent_type,
                status="idle",
                round_id=0,
                created_at=now,
                updated_at=now,
            )
            self._records[record.path] = record
            self._reservations.pop(record.path, None)
            return record

    def _rollback(self, reservation: AgentReservation) -> None:
        with self._lock:
            if self._reservations.get(reservation.ref.path) == reservation._token:
                self._reservations.pop(reservation.ref.path, None)

    def _require_current(self, ref: AgentRef) -> AgentRecord:
        with self._lock:
            record = self._records.get(ref.path)
            if record is None or record.ref != ref:
                raise MultiAgentError(
                    "stale_agent_ref",
                    f"agent reference is stale: {ref}",
                )
            return record

    def _require_addressable(self, path: AgentPath) -> AgentRecord:
        with self._lock:
            record = self._records.get(path)
            if record is None:
                raise MultiAgentError("agent_not_found", f"agent was not found: {path}")
            if not record.is_open:
                raise MultiAgentError(
                    "agent_not_addressable", f"agent is closed: {path}"
                )
            return record


__all__ = ["AgentRegistry", "AgentReservation", "Clock"]
