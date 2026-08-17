"""Internal local transport and spawn seam for Process Hosting."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import NoReturn, Protocol, cast

from loushang.harness.workspace._local_process import (
    kill_local_process_tree,
    spawn_local_process,
)

from .types import ProcessLaunchRequest


class ProcessReader(Protocol):
    async def read(self, max_bytes: int = -1) -> bytes: ...


class ProcessWriter(Protocol):
    def write(self, data: bytes) -> None: ...

    async def drain(self) -> None: ...

    def close(self) -> None: ...

    async def wait_closed(self) -> None: ...


class ProcessTransport(Protocol):
    @property
    def pid(self) -> int | None: ...

    @property
    def returncode(self) -> int | None: ...

    @property
    def stdin(self) -> ProcessWriter | None: ...

    @property
    def stdout(self) -> ProcessReader | None: ...

    @property
    def stderr(self) -> ProcessReader | None: ...

    async def wait(self) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


SpawnAttachment = Callable[[ProcessTransport], None]
ContainmentClose = Callable[[], Awaitable[None] | None]


class ProcessContainmentPlan:
    """Internal spawn material plus one idempotent lifetime cleanup."""

    def __init__(
        self,
        request: ProcessLaunchRequest,
        *,
        close: ContainmentClose | None = None,
    ) -> None:
        if not isinstance(request, ProcessLaunchRequest):
            raise TypeError("containment plan requires ProcessLaunchRequest")
        if close is not None and not callable(close):
            raise TypeError("containment plan close callback must be callable")
        self.request = request
        self._close_callback = close
        self._close_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None

    async def close(self) -> None:
        async with self._close_lock:
            task = self._close_task
            if task is None:
                task = asyncio.create_task(
                    self._close_owned(),
                    name="harness-process-containment-close",
                )
                self._close_task = task
        await asyncio.shield(task)

    async def _close_owned(self) -> None:
        if self._close_callback is None:
            return
        result = self._close_callback()
        if inspect.isawaitable(result):
            await result


class ProcessContainmentPlanner(Protocol):
    async def __call__(
        self,
        request: ProcessLaunchRequest,
    ) -> ProcessContainmentPlan: ...


class ProcessSpawner(Protocol):
    async def __call__(
        self,
        request: ProcessLaunchRequest,
        *,
        on_spawn: SpawnAttachment,
    ) -> ProcessTransport: ...


class LocalProcessSpawner:
    """Spawn locally while making cancellation after OS creation recoverable."""

    async def __call__(
        self,
        request: ProcessLaunchRequest,
        *,
        on_spawn: SpawnAttachment,
    ) -> ProcessTransport:
        spawn_task = cast(
            "asyncio.Task[ProcessTransport]",
            asyncio.create_task(
                spawn_local_process(
                    command=request.command,
                    cwd=request.cwd,
                    environment=dict(request.effective_environment),
                    pipe_stdin=True,
                ),
                name="harness-local-process-spawn",
            ),
        )
        try:
            process = await asyncio.shield(spawn_task)
        except asyncio.CancelledError as cancelled:
            await _reclaim_spawn_before_propagating_cancellation(
                spawn_task,
                on_spawn=on_spawn,
                cancellation=cancelled,
            )
        try:
            on_spawn(process)
        except BaseException:
            await kill_local_process_tree(process)
            await process.wait()
            raise
        return process


async def _reclaim_spawn_before_propagating_cancellation(
    spawn_task: asyncio.Task[ProcessTransport],
    *,
    on_spawn: SpawnAttachment,
    cancellation: asyncio.CancelledError,
) -> NoReturn:
    while True:
        try:
            process = await asyncio.shield(spawn_task)
            break
        except asyncio.CancelledError:
            if not spawn_task.done():
                continue
            try:
                process = spawn_task.result()
            except BaseException as exc:
                raise cancellation from exc
            break
        except BaseException as exc:
            raise cancellation from exc

    try:
        on_spawn(process)
    except BaseException as exc:
        attachment_error: BaseException | None = exc
    else:
        attachment_error = None

    await kill_local_process_tree(process)
    wait_task = asyncio.create_task(
        process.wait(),
        name="harness-cancelled-local-process-wait",
    )
    while True:
        try:
            await asyncio.shield(wait_task)
            break
        except asyncio.CancelledError:
            if not wait_task.done():
                continue
            try:
                wait_task.result()
            except BaseException as exc:
                raise cancellation from exc
            break
        except BaseException as exc:
            raise cancellation from exc
    if attachment_error is not None:
        raise cancellation from attachment_error
    raise cancellation


__all__ = [
    "LocalProcessSpawner",
    "ProcessContainmentPlan",
    "ProcessContainmentPlanner",
    "ProcessReader",
    "ProcessSpawner",
    "ProcessTransport",
    "ProcessWriter",
    "SpawnAttachment",
]
