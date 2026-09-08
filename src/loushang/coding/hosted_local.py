"""Trusted real Coding composition for the explicit detachable local profile."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path

from loushang.agent.types import StreamFn
from loushang.ai.model import Model, ModelSelection
from loushang.apphost.application import HostedApplicationError
from loushang.apphost.continuity import HostedApplicationContinuityRuntimeV1
from loushang.apphost.local import HostedLocalRuntimeV1
from loushang.appserver.framing import require_timeout
from loushang.appserver.local_record import (
    LocalConnectionDirectoryV1,
    LocalConnectionRecordV1,
    LocalRecordScopeV1,
)
from loushang.appserver.protocol.connection_profile import AppConnectionProfileV1
from loushang.harness.tools.core import ToolDefinition

from .hosted_bootstrap import CodingHostedLaunchV1, create_coding_hosted_attempt


@dataclass(frozen=True, slots=True)
class CodingLocalLaunchV1:
    application: CodingHostedLaunchV1
    connection_root: Path = field(repr=False)
    endpoint: str
    session_discovery: bool = field(default=False, kw_only=True)

    def __post_init__(self) -> None:
        if type(self.session_discovery) is not bool:
            raise TypeError("invalid discovery activation")
        root = self.connection_root
        if (
            type(self.application) is not CodingHostedLaunchV1
            or not isinstance(root, Path)
            or not root.is_absolute()
            or root != root.resolve()
            or not root.parent.is_dir()
            or self.application.workspace.is_relative_to(root)
        ):
            raise ValueError("invalid private connection root")
        for canonical in (
            self.application.application_root,
            self.application.cwd_sessions,
            self.application.home_sessions,
        ):
            if root.is_relative_to(canonical) or canonical.is_relative_to(root):
                raise ValueError("connection and durable roots must be separate")
        # Reuse the closed record's identity validation, without creating IO.
        LocalConnectionRecordV1(
            endpoint=self.endpoint,
            application_id=self.application.application_id,
            product_id="coding",
            instance="0" * 32,
            key=bytes(32),
            port=1,
            scopes=self.scopes,
        )

    @property
    def scopes(self) -> tuple[LocalRecordScopeV1, ...]:
        return tuple(
            LocalRecordScopeV1(scope.scope, scope.fingerprint)
            for scope in self.application.scopes
        )

    def describe(self) -> dict[str, object]:
        return {
            **self.application.describe(profile=(
                AppConnectionProfileV1.LOCAL_DISCOVERY if self.session_discovery
                else AppConnectionProfileV1.LOCAL
            )),
            "endpoint": self.endpoint,
        }


class CodingLocalCommandV1:
    """Own startup until the ready AppHost deployment adopts the application.

    Before handoff, retain the G13 attempt and any late application. Afterwards
    AppHost is the only application-stop owner; this wrapper must not reset its
    budget, close the application separately, or stop it on client EOF.
    """

    def __init__(
        self,
        launch: CodingLocalLaunchV1,
        *,
        model: Model | ModelSelection | None = None,
        stream_fn: StreamFn | None = None,
        tools: list[ToolDefinition] | None = None,
        startup_timeout: float = 30.0,
        settlement_timeout: float = 30.0,
    ) -> None:
        if type(launch) is not CodingLocalLaunchV1:
            raise TypeError("local command requires admitted launch facts")
        for timeout in (startup_timeout, settlement_timeout):
            _require_budget(timeout)
        self._launch = launch
        self._directory = LocalConnectionDirectoryV1(launch.connection_root)
        self._attempt = create_coding_hosted_attempt(
            launch.application, model=model, stream_fn=stream_fn, tools=tools,
            session_discovery=launch.session_discovery,
        )
        self._application: HostedApplicationContinuityRuntimeV1 | None = None
        self._local: HostedLocalRuntimeV1 | None = None
        self._startup_timeout, self._timeout = startup_timeout, settlement_timeout
        self._start_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._phases: dict[str, asyncio.Task[None]] = {}
        self._deadline: float | None = None
        self._closing = False
        self._settled = False

    @property
    def cleanup_pending(self) -> bool:
        return not self._settled

    async def start(self) -> None:
        if self._closing or self._start_task is not None:
            raise HostedApplicationError("coding_local_closed")
        self._start_task = _spawn(self._start_once())
        try:
            done, _ = await asyncio.wait(
                {self._start_task}, timeout=self._startup_timeout
            )
            if not done:
                raise HostedApplicationError("coding_local_startup_timeout")
            await asyncio.shield(self._start_task)
            if self._closing or self._local is None or not self._local.accepting:
                raise HostedApplicationError("coding_local_closed")
        except BaseException:
            await self.close()
            raise

    async def _start_once(self) -> None:
        if self._closing:
            raise HostedApplicationError("coding_local_closed")
        self._application = await self._attempt.open()
        if self._closing:
            raise HostedApplicationError("coding_local_closed")
        self._local = HostedLocalRuntimeV1(
            self._application,
            self._directory,
            self._launch.endpoint,
            scopes=self._launch.scopes,
            settlement_timeout=self._timeout,
            session_discovery=self._launch.session_discovery,
        )
        self._application = None  # AppHost has adopted both application and directory.
        await self._local.start()

    async def wait_closed(self) -> None:
        if self._local is None:
            raise HostedApplicationError("coding_local_not_ready")
        await self._local.wait_closed()
        await self.close()

    async def run(self, *, ready: Callable[[], None] | None = None) -> None:
        try:
            await self.start()
            if ready is not None:
                ready()
            await self.wait_closed()
        finally:
            await self.close()

    async def close(self, *, retry_timeout: float | None = None) -> None:
        if retry_timeout is not None:
            _require_budget(retry_timeout)
        if self._settled:
            return
        self._closing = True
        if self._deadline is None:
            self._deadline = asyncio.get_running_loop().time() + self._timeout
        task = self._close_task
        if task is None or _failed(task):
            if retry_timeout is not None:
                self._deadline = asyncio.get_running_loop().time() + retry_timeout
            task = self._close_task = _spawn(self._close_once(retry_timeout))
        await asyncio.shield(task)

    async def _close_once(self, retry_timeout: float | None) -> None:
        assert self._deadline is not None
        if self._local is not None:
            # Do not await the outer startup task first: it can itself be
            # waiting for this adopted deployment's start/close settlement.
            await self._local.close(retry_timeout=retry_timeout)
        if self._start_task is not None:
            await _wait(self._start_task, self._deadline, ignore_failure=True)
        if self._local is None:
            self._directory.close()
            await self._phase(
                "application",
                self._application.close
                if self._application is not None
                else self._attempt.close,
            )
        self._settled = True

    async def _phase(
        self, name: str, operation: Callable[[], Coroutine[object, object, None]]
    ) -> None:
        assert self._deadline is not None
        task = self._phases.get(name)
        if task is None or _failed(task):
            if asyncio.get_running_loop().time() >= self._deadline:
                raise HostedApplicationError("coding_local_cleanup_incomplete")
            task = self._phases[name] = _spawn(operation())
        await _wait(task, self._deadline)


def _require_budget(value: float) -> None:
    require_timeout(value)
    if value > 30:
        raise ValueError("Coding local budget exceeds profile bound")


def _failed(task: asyncio.Task[None]) -> bool:
    return task.done() and (task.cancelled() or task.exception() is not None)


async def _wait(
    task: asyncio.Task[None], deadline: float, *, ignore_failure: bool = False
) -> None:
    if not task.done():
        await asyncio.wait(
            {task}, timeout=max(0, deadline - asyncio.get_running_loop().time())
        )
    if not task.done() or (not ignore_failure and _failed(task)):
        raise HostedApplicationError("coding_local_cleanup_incomplete")


def _spawn(work: Coroutine[object, object, None]) -> asyncio.Task[None]:
    published = asyncio.get_running_loop().create_future()

    async def invoke() -> None:
        await published
        await work

    def finished(task: asyncio.Task[None]) -> None:
        work.close()
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


__all__ = ["CodingLocalLaunchV1", "CodingLocalCommandV1"]
