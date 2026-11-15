"""Fixed managed-command resource lifetime over existing admitted owners.

This private base is configured by a Product CLI subclass. It owns the original
same-object resource anchors and retirement barrier, never a second command or
Task engine. CLI qualification and presentation remain in the subclass.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar, Generic, Protocol, TextIO, TypeAlias, TypeVar

from loushang.apphost.managed._files import (
    ManagedStorageError,
    PrivateManagedDirectory,
    _check_deadline,
)
from loushang.apphost.managed.connection import (
    ManagedConnectionLeaseV1,
    _settled_native,
)
from loushang.apphost.managed.coordinator import ManagedServiceCoordinatorV1
from loushang.apphost.managed.defaults import ManagedDefaultsV1
from loushang.apphost.managed.lifecycle import (
    ManagedServiceJournalV1,
    ManagedServiceStateV1,
)
from loushang.apphost.managed.mux_creation import ManagedMuxCreateOperationV1
from loushang.apphost.managed.mux_management import (
    ManagedMuxInspectionV1,
    ManagedMuxManagerV1,
)
from loushang.apphost.managed.mux_probe import (
    ManagedMuxProbeOperationV1,
    ManagedMuxProbeSnapshotV1,
)
from loushang.apphost.managed.namespace_admission import ManagedNamespaceAdmissionV1
from loushang.apphost.managed.registry import (
    ManagedMuxCreationInspectionV1,
    ManagedMuxReservationV1,
    ManagedServiceAliasReservationV1,
)
from loushang.apphost.managed.service_admission import ManagedServiceAdmissionV1
from loushang.apphost.managed.stopper import (
    ManagedServiceStopOperationV1,
    _ManagedServiceStopBatch,
)
from loushang.appserver.managed_mux_close import (
    ManagedMuxCloseStateV1,
    ManagedMuxCloseV1,
)
from loushang.appserver.protocol import (
    MuxReadV1,
    MuxSelectorV1,
    SessionScopeV1,
    WorkspaceRequestV1,
)


class _ManagedShell(Protocol):
    async def close(self) -> None: ...


ShellT = TypeVar("ShellT", bound=_ManagedShell)
_ShellArg = TypeVar("_ShellArg", bound=_ManagedShell, contravariant=True)
_ShellFactory: TypeAlias = Callable[
    [ManagedConnectionLeaseV1, MuxSelectorV1, tuple[tuple[SessionScopeV1, str], ...]],
    ShellT,
]


class _TerminalRunner(Protocol[_ShellArg]):
    async def __call__(
        self,
        shell: _ShellArg,
        *,
        stdin: TextIO,
        stdout: TextIO,
        startup_deadline: float,
    ) -> int: ...


class _ManagedMuxCommandLifecycle(Generic[ShellT]):
    defaults: ManagedDefaultsV1
    stdin: TextIO
    stdout: TextIO
    _managed_product_id: ClassVar[str]

    def __init__(self) -> None:
        self.namespace: ManagedNamespaceAdmissionV1 | None = None
        self.service: ManagedServiceAdmissionV1 | None = None
        self.journal: ManagedServiceJournalV1 | None = None
        self.log_directory: PrivateManagedDirectory | None = None
        self.creation: ManagedMuxCreateOperationV1 | None = None
        self.creation_recovery = False
        self.creation_reservation: ManagedMuxReservationV1 | None = None
        self.starter: ManagedServiceCoordinatorV1 | None = None
        self.alias_reservation: ManagedServiceAliasReservationV1 | None = None
        self.stopper: ManagedServiceStopOperationV1 | None = None
        self.stop_all: _ManagedServiceStopBatch | None = None
        self.connection: ManagedConnectionLeaseV1 | None = None
        self.shell: ShellT | None = None
        self.target: str | None = None
        self.workspace: Path | None = None
        self.mux_space_id: str | None = None
        self.close_manager: ManagedMuxManagerV1 | None = None
        self.close_inspection: ManagedMuxInspectionV1 | None = None
        self.close_reservation: ManagedMuxReservationV1 | None = None
        self.close_operation: str | None = None
        self.close_instance_id: str | None = None
        self.close_request: ManagedMuxCloseV1 | None = None
        self.close_result: ManagedMuxCloseStateV1 | None = None
        self.close_readonly = self.close_continue = self.close_by_name = False
        self.deadline = 0.0
        self.active = False
        self.native_closed = False
        self.trace_deadline_ms: int | None = None
        self.result_status = 0
        self.probe: ManagedMuxProbeOperationV1 | None = None
        self.probe_result: ManagedMuxProbeSnapshotV1 | None = None
        self.probe_entered = False
        self.probed_mux_id: str | None = None

    @property
    def _managed_application_id(self) -> str:
        raise NotImplementedError

    @property
    def _managed_endpoint(self) -> str:
        raise NotImplementedError

    def _emit_value(self, value: object) -> None:
        raise NotImplementedError

    def _ready_value(self, ready: ManagedConnectionLeaseV1) -> dict[str, object]:
        raise NotImplementedError

    def _stopped_value(self, state: ManagedServiceStateV1) -> dict[str, object]:
        raise NotImplementedError

    def _new_trace_value(
        self, deadline_ms: int | None, operation_id: str
    ) -> dict[str, object]:
        raise NotImplementedError

    def _trace_failure_value(self, value: dict[str, object], code: str) -> None:
        raise NotImplementedError

    def _apply_trace_value(
        self, result: dict[str, object], value: dict[str, object]
    ) -> None:
        raise NotImplementedError

    def _creation_output(
        self, status: str, inspection: ManagedMuxCreationInspectionV1 | None = None
    ) -> None:
        raise NotImplementedError

    def _close_output(
        self, status: str, *, reconciled: bool = False, historical: bool = False
    ) -> None:
        raise NotImplementedError

    def _bind_shell(self) -> _ShellFactory[ShellT]:
        raise NotImplementedError

    def _bind_terminal_runner(self) -> _TerminalRunner[ShellT]:
        raise NotImplementedError

    def _execute_probe(self) -> int:
        raise NotImplementedError

    @property
    def cleanup_pending(self) -> bool:
        return self.active or not self.native_closed

    def finish_native_if_idle(self) -> bool:
        # Runner.run can reject before entering our coroutine/finally. In that
        # case no async borrower exists, but synchronous admission still owns IO.
        if not self.active:
            try:
                self.close_native()
            except BaseException:
                return True
        return self.cleanup_pending

    async def _run_close(self) -> None:
        assert self.connection is not None and self.close_manager is not None
        assert (
            self.close_inspection is not None
            and self.close_reservation is not None
            and self.close_operation is not None
        )
        manager, inspection, reservation = (
            self.close_manager,
            self.close_inspection,
            self.close_reservation,
        )
        operation = self.close_operation
        await self.connection.prepare(deadline=self.deadline)
        if self.connection.application_id != self._managed_application_id:
            raise ManagedStorageError("conflict")
        client = self.connection.managed_mux_close_client
        if client is None:
            raise ManagedStorageError("unavailable")
        # Recheck the frozen target/permission, not a later name selection.
        current = await _settled_native(
            lambda: (
                manager.inspect_mux(
                    reservation, deadline=self.deadline, wait_for_lock=True
                )
                if self.close_by_name
                else manager.inspect_close_operation(
                    operation, deadline=self.deadline, wait_for_lock=True
                )
            )
        )
        if (
            current.creation != inspection.creation
            or current.close_request != inspection.close_request
        ):
            raise ManagedStorageError("conflict")
        request = inspection.close_request
        if not self.close_readonly:
            request = await _settled_native(
                lambda: manager.issue_close(
                    reservation,
                    operation_id=operation,
                    deadline=self.deadline,
                    wait_for_lock=True,
                )
            )
        assert request is not None
        self.close_request = request
        _check_deadline(self.deadline)
        async with asyncio.timeout_at(self.deadline):
            # At most one RPC effect per explicit invocation. A status query or
            # ordinary rejoin never interprets None as permission to replay.
            result = (
                await client.close_managed_mux(request)
                if not self.close_readonly
                and (inspection.close_request is None or self.close_continue)
                else await client.read_managed_mux_close(request)
            )
        _check_deadline(self.deadline)
        if result is None:
            self._close_output("unknown")
            raise ManagedStorageError("unavailable")
        await _settled_native(
            lambda: manager.verify_close_result(
                request, result, deadline=self.deadline, wait_for_lock=True
            )
        )
        self.close_result = result
        _check_deadline(self.deadline)
        if not self.close_readonly:
            self._close_output(result.phase.value)
            await _settled_native(
                lambda: manager.record_close(
                    request, result, deadline=self.deadline, wait_for_lock=True
                )
            )
        _check_deadline(self.deadline)
        self._close_output(result.phase.value, reconciled=not self.close_readonly)

    async def _run_probe(self) -> None:
        assert self.probe is not None
        self.probe_entered = True
        try:
            self.probe_result = await self.probe.run()
        finally:
            await self.probe.close()

    def _probe_pending(self) -> bool:
        assert self.probe is not None
        if not self.probe_entered:
            self.probe.close_unstarted()
        return self.probe.cleanup_pending

    def _probe_snapshot(self) -> ManagedMuxProbeSnapshotV1:
        assert self.namespace is not None
        if self.probe is not None and self.probe.cleanup_pending:
            raise ManagedStorageError("busy")
        self.probe_entered = False
        self.probe_result = None
        self.probe = ManagedMuxProbeOperationV1(
            self.namespace.registry,
            self.defaults.namespace,
            product_id=self._managed_product_id,
            runtime_root=str(self.defaults.platform.runtime),
            endpoint=self._managed_endpoint,
            expected_application_id=self._managed_application_id,
            deadline=self.deadline,
        )
        status = self._execute_probe()
        if status or self.probe_result is None:
            raise ManagedStorageError("unavailable")
        return self.probe_result

    async def run(self) -> None:
        self.active = True
        try:
            if self.stop_all is not None:
                await self.stop_all.run()
                return
            if self.close_manager is not None:
                await self._run_close()
                return
            if self.stopper is not None:
                state = await self.stopper.run(deadline=self.deadline)
                self._emit_value(self._stopped_value(state))
                return
            if self.starter is not None:
                ready = await self.starter.ensure_started(deadline=self.deadline)
                if ready.application_id != self._managed_application_id:
                    raise ManagedStorageError("conflict")
                result = self._ready_value(ready)
                if self.trace_deadline_ms is not None:
                    trace_result = self._new_trace_value(
                        self.trace_deadline_ms, self.starter.operation_id
                    )
                    try:
                        trace_result[
                            "status"
                        ] = await self.starter.observe_requested_trace(
                            deadline=self.deadline
                        )
                    except ManagedStorageError as error:
                        trace_result.update(
                            status="observation_failed", errorCode=error.code
                        )
                    except Exception:
                        self._trace_failure_value(trace_result, "unavailable")
                    self._apply_trace_value(result, trace_result)
                self._emit_value(result)
                return
            if self.creation is not None:
                created = await self.creation.run(deadline=self.deadline)
                if self.creation_recovery:
                    assert self.creation_reservation is not None
                    self._creation_output(
                        "created",
                        ManagedMuxCreationInspectionV1(
                            self.creation_reservation, True, created
                        ),
                    )
                    return
                connection = self.creation.connection
                selector = MuxSelectorV1(mux_space_id=created.mux_space_id)
            else:
                assert self.connection is not None
                await self.connection.prepare(deadline=self.deadline)
                connection = self.connection
                assert self.mux_space_id is not None
                selector = MuxSelectorV1(mux_space_id=self.mux_space_id)
            if connection.application_id != self._managed_application_id:
                raise ManagedStorageError("conflict")
            make_shell = self._bind_shell()
            run_hosted_mux_shell = self._bind_terminal_runner()

            scopes: tuple[tuple[SessionScopeV1, str], ...] = ()
            if self.creation is None:
                mux = await connection.client.read_mux(MuxReadV1(selector))
                scopes = tuple(
                    dict.fromkeys(
                        (m.session.scope, m.session.scope_fingerprint)
                        for m in mux.members
                    )
                )
            if not scopes:
                if self.workspace is not None:
                    # Register without provisioning a separate GUI Mux.
                    registered = await connection.client.workspace(
                        WorkspaceRequestV1("register", str(self.workspace))
                    )
                    workspaces = tuple(
                        item
                        for item in registered.workspaces
                        if Path(item.path) == self.workspace
                    )
                else:
                    workspaces = (
                        await connection.client.workspace(WorkspaceRequestV1("list"))
                    ).workspaces
                if len(workspaces) != 1:
                    raise ManagedStorageError("unavailable")
                scopes = tuple(
                    (item.scope, item.scope_fingerprint) for item in workspaces
                )
            self.shell = make_shell(connection, selector, scopes)
            status = await run_hosted_mux_shell(
                self.shell,
                stdin=self.stdin,
                stdout=self.stdout,
                startup_deadline=self.deadline,
            )
            if status:
                raise ManagedStorageError("unavailable")
        finally:
            try:
                if self.shell is not None:
                    await self.shell.close()
            finally:
                if self.stop_all is not None:
                    await self.stop_all.close()
                elif self.stopper is not None:
                    await self.stopper.close()
                elif self.starter is not None:
                    await self.starter.close()
                elif self.creation is not None:
                    await self.creation.close()
                elif self.connection is not None:
                    await self.connection.close()
            self.active = False
            self.close_native()

    def close_native(self) -> None:
        if self.active:
            raise ManagedStorageError("busy")
        if self.probe is not None and self.probe.cleanup_pending:
            raise ManagedStorageError("busy")
        if self.stop_all is not None and self.stop_all.cleanup_pending:
            raise ManagedStorageError("busy")
        if self.log_directory is not None:
            self.log_directory.close()
            self.log_directory = None
        if self.service is not None:
            self.service.close()
            self.service = None
            self.journal = None  # borrowed from the service owner
        elif self.journal is not None:
            self.journal.close()
            self.journal = None
        if self.namespace is not None:
            self.namespace.close()
            self.namespace = None
        self.native_closed = True
