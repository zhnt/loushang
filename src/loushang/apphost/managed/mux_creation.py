"""One explicit managed Mux creation over already admitted deployment storage.

Own the original service coordinator and one creation task, not the namespace,
journal, application or Session. Unknown results retain their name reservation;
neither close nor caller cancellation stops a service or repeats a create RPC.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from time import monotonic
from typing import TypeVar

from loushang.appserver.managed_mux import ManagedMuxCreatedV1
from loushang.appservice.continuity import require_application_id

from ._files import ManagedStorageError, _check_deadline
from .child import _failed, _spawn
from .connection import ManagedConnectionLeaseV1, _settled_native
from .contracts import ManagedContractError, ManagedNamespaceV1
from .coordinator import ManagedServiceCoordinatorV1
from .lifecycle import ManagedServiceJournalV1
from .mux_management import ManagedMuxManagerV1
from .registry import ManagedMuxReservationV1, ManagedRegistryV1
from .starter import ManagedLaunchRequestFactoryV1

_T = TypeVar("_T")


class ManagedMuxCreateOperationV1:
    """Retain before run; keep borrowed storage and event loop alive until close.

    The reservation's operation ID is supplied once by composition and differs
    from the service-start attempt ID. Rejoin uses exactly the original deadline.
    ``created`` is a known immutable creation fact, even when result registration
    fails; ``result`` additionally proves registry reconciliation succeeded.
    Neither property is a liveness assertion or a claim that the Mux is open.
    """

    def __init__(
        self, registry: ManagedRegistryV1, journal: ManagedServiceJournalV1,
        namespace: ManagedNamespaceV1, reservation: ManagedMuxReservationV1, *,
        runtime_root: str, endpoint: str, application_id: str,
        request_factory: ManagedLaunchRequestFactoryV1,
        temporary_override: str | None = None,
    ) -> None:
        require_application_id(application_id)
        if (
            type(registry) is not ManagedRegistryV1 or type(journal) is not ManagedServiceJournalV1
            or type(namespace) is not ManagedNamespaceV1 or type(reservation) is not ManagedMuxReservationV1
            or namespace.user_id != os.geteuid() or journal._database is not registry._database
            or journal._namespace != namespace or journal._service != reservation.service
            or registry._database._namespace != namespace.namespace_key
        ):
            raise ManagedContractError()
        self._registry, self._journal, self._namespace = registry, journal, namespace
        self._reservation, self._application_id = reservation, application_id
        self._coordinator = ManagedServiceCoordinatorV1(
            journal, namespace, reservation.service, runtime_root=runtime_root,
            endpoint=endpoint, request_factory=request_factory,
            temporary_override=temporary_override,
        )
        self._manager: ManagedMuxManagerV1 | None = None
        self._connection: ManagedConnectionLeaseV1 | None = None
        self._created: ManagedMuxCreatedV1 | None = None
        self._result: ManagedMuxCreatedV1 | None = None
        self._task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._deadline: float | None = None
        self._closing = self._settled = False

    @property
    def created(self) -> ManagedMuxCreatedV1 | None:
        return self._created

    @property
    def result(self) -> ManagedMuxCreatedV1 | None:
        return self._result

    @property
    def connection(self) -> ManagedConnectionLeaseV1:
        self._bind_loop()
        if self._closing or self._result is None or self._connection is None:
            raise ManagedStorageError("closed")
        _ = self._connection.client
        return self._connection

    @property
    def cleanup_pending(self) -> bool:
        return not self._settled

    def _bind_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise ManagedStorageError("conflict")

    def _check(self, deadline: float, *, settling: bool = False) -> None:
        if type(deadline) not in (int, float):
            raise ManagedStorageError("invalid_record")
        _check_deadline(deadline)
        if self._closing and not settling:
            raise ManagedStorageError("closed")

    async def run(self, *, deadline: float) -> ManagedMuxCreatedV1:
        self._bind_loop()
        self._check(deadline)
        if self._task is None:
            self._deadline = deadline
            self._task = _spawn(self._run_once(deadline))
        elif deadline != self._deadline:
            raise ManagedStorageError("conflict")
        await asyncio.shield(self._task)
        self._check(deadline)
        if self._result is None:
            raise ManagedStorageError("unavailable")
        return self._result

    async def _control(self, operation: Callable[[], _T], deadline: float, *, settling: bool = False) -> _T:
        while True:
            self._check(deadline, settling=settling)
            try:
                return await _settled_native(operation)
            except ManagedStorageError as error:
                if error.code != "busy":
                    raise
                self._check(deadline, settling=settling)
                await asyncio.sleep(min(0.01, max(0, deadline - monotonic())))

    async def _run_once(self, deadline: float) -> None:
        reservation = self._reservation
        await self._control(lambda: self._registry.reserve_mux(reservation, deadline=deadline), deadline)
        self._check(deadline)
        connection = self._connection = await self._coordinator.ensure_started(deadline=deadline)
        self._check(deadline)
        if connection.application_id != self._application_id:
            raise ManagedStorageError("conflict")
        capability = connection.managed_mux_client
        if capability is None:
            raise ManagedStorageError("unavailable")
        manager = self._manager = ManagedMuxManagerV1(
            self._registry, self._journal, self._namespace, reservation.service,
            connection.instance, application_id=self._application_id,
        )
        permit = await self._control(lambda: manager.issue_create(reservation, deadline=deadline), deadline)
        self._check(deadline)
        # One RPC only. Timeout cancels its delivery waiter, not accepted remote
        # work. Explicit close later settles the original local connection.
        try:
            async with asyncio.timeout(max(0, deadline - monotonic())):
                created = await capability.create_managed_mux(permit)
        except TimeoutError:
            raise ManagedStorageError("unavailable") from None
        if (type(created) is not ManagedMuxCreatedV1 or created.operation_id != reservation.operation_id
                or created.name != reservation.name):
            raise ManagedStorageError("invalid_record")
        self._created = created  # Preserve known fact before fallible reconciliation.
        self._result = await self._control(
            lambda: manager.record_created(permit, created, deadline=deadline), deadline, settling=True,
        )

    async def close(self) -> None:
        self._bind_loop()
        self._closing = True
        self._coordinator.fence()
        if self._close_task is None or _failed(self._close_task):
            self._close_task = _spawn(self._close_once())
        await asyncio.shield(self._close_task)

    async def _close_once(self) -> None:
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
        await self._coordinator.close()
        self._settled = True


__all__ = ["ManagedMuxCreateOperationV1"]
