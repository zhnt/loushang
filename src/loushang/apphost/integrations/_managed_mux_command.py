"""Prepare, execute and settle managed commands on the same resource owners.

The Product CLI supplies argument qualification, confirmation and launch policy.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from secrets import token_hex
from time import monotonic
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
from loushang.apphost.managed.contracts import (
    ManagedContractError,
    ManagedInstanceRefV1,
    ManagedServiceKeyV1,
)
from loushang.apphost.managed.coordinator import ManagedServiceCoordinatorV1
from loushang.apphost.managed.defaults import ManagedDefaultsV1
from loushang.apphost.managed.discovery import (
    ManagedDiscoverySnapshotV1,
    ManagedDiscoveryV1,
    ManagedMuxObservationV1,
    ManagedServiceObservationV1,
)
from loushang.apphost.managed.event_log import ManagedLifecycleLogV1
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
from loushang.apphost.managed.paths import (
    ManagedServicePathsV1,
    resolve_managed_service_paths,
)
from loushang.apphost.managed.registry import (
    MAX_PAGE,
    ManagedMuxCreationInspectionV1,
    ManagedMuxReservationV1,
    ManagedServiceAliasReservationV1,
)
from loushang.apphost.managed.service_admission import ManagedServiceAdmissionV1
from loushang.apphost.managed.stopper import (
    ManagedServiceStopOperationV1,
    _ManagedServiceStopBatch,
)
from loushang.apphost.managed.storage_budget import ManagedStorageBudgetV1
from loushang.appserver.managed_mux_close import (
    ManagedMuxClosePhaseV1,
    ManagedMuxCloseStateV1,
    ManagedMuxCloseV1,
)
from loushang.appserver.protocol import (
    MuxReadV1,
    MuxSelectorV1,
    SessionScopeV1,
    WorkspaceRequestV1,
)

from ._foreground_client_control import mux_member_scopes


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


def _recorded_service(observed: ManagedServiceObservationV1) -> dict[str, object]:
    return {
        "serviceId": observed.service.service_id,
        "productId": observed.service.product_id,
        "hostRoot": observed.service.host_root,
        "profile": observed.service.profile,
        "instanceId": None if observed.instance is None else observed.instance.instance_id,
        "revision": observed.revision,
        "recordedPhase": None if observed.recorded_phase is None else observed.recorded_phase.value,
        "stopRequested": observed.stop_requested,
        "cleanlyStopped": observed.cleanly_stopped,
    }


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

    def _connection_type(self) -> type[ManagedConnectionLeaseV1]:
        return ManagedConnectionLeaseV1

    def _prepare_starter(self, service: ManagedServiceKeyV1) -> None:
        raise NotImplementedError

    def _prepare_creation_owner(self, reservation: ManagedMuxReservationV1) -> None:
        raise NotImplementedError

    def _service_paths(self, service: ManagedServiceKeyV1) -> ManagedServicePathsV1:
        return resolve_managed_service_paths(
            self.defaults.namespace, service, runtime_root=str(self.defaults.platform.runtime)
        )

    def _open_service_journal(self, service: ManagedServiceKeyV1) -> ManagedServiceJournalV1:
        assert self.namespace is not None
        journal = self.journal = ManagedServiceJournalV1(
            self.namespace.registry, self.defaults.namespace, service,
            Path(self._service_paths(service).lifecycle), defer_open=True,
        )
        journal.open(deadline=self.deadline, wait_for_lock=True)
        return journal

    def _read_service(self, service: ManagedServiceKeyV1) -> ManagedServiceStateV1:
        journal = self._open_service_journal(service)
        state = journal.read(deadline=self.deadline, wait_for_lock=True)
        if state is None:
            raise ManagedStorageError("unavailable")
        return state

    def _bind_connection(self, service: ManagedServiceKeyV1, instance: ManagedInstanceRefV1) -> None:
        assert self.journal is not None
        self.connection = self._connection_type()(
            self.journal, self.defaults.namespace, service, instance,
            runtime_root=str(self.defaults.platform.runtime), endpoint=self._managed_endpoint,
        )

    def _prepare_server(self, service: ManagedServiceKeyV1, alias: str | None) -> None:
        assert self.namespace is not None
        registry = self.namespace.registry
        if alias is not None:
            existing = registry.resolve_service_alias(alias, deadline=self.deadline, wait_for_lock=True)
            if existing is None:
                existing = ManagedServiceAliasReservationV1(alias, service, token_hex(16))
                self.alias_reservation = existing
                try:
                    registry.reserve_service_alias(existing, deadline=self.deadline, wait_for_lock=True)
                except ManagedStorageError as error:
                    if error.code != "conflict" or registry.cleanup_pending:
                        raise
                    # Rejoin only the exact alias won by a concurrent caller.
                    existing = registry.resolve_service_alias(alias, deadline=self.deadline, wait_for_lock=True)
                    if existing is None or existing.service != service:
                        raise
            elif existing.service != service:
                raise ManagedStorageError("conflict")
            self.alias_reservation = existing
        self.service = ManagedServiceAdmissionV1(self.namespace, service)
        self.journal = self.service.open(deadline=self.deadline, wait_for_lock=True)
        self._prepare_starter(service)

    def _prepare_attachment(self, observed: ManagedMuxObservationV1, *, start: bool) -> None:
        if not start and (observed.instance is None or observed.stop_requested or observed.cleanly_stopped):
            raise ManagedStorageError("unavailable")
        if observed.service.product_id != self._managed_product_id:
            raise ManagedStorageError("conflict")
        journal = self._open_service_journal(observed.service)
        self.target = observed.name
        if start:
            self._prepare_starter(observed.service)
            return
        assert self.namespace is not None and observed.instance is not None
        manager = ManagedMuxManagerV1(
            self.namespace.registry, journal, self.defaults.namespace,
            observed.service, observed.instance, application_id=self._managed_application_id,
        )
        inspection = manager.inspect_mux(observed.reservation, deadline=self.deadline, wait_for_lock=True)
        self.mux_space_id = inspection.creation.mux_space_id
        if self.probed_mux_id is not None and self.mux_space_id != self.probed_mux_id:
            raise ManagedStorageError("conflict")
        self._bind_connection(observed.service, observed.instance)

    def _read_status(
        self, discovery: ManagedDiscoveryV1, *, service_id: str | None,
        target: str | None, log_limit: int | None,
    ) -> None:
        """Project recorded status and bounded log tails without a connection."""
        if log_limit is None and service_id is None and target is None:
            snapshot = discovery.snapshot_namespace(deadline=self.deadline, wait_for_lock=True)
            muxes: dict[str, list[str]] = {}
            for item in snapshot.muxes:
                muxes.setdefault(item.service.service_id, []).append(item.name)
            services = [
                {**_recorded_service(item), "reservedMuxes": muxes.get(item.service.service_id, [])}
                for item in snapshot.services
            ]
            _check_deadline(self.deadline)
            self._emit_value({"services": services, "observation": "recorded_only", "liveStatus": "not_probed"})
            return
        if target is not None:
            named = discovery.resolve(target, deadline=self.deadline, wait_for_lock=True)
            if named is None:
                raise ManagedStorageError("not_found")
            service_id = named.service.service_id
        if service_id is None:
            raise ManagedContractError()
        observed = discovery.inspect_service(service_id, deadline=self.deadline, wait_for_lock=True)
        if observed is None:
            raise ManagedStorageError("not_found")
        paths = self._service_paths(observed.service)
        if log_limit is not None:
            assert self.namespace is not None
            self.log_directory = PrivateManagedDirectory(Path(paths.logs), defer_open=True)
            self.log_directory.open(deadline=self.deadline)
            reader = ManagedLifecycleLogV1(
                self.log_directory, ManagedStorageBudgetV1(self.namespace.registry), service_id
            )
            records = reader.read_tail(limit=log_limit, deadline=self.deadline)
            self._emit_value({
                "serviceId": service_id, "observation": "bounded_tail", "completeHistory": False,
                "scan": {"maxSegments": 5, "maxBytesPerSegment": 16384},
                "events": [
                    {"sequence": record.sequence, "instanceId": record.event.instance_id,
                     "event": record.event.event, "code": record.event.code}
                    for record in records
                ],
            })
            return
        self._emit_value({
            **_recorded_service(observed), "liveStatus": "not_probed", "observation": "recorded_only",
            "paths": {"logs": str(paths.logs), "application": str(paths.application)},
            "temporary": {"defaultBase": str(paths.logs.parent / "tmp"), "actualRoot": None,
                          "reason": "instance_override_not_recorded"},
        })

    def _prepare_close(
        self, discovery: ManagedDiscoveryV1, *, service_id: str, target: str | None,
        operation_id: str, read_only: bool, continue_close: bool,
        confirm: Callable[[bool], bool] | None,
    ) -> bool:
        """Inspect and confirm the exact close target before opening a connection."""
        assert self.namespace is not None
        self.close_readonly = read_only
        self.close_continue = continue_close
        self.close_by_name = target is not None
        if target is None:
            observed = None
            service = discovery.resolve_service(service_id, deadline=self.deadline, wait_for_lock=True)
        else:
            observed = discovery.resolve(target, deadline=self.deadline, wait_for_lock=True)
            service = observed.service if observed is not None else None
        if service is None:
            raise ManagedStorageError("not_found")
        if service.product_id != self._managed_product_id:
            raise ManagedStorageError("conflict")
        instance = self._read_service(service).handoff.instance
        if observed is not None and observed.instance != instance:
            raise ManagedStorageError("conflict")
        self.close_instance_id = instance.instance_id
        assert self.journal is not None
        manager = self.close_manager = ManagedMuxManagerV1(
            self.namespace.registry, self.journal, self.defaults.namespace,
            service, instance, application_id=self._managed_application_id,
        )
        inspection = self.close_inspection = (
            manager.inspect_mux(observed.reservation, deadline=self.deadline, wait_for_lock=True)
            if observed is not None
            else manager.inspect_close_operation(operation_id, deadline=self.deadline, wait_for_lock=True)
        )
        creation, request = inspection.creation, inspection.close_request
        self.close_reservation = ManagedMuxReservationV1(creation.name, service, creation.operation_id)
        self.close_operation = token_hex(16) if request is None else request.operation_id
        if not read_only:
            self._close_output("planned_close" if request is None else "close_preview")
            if confirm is not None and not confirm(continue_close or request is None):
                return False
            self.deadline = monotonic() + 30
        if inspection.close_result is not None and inspection.close_result.phase is ManagedMuxClosePhaseV1.CLOSED:
            self._close_output("closed", reconciled=True, historical=True)
            return False
        if read_only and (request is None or request.instance_id != instance.instance_id):
            self._close_output("reauthorization_required")
            raise ManagedStorageError("unavailable")
        self._bind_connection(service, instance)
        return True

    def _preview_stop_all(self, discovery: ManagedDiscoveryV1) -> ManagedDiscoverySnapshotV1:
        snapshot = discovery.snapshot_namespace(deadline=self.deadline, wait_for_lock=True)
        self._emit_value({
            "action": "stop_all_preview", "namespaceKey": self.defaults.namespace.namespace_key,
            "ordering": "service_id", "budgetSeconds": 30, "sharedBudget": True,
            "services": [
                {"serviceId": item.service.service_id, "productId": item.service.product_id,
                 "hostRoot": item.service.host_root,
                 "instanceId": None if item.instance is None else item.instance.instance_id,
                 "muxes": [mux.name for mux in snapshot.muxes if mux.service == item.service]}
                for item in snapshot.services
            ],
        })
        return snapshot

    def _prepare_stop(
        self, discovery: ManagedDiscoveryV1, *, service_id: str, confirm: Callable[[], bool] | None,
    ) -> bool:
        service = discovery.resolve_service(service_id, deadline=self.deadline, wait_for_lock=True)
        if service is None:
            raise ManagedStorageError("not_found")
        instance = self._read_service(service).handoff.instance
        names: list[str] = []
        after = None
        while True:
            page = discovery.list_muxes(deadline=self.deadline, after=after, wait_for_lock=True)
            names.extend(item.name for item in page if item.service == service)
            if len(page) < MAX_PAGE:
                break
            after = page[-1].name
        self._emit_value({"action": "stop_preview", "serviceId": service.service_id,
                          "instanceId": instance.instance_id, "muxes": names})
        if confirm is not None:
            if not confirm():
                return False
            self.deadline = monotonic() + 30
        assert self.journal is not None
        self.stopper = ManagedServiceStopOperationV1(
            self.journal, self.defaults.namespace, service, instance,
            runtime_root=str(self.defaults.platform.runtime),
        )
        return True

    def _prepare_creation_recovery(
        self, *, service_id: str, operation_id: str, continue_create: bool,
        confirm: Callable[[], bool] | None,
    ) -> bool:
        """Recheck a confirmed creation reservation before admitting recovery."""
        assert self.namespace is not None
        registry = self.namespace.registry
        inspection = registry.inspect_mux_creation(operation_id, deadline=self.deadline, wait_for_lock=True)
        if inspection is None:
            raise ManagedStorageError("not_found")
        reservation = inspection.reservation
        if reservation.service.service_id != service_id or reservation.service.product_id != self._managed_product_id:
            raise ManagedStorageError("conflict")
        self.creation_reservation = reservation
        if not continue_create:
            self._creation_output("created" if inspection.created is not None else "unknown", inspection)
            self.result_status = 0 if inspection.created is not None else 1
            return False
        if not inspection.active:
            raise ManagedStorageError("conflict")
        if inspection.created is not None:
            self._creation_output("created", inspection)
            return False
        self._creation_output("creation_continue_preview", inspection)
        if confirm is not None and not confirm():
            return False
        self.deadline = monotonic() + 30
        current = registry.inspect_mux_creation(operation_id, deadline=self.deadline, wait_for_lock=True)
        if current != inspection:
            raise ManagedStorageError("conflict")
        self.creation_recovery = True
        self._prepare_creation_owner(reservation)
        return True

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
                scopes = mux_member_scopes(mux)
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
