"""Parent-side launch composition; durable birth is not application readiness.

The caller adopts this object before calling start and retains it after errors.
It borrows an already admitted journal and never creates/replaces its registry
or lifecycle fence. Async consumers must join the original synchronous worker.
Closing releases parent-local resources, not a committed background service.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Callable
from secrets import token_hex
from threading import Event, RLock

from loushang.hosting.contracts import ProcessLaunchRequest
from loushang.hosting.service_process import LinuxServiceProcessV1

from ._files import ManagedStorageError, _check_deadline
from .contracts import (
    ManagedContractError,
    ManagedHandoffPhaseV1,
    ManagedInstanceRefV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
)
from .invocation import ManagedChildInvocationV1, _validate_trace_deadline
from .layout import ManagedLayoutPreparationV1
from .lifecycle import ManagedServiceJournalV1, ManagedServiceStateV1
from .paths import resolve_managed_paths, resolve_managed_service_paths

ManagedLaunchRequestFactoryV1 = Callable[[ManagedChildInvocationV1, int], ProcessLaunchRequest]


class ManagedServiceStarterV1:
    """One original prepare/spawn attempt, with repeatable birth observation.

    Request construction is a pure Product callback outside durable locks.
    Neither a callback error, timeout nor an uncertain spawn permits replay.
    A fresh starter must win a new journal generation, not reuse this attempt.
    """

    def __init__(
        self, journal: ManagedServiceJournalV1, namespace: ManagedNamespaceV1,
        service: ManagedServiceKeyV1, *, runtime_root: str,
        request_factory: ManagedLaunchRequestFactoryV1,
        temporary_override: str | None = None,
        trace_deadline_ms: int | None = None,
    ) -> None:
        _validate_trace_deadline(trace_deadline_ms)
        paths = resolve_managed_service_paths(namespace, service, runtime_root=runtime_root)
        # Validate scratch before durable prepare; this placeholder is used only
        # for pure lexical validation, never as a native or persisted instance.
        resolve_managed_paths(namespace, service, ManagedInstanceRefV1(
            namespace.namespace_key, service.service_id, "0" * 32,
        ), runtime_root=runtime_root, temporary_override=temporary_override)
        if (namespace.user_id != os.geteuid()
                or type(journal) is not ManagedServiceJournalV1 or not callable(request_factory)
                or journal._namespace != namespace or journal._service != service
                or str(journal._fence._root) != str(paths.lifecycle)
                or str(journal._database._directory._root) != str(paths.registry)):
            raise ManagedContractError()
        self._journal, self._namespace, self._service = journal, namespace, service
        self._runtime_root, self._request_factory = runtime_root, request_factory
        self._temporary_override = temporary_override
        self._trace_deadline_ms = trace_deadline_ms
        self._attempt = token_hex(16)
        self._state: ManagedServiceStateV1 | None = None
        self._layout: ManagedLayoutPreparationV1 | None = None
        self._process: LinuxServiceProcessV1 | None = None
        self._endpoints: tuple[socket.socket, socket.socket] | None = None
        self._closed_endpoints: set[int] = set()
        self._unknown_endpoints: set[int] = set()
        self._started = False
        self._closing = Event()
        self._mutex = RLock()

    @property
    def cleanup_pending(self) -> bool:
        return bool(
            self._layout is not None and self._layout.cleanup_pending
            or self._process is not None and not self._process.handles_closed
            or self._endpoints is not None and len(self._closed_endpoints) != 2
        )

    def _check(self, deadline: float) -> None:
        _check_deadline(deadline)
        if self._closing.is_set():
            raise ManagedStorageError("closed")

    def start(
        self, *, expected: ManagedServiceStateV1 | None, deadline: float,
    ) -> ManagedServiceStateV1:
        """Reserve once, prepare real-instance layout, spawn once and bind birth."""
        self._check(deadline)
        if not self._mutex.acquire(blocking=False):
            raise ManagedStorageError("busy")
        try:
            self._check(deadline)
            if self._started:
                raise ManagedStorageError("conflict")
            self._started = True
            self._state = self._journal.prepare(self._attempt, expected=expected, deadline=deadline)
            self._check(deadline)
            self._layout = ManagedLayoutPreparationV1(
                self._namespace, self._service, self._state.handoff.instance,
                runtime_root=self._runtime_root, require_control_roots=True,
                temporary_override=self._temporary_override,
            )
            self._layout.open(deadline=deadline)
            self._check(deadline)
            self._require_provisional(deadline)
            self._endpoints = socket.socketpair()
            invocation = ManagedChildInvocationV1(
                self._namespace, self._service, self._state.handoff.instance,
                self._attempt, self._runtime_root, self._temporary_override, self._trace_deadline_ms,
            )
            request = self._request_factory(invocation, self._endpoints[1].fileno())
            self._check(deadline)
            self._require_provisional(deadline)
            self._process = LinuxServiceProcessV1(request, self._endpoints[1])
            # Admission linearizes here. Native spawn cannot be preempted after
            # this check; its original owner remains retained through the effect.
            self._check(deadline)
            self._process.spawn()
            return self.register_birth(deadline=deadline)
        finally:
            self._mutex.release()

    def _require_current(self, deadline: float) -> ManagedServiceStateV1:
        observed = self._journal.read(deadline=deadline)
        if (observed is None or observed.handoff.attempt_id != self._attempt
                or self._state is not None and observed.handoff.instance != self._state.handoff.instance):
            raise ManagedStorageError("conflict")
        return observed

    def _require_provisional(self, deadline: float) -> None:
        observed = self._require_current(deadline)
        if (observed.handoff.phase is not ManagedHandoffPhaseV1.PROVISIONAL
                or observed.handoff.stop_requested or observed.native_identity is not None):
            raise ManagedStorageError("conflict")

    def register_birth(self, *, deadline: float) -> ManagedServiceStateV1:
        """Retry only durable identity binding; never repeat native creation."""
        self._check(deadline)
        if not self._mutex.acquire(blocking=False):
            raise ManagedStorageError("busy")
        try:
            self._check(deadline)
            if self._process is None or self._process.identity is None:
                raise ManagedStorageError("unavailable")
            observed = self._require_current(deadline)
            identity = self._process.identity
            if observed.native_identity == identity:
                return observed
            return self._journal.register_native(
                observed.handoff.instance, self._attempt, identity, deadline=deadline,
            )
        finally:
            self._mutex.release()

    def observe(self, *, deadline: float) -> ManagedServiceStateV1:
        """Read this exact attempt even after local close; no liveness claim."""
        return self._require_current(deadline)

    def fence(self) -> None:
        """Revoke new local effects without waiting for a native worker."""
        self._closing.set()

    def close(self) -> None:
        self.fence()
        if not self._mutex.acquire(blocking=False):
            raise ManagedStorageError("busy")
        try:
            errors: list[BaseException] = []
            if self._process is not None:
                try:
                    self._process.close()
                except BaseException as error:
                    errors.append(error)
                else:
                    self._closed_endpoints.add(1)
            if self._endpoints is not None:
                for index, endpoint in enumerate(self._endpoints):
                    if index in self._closed_endpoints or index in self._unknown_endpoints:
                        continue
                    if index == 1 and self._process is not None:
                        continue  # Only the original process owner can close it.
                    self._unknown_endpoints.add(index)
                    try:
                        endpoint.close()
                    except BaseException as error:
                        errors.append(error)
                    else:
                        self._unknown_endpoints.remove(index)
                        self._closed_endpoints.add(index)
            if self._layout is not None:
                try:
                    self._layout.close()
                except BaseException as error:
                    errors.append(error)
            if errors:
                raise errors[0]
            if self.cleanup_pending:
                raise ManagedStorageError("unavailable")
        finally:
            self._mutex.release()


__all__ = ["ManagedServiceStarterV1", "ManagedLaunchRequestFactoryV1"]
