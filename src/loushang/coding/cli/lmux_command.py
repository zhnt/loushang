"""Coding CLI composition over public managed discovery/start/connection owners.

Synchronous admission and selection precede the event loop. No native worker
outlives its borrowed journal; terminal detach closes local resources only.
The thin HostedMuxShell is an interim UI, not the final full conversation view.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from functools import partial
from pathlib import Path
from secrets import token_hex
from time import monotonic
from typing import TYPE_CHECKING, TextIO

from loushang.apphost.integrations._managed_mux_command import (
    _ManagedMuxCommandLifecycle,
)
from loushang.apphost.managed._files import (
    ManagedStorageError,
)
from loushang.apphost.managed.connection import (
    ManagedConnectionLeaseV1,
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
from loushang.apphost.managed.mux_creation import ManagedMuxCreateOperationV1
from loushang.apphost.managed.mux_probe import (
    ManagedMuxProbeSnapshotV1,
)
from loushang.apphost.managed.namespace_admission import ManagedNamespaceAdmissionV1
from loushang.apphost.managed.registry import (
    MAX_PAGE,
    ManagedMuxCreationInspectionV1,
    ManagedMuxReservationV1,
)
from loushang.apphost.managed.service_admission import ManagedServiceAdmissionV1
from loushang.coding.hosted.managed.process import (
    APPLICATION_ID,
    ENDPOINT,
    coding_managed_process_request,
)

from .lmux_stop_all import StopAll
from .mux import _bind_coding_mux_shell, _execute

if TYPE_CHECKING:
    from loushang.apphost.integrations._managed_mux_command import (
        _ShellFactory,
        _TerminalRunner,
    )
    from loushang.apphost.managed.lifecycle import ManagedServiceStateV1
    from loushang.harnesstui.mux.shell import HostedMuxShellV1


def _emit(value: object, output: TextIO) -> None:
    # Escape workspace/control characters before any terminal output.
    print(json.dumps(value, ensure_ascii=True, sort_keys=True), file=output, flush=True)


def _observation(value: ManagedMuxObservationV1) -> dict[str, object]:
    return {"name": value.name, "hostRoot": value.service.host_root, "serviceId": value.service.service_id,
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


class ManagedMuxCommand(_ManagedMuxCommandLifecycle["HostedMuxShellV1"]):
    """Process-local original owners; retain through all errors and cleanup."""

    def __init__(
        self,
        defaults: ManagedDefaultsV1,
        environment: dict[str, str],
        *,
        stdin: TextIO,
        stdout: TextIO,
    ) -> None:
        self.defaults, self.environment = defaults, dict(environment)
        self.stdin, self.stdout = stdin, stdout
        super().__init__()



    _managed_product_id = "coding"

    @property
    def _managed_application_id(self) -> str:
        return APPLICATION_ID

    @property
    def _managed_endpoint(self) -> str:
        return ENDPOINT

    def _emit_value(self, value: object) -> None:
        _emit(value, self.stdout)

    def _ready_value(self, ready: ManagedConnectionLeaseV1) -> dict[str, object]:
        return {
            "status": "service_ready",
            "serviceId": ready.instance.service_id,
            "instanceId": ready.instance.instance_id,
            "recordRoot": str(ready.record_root),
        }

    def _stopped_value(self, state: ManagedServiceStateV1) -> dict[str, object]:
        return {"status": "stopped", "instanceId": state.handoff.instance.instance_id}

    def _new_trace_value(
        self, deadline_ms: int | None, operation_id: str
    ) -> dict[str, object]:
        return {
            "deadlineMs": deadline_ms,
            "operationId": operation_id,
            "observation": "historical_configuration_not_write_guarantee",
        }

    def _trace_failure_value(self, value: dict[str, object], code: str) -> None:
        value.update(status="observation_failed", errorCode=code)

    def _apply_trace_value(
        self, result: dict[str, object], value: dict[str, object]
    ) -> None:
        result["trace"] = value
        self.result_status = 0 if value["status"] == "applied" else 1

    def _bind_shell(self) -> _ShellFactory[HostedMuxShellV1]:
        return _bind_coding_mux_shell()

    def _bind_terminal_runner(self) -> _TerminalRunner[HostedMuxShellV1]:
        from loushang.harnesstui.mux.terminal import run_hosted_mux_shell

        return run_hosted_mux_shell

    def _execute_probe(self) -> int:
        return _execute(self._run_probe, self._probe_pending)

    def prepare(self, args: argparse.Namespace) -> bool:
        self.deadline = monotonic() + 30
        trace_for = getattr(args, "trace_for", None)
        if trace_for is not None:
            if args.action != "server" or type(trace_for) is not int or not 1 <= trace_for <= 3600:
                raise ManagedContractError()
            self.trace_deadline_ms = int((monotonic() + trace_for) * 1000)
        selected_service = None
        if args.action in (None, "new", "server"):
            selected_service = ManagedServiceKeyV1("coding", self.defaults.namespace.platform_home)
        workspace = getattr(args, "workspace", None)
        if args.action == "new" or (args.action in (None, "attach") and workspace is not None):
            self.workspace = Path(workspace or Path.cwd()).expanduser().resolve(strict=True)
            if not self.workspace.is_dir():
                raise ManagedContractError()
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
            self._prepare_server(selected_service, args.name)
            return True
        if args.action in ("status", "logs"):
            self._read_status(
                discovery, service_id=args.server, target=args.target,
                log_limit=args.limit if args.action == "logs" else None,
            )
            return False
        if args.action == "ls":
            page = discovery.list_muxes(deadline=self.deadline, after=args.after, wait_for_lock=True)
            _emit({"muxes": [_observation(item) for item in page],
                   "nextAfter": page[-1].name if len(page) == MAX_PAGE else None}, self.stdout)
            return False
        if args.action == "stop":
            if getattr(args, "all", False):
                return self._prepare_stop_all(args, discovery)
            return self._prepare_stop(
                discovery, service_id=args.server,
                confirm=None if args.yes else partial(
                    self._confirm_yes, "Stop this service and all its muxes? Type yes: "
                ),
            )
        if args.action in ("close", "close-status"):
            return self._prepare_close(
                discovery, service_id=args.server, target=getattr(args, "target", None),
                operation_id=args.operation, read_only=args.action == "close-status",
                continue_close=getattr(args, "continue_close", False),
                confirm=self._confirm_close if args.action == "close" and not args.yes else None,
            )
        if args.action in ("create", "create-status"):
            return self._prepare_creation_recovery(
                service_id=args.server, operation_id=args.operation,
                continue_create=getattr(args, "continue_create", False),
                confirm=None if getattr(args, "yes", False) else partial(
                    self._confirm_yes,
                    "Start/reuse this original service and resend this same idempotent creation once? Type yes: ",
                    ignore_case=True,
                ),
            )
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
        self._prepare_attachment(observed, start=args.action == "start")
        return True

    def _connection_type(self) -> type[ManagedConnectionLeaseV1]:
        return ManagedConnectionLeaseV1

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

    def _confirm_yes(self, prompt: str, *, ignore_case: bool = False, end: str = "") -> bool:
        print(prompt, file=self.stdout, end=end, flush=True)
        answer = self.stdin.readline(8)
        if not answer.endswith("\n"):
            return False
        value = answer.strip()
        return (value.lower() if ignore_case else value) == "yes"

    def _confirm_close(self, will_send: bool) -> bool:
        prompt = (
            "This closes only the selected mux; persistent Session files are kept. Continue [yes/No]?"
            if will_send else
            "Query and reconcile only; no close request will be resent. Continue [yes/No]?"
        )
        return self._confirm_yes(prompt, ignore_case=True, end="\n")

    def _prepare_stop_all(self, args: argparse.Namespace, discovery: ManagedDiscoveryV1) -> bool:
        assert self.namespace is not None
        snapshot = self._preview_stop_all(discovery)
        if not args.yes and not self._confirm_yes(
            "Stop these exact instances using one shared 30s budget? Type yes: "
        ):
            return False
        self.deadline = monotonic() + 30
        self.stop_all = StopAll(
            self.namespace, self.defaults, snapshot, deadline=self.deadline, emit=self._emit_value
        )
        return True

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
               "hostRoot": reservation.service.host_root, "name": reservation.name,
               "operationId": reservation.operation_id,
               "muxId": None if created is None else created.mux_space_id,
               "originInstanceId": None if created is None else created.instance_id,
               "activeReservation": None if inspection is None else inspection.active,
               "observation": "recorded_only", "liveStatus": "not_probed",
               "automaticReplay": False,
               "nextCommand": ["lmux", "create-status", "--server", reservation.service.service_id,
                               "--operation", reservation.operation_id],
               **continuation}, self.stdout)

    def _new(self, name: str, service: ManagedServiceKeyV1) -> None:
        assert self.namespace is not None
        self.workspace = self.workspace or Path.cwd()
        registry = self.namespace.registry
        reservation = self.creation_reservation = ManagedMuxReservationV1(name, service, token_hex(16))
        # Printed before the first fallible commit: this is only a planned
        # intent, not a creation receipt, serving claim, or proof of reservation.
        self._creation_output("planned_creation")
        # Reserve the exact intent before service creation; retries rejoin it.
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
        await super().run()



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
