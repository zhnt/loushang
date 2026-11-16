"""Authorized process/client lifetime base for protocol-specific subclasses.

Subclasses bind domain data, client construction and a single protocol handshake;
this owner retains actual starts/stops/runtimes and executes all resource cleanup.
There is no task-pool mode grammar, retry policy or implicit authorization.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Hashable
from contextlib import suppress
from typing import ClassVar, Generic, Literal, Protocol, TypeVar

from .types import AuthorizedProcessLauncher, ProcessHandle, ProcessLaunchRequest


class _ProcessClient(Protocol):
    @property
    def is_closed(self) -> bool: ...
    async def abort(self) -> None: ...
    async def shutdown(self) -> None: ...


class _ClientRuntime(Protocol):
    @property
    def client(self) -> _ProcessClient: ...


KeyT = TypeVar("KeyT", bound=Hashable)
RuntimeT = TypeVar("RuntimeT", bound=_ClientRuntime)
InputsT = TypeVar("InputsT")
ClientT = TypeVar("ClientT", bound=_ProcessClient)
ProcessClientState = Literal["starting", "ready", "stopped", "failed"]


class ProcessClientSupervisor(Generic[KeyT, RuntimeT, InputsT, ClientT]):
    _launcher: AuthorizedProcessLauncher
    _disposed_message: ClassVar[str]
    _startup_disposed_message: ClassVar[str]
    _dispose_task_name: ClassVar[str]

    def __init__(self) -> None:
        self._runtimes: dict[KeyT, RuntimeT] = {}
        self._starts: dict[KeyT, asyncio.Task[RuntimeT]] = {}
        self._stops: dict[KeyT, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._next_runtime_id = 1
        self._disposed = False
        self._dispose_task: asyncio.Task[None] | None = None
        self._states: dict[KeyT, ProcessClientState] = {}
        self._last_errors: dict[KeyT, str] = {}
        self._start_counts: dict[KeyT, int] = {}

    def _supervision_error(self, message: str) -> Exception:
        raise NotImplementedError

    def _startup_inputs(self, key: KeyT) -> InputsT:
        raise NotImplementedError

    def _launch_request(self, key: KeyT, inputs: InputsT) -> ProcessLaunchRequest:
        raise NotImplementedError

    def _new_client(
        self, handle: ProcessHandle, key: KeyT, runtime_id: int, inputs: InputsT
    ) -> ClientT:
        raise NotImplementedError

    async def _initialize_client(
        self, client: ClientT, key: KeyT, inputs: InputsT
    ) -> None:
        raise NotImplementedError

    def _runtime_record(self, key: KeyT, runtime_id: int, client: ClientT) -> RuntimeT:
        raise NotImplementedError

    def _retire_failed_client(
        self, key: KeyT, runtime_id: int, client: ClientT | None
    ) -> None:
        raise NotImplementedError

    def _retire_runtime(self, runtime: RuntimeT) -> None:
        raise NotImplementedError

    def _remember_state(self, key: KeyT, state: ProcessClientState) -> None:
        raise NotImplementedError

    def _stop_task_name(self, key: KeyT) -> str:
        raise NotImplementedError

    async def _ensure_process_runtime(
        self,
        key: KeyT,
        *,
        correlation_id: str,
        signal: object | None = None,
        task_name: Callable[[], str],
    ) -> RuntimeT:
        async with self._lock:
            if self._disposed:
                raise self._supervision_error(self._disposed_message)
            current = self._runtimes.get(key)
            if current is not None and not current.client.is_closed:
                return current
            if current is not None:
                self._runtimes.pop(key, None)
                self._retire_runtime(current)
                self._remember_state(key, "failed")
                self._last_errors[key] = "connection_closed"
            task = self._starts.get(key)
            if task is None:
                runtime_id = self._next_runtime_id
                self._next_runtime_id += 1
                self._start_counts[key] = self._start_counts.get(key, 0) + 1
                self._remember_state(key, "starting")
                task = asyncio.create_task(
                    self._start_runtime(
                        key,
                        runtime_id=runtime_id,
                        correlation_id=correlation_id,
                        signal=signal,
                    ),
                    name=task_name(),
                )
                self._starts[key] = task

        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                async with self._lock:
                    if self._starts.get(key) is task:
                        self._starts.pop(key, None)

    async def _stop_process_runtime(self, key: KeyT) -> bool:
        async with self._lock:
            if self._disposed:
                return False
            existing_stop = self._stops.get(key)
            if existing_stop is not None:
                stop_task = existing_stop
                stopped = True
            else:
                runtime = self._runtimes.pop(key, None)
                start = self._starts.pop(key, None)
                stopped = runtime is not None or start is not None
                if not stopped:
                    if key in self._states:
                        self._remember_state(key, "stopped")
                        self._last_errors.pop(key, None)
                    return False
                self._remember_state(key, "stopped")
                self._last_errors.pop(key, None)
                stop_task = asyncio.create_task(
                    self._stop_owned_runtime(
                        key,
                        start=start,
                        runtime=runtime,
                    ),
                    name=self._stop_task_name(key),
                )
                self._stops[key] = stop_task
        await asyncio.shield(stop_task)
        return stopped

    async def dispose(self) -> None:
        async with self._lock:
            task = self._dispose_task
            if task is None:
                self._disposed = True
                task = asyncio.create_task(
                    self._dispose_all(),
                    name=self._dispose_task_name,
                )
                self._dispose_task = task
        await asyncio.shield(task)

    async def _dispose_all(self) -> None:
        async with self._lock:
            starts = tuple(self._starts.values())
            stops = tuple(self._stops.values())
            runtimes = tuple(self._runtimes.values())
            for key in set(self._states) | set(self._starts) | set(self._runtimes):
                self._remember_state(key, "stopped")
                self._last_errors.pop(key, None)
            self._starts.clear()
            self._stops.clear()
            self._runtimes.clear()
        for task in starts:
            task.cancel()
        if starts:
            await asyncio.gather(*starts, return_exceptions=True)
        if stops or runtimes:
            results = await asyncio.gather(
                *stops,
                *(self._shutdown_runtime(runtime) for runtime in runtimes),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result

    async def _stop_owned_runtime(
        self,
        key: KeyT,
        *,
        start: asyncio.Task[RuntimeT] | None,
        runtime: RuntimeT | None,
    ) -> None:
        try:
            if start is not None:
                start.cancel()
                await asyncio.gather(start, return_exceptions=True)
            if runtime is not None:
                await self._shutdown_runtime(runtime)
        finally:
            async with self._lock:
                if self._stops.get(key) is asyncio.current_task():
                    self._stops.pop(key, None)

    async def _start_runtime(
        self,
        key: KeyT,
        *,
        runtime_id: int,
        correlation_id: str,
        signal: object | None,
    ) -> RuntimeT:
        inputs = self._startup_inputs(key)
        handle: ProcessHandle | None = None
        client: ClientT | None = None
        try:
            handle = await self._launcher.start(
                self._launch_request(key, inputs),
                correlation_id=correlation_id,
                signal=signal,
            )
            client = self._new_client(handle, key, runtime_id, inputs)
            await self._initialize_client(client, key, inputs)
            runtime = self._runtime_record(key, runtime_id, client)
            async with self._lock:
                if self._disposed:
                    raise self._supervision_error(self._startup_disposed_message)
                self._runtimes[key] = runtime
                self._remember_state(key, "ready")
                self._last_errors.pop(key, None)
            return runtime
        except BaseException as exc:
            with suppress(BaseException):
                if client is not None:
                    await client.abort()
                elif handle is not None:
                    await handle.close()
            self._retire_failed_client(key, runtime_id, client)
            async with self._lock:
                if self._states.get(key) == "starting":
                    if isinstance(exc, asyncio.CancelledError) or self._disposed:
                        self._remember_state(key, "stopped")
                    else:
                        self._remember_state(key, "failed")
                        self._last_errors[key] = "initialization_failed"
            raise

    async def _shutdown_runtime(self, runtime: RuntimeT) -> None:
        try:
            await runtime.client.shutdown()
        finally:
            self._retire_runtime(runtime)
