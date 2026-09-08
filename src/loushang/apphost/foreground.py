"""Optional G14 connection-before-application foreground lifetime owner.

The trusted Product opens/recovers its G13 application before constructing
this owner. This module neither chooses Product code nor spawns a process.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine

from loushang.appserver.connection import AppServerConnectionV1
from loushang.appserver.framing import (
    AppByteTransportV1,
    AppFramedStreamV1,
    require_timeout,
)
from loushang.appserver.protocol.connection_profile import AppConnectionProfileV1

from .application import HostedApplicationError
from .continuity import HostedApplicationContinuityRuntimeV1


class HostedForegroundRuntimeV1:
    """Adopt a ready G13 application and byte IO before serving one connection.

    EOF is terminal. A failed/timed-out cleanup retains its exact task/owner
    for a later close; application cleanup cannot overtake connection work.
    The caller continues to own process exit and any terminate/reap policy.
    """

    def __init__(
        self,
        application: HostedApplicationContinuityRuntimeV1,
        transport: AppByteTransportV1,
        *,
        connection_timeout: float = 10.0,
        settlement_timeout: float = 60.0,
        session_discovery: bool = False,
    ) -> None:
        if type(session_discovery) is not bool:
            raise TypeError("invalid discovery activation")
        require_timeout(connection_timeout)
        require_timeout(settlement_timeout)
        discovery = application.discovery_client if session_discovery else None
        if session_discovery and discovery is None:
            raise HostedApplicationError("hosted_discovery_unavailable")
        self._application = application
        self._connection = AppServerConnectionV1(
            application.client,
            AppFramedStreamV1(transport, io_timeout=connection_timeout),
            phase_timeout=connection_timeout,
            profile=(
                AppConnectionProfileV1.STDIO_DISCOVERY
                if session_discovery
                else AppConnectionProfileV1.STDIO
            ),
            discovery=discovery,
        )
        self._timeout = settlement_timeout
        self._serving: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._phases: dict[str, asyncio.Task[None]] = {}
        self._closing = False
        self._settled = False

    @property
    def cleanup_pending(self) -> bool:
        return not self._settled

    async def run(self) -> None:
        if self._serving is not None or self._closing:
            raise HostedApplicationError("hosted_foreground_closed")
        self._serving = asyncio.create_task(self._connection.serve())
        self._serving.add_done_callback(_observe)
        try:
            await asyncio.shield(self._serving)
        except asyncio.CancelledError:
            caller = asyncio.current_task()
            if not (
                self._closing
                and self._serving.cancelled()
                and caller is not None
                and caller.cancelling() == 0
            ):
                raise
        finally:
            await self.close()

    async def close(self) -> None:
        self._closing = True
        if self._settled:
            return
        task = self._close_task
        if task is None or _failed(task):
            task = asyncio.create_task(self._close_once())
            task.add_done_callback(_observe)
            self._close_task = task
        await asyncio.shield(task)

    async def _close_once(self) -> None:
        serving = self._serving
        if serving is not None and not serving.done():
            serving.cancel()
        # Connection close fences byte IO as well as semantic dispatch. The
        # inherited descriptors themselves remain borrowed until process exit.
        await self._phase("connection", self._connection.close)
        if serving is not None:
            done, _ = await asyncio.wait({serving}, timeout=self._timeout)
            if not done:
                raise HostedApplicationError("hosted_foreground_cleanup_incomplete")
            _observe(serving)  # run(), not close(), reports the connection outcome.
        # G13 owns service/AppHost/Product settlement and releases its lease last.
        await self._phase("application", self._application.close)
        self._settled = True

    async def _phase(
        self, name: str, close: Callable[[], Coroutine[object, object, None]]
    ) -> None:
        task = self._phases.get(name)
        if task is None or _failed(task):
            task = asyncio.create_task(close())
            task.add_done_callback(_observe)
            self._phases[name] = task
        done, _ = await asyncio.wait({task}, timeout=self._timeout)
        if not done:
            # No second task and no cancellation of the retained close owner.
            raise HostedApplicationError("hosted_foreground_cleanup_incomplete")
        if task.cancelled() or task.exception() is not None:
            raise HostedApplicationError("hosted_foreground_cleanup_incomplete")


def _failed(task: asyncio.Task[None]) -> bool:
    return task.done() and (task.cancelled() or task.exception() is not None)


def _observe(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


__all__ = ["HostedForegroundRuntimeV1"]
