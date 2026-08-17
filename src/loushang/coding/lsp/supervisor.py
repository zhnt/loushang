"""Session-scoped lazy LSP runtime ownership and startup single-flight."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass

from loushang.coding.lsp.catalog import LspCatalog
from loushang.coding.lsp.client import LspClient
from loushang.coding.lsp.diagnostics import DiagnosticInbox
from loushang.coding.lsp.model import (
    LspProtocolError,
    LspServerKey,
    LspServerSelection,
)
from loushang.coding.lsp.ports import (
    AuthorizedProcessLauncher,
    ProcessHandle,
    ProcessLaunchRequest,
)
from loushang.coding.lsp.status import (
    LspServerRuntimeState,
    LspServerRuntimeStatus,
    LspSessionStatus,
)

_MAX_RUNTIME_STATUS_RECORDS = 128


@dataclass(frozen=True, slots=True)
class LspRuntimeHandle:
    key: LspServerKey
    runtime_id: int
    client: LspClient


class LspServerSupervisor:
    """Own every LSP runtime created by one Coding capability binding."""

    def __init__(
        self,
        *,
        catalog: LspCatalog,
        launcher: AuthorizedProcessLauncher,
        baseline_environment: Mapping[str, str],
        open_document_count: Callable[[int], int] | None = None,
        release_runtime_documents: Callable[[int], None] | None = None,
        diagnostics: DiagnosticInbox | None = None,
    ) -> None:
        self._catalog = catalog
        self._launcher = launcher
        self._baseline_environment = dict(baseline_environment)
        self._runtimes: dict[LspServerKey, LspRuntimeHandle] = {}
        self._starts: dict[LspServerKey, asyncio.Task[LspRuntimeHandle]] = {}
        self._stops: dict[LspServerKey, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._next_runtime_id = 1
        self._disposed = False
        self._dispose_task: asyncio.Task[None] | None = None
        self._states: dict[LspServerKey, LspServerRuntimeState] = {}
        self._last_errors: dict[LspServerKey, str] = {}
        self._start_counts: dict[LspServerKey, int] = {}
        self._request_counts: dict[LspServerKey, int] = {}
        self._timeout_counts: dict[LspServerKey, int] = {}
        self._accepted_diagnostic_counts: dict[LspServerKey, int] = {}
        self._diagnostic_counts: dict[LspServerKey, int] = {}
        self._last_request_durations: dict[LspServerKey, float] = {}
        self._open_document_count = open_document_count or (lambda _runtime_id: 0)
        self._release_runtime_documents = release_runtime_documents or (
            lambda _runtime_id: None
        )
        self._diagnostics = diagnostics

    async def ensure_runtime(
        self,
        selection: LspServerSelection,
        *,
        correlation_id: str,
        signal: object | None = None,
    ) -> LspRuntimeHandle:
        key = LspServerKey(selection.definition_id, selection.workspace_root)
        async with self._lock:
            if self._disposed:
                raise LspProtocolError("LSP supervisor is disposed")
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
                    name=f"coding-lsp-start:{selection.definition_id}",
                )
                self._starts[key] = task

        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                async with self._lock:
                    if self._starts.get(key) is task:
                        self._starts.pop(key, None)

    async def stop(self, key: LspServerKey) -> bool:
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
                    name=f"coding-lsp-stop:{key.definition_id}",
                )
                self._stops[key] = stop_task
        await asyncio.shield(stop_task)
        return stopped

    def status(self) -> LspSessionStatus:
        """Return one read-only snapshot without starting or stopping a Server."""

        keys = set(self._states) | set(self._starts) | set(self._runtimes)
        servers: list[LspServerRuntimeStatus] = []
        for key in sorted(
            keys,
            key=lambda item: (item.definition_id, str(item.workspace_root)),
        ):
            runtime = self._runtimes.get(key)
            if key in self._starts:
                state: LspServerRuntimeState = "starting"
            elif runtime is not None and runtime.client.is_closed:
                state = "failed"
            elif runtime is not None:
                state = "ready"
            else:
                state = self._states.get(key, "stopped")
            client = runtime.client if runtime is not None else None
            request_count = self._request_counts.get(key, 0)
            timeout_count = self._timeout_counts.get(key, 0)
            accepted_diagnostic_count = self._accepted_diagnostic_counts.get(key, 0)
            diagnostic_count = self._diagnostic_counts.get(key, 0)
            last_duration = self._last_request_durations.get(key)
            if client is not None:
                request_count += client.request_count
                timeout_count += client.timeout_count
                accepted_diagnostic_count += client.accepted_diagnostic_publications
                diagnostic_count += client.discarded_diagnostic_publications
                if client.last_request_duration_ms is not None:
                    last_duration = client.last_request_duration_ms
            diagnostic_document_count = 0
            current_diagnostic_count = 0
            if (
                runtime is not None
                and state == "ready"
                and self._diagnostics is not None
            ):
                (
                    diagnostic_document_count,
                    current_diagnostic_count,
                ) = self._diagnostics.counts(runtime.runtime_id)
            last_error = self._last_errors.get(key)
            if state == "failed" and last_error is None:
                last_error = (
                    "connection_closed"
                    if client is not None and client.is_closed
                    else client.last_error
                    if client is not None
                    else "runtime_failed"
                )
            servers.append(
                LspServerRuntimeStatus(
                    definition_id=key.definition_id,
                    workspace_root=str(key.workspace_root),
                    state=state,
                    runtime_id=runtime.runtime_id if runtime is not None else None,
                    open_document_count=(
                        self._open_document_count(runtime.runtime_id)
                        if runtime is not None and state == "ready"
                        else 0
                    ),
                    request_count=request_count,
                    timeout_count=timeout_count,
                    replacement_count=max(self._start_counts.get(key, 0) - 1, 0),
                    accepted_diagnostic_publications=accepted_diagnostic_count,
                    discarded_diagnostic_publications=diagnostic_count,
                    diagnostic_document_count=diagnostic_document_count,
                    current_diagnostic_count=current_diagnostic_count,
                    last_request_duration_ms=last_duration,
                    last_error=last_error,
                )
            )
        return LspSessionStatus(disposed=self._disposed, servers=tuple(servers))

    async def dispose(self) -> None:
        async with self._lock:
            task = self._dispose_task
            if task is None:
                self._disposed = True
                task = asyncio.create_task(
                    self._dispose_all(),
                    name="coding-lsp-dispose",
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
        key: LspServerKey,
        *,
        start: asyncio.Task[LspRuntimeHandle] | None,
        runtime: LspRuntimeHandle | None,
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
        key: LspServerKey,
        *,
        runtime_id: int,
        correlation_id: str,
        signal: object | None,
    ) -> LspRuntimeHandle:
        definition = self._catalog.definition(key.definition_id)
        environment = dict(self._baseline_environment)
        environment.update(definition.environment)
        handle: ProcessHandle | None = None
        client: LspClient | None = None
        try:
            handle = await self._launcher.start(
                ProcessLaunchRequest(
                    command=definition.command,
                    cwd=str(key.workspace_root),
                    effective_environment=tuple(sorted(environment.items())),
                ),
                correlation_id=correlation_id,
                signal=signal,
            )
            client = LspClient(
                handle,
                request_timeout_seconds=definition.request_timeout_seconds,
                shutdown_timeout_seconds=definition.shutdown_timeout_seconds,
                settings=definition.settings,
                on_publish_diagnostics=(
                    lambda params: (
                        self._diagnostics is not None
                        and self._replace_diagnostics(
                            runtime_id=runtime_id,
                            server_id=key.definition_id,
                            params=params,
                        )
                    )
                ),
                on_close=lambda: self._release_diagnostics(runtime_id),
            )
            await client.initialize(
                root_uri=key.workspace_root.as_uri(),
                initialization_options=definition.initialization_options,
                timeout_seconds=definition.startup_timeout_seconds,
            )
            runtime = LspRuntimeHandle(
                key=key,
                runtime_id=runtime_id,
                client=client,
            )
            async with self._lock:
                if self._disposed:
                    raise LspProtocolError("LSP supervisor was disposed during startup")
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
            if client is not None:
                self._accumulate_client(key, client)
                self._release_runtime_documents(runtime_id)
            if self._diagnostics is not None:
                self._diagnostics.release_runtime(runtime_id)
            async with self._lock:
                if self._states.get(key) == "starting":
                    if isinstance(exc, asyncio.CancelledError) or self._disposed:
                        self._remember_state(key, "stopped")
                    else:
                        self._remember_state(key, "failed")
                        self._last_errors[key] = "initialization_failed"
            raise

    async def _shutdown_runtime(self, runtime: LspRuntimeHandle) -> None:
        try:
            await runtime.client.shutdown()
        finally:
            self._retire_runtime(runtime)

    def _retire_runtime(self, runtime: LspRuntimeHandle) -> None:
        self._accumulate_client(runtime.key, runtime.client)
        if self._diagnostics is not None:
            self._diagnostics.release_runtime(runtime.runtime_id)
        self._release_runtime_documents(runtime.runtime_id)

    def _replace_diagnostics(
        self,
        *,
        runtime_id: int,
        server_id: str,
        params: Mapping[str, object],
    ) -> bool:
        diagnostics = self._diagnostics
        if diagnostics is None:
            return False
        return diagnostics.replace_publication(
            runtime_id=runtime_id,
            server_id=server_id,
            uri=params.get("uri"),
            version=params.get("version"),
            diagnostics=params.get("diagnostics"),
        )

    def _release_diagnostics(self, runtime_id: int) -> None:
        if self._diagnostics is not None:
            self._diagnostics.release_runtime(runtime_id)

    def _accumulate_client(self, key: LspServerKey, client: LspClient) -> None:
        self._request_counts[key] = (
            self._request_counts.get(key, 0) + client.request_count
        )
        self._timeout_counts[key] = (
            self._timeout_counts.get(key, 0) + client.timeout_count
        )
        self._diagnostic_counts[key] = (
            self._diagnostic_counts.get(key, 0)
            + client.discarded_diagnostic_publications
        )
        self._accepted_diagnostic_counts[key] = (
            self._accepted_diagnostic_counts.get(key, 0)
            + client.accepted_diagnostic_publications
        )
        if client.last_request_duration_ms is not None:
            self._last_request_durations[key] = client.last_request_duration_ms

    def _remember_state(
        self,
        key: LspServerKey,
        state: LspServerRuntimeState,
    ) -> None:
        self._states.pop(key, None)
        self._states[key] = state
        while len(self._states) > _MAX_RUNTIME_STATUS_RECORDS:
            candidate = next(
                (
                    item
                    for item in self._states
                    if item != key
                    and item not in self._starts
                    and item not in self._stops
                    and item not in self._runtimes
                ),
                None,
            )
            if candidate is None:
                break
            self._states.pop(candidate, None)
            self._last_errors.pop(candidate, None)
            self._start_counts.pop(candidate, None)
            self._request_counts.pop(candidate, None)
            self._timeout_counts.pop(candidate, None)
            self._accepted_diagnostic_counts.pop(candidate, None)
            self._diagnostic_counts.pop(candidate, None)
            self._last_request_durations.pop(candidate, None)


__all__ = ["LspRuntimeHandle", "LspServerSupervisor"]
