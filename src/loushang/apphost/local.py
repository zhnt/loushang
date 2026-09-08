"""Optional G16 deployment owner for a ready G13 application.

The caller adopts this owner before start. It owns the supplied private record
directory and recovered application; it never discovers roots, opens native IO
itself, selects Product code or terminates a process. Client EOF is nonterminal.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine

from loushang.appserver.framing import require_timeout
from loushang.appserver.local import LocalAppServerV1
from loushang.appserver.local_record import (
    LocalConnectionDirectoryV1,
    LocalRecordScopeV1,
)

from .application import HostedApplicationError
from .continuity import HostedApplicationContinuityRuntimeV1


class HostedLocalRuntimeV1:
    """Fence scopes, settle connections, then close G13 with its lease last.

    One monotonic budget covers the entire stop, including the reply attempt.
    A cancelled waiter never cancels an owned phase. An incomplete close keeps
    exact tasks and owners; ordinary retries do not renew the deadline. A caller
    may grant a new retry_timeout only after the previous close attempt ends.
    """

    def __init__(
        self,
        application: HostedApplicationContinuityRuntimeV1,
        directory: LocalConnectionDirectoryV1,
        endpoint: str,
        *,
        scopes: tuple[LocalRecordScopeV1, ...],
        connection_timeout: float = 10.0,
        startup_timeout: float = 30.0,
        settlement_timeout: float = 30.0,
    ) -> None:
        for timeout in (startup_timeout, settlement_timeout):
            _require_budget(timeout)
        self._application, self._directory = application, directory
        self._server = LocalAppServerV1(
            directory,
            endpoint,
            application_id=application.application_id,
            product_id=application.product_id,
            scopes=scopes,
            scope_factory=application.open_client_scope,
            request_stop=self._request_stop,
            close_timeout=connection_timeout,
        )
        self._startup_timeout, self._timeout = startup_timeout, settlement_timeout
        self._start_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._phases: dict[str, asyncio.Task[None]] = {}
        self._reply: Awaitable[None] | None = None
        self._deadline: float | None = None
        self._stop_started = asyncio.Event()
        self._scopes_enabled = False
        self._closing = False
        self._settled = False

    @property
    def cleanup_pending(self) -> bool:
        return not self._settled

    @property
    def accepting(self) -> bool:
        """Current deployment readiness, revoked synchronously by stop."""
        task = self._start_task
        return (
            self._scopes_enabled
            and not self._closing
            and task is not None
            and task.done()
            and not _failed(task)
        )

    async def start(self) -> None:
        if self._start_task is not None or self._closing:
            raise HostedApplicationError("hosted_local_closed")
        self._start_task = _spawn(self._start_once())
        try:
            done, _ = await asyncio.wait(
                {self._start_task}, timeout=self._startup_timeout
            )
            if not done:
                raise HostedApplicationError("hosted_local_startup_timeout")
            await asyncio.shield(self._start_task)
            if not self.accepting:
                raise HostedApplicationError("hosted_local_closed")
        except BaseException:
            await self.close()
            raise

    async def _start_once(self) -> None:
        if self._closing:
            raise HostedApplicationError("hosted_local_closed")
        self._application.enable_client_scopes()
        self._scopes_enabled = True
        await self._server.start()
        if self._closing:
            raise HostedApplicationError("hosted_local_closed")

    async def wait_closed(self) -> None:
        """Wait for explicit stop or close, not for a client to disconnect."""
        await self._stop_started.wait()
        await self.close()

    async def run(self) -> None:
        try:
            await self.start()
            await self.wait_closed()
        finally:
            await self.close()

    def _request_stop(self, reply_finished: Awaitable[None]) -> None:
        # The native peer calls this synchronously before writing stop_requested.
        # It completes the barrier even when the write or its waiter fails.
        self._begin_close(reply=reply_finished)

    def _begin_close(
        self,
        *,
        reply: Awaitable[None] | None = None,
        retry_timeout: float | None = None,
    ) -> asyncio.Task[None]:
        if not self._closing:
            self._closing = True
            self._reply = reply
            self._deadline = asyncio.get_running_loop().time() + self._timeout
            self._server.fence()
            if self._scopes_enabled:
                self._application.fence_client_scopes()
            self._stop_started.set()
        task = self._close_task
        if task is None or _failed(task):
            if retry_timeout is not None:
                self._deadline = asyncio.get_running_loop().time() + retry_timeout
            self._close_task = task = _spawn(self._close_once())
        return task

    async def close(self, *, retry_timeout: float | None = None) -> None:
        if retry_timeout is not None:
            _require_budget(retry_timeout)
        if self._settled:
            return
        await asyncio.shield(self._begin_close(retry_timeout=retry_timeout))

    async def _close_once(self) -> None:
        assert self._deadline is not None
        deadline = self._deadline
        if self._start_task is not None:
            # A failed startup may still own a late listener/record handoff.
            await _wait(self._start_task, deadline, ignore_failure=True)
        await self._phase("reply", self._finish_reply, deadline)
        await self._phase("connection", self._server.close, deadline)
        await self._phase("directory", self._close_directory, deadline)
        # G13 closes AppService/AppHost/Product first and retains desired state.
        await self._phase("application", self._application.close, deadline)
        self._settled = True

    async def _finish_reply(self) -> None:
        if self._reply is not None:
            # A lost reply is not a failed application-stop admission.
            await asyncio.gather(self._reply, return_exceptions=True)

    async def _close_directory(self) -> None:
        self._directory.close()

    async def _phase(
        self,
        name: str,
        action: Callable[[], Coroutine[object, object, None]],
        deadline: float,
    ) -> None:
        task = self._phases.get(name)
        if task is None or _failed(task):
            if asyncio.get_running_loop().time() >= deadline:
                raise HostedApplicationError("hosted_local_cleanup_incomplete")
            self._phases[name] = task = _spawn(action())
        await _wait(task, deadline)


def _require_budget(timeout: float) -> None:
    require_timeout(timeout)
    if timeout > 30:
        raise ValueError("local application budget exceeds profile bound")


async def _wait(
    task: asyncio.Task[None],
    deadline: float,
    *,
    ignore_failure: bool = False,
) -> None:
    if not task.done():
        await asyncio.wait(
            {task}, timeout=max(0.0, deadline - asyncio.get_running_loop().time())
        )
    if not task.done() or (not ignore_failure and _failed(task)):
        raise HostedApplicationError("hosted_local_cleanup_incomplete")


def _failed(task: asyncio.Task[None]) -> bool:
    return task.done() and (task.cancelled() or task.exception() is not None)


def _spawn(work: Coroutine[object, object, None]) -> asyncio.Task[None]:
    published = asyncio.get_running_loop().create_future()

    async def invoke() -> None:
        await published
        await work

    def finished(task: asyncio.Task[None]) -> None:
        work.close()  # Also close unstarted work if its wrapper was cancelled.
        if not task.cancelled():
            task.exception()

    invocation = invoke()
    try:
        task = asyncio.create_task(invocation)
    except BaseException:
        invocation.close()
        work.close()
        raise
    task.add_done_callback(finished)
    if not published.done():
        published.set_result(None)
    return task


__all__ = ["HostedLocalRuntimeV1"]
