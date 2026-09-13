"""Bind Hosting's inherited-channel protocol to one durable AppHost attempt."""

from __future__ import annotations

from collections.abc import Callable

from loushang.hosting.service_handoff import ServiceHandoffPhaseV1

from ._files import ManagedStorageError
from .contracts import _HEX32, ManagedContractError, ManagedInstanceRefV1, _match
from .lifecycle import ManagedServiceJournalV1, ManagedServiceStateV1


class ManagedServiceHandoffPortV1:
    """Borrow a journal; never turn a stale generation into current authority.

    Failed mutation is resolved by a fresh durable read, not by replaying spawn
    or by assuming rollback. A provisional stop fence rejects commit but is not
    itself ABORTING: the application owner must explicitly request abort before
    performing startup cleanup. No process or application cleanup is done here.
    """

    def __init__(
        self, journal: ManagedServiceJournalV1, instance: ManagedInstanceRefV1,
        attempt_id: str,
    ) -> None:
        if type(journal) is not ManagedServiceJournalV1 or type(instance) is not ManagedInstanceRefV1:
            raise ManagedContractError()
        _match(attempt_id, _HEX32)
        self._journal, self._instance, self._attempt = journal, instance, attempt_id

    def _phase(self, state: ManagedServiceStateV1 | None) -> ServiceHandoffPhaseV1:
        if (state is None or state.handoff.instance != self._instance
                or state.handoff.attempt_id != self._attempt):
            return ServiceHandoffPhaseV1.UNKNOWN
        return ServiceHandoffPhaseV1(state.handoff.phase.value)

    def observe(self, deadline: float | None = None) -> ServiceHandoffPhaseV1:
        try:
            return self._phase(self._journal.read(deadline=deadline))
        except (ManagedStorageError, ManagedContractError, OSError):
            return ServiceHandoffPhaseV1.UNKNOWN

    def _mutate(self, operation: Callable[[], ManagedServiceStateV1], deadline: float | None) -> ServiceHandoffPhaseV1:
        try:
            return self._phase(operation())
        except (ManagedStorageError, ManagedContractError, OSError):
            return self.observe(deadline)

    def commit(self, deadline: float | None = None) -> ServiceHandoffPhaseV1:
        return self._mutate(lambda: self._journal.commit(self._instance, self._attempt, deadline=deadline), deadline)

    def abort(self, deadline: float | None = None) -> ServiceHandoffPhaseV1:
        return self._mutate(lambda: self._journal.abort(self._instance, self._attempt, deadline=deadline), deadline)
