"""Compose the Coding AppHost service lifecycle for loushang-mux."""

from __future__ import annotations

import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from time import monotonic

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.connection import (
    ManagedConnectionLeaseV1,
    _settled_native,
)
from loushang.apphost.managed.contracts import (
    ManagedHandoffPhaseV1,
    ManagedServiceKeyV1,
)
from loushang.apphost.managed.coordinator import ManagedServiceCoordinatorV1
from loushang.apphost.managed.defaults import resolve_managed_defaults
from loushang.apphost.managed.lifecycle import (
    ManagedServiceJournalV1,
    ManagedServiceStateV1,
)
from loushang.apphost.managed.namespace_admission import ManagedNamespaceAdmissionV1
from loushang.apphost.managed.paths import resolve_managed_service_paths
from loushang.apphost.managed.service_admission import ManagedServiceAdmissionV1
from loushang.apphost.managed.stopper import ManagedServiceStopOperationV1

from .managed_process import APPLICATION_ID, ENDPOINT, coding_managed_process_request


class ServiceControlError(RuntimeError):
    """A safe lifecycle error for command clients."""


async def control_managed_service(operation: str, expected: str | None) -> dict[str, object]:
    deadline = monotonic() + (60 if operation == "restart" else 30)
    defaults = resolve_managed_defaults()
    namespace = defaults.namespace
    service = ManagedServiceKeyV1("coding", namespace.platform_home)
    runtime = str(defaults.platform.runtime)
    paths = resolve_managed_service_paths(namespace, service, runtime_root=runtime)
    admission = ManagedNamespaceAdmissionV1(namespace, runtime_root=runtime, create_if_missing=operation == "start")

    async with AsyncExitStack() as owners:
        owners.push_async_callback(_settled_native, admission.close)
        try:
            registry = await _settled_native(lambda: admission.open(deadline=deadline, wait_for_lock=True))
            if operation == "start":
                admitted = ManagedServiceAdmissionV1(admission, service)
                owners.push_async_callback(_settled_native, admitted.close)
                journal = await _settled_native(lambda: admitted.open(deadline=deadline, wait_for_lock=True))
            else:
                journal = ManagedServiceJournalV1(registry, namespace, service, Path(paths.lifecycle), defer_open=True)
                owners.push_async_callback(_settled_native, journal.close)
                await _settled_native(lambda: journal.open(deadline=deadline, wait_for_lock=True))
        except ManagedStorageError as error:
            if error.code == "not_found" and operation != "start":
                return _absent(operation, expected)
            raise

        state = await _settled_native(lambda: journal.read(deadline=deadline, wait_for_lock=True))
        if operation in {"stop", "restart"}:
            if state is None or state.cleanly_stopped:
                return _absent(operation, expected)
            instance = state.handoff.instance
            if expected is not None and expected != instance.instance_id:
                raise ServiceControlError("instance_changed")
            stopper = ManagedServiceStopOperationV1(journal, namespace, service, instance, runtime_root=runtime)
            try:
                stopped = await stopper.run(deadline=deadline)
            finally:
                await stopper.close()
            if not stopped.cleanly_stopped:
                raise ServiceControlError("cleanup_incomplete")
            if operation == "stop":
                return {"state": "not_running"}

        if operation in {"start", "restart"}:
            starter = ManagedServiceCoordinatorV1(
                journal, namespace, service, runtime_root=runtime, endpoint=ENDPOINT,
                temporary_override=defaults.temporary_override,
                request_factory=lambda invocation, descriptor: coding_managed_process_request(
                    invocation, descriptor, executable=sys.executable, environment=os.environ,
                ),
            )
            owners.push_async_callback(starter.close)
            ready = await starter.ensure_started(deadline=deadline)
            return _running(ready)

        status = _recorded_state(state)
        if status != "running":
            return {"state": status}
        assert state is not None
        connection = ManagedConnectionLeaseV1(
            journal, namespace, service, state.handoff.instance, runtime_root=runtime, endpoint=ENDPOINT,
        )
        owners.push_async_callback(connection.close)
        await connection.prepare(deadline=deadline)
        return _running(connection)


def _absent(operation: str, expected: str | None) -> dict[str, object]:
    if expected is not None or operation == "restart":
        raise ServiceControlError("instance_changed")
    return {"state": "not_running"}


def _recorded_state(state: ManagedServiceStateV1 | None) -> str:
    if state is None or state.cleanly_stopped:
        return "not_running"
    if state.evidence.process_exited:
        raise ServiceControlError("unclean_exit")
    if state.handoff.stop_requested:
        return "stopping"
    return {
        ManagedHandoffPhaseV1.COMMITTED: "running",
        ManagedHandoffPhaseV1.ABORTING: "unknown",
    }.get(state.handoff.phase, "starting")


def _running(connection: ManagedConnectionLeaseV1) -> dict[str, object]:
    if connection.application_id != APPLICATION_ID or connection.execution_client is None:
        raise ServiceControlError("protocol_incompatible")
    return {
        "state": "running",
        "instanceId": connection.instance.instance_id,
        "serviceInstanceId": connection.execution_client.service_instance_id,
        "recordRoot": str(connection.record_root),
    }
