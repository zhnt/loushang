"""Optional inherited stdio handoff for a prepared AppHost application."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from loushang.apphost.continuity import (
    HostedApplicationContinuityRuntimeV1,
    _ContinuityAttemptLifecycle,
)
from loushang.apphost.foreground import HostedForegroundRuntimeV1, _failed, _observe
from loushang.appserver.stdio import InheritedStdioTransportV1


class _InheritedStdioForeground:
    """Transfer a prepared application and inherited stdio to the foreground owner."""

    def __init__(
        self,
        attempt: _ContinuityAttemptLifecycle,
        *,
        connection_timeout: float,
        settlement_timeout: float,
        session_discovery: bool,
        session_execution: bool,
        prepare_session_roots: Callable[[], None] | None,
    ) -> None:
        self._attempt = attempt
        self._connection_timeout = connection_timeout
        self._settlement_timeout = settlement_timeout
        self._session_discovery = session_discovery
        self._session_execution = session_execution
        self._prepare_session_roots = prepare_session_roots
        self._application: HostedApplicationContinuityRuntimeV1 | None = None
        self._transport: InheritedStdioTransportV1 | None = None
        self._foreground: HostedForegroundRuntimeV1 | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._started = False
        self._closing = False
        self._settled = False

    @property
    def cleanup_pending(self) -> bool:
        return not self._settled

    async def run(self, *, input_fd: int, output_fd: int) -> None:
        if self._started or self._closing:
            raise RuntimeError("hosted_command_closed")
        self._started = True
        try:
            if self._prepare_session_roots is not None:
                await asyncio.to_thread(self._prepare_session_roots)
            self._application = await self._attempt.open()
            self._transport = InheritedStdioTransportV1(
                input_fd=input_fd, output_fd=output_fd
            )
            self._foreground = HostedForegroundRuntimeV1(
                self._application,
                self._transport,
                connection_timeout=self._connection_timeout,
                settlement_timeout=self._settlement_timeout,
                session_discovery=self._session_discovery,
                session_execution=self._session_execution,
            )
            await self._foreground.run()
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
        if self._foreground is not None:
            await self._foreground.close()
        else:
            if self._application is not None:
                await self._application.close()
            else:
                await self._attempt.close()
            if self._transport is not None:
                await self._transport.close()
        self._settled = True
