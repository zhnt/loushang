"""An explicitly selected managed instance, authenticated without retargeting.

Composition adopts this lease before prepare and closes it before the borrowed
journal. Cancellation of a waiter never abandons the original preparation or
cleanup task. No discovery, spawn, stop, directory creation or mutation replay.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event
from time import monotonic
from typing import Any, TypeVar, cast

from loushang.appserver.client import (
    AppClientV1,
    AppConnectionClosedError,
    SessionDiscoveryClientV1,
)
from loushang.appserver.execution.client import ExecutionClientV1
from loushang.appserver.local import LocalAppClientConnectionV1
from loushang.appserver.local_record import (
    LocalConnectionDirectoryV1,
    LocalRecordScopeV1,
    require_endpoint,
)
from loushang.appserver.managed_mux import ManagedMuxCreationClientV1
from loushang.appserver.managed_mux_close import ManagedMuxCloseClientV1
from loushang.hosting.service import LinuxServiceObserverV1

from ._files import ManagedStorageError, _check_deadline
from .child import _spawn
from .contracts import (
    ManagedContractError,
    ManagedHandoffPhaseV1,
    ManagedInstanceRefV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
)
from .lifecycle import ManagedServiceJournalV1, ManagedServiceStateV1
from .paths import resolve_managed_service_paths


def _same_connection_state(original: ManagedServiceStateV1, current: ManagedServiceStateV1) -> bool:
    if current == original:
        return True
    # The optional, write-once trace receipt is not connection authority. Only
    # its single publication may cross authentication; every lifecycle field,
    # native identity and other revision change retains the exact fence.
    return (
        original.trace_application is None and current.trace_application is not None
        and current.revision == original.revision + 1
        and replace(current, revision=original.revision, trace_application=None) == original
    )


class ManagedConnectionLeaseV1:
    """One same-loop connection admission; close never signals the service.

    The post-authentication check is an admission observation, not a guarantee
    against a subsequent service stop. The server retains per-request authority.
    Failed preparation is not retried; an explicit fresh selection needs a new
    lease. Failed cleanup retains the original resources for close retries.
    """

    def __init__(
        self, journal: ManagedServiceJournalV1, namespace: ManagedNamespaceV1,
        service: ManagedServiceKeyV1, instance: ManagedInstanceRefV1, *,
        runtime_root: str, endpoint: str,
    ) -> None:
        paths = resolve_managed_service_paths(namespace, service, runtime_root=runtime_root)
        require_endpoint(endpoint)
        if (
            namespace.user_id != os.geteuid()
            or type(journal) is not ManagedServiceJournalV1
            or type(instance) is not ManagedInstanceRefV1
            or instance.namespace_key != namespace.namespace_key
            or instance.service_id != service.service_id
            or journal._namespace != namespace or journal._service != service
            or str(journal._fence._root) != str(paths.lifecycle)
            or str(journal._database._directory._root) != str(paths.registry)
        ):
            raise ManagedContractError()
        self._journal, self._service, self._instance = journal, service, instance
        self._root, self._endpoint = Path(paths.connection), endpoint
        self._observer: LinuxServiceObserverV1 | None = None
        self._native_uncertain = False
        self._observer_close_unknown = False
        self._directory: LocalConnectionDirectoryV1 | None = None
        self._connection: LocalAppClientConnectionV1 | None = None
        self._prepare_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = False
        self._closing = False
        self._settled = False

    @property
    def instance(self) -> ManagedInstanceRefV1:
        return self._instance

    @property
    def cleanup_pending(self) -> bool:
        return not self._settled

    def _require_connection(self) -> LocalAppClientConnectionV1:
        self._bind_loop()
        if self._closing or not self._ready or self._connection is None:
            raise AppConnectionClosedError()
        return self._connection

    @property
    def client(self) -> AppClientV1:
        return self._require_connection().client

    @property
    def discovery_client(self) -> SessionDiscoveryClientV1 | None:
        return self._require_connection().discovery_client

    @property
    def execution_client(self) -> ExecutionClientV1 | None:
        return self._require_connection().execution_client

    @property
    def managed_mux_client(self) -> ManagedMuxCreationClientV1 | None:
        return self._require_connection().managed_mux_client

    @property
    def managed_mux_close_client(self) -> ManagedMuxCloseClientV1 | None:
        return self._require_connection().managed_mux_close_client

    @property
    def application_id(self) -> str:
        return self._require_connection().application_id

    @property
    def scopes(self) -> tuple[LocalRecordScopeV1, ...]:
        return self._require_connection().scopes

    def _bind_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise ManagedStorageError("conflict")

    async def prepare(self, *, deadline: float) -> None:
        self._bind_loop()
        _check_deadline(deadline)
        if self._closing or self._prepare_task is not None:
            raise ManagedStorageError("conflict")
        self._prepare_task = _spawn(self._prepare_once(deadline))
        await asyncio.shield(self._prepare_task)
        if self._closing or not self._ready:
            raise AppConnectionClosedError()

    def _current(self, deadline: float) -> ManagedServiceStateV1:
        state = self._journal.read(deadline=deadline, wait_for_lock=True)
        if (state is None or state.handoff.instance != self._instance
                or state.handoff.phase is not ManagedHandoffPhaseV1.COMMITTED
                or state.handoff.stop_requested or state.native_identity is None):
            raise ManagedStorageError("unavailable")
        return state

    def _admit_native(self, deadline: float) -> ManagedServiceStateV1:
        state = self._current(deadline)
        assert state.native_identity is not None
        self._native_uncertain = True
        self._observer = LinuxServiceObserverV1.reopen(state.native_identity)
        self._native_uncertain = False
        if self._observer.exited():
            raise ManagedStorageError("unavailable")
        _check_deadline(deadline)
        return state

    def _recheck(self, original: ManagedServiceStateV1, deadline: float) -> None:
        current = self._current(deadline)
        if (not _same_connection_state(original, current) or self._observer is None
                or self._observer.identity != current.native_identity or self._observer.exited()):
            raise ManagedStorageError("unavailable")
        _check_deadline(deadline)

    async def _prepare_once(self, deadline: float) -> None:
        original = await _settled_native(self._admit_native, deadline)
        if self._closing:
            raise AppConnectionClosedError()
        _check_deadline(deadline)
        self._directory = LocalConnectionDirectoryV1(self._root)
        self._connection = LocalAppClientConnectionV1(
            self._directory, self._endpoint, timeout=min(30.0, deadline - monotonic()),
            expected_product_id=self._service.product_id,
            expected_instance=self._instance.instance_id,
        )
        await self._connection.start()
        await _settled_native(self._recheck, original, deadline)
        if self._closing:
            raise AppConnectionClosedError()
        _check_deadline(deadline)
        self._ready = True

    async def close(self) -> None:
        self._bind_loop()
        self._closing = True
        self._ready = False
        task = self._close_task
        if task is None or (task.done() and (task.cancelled() or task.exception() is not None)):
            task = self._close_task = _spawn(self._close_once())
        await asyncio.shield(task)

    async def _close_once(self) -> None:
        if self._prepare_task is not None:
            await asyncio.gather(self._prepare_task, return_exceptions=True)
        errors: list[BaseException] = []
        if self._connection is not None:
            try:
                await self._connection.close()
            except BaseException as error:
                errors.append(error)
            else:
                self._connection = None
        # The directory is borrowed by the connection until it fully settles.
        if self._connection is None and self._directory is not None:
            try:
                await _settled_native(self._directory.close)
            except BaseException as error:
                errors.append(error)
            else:
                self._directory = None
        if self._observer is not None:
            if self._observer_close_unknown:
                errors.append(ManagedStorageError("unavailable"))
            else:
                self._observer_close_unknown = True
                try:
                    await _settled_native(self._observer.close)
                except BaseException as error:
                    errors.append(error)
                else:
                    self._observer_close_unknown = False
                    self._observer = None
        if self._native_uncertain:
            errors.append(ManagedStorageError("unavailable"))
        if errors:
            raise errors[0]
        self._settled = True


_T = TypeVar("_T")


async def _settled_native(operation: Callable[..., _T], *args: Any) -> _T:
    """Actual callable receipt, independent of cancellation of executor futures.

    Publication gates submission faults before native effects, using the same
    receipt pattern as existing IO owners without importing Harness internals.
    The caller must keep this loop alive until its lease finishes closing.
    """
    loop = asyncio.get_running_loop()
    receipt: asyncio.Future[tuple[bool, object]] = loop.create_future()
    published = Event()
    admitted = False

    def native() -> None:
        published.wait()
        if not admitted:
            return
        try:
            outcome: tuple[bool, object] = (True, operation(*args))
        except BaseException as error:
            outcome = (False, error)
        loop.call_soon_threadsafe(receipt.set_result, outcome)

    try:
        offload = loop.run_in_executor(None, native)
        admitted = True
    finally:
        published.set()
    offload.add_done_callback(lambda future: None if future.cancelled() else future.exception())
    cancellation = None
    while not receipt.done():
        try:
            await asyncio.shield(receipt)
        except asyncio.CancelledError as error:
            cancellation = error
    succeeded, result = receipt.result()
    if not succeeded:
        raise cast(BaseException, result)
    if cancellation is not None:
        raise cancellation
    return cast(_T, result)


__all__ = ["ManagedConnectionLeaseV1"]
