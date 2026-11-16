"""Session-scoped lazy LSP runtime ownership and startup single-flight."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from loushang.coding.lsp.catalog import LspCatalog
from loushang.coding.lsp.client import LspClient
from loushang.coding.lsp.diagnostics import DiagnosticInbox
from loushang.coding.lsp.model import (
    LspProtocolError,
    LspServerDefinition,
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
from loushang.harness.workspace.process.supervision import ProcessClientSupervisor

_MAX_RUNTIME_STATUS_RECORDS = 128


@dataclass(frozen=True, slots=True)
class LspRuntimeHandle:
    key: LspServerKey
    runtime_id: int
    client: LspClient


class LspServerSupervisor(
    ProcessClientSupervisor[
        LspServerKey,
        LspRuntimeHandle,
        tuple[LspServerDefinition, dict[str, str]],
        LspClient,
    ]
):
    """Own every LSP runtime created by one Coding capability binding."""

    _disposed_message = "LSP supervisor is disposed"
    _startup_disposed_message = "LSP supervisor was disposed during startup"
    _dispose_task_name = "coding-lsp-dispose"

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
        super().__init__()
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
        return await self._ensure_process_runtime(
            key,
            correlation_id=correlation_id,
            signal=signal,
            task_name=lambda: f"coding-lsp-start:{selection.definition_id}",
        )

    async def stop(self, key: LspServerKey) -> bool:
        return await self._stop_process_runtime(key)

    def _stop_task_name(self, key: LspServerKey) -> str:
        return f"coding-lsp-stop:{key.definition_id}"

    def _supervision_error(self, message: str) -> LspProtocolError:
        return LspProtocolError(message)

    def _startup_inputs(
        self, key: LspServerKey
    ) -> tuple[LspServerDefinition, dict[str, str]]:
        definition = self._catalog.definition(key.definition_id)
        environment = dict(self._baseline_environment)
        environment.update(definition.environment)
        return definition, environment

    def _launch_request(
        self, key: LspServerKey, inputs: tuple[LspServerDefinition, dict[str, str]]
    ) -> ProcessLaunchRequest:
        definition, environment = inputs
        return ProcessLaunchRequest(
            command=definition.command,
            cwd=str(key.workspace_root),
            effective_environment=tuple(sorted(environment.items())),
        )

    def _new_client(
        self,
        handle: ProcessHandle,
        key: LspServerKey,
        runtime_id: int,
        inputs: tuple[LspServerDefinition, dict[str, str]],
    ) -> LspClient:
        definition, _ = inputs
        return LspClient(
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

    async def _initialize_client(
        self,
        client: LspClient,
        key: LspServerKey,
        inputs: tuple[LspServerDefinition, dict[str, str]],
    ) -> None:
        definition, _ = inputs
        await client.initialize(
            root_uri=key.workspace_root.as_uri(),
            initialization_options=definition.initialization_options,
            timeout_seconds=definition.startup_timeout_seconds,
        )

    def _runtime_record(
        self, key: LspServerKey, runtime_id: int, client: LspClient
    ) -> LspRuntimeHandle:
        return LspRuntimeHandle(key=key, runtime_id=runtime_id, client=client)

    def _retire_failed_client(
        self, key: LspServerKey, runtime_id: int, client: LspClient | None
    ) -> None:
        if client is not None:
            self._accumulate_client(key, client)
            self._release_runtime_documents(runtime_id)
        if self._diagnostics is not None:
            self._diagnostics.release_runtime(runtime_id)

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
