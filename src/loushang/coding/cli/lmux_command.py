"""Coding CLI composition over public managed discovery/start/connection owners.

Synchronous admission and selection precede the event loop. No native worker
outlives its borrowed journal; terminal detach closes local resources only.
The thin HostedMuxShell is an interim UI, not the final full conversation view.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from secrets import token_hex
from time import monotonic
from typing import TYPE_CHECKING, TextIO

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
    _HEX64,
    ManagedContractError,
    ManagedHandoffPhaseV1,
    ManagedServiceKeyV1,
)
from loushang.apphost.managed.coordinator import ManagedServiceCoordinatorV1
from loushang.apphost.managed.defaults import (
    ManagedDefaultsV1,
    resolve_managed_defaults,
)
from loushang.apphost.managed.discovery import (
    ManagedDiscoveryV1,
    ManagedMuxObservationV1,
)
from loushang.apphost.managed.event_log import ManagedLifecycleLogV1
from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
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
from loushang.apphost.managed.paths import resolve_managed_service_paths
from loushang.apphost.managed.registry import (
    MAX_PAGE,
    ManagedMuxCreationInspectionV1,
    ManagedMuxReservationV1,
    ManagedServiceAliasReservationV1,
)
from loushang.apphost.managed.service_admission import ManagedServiceAdmissionV1
from loushang.apphost.managed.stopper import ManagedServiceStopOperationV1
from loushang.apphost.managed.storage_budget import ManagedStorageBudgetV1
from loushang.appserver.managed_mux_close import (
    ManagedMuxClosePhaseV1,
    ManagedMuxCloseStateV1,
    ManagedMuxCloseV1,
)
from loushang.appserver.protocol import MuxSelectorV1

from ..managed_process import APPLICATION_ID, ENDPOINT, coding_managed_process_request
from .lmux_stop_all import StopAll
from .mux import _execute

if TYPE_CHECKING:
    from loushang.harnesstui.mux.shell import HostedMuxShellV1


def _emit(value: object, output: TextIO) -> None:
    # Escape workspace/control characters before any terminal output.
    print(json.dumps(value, ensure_ascii=True, sort_keys=True), file=output, flush=True)


def _observation(value: ManagedMuxObservationV1) -> dict[str, object]:
    return {"name": value.name, "workspace": value.service.workspace, "serviceId": value.service.service_id,
            "creationOperationId": value.reservation.operation_id,
            "recordedPhase": None if value.recorded_phase is None else value.recorded_phase.value,
            "stopRequested": value.stop_requested, "cleanlyStopped": value.cleanly_stopped,
            "status": "unknown", "tabs": None}


def _single_candidate(page: tuple[ManagedMuxObservationV1, ...]) -> ManagedMuxObservationV1 | None:
    """Choose a sole recorded candidate, never certify it as online."""
    if len(page) != 1 or len(page) >= MAX_PAGE:
        return None
    item = page[0]
    if (item.service.product_id != "coding" or item.instance is None
            or item.recorded_phase is not ManagedHandoffPhaseV1.COMMITTED
            or item.stop_requested or item.cleanly_stopped):
        return None
    return item


class ManagedMuxCommand:
    """Process-local original owners; retain through all errors and cleanup."""

    def __init__(self, defaults: ManagedDefaultsV1, environment: dict[str, str], *, stdin: TextIO, stdout: TextIO) -> None:
        self.defaults, self.environment = defaults, dict(environment)
        self.stdin, self.stdout = stdin, stdout
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
        self.stop_all: StopAll | None = None
        self.connection: ManagedConnectionLeaseV1 | None = None
        self.shell: HostedMuxShellV1 | None = None
        self.target: str | None = None
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

    def prepare(self, args: argparse.Namespace) -> bool:
        self.deadline = monotonic() + 30
        trace_for = getattr(args, "trace_for", None)
        if trace_for is not None:
            if args.action != "server" or type(trace_for) is not int or not 1 <= trace_for <= 3600:
                raise ManagedContractError()
            self.trace_deadline_ms = int((monotonic() + trace_for) * 1000)
        selected_service = None
        if args.action in (None, "new", "server"):
            workspace = Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve(strict=True)
            if not workspace.is_dir():
                raise ManagedContractError()
            selected_service = ManagedServiceKeyV1("coding", str(workspace))
        self.namespace = ManagedNamespaceAdmissionV1(
            self.defaults.namespace, runtime_root=str(self.defaults.platform.runtime),
            create_if_missing=args.action in (None, "new", "server"),
        )
        try:
            registry = self.namespace.open(deadline=self.deadline, wait_for_lock=True)
        except ManagedStorageError as error:
            if error.code == "not_found" and args.action == "status" and args.server is None and args.target is None:
                _emit({"services": [], "observation": "recorded_only", "liveStatus": "not_probed"}, self.stdout)
                return False
            if error.code != "not_found" or args.action != "ls":
                raise
            _emit({"muxes": [], "nextAfter": None}, self.stdout)
            return False
        discovery = ManagedDiscoveryV1(registry, self.defaults.namespace)
        if args.action in ("stop", "status", "logs") and args.server is not None and _HEX64.fullmatch(args.server) is None:
            alias = registry.resolve_service_alias(args.server, deadline=self.deadline, wait_for_lock=True)
            if alias is None:
                raise ManagedStorageError("not_found")
            # Resolve exactly once; all later confirmation and effects use this
            # immutable service identity, never a mutable display selector.
            args.server = alias.service.service_id
        if args.action == "server":
            assert selected_service is not None
            if args.name is not None:
                existing = registry.resolve_service_alias(args.name, deadline=self.deadline, wait_for_lock=True)
                if existing is not None:
                    if existing.service != selected_service:
                        raise ManagedStorageError("conflict")
                    self.alias_reservation = existing
                else:
                    self.alias_reservation = ManagedServiceAliasReservationV1(args.name, selected_service, token_hex(16))
                    try:
                        registry.reserve_service_alias(self.alias_reservation, deadline=self.deadline, wait_for_lock=True)
                    except ManagedStorageError as error:
                        if error.code != "conflict" or registry.cleanup_pending:
                            raise
                        # Another first caller may have won this same mapping.
                        # Reconcile once, read-only; never retry a new intent or
                        # adopt a different workspace/profile after a conflict.
                        winner = registry.resolve_service_alias(args.name, deadline=self.deadline, wait_for_lock=True)
                        if winner is None or winner.service != selected_service:
                            raise
                        self.alias_reservation = winner
            self.service = ManagedServiceAdmissionV1(self.namespace, selected_service)
            self.journal = self.service.open(deadline=self.deadline, wait_for_lock=True)
            self._prepare_starter(selected_service)
            return True
        if args.action in ("status", "logs"):
            return self._prepare_status(args, discovery)
        if args.action == "ls":
            page = discovery.list_muxes(deadline=self.deadline, after=args.after, wait_for_lock=True)
            _emit({"muxes": [_observation(item) for item in page],
                   "nextAfter": page[-1].name if len(page) == MAX_PAGE else None}, self.stdout)
            return False
        if args.action == "stop":
            if getattr(args, "all", False):
                return self._prepare_stop_all(args, discovery)
            return self._prepare_stop(args, discovery)
        if args.action in ("close", "close-status"):
            return self._prepare_close(args, discovery)
        if args.action in ("create", "create-status"):
            return self._prepare_creation_recovery(args)
        if args.action == "new":
            assert selected_service is not None
            self._new(args.name, selected_service)
            return True
        target = getattr(args, "target", None)
        selected = None
        if target is None:
            page = discovery.list_muxes(deadline=self.deadline, wait_for_lock=True)
            if not page:
                if args.action is None:
                    assert selected_service is not None
                    self._new("main", selected_service)
                    return True
                raise ManagedStorageError("not_found")
            selected = _single_candidate(page)
            if selected is None:
                snapshot = self._probe_snapshot()
                unique = snapshot.unique_present
                selected = unique.observation if unique is not None else self._select_probe(snapshot)
            if selected is None:
                return False
            if self.probe_result is not None:
                self.probed_mux_id = next((row.mux_space_id for row in self.probe_result.results
                    if row.observation == selected), None)
            target = selected.name
        observed = discovery.resolve(target, deadline=self.deadline, wait_for_lock=True)
        if observed is None:
            raise ManagedStorageError("not_found")
        if selected is not None and (observed.reservation != selected.reservation or observed.instance != selected.instance):
            raise ManagedStorageError("conflict")
        if args.action != "start" and (observed.instance is None or observed.stop_requested or observed.cleanly_stopped):
            raise ManagedStorageError("unavailable")
        if observed.service.product_id != "coding":
            raise ManagedStorageError("conflict")
        paths = resolve_managed_service_paths(self.defaults.namespace, observed.service,
                                              runtime_root=str(self.defaults.platform.runtime))
        self.journal = ManagedServiceJournalV1(registry, self.defaults.namespace, observed.service,
                                               Path(paths.lifecycle), defer_open=True)
        self.journal.open(deadline=self.deadline, wait_for_lock=True)
        self.target = observed.name
        if args.action == "start":
            self._prepare_starter(observed.service)
            return True
        assert observed.instance is not None
        manager = ManagedMuxManagerV1(registry, self.journal, self.defaults.namespace,
                                      observed.service, observed.instance, application_id=APPLICATION_ID)
        inspection = manager.inspect_mux(observed.reservation, deadline=self.deadline, wait_for_lock=True)
        self.mux_space_id = inspection.creation.mux_space_id
        if self.probed_mux_id is not None and self.mux_space_id != self.probed_mux_id:
            raise ManagedStorageError("conflict")
        self.connection = ManagedConnectionLeaseV1(
            self.journal, self.defaults.namespace, observed.service, observed.instance,
            runtime_root=str(self.defaults.platform.runtime), endpoint=ENDPOINT,
        )
        return True

    def _prepare_starter(self, service: ManagedServiceKeyV1) -> None:
        assert self.journal is not None
        self.starter = ManagedServiceCoordinatorV1(
            self.journal, self.defaults.namespace, service,
            runtime_root=str(self.defaults.platform.runtime), endpoint=ENDPOINT,
            temporary_override=self.defaults.temporary_override,
            trace_deadline_ms=self.trace_deadline_ms,
            request_factory=lambda invocation, descriptor: coding_managed_process_request(
                invocation, descriptor, executable=sys.executable, environment=self.environment,
            ),
        )

    def _prepare_status(self, args: argparse.Namespace, discovery: ManagedDiscoveryV1) -> bool:
        service_id = args.server
        if args.action == "status" and service_id is None and args.target is None:
            snapshot = discovery.snapshot_namespace(deadline=self.deadline, wait_for_lock=True)
            muxes: dict[str, list[str]] = {}
            for item in snapshot.muxes:
                muxes.setdefault(item.service.service_id, []).append(item.name)
            services = [{"serviceId": item.service.service_id, "productId": item.service.product_id,
                         "workspace": item.service.workspace, "profile": item.service.profile,
                         "instanceId": None if item.instance is None else item.instance.instance_id,
                         "revision": item.revision,
                         "recordedPhase": None if item.recorded_phase is None else item.recorded_phase.value,
                         "stopRequested": item.stop_requested, "cleanlyStopped": item.cleanly_stopped,
                         "reservedMuxes": muxes.get(item.service.service_id, [])} for item in snapshot.services]
            _check_deadline(self.deadline)
            _emit({"services": services, "observation": "recorded_only", "liveStatus": "not_probed"}, self.stdout)
            return False
        if args.target is not None:
            named = discovery.resolve(args.target, deadline=self.deadline, wait_for_lock=True)
            if named is None:
                raise ManagedStorageError("not_found")
            service_id = named.service.service_id
        observed = discovery.inspect_service(service_id, deadline=self.deadline, wait_for_lock=True)
        if observed is None:
            raise ManagedStorageError("not_found")
        paths = resolve_managed_service_paths(self.defaults.namespace, observed.service,
                                              runtime_root=str(self.defaults.platform.runtime))
        if args.action == "logs":
            assert self.namespace is not None
            self.log_directory = PrivateManagedDirectory(Path(paths.logs), defer_open=True)
            self.log_directory.open(deadline=self.deadline)
            reader = ManagedLifecycleLogV1(self.log_directory, ManagedStorageBudgetV1(self.namespace.registry), service_id)
            records = reader.read_tail(limit=args.limit, deadline=self.deadline)
            _emit({"serviceId": service_id, "observation": "bounded_tail", "completeHistory": False,
                   "scan": {"maxSegments": 5, "maxBytesPerSegment": 16384},
                   "events": [{"sequence": record.sequence, "instanceId": record.event.instance_id,
                               "event": record.event.event, "code": record.event.code} for record in records]}, self.stdout)
            return False
        _emit({"serviceId": service_id, "productId": observed.service.product_id,
               "workspace": observed.service.workspace, "profile": observed.service.profile,
               "instanceId": None if observed.instance is None else observed.instance.instance_id,
               "revision": observed.revision,
               "recordedPhase": None if observed.recorded_phase is None else observed.recorded_phase.value,
               "stopRequested": observed.stop_requested, "cleanlyStopped": observed.cleanly_stopped,
               "liveStatus": "not_probed", "observation": "recorded_only",
               "paths": {"logs": str(paths.logs), "application": str(paths.application)},
               "temporary": {"defaultBase": str(paths.logs.parent / "tmp"), "actualRoot": None,
                             "reason": "instance_override_not_recorded"}}, self.stdout)
        return False

    def _close_output(self, status: str, *, reconciled: bool = False, historical: bool = False) -> None:
        assert self.close_inspection is not None and self.close_reservation is not None
        creation = self.close_inspection.creation
        result = self.close_result or self.close_inspection.close_result
        followup: dict[str, object] = {}
        if status in ("unknown", "reauthorization_required"):
            command = ["lmux", "close", "--server", self.close_reservation.service.service_id,
                       "--operation", self.close_operation]
            if status == "unknown":
                command.append("--continue")
            followup = {"nextCommand": command, "requiresConfirmation": True,
                        "automaticReplay": False}
        _emit({"status": status, "serviceId": self.close_reservation.service.service_id,
               "observedInstanceId": self.close_instance_id,
               "originInstanceId": None if result is None else result.instance_id,
               "operationId": self.close_operation, "creationOperationId": creation.operation_id,
               "name": creation.name, "muxId": creation.mux_space_id,
               "reconciled": reconciled, "historical": historical, **followup}, self.stdout)

    def _prepare_close(self, args: argparse.Namespace, discovery: ManagedDiscoveryV1) -> bool:
        assert self.namespace is not None
        self.close_readonly = args.action == "close-status"
        self.close_continue = getattr(args, "continue_close", False)
        self.close_by_name = getattr(args, "target", None) is not None
        observed = discovery.resolve(args.target, deadline=self.deadline, wait_for_lock=True) if self.close_by_name else None
        if self.close_by_name and observed is None:
            raise ManagedStorageError("not_found")
        service = observed.service if observed is not None else discovery.resolve_service(
            args.server, deadline=self.deadline, wait_for_lock=True)
        if service is None:
            raise ManagedStorageError("not_found")
        if service.product_id != "coding":
            raise ManagedStorageError("conflict")
        paths = resolve_managed_service_paths(self.defaults.namespace, service,
                                              runtime_root=str(self.defaults.platform.runtime))
        self.journal = ManagedServiceJournalV1(self.namespace.registry, self.defaults.namespace, service,
                                               Path(paths.lifecycle), defer_open=True)
        self.journal.open(deadline=self.deadline, wait_for_lock=True)
        state = self.journal.read(deadline=self.deadline, wait_for_lock=True)
        if state is None:
            raise ManagedStorageError("unavailable")
        if observed is not None and observed.instance != state.handoff.instance:
            raise ManagedStorageError("conflict")
        self.close_instance_id = state.handoff.instance.instance_id
        manager = self.close_manager = ManagedMuxManagerV1(self.namespace.registry, self.journal,
            self.defaults.namespace, service, state.handoff.instance, application_id=APPLICATION_ID)
        inspection = self.close_inspection = manager.inspect_mux(
            observed.reservation, deadline=self.deadline, wait_for_lock=True) if observed is not None else manager.inspect_close_operation(
                args.operation, deadline=self.deadline, wait_for_lock=True)
        creation, request = inspection.creation, inspection.close_request
        self.close_reservation = ManagedMuxReservationV1(creation.name, service, creation.operation_id)
        self.close_operation = token_hex(16) if request is None else request.operation_id
        if self.close_readonly and inspection.close_result is not None and inspection.close_result.phase is ManagedMuxClosePhaseV1.CLOSED:
            self._close_output("closed", reconciled=True, historical=True)
            return False
        if not self.close_readonly:
            self._close_output("planned_close" if request is None else "close_preview")
            if not args.yes:
                print("This closes only the selected mux; persistent Session files are kept. "
                      "Continue [yes/No]?" if self.close_continue or request is None else
                      "Query and reconcile only; no close request will be resent. Continue [yes/No]?",
                      file=self.stdout, flush=True)
                answer = self.stdin.readline(8)
                if not answer.endswith("\n") or answer.strip().lower() != "yes":
                    return False
            self.deadline = monotonic() + 30
            if inspection.close_result is not None and inspection.close_result.phase is ManagedMuxClosePhaseV1.CLOSED:
                self._close_output("closed", reconciled=True, historical=True)
                return False
        elif request is None or request.instance_id != state.handoff.instance.instance_id:
            self._close_output("reauthorization_required")
            raise ManagedStorageError("unavailable")
        self.connection = ManagedConnectionLeaseV1(self.journal, self.defaults.namespace, service,
            state.handoff.instance, runtime_root=str(self.defaults.platform.runtime), endpoint=ENDPOINT)
        return True

    async def _run_close(self) -> None:
        assert self.connection is not None and self.close_manager is not None
        assert self.close_inspection is not None and self.close_reservation is not None and self.close_operation is not None
        manager, inspection, reservation = self.close_manager, self.close_inspection, self.close_reservation
        operation = self.close_operation
        await self.connection.prepare(deadline=self.deadline)
        if self.connection.application_id != APPLICATION_ID:
            raise ManagedStorageError("conflict")
        client = self.connection.managed_mux_close_client
        if client is None:
            raise ManagedStorageError("unavailable")
        # Recheck the frozen target/permission, not a later name selection.
        current = await _settled_native(lambda: manager.inspect_mux(reservation, deadline=self.deadline, wait_for_lock=True)
            if self.close_by_name else manager.inspect_close_operation(operation, deadline=self.deadline, wait_for_lock=True))
        if current.creation != inspection.creation or current.close_request != inspection.close_request:
            raise ManagedStorageError("conflict")
        request = inspection.close_request
        if not self.close_readonly:
            request = await _settled_native(lambda: manager.issue_close(reservation, operation_id=operation,
                deadline=self.deadline, wait_for_lock=True))
        assert request is not None
        self.close_request = request
        _check_deadline(self.deadline)
        async with asyncio.timeout_at(self.deadline):
            # At most one RPC effect per explicit invocation. A status query or
            # ordinary rejoin never interprets None as permission to replay.
            result = await client.close_managed_mux(request) if not self.close_readonly and (
                inspection.close_request is None or self.close_continue) else await client.read_managed_mux_close(request)
        _check_deadline(self.deadline)
        if result is None:
            self._close_output("unknown")
            raise ManagedStorageError("unavailable")
        await _settled_native(lambda: manager.verify_close_result(request, result, deadline=self.deadline, wait_for_lock=True))
        self.close_result = result
        _check_deadline(self.deadline)
        if not self.close_readonly:
            self._close_output(result.phase.value)
            await _settled_native(lambda: manager.record_close(request, result, deadline=self.deadline, wait_for_lock=True))
        _check_deadline(self.deadline)
        self._close_output(result.phase.value, reconciled=not self.close_readonly)

    def _prepare_stop_all(self, args: argparse.Namespace, discovery: ManagedDiscoveryV1) -> bool:
        assert self.namespace is not None
        snapshot = discovery.snapshot_namespace(deadline=self.deadline, wait_for_lock=True)
        _emit({"action": "stop_all_preview", "namespaceKey": self.defaults.namespace.namespace_key,
               "ordering": "service_id", "budgetSeconds": 30, "sharedBudget": True,
               "services": [{"serviceId": item.service.service_id, "productId": item.service.product_id,
                   "workspace": item.service.workspace,
                   "instanceId": None if item.instance is None else item.instance.instance_id,
                   "muxes": [mux.name for mux in snapshot.muxes if mux.service == item.service]}
                   for item in snapshot.services]}, self.stdout)
        if not args.yes:
            print("Stop these exact instances using one shared 30s budget? Type yes: ",
                  file=self.stdout, end="", flush=True)
            confirmation = self.stdin.readline(8)
            if not confirmation.endswith("\n") or confirmation.strip() != "yes":
                return False
        self.deadline = monotonic() + 30
        self.stop_all = StopAll(self.namespace, self.defaults, snapshot, deadline=self.deadline,
                               emit=lambda value: _emit(value, self.stdout))
        return True

    def _prepare_stop(self, args: argparse.Namespace, discovery: ManagedDiscoveryV1) -> bool:
        assert self.namespace is not None
        service = discovery.resolve_service(args.server, deadline=self.deadline, wait_for_lock=True)
        if service is None:
            raise ManagedStorageError("not_found")
        paths = resolve_managed_service_paths(self.defaults.namespace, service,
                                              runtime_root=str(self.defaults.platform.runtime))
        self.journal = ManagedServiceJournalV1(self.namespace.registry, self.defaults.namespace, service,
                                               Path(paths.lifecycle), defer_open=True)
        self.journal.open(deadline=self.deadline, wait_for_lock=True)
        state = self.journal.read(deadline=self.deadline, wait_for_lock=True)
        if state is None:
            raise ManagedStorageError("unavailable")
        names: list[str] = []
        after = None
        while True:
            page = discovery.list_muxes(deadline=self.deadline, after=after, wait_for_lock=True)
            names.extend(item.name for item in page if item.service == service)
            if len(page) < MAX_PAGE:
                break
            after = page[-1].name
        _emit({"action": "stop_preview", "serviceId": service.service_id,
               "instanceId": state.handoff.instance.instance_id, "muxes": names}, self.stdout)
        if not args.yes:
            print("Stop this service and all its muxes? Type yes: ", file=self.stdout, end="", flush=True)
            confirmation = self.stdin.readline(8)
            if not confirmation.endswith("\n") or confirmation.strip() != "yes":
                return False
            self.deadline = monotonic() + 30
        self.stopper = ManagedServiceStopOperationV1(
            self.journal, self.defaults.namespace, service, state.handoff.instance,
            runtime_root=str(self.defaults.platform.runtime),
        )
        return True

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
        self.probe = ManagedMuxProbeOperationV1(self.namespace.registry, self.defaults.namespace,
            product_id="coding", runtime_root=str(self.defaults.platform.runtime), endpoint=ENDPOINT,
            expected_application_id=APPLICATION_ID, deadline=self.deadline)
        status = _execute(self._run_probe, self._probe_pending)
        if status or self.probe_result is None:
            raise ManagedStorageError("unavailable")
        return self.probe_result

    def _select_probe(self, snapshot: ManagedMuxProbeSnapshotV1) -> ManagedMuxObservationV1 | None:
        offset = 0
        while True:
            page = snapshot.results[offset:offset + MAX_PAGE]
            for index, row in enumerate(page, 1):
                _emit({"choice": index, **_observation(row.observation), "status": row.status,
                       "control": "not_requested"}, self.stdout)
            next_hint = "; n next page" if offset + MAX_PAGE < len(snapshot.results) else ""
            print("Choose a number (Enter cancels)" + next_hint + "; r first page; f refresh: ",
                  file=self.stdout, end="", flush=True)
            line = self.stdin.readline(32)
            if len(line) == 32 and not line.endswith("\n"):
                raise ManagedContractError()
            choice = line.strip()
            if not choice:
                return None
            if choice == "r":
                offset = 0
                continue
            if choice == "n":
                if offset + MAX_PAGE < len(snapshot.results):
                    offset += MAX_PAGE
                else:
                    print("No more muxes; staying on this page.", file=self.stdout, flush=True)
                continue
            if choice == "f":
                self.deadline = monotonic() + 30
                snapshot = self._probe_snapshot()
                offset = 0
                if snapshot.unique_present is not None:
                    return snapshot.unique_present.observation
                continue
            if not choice.isascii() or not choice.isdecimal() or not 1 <= int(choice) <= len(page):
                raise ManagedContractError()
            self.deadline = monotonic() + 30
            return page[int(choice) - 1].observation

    def _creation_output(self, status: str, inspection: ManagedMuxCreationInspectionV1 | None = None) -> None:
        assert self.creation_reservation is not None
        reservation = self.creation_reservation
        created = None if inspection is None else inspection.created
        continuation: dict[str, object] = {}
        if created is None and (inspection is None or inspection.active):
            continuation = {"continueCommand": ["lmux", "create", "--server", reservation.service.service_id,
                                                "--operation", reservation.operation_id, "--continue"],
                            "requiresConfirmation": True}
        _emit({"status": status, "serviceId": reservation.service.service_id,
               "workspace": reservation.service.workspace, "name": reservation.name,
               "operationId": reservation.operation_id,
               "muxId": None if created is None else created.mux_space_id,
               "originInstanceId": None if created is None else created.instance_id,
               "activeReservation": None if inspection is None else inspection.active,
               "observation": "recorded_only", "liveStatus": "not_probed",
               "automaticReplay": False,
               "nextCommand": ["lmux", "create-status", "--server", reservation.service.service_id,
                               "--operation", reservation.operation_id],
               **continuation}, self.stdout)

    def _prepare_creation_recovery(self, args: argparse.Namespace) -> bool:
        assert self.namespace is not None
        registry = self.namespace.registry
        inspection = registry.inspect_mux_creation(args.operation, deadline=self.deadline, wait_for_lock=True)
        if inspection is None:
            raise ManagedStorageError("not_found")
        reservation = inspection.reservation
        if reservation.service.service_id != args.server or reservation.service.product_id != "coding":
            raise ManagedStorageError("conflict")
        self.creation_reservation = reservation
        if not getattr(args, "continue_create", False):
            self._creation_output("created" if inspection.created is not None else "unknown", inspection)
            self.result_status = 0 if inspection.created is not None else 1
            return False
        if not inspection.active:
            # An old operation cannot reclaim its name after a confirmed close.
            raise ManagedStorageError("conflict")
        if inspection.created is not None:
            self._creation_output("created", inspection)
            return False
        self._creation_output("creation_continue_preview", inspection)
        if not args.yes:
            print("Start/reuse this original service and resend this same idempotent creation once? "
                  "Type yes: ", file=self.stdout, end="", flush=True)
            answer = self.stdin.readline(8)
            if not answer.endswith("\n") or answer.strip().lower() != "yes":
                return False
        self.deadline = monotonic() + 30
        current = registry.inspect_mux_creation(args.operation, deadline=self.deadline, wait_for_lock=True)
        if current != inspection:
            raise ManagedStorageError("conflict")
        self.creation_recovery = True
        self._prepare_creation_owner(reservation)
        return True

    def _new(self, name: str, service: ManagedServiceKeyV1) -> None:
        assert self.namespace is not None
        registry = self.namespace.registry
        reservation = self.creation_reservation = ManagedMuxReservationV1(name, service, token_hex(16))
        # Printed before the first fallible commit: this is only a planned
        # intent, not a creation receipt, serving claim, or proof of reservation.
        self._creation_output("planned_creation")
        # First reserve the exact global intent, before service creation. The
        # operation rejoins this same reservation; it never allocates a new ID.
        registry.reserve_mux(reservation, deadline=self.deadline, wait_for_lock=True)
        self._prepare_creation_owner(reservation)

    def _prepare_creation_owner(self, reservation: ManagedMuxReservationV1) -> None:
        assert self.namespace is not None
        registry, service = self.namespace.registry, reservation.service
        self.service = ManagedServiceAdmissionV1(self.namespace, service)
        self.journal = self.service.open(deadline=self.deadline, wait_for_lock=True)
        self.creation = ManagedMuxCreateOperationV1(
            registry, self.journal, self.defaults.namespace, reservation,
            runtime_root=str(self.defaults.platform.runtime), endpoint=ENDPOINT, application_id=APPLICATION_ID,
            temporary_override=self.defaults.temporary_override,
            request_factory=lambda invocation, descriptor: coding_managed_process_request(
                invocation, descriptor, executable=sys.executable, environment=self.environment,
            ),
        )
        self.target = reservation.name

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
                _emit({"status": "stopped", "instanceId": state.handoff.instance.instance_id}, self.stdout)
                return
            if self.starter is not None:
                ready = await self.starter.ensure_started(deadline=self.deadline)
                if ready.application_id != APPLICATION_ID:
                    raise ManagedStorageError("conflict")
                result: dict[str, object] = {"status": "service_ready", "serviceId": ready.instance.service_id,
                                             "instanceId": ready.instance.instance_id}
                if self.trace_deadline_ms is not None:
                    trace_result: dict[str, object] = {
                        "deadlineMs": self.trace_deadline_ms,
                        "operationId": self.starter.operation_id,
                        "observation": "historical_configuration_not_write_guarantee",
                    }
                    try:
                        trace_result["status"] = await self.starter.observe_requested_trace(deadline=self.deadline)
                    except ManagedStorageError as error:
                        trace_result.update(status="observation_failed", errorCode=error.code)
                    except Exception:
                        trace_result.update(status="observation_failed", errorCode="unavailable")
                    result["trace"] = trace_result
                    self.result_status = 0 if trace_result["status"] == "applied" else 1
                _emit(result, self.stdout)
                return
            if self.creation is not None:
                created = await self.creation.run(deadline=self.deadline)
                if self.creation_recovery:
                    assert self.creation_reservation is not None
                    self._creation_output("created", ManagedMuxCreationInspectionV1(
                        self.creation_reservation, True, created))
                    return
                connection = self.creation.connection
                selector = MuxSelectorV1(mux_space_id=created.mux_space_id)
            else:
                assert self.connection is not None
                await self.connection.prepare(deadline=self.deadline)
                connection = self.connection
                assert self.mux_space_id is not None
                selector = MuxSelectorV1(mux_space_id=self.mux_space_id)
            if connection.application_id != APPLICATION_ID:
                raise ManagedStorageError("conflict")
            from loushang.harnesstui.conversation.theme import terminal_transcript_theme
            from loushang.harnesstui.mux.shell import HostedMuxShellV1
            from loushang.harnesstui.mux.terminal import run_hosted_mux_shell

            self.shell = HostedMuxShellV1(
                connection.client, selector=selector, product_id="coding",
                scopes=tuple((item.scope, item.fingerprint) for item in connection.scopes),
                discovery_client=connection.discovery_client,
                transcript_theme=terminal_transcript_theme(),
            )
            status = await run_hosted_mux_shell(self.shell, stdin=self.stdin, stdout=self.stdout,
                                                 startup_deadline=self.deadline)
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


def execute(args: argparse.Namespace, *, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    command = None
    status = 0
    try:
        environment = dict(os.environ)
        defaults = resolve_managed_defaults(environ=environment)
        command = ManagedMuxCommand(defaults, environment, stdin=stdin, stdout=stdout)
        if command.prepare(args):
            status = _execute(command.run, command.finish_native_if_idle)
        status = status or command.result_status
    except KeyboardInterrupt:
        print("lmux_interrupted", file=stderr)
        status = 130
    except ManagedStorageError as error:
        print("lmux_" + error.code, file=stderr)
        status = 1
    except Exception:
        print("lmux_unavailable", file=stderr)
        status = 1
    finally:
        if command is not None:
            if command.active:
                print("lmux_cleanup_incomplete", file=stderr, flush=True)
                os._exit(status or 1)
            try:
                command.close_native()
            except BaseException:
                print("lmux_cleanup_incomplete", file=stderr, flush=True)
                os._exit(status or 1)
    return status
