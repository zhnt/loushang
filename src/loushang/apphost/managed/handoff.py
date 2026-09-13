"""Bind Hosting's inherited-channel protocol to one durable AppHost attempt."""

from __future__ import annotations

import socket
from collections.abc import Callable
from time import monotonic
from typing import Literal

from loushang.hosting.errors import HostingError
from loushang.hosting.service import LinuxServiceIdentityV1
from loushang.hosting.service_handoff import (
    ServiceChildHandoffV1,
    ServiceHandoffPhaseV1,
)

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
        attempt_id: str, *, native_identity: LinuxServiceIdentityV1 | None = None,
    ) -> None:
        if type(journal) is not ManagedServiceJournalV1 or type(instance) is not ManagedInstanceRefV1:
            raise ManagedContractError()
        _match(attempt_id, _HEX32)
        if native_identity is not None and type(native_identity) is not LinuxServiceIdentityV1:
            raise ManagedContractError()
        self._journal, self._instance, self._attempt = journal, instance, attempt_id
        self._native = native_identity

    def _phase(self, state: ManagedServiceStateV1 | None) -> ServiceHandoffPhaseV1:
        if (state is None or state.handoff.instance != self._instance
                or state.handoff.attempt_id != self._attempt):
            return ServiceHandoffPhaseV1.UNKNOWN
        if (self._native is not None and state.native_identity is not None
                and self._native != state.native_identity):
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
        # Query/starter-side ports deliberately have no commit capability.
        if self._native is None:
            return ServiceHandoffPhaseV1.UNKNOWN
        return self._mutate(lambda: self._journal.commit(
            self._instance, self._attempt, native_identity=self._native, deadline=deadline,
        ), deadline)

    def abort(self, deadline: float | None = None) -> ServiceHandoffPhaseV1:
        return self._mutate(lambda: self._journal.abort(
            self._instance, self._attempt, native_identity=self._native, deadline=deadline,
        ), deadline)


class ManagedChildControlV1:
    """Synchronous child control; exclusively used by one retained IO worker.

    Owns the supplied startup channel after successful construction, borrows the
    journal. Never launches, signals or closes an application. Returned state
    includes the matching stop fence; phase-only hints are insufficient here.
    """

    def __init__(
        self, journal: ManagedServiceJournalV1, instance: ManagedInstanceRefV1,
        attempt_id: str, native_identity: LinuxServiceIdentityV1, endpoint: socket.socket,
    ) -> None:
        if type(native_identity) is not LinuxServiceIdentityV1:
            raise ManagedContractError()
        self._port = ManagedServiceHandoffPortV1(
            journal, instance, attempt_id, native_identity=native_identity,
        )
        journal._require_native(native_identity)  # Pure admission before taking the socket.
        self._journal, self._instance, self._attempt = journal, instance, attempt_id
        self._native = native_identity
        self._channel = ServiceChildHandoffV1(endpoint, self._port)

    def observe(
        self, action: Literal["read", "poll", "commit", "stop", "cleanup"], deadline: float,
    ) -> ManagedServiceStateV1 | None:
        """Mutate at most once, then reobserve; unknown never supplies authority."""
        if action not in {"read", "poll", "commit", "stop", "cleanup"}:
            raise ManagedContractError()
        if type(deadline) not in (int, float) or not 0 < deadline <= 1e12:
            raise ManagedContractError()
        try:
            remaining = max(0.0, min(2.0, deadline - monotonic()))
            if remaining <= 0:
                return None
            if action == "poll":
                self._channel.poll_parent(timeout=remaining, deadline=deadline)
            elif action == "commit":
                self._channel.commit(timeout=remaining, deadline=deadline)
            elif action == "stop":
                self._journal.request_child_stop(
                    self._instance, self._attempt, self._native, deadline=deadline,
                )
            elif action == "cleanup":
                self._journal.record_child_cleanup(
                    self._instance, self._attempt, self._native, deadline=deadline,
                )
        except (ManagedStorageError, ManagedContractError, HostingError, OSError):
            pass  # The write may already have committed; reobserve, never replay.
        if monotonic() >= deadline:
            return None
        try:
            state = self._journal.read(deadline=deadline)
            return state if self._port._phase(state) is not ServiceHandoffPhaseV1.UNKNOWN else None
        except (ManagedStorageError, ManagedContractError, OSError):
            return None

    def close(self) -> None:
        self._channel.close()
