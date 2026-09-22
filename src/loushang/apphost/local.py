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
        session_discovery: bool = False,
        session_execution: bool = False,
        mux_management: bool = False,
        connection_instance: str | None = None,
    ) -> None:
        if type(session_discovery) is not bool:
            raise TypeError("invalid discovery activation")
        if type(session_execution) is not bool or (session_execution and not application.execution_enabled):
            raise ValueError("execution deployment requires an admitted application capability")
        if type(mux_management) is not bool:
            raise TypeError("invalid managed Mux activation")
        if mux_management and (application.managed_mux_instance is None
                               or application.managed_mux_instance != connection_instance):
            raise ValueError("managed deployment requires its admitted application instance")
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
            discovery_scope_factory=application.open_client_scope if session_discovery else None,
            execution_scope_factory=application.open_client_scope if session_execution else None,
            managed_mux_scope_factory=application.open_client_scope if mux_management else None,
            mux_closure=mux_management and application.managed_mux_close_enabled,
            instance=connection_instance,
        )
        self._startup_timeout, self._timeout = startup_timeout, settlement_timeout
        self._start_task: asyncio.Task[None] | None = None
        self._activate_task: asyncio.Task[None] | None = None
        self._startup_deadline: float | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._phases: dict[str, asyncio.Task[None]] = {}
        self._reply: Awaitable[None] | None = None
        self._deadline: float | None = None
        self._stop_started = asyncio.Event()
        self._scopes_enabled = False
        self._prepared = False
        self._one_step = False
        self._closing = False
        self._settled = False

    @property
    def cleanup_pending(self) -> bool:
        return not self._settled

    @property
    def accepting(self) -> bool:
        """Current deployment readiness, revoked synchronously by stop."""
        task = self._activate_task
        return (
            self._scopes_enabled
            and not self._closing
            and task is not None
            and task.done()
            and not _failed(task)
        )

    async def start(self) -> None:
        """Original one-step entrypoint over the same two owned phases."""
        if self._one_step or self._closing or self._start_task is not None:
            raise HostedApplicationError("hosted_local_closed")
        self._one_step = True
        await self._prepare()
        await self._activate()

    async def prepare(self, *, deadline: float | None = None) -> None:
        """Prepare transport without enabling application client scopes."""
        if self._one_step:
            raise HostedApplicationError("hosted_local_closed")
        await self._prepare(deadline=deadline)

    async def _prepare(self, *, deadline: float | None = None) -> None:
        if self._start_task is not None or self._closing:
            raise HostedApplicationError("hosted_local_closed")
        if deadline is not None and (
            type(deadline) not in (int, float) or not 0 < deadline <= 1e12
        ):
            raise ValueError("invalid local startup deadline")
        self._startup_deadline = asyncio.get_running_loop().time() + self._startup_timeout
        if deadline is not None:
            self._startup_deadline = min(self._startup_deadline, deadline)
        try:
            self._remaining_startup()
            self._start_task = _spawn(self._start_once())
            done, _ = await asyncio.wait(
                {self._start_task}, timeout=self._remaining_startup()
            )
            if not done:
                raise HostedApplicationError("hosted_local_startup_timeout")
            await asyncio.shield(self._start_task)
            self._remaining_startup()
            if not self._prepared:
                raise HostedApplicationError("hosted_local_closed")
        except BaseException:
            await self.close()
            raise

    async def _start_once(self) -> None:
        self._remaining_startup()
        await self._server.prepare(deadline=self._startup_deadline)
        self._remaining_startup()
        self._prepared = True

    async def activate(self) -> None:
        """Enable scopes and publish transport only after explicit admission."""
        if self._one_step:
            raise HostedApplicationError("hosted_local_closed")
        await self._activate()

    async def _activate(self) -> None:
        if (self._closing or not self._prepared or self._activate_task is not None
                or self._start_task is None or not self._start_task.done() or _failed(self._start_task)):
            raise HostedApplicationError("hosted_local_closed")
        try:
            self._remaining_startup()
            self._activate_task = _spawn(self._activate_once())
            done, _ = await asyncio.wait(
                {self._activate_task}, timeout=self._remaining_startup()
            )
            if not done:
                raise HostedApplicationError("hosted_local_startup_timeout")
            await asyncio.shield(self._activate_task)
            self._remaining_startup()
            if not self.accepting:
                raise HostedApplicationError("hosted_local_closed")
        except BaseException:
            await self.close()
            raise

    def _remaining_startup(self) -> float:
        if self._closing or self._startup_deadline is None:
            raise HostedApplicationError("hosted_local_closed")
        remaining = self._startup_deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise HostedApplicationError("hosted_local_startup_timeout")
        return remaining

    async def _activate_once(self) -> None:
        self._remaining_startup()
        # Retain the scope fence even if enable partially fails.
        self._scopes_enabled = True
        self._application.enable_client_scopes()
        self._remaining_startup()
        await self._server.activate()
        self._remaining_startup()

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
        self._fence(reply)
        task = self._close_task
        if task is None or _failed(task):
            if retry_timeout is not None:
                self._deadline = asyncio.get_running_loop().time() + retry_timeout
            self._close_task = task = _spawn(self._close_once())
        return task

    def fence(self) -> None:
        """Synchronously revoke activation before an outer owner schedules close.

        This transfers no cleanup ownership and does not discard a stop reply.
        The adopting caller must still close and retain incomplete settlement.
        """
        self._fence(None)

    def _fence(self, reply: Awaitable[None] | None) -> None:
        if not self._closing:
            self._closing = True
            self._reply = reply
            self._deadline = asyncio.get_running_loop().time() + self._timeout
            self._server.fence()
            if self._scopes_enabled:
                self._application.fence_client_scopes()
            self._stop_started.set()

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
        if self._activate_task is not None:
            await _wait(self._activate_task, deadline, ignore_failure=True)
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
