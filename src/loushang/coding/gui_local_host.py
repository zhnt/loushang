"""One bounded desktop management request over existing managed owners.

This short-lived native helper is neither a service nor an Agent Runtime.
Its private response goes to Rust; record paths never contain credentials.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from secrets import token_hex
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
from loushang.apphost.managed.discovery import ManagedDiscoveryV1
from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
from loushang.apphost.managed.mux_creation import ManagedMuxCreateOperationV1
from loushang.apphost.managed.namespace_admission import ManagedNamespaceAdmissionV1
from loushang.apphost.managed.paths import resolve_managed_service_paths
from loushang.apphost.managed.registry import ManagedMuxReservationV1
from loushang.apphost.managed.service_admission import ManagedServiceAdmissionV1
from loushang.apphost.managed.stopper import ManagedServiceStopOperationV1
from loushang.appserver.client import AppConnectionClosedError
from loushang.appserver.local_auth import LocalAuthenticationError
from loushang.appserver.local_record import LocalRecordError
from loushang.appserver.protocol import AppServiceError, InvalidAppMessageError
from loushang.appservice.managed_mux import project_mux_name
from loushang.hosting.errors import HostingError

from .managed_process import APPLICATION_ID, ENDPOINT, coding_managed_process_request

TEMPORARY_MUX = "gui-temporary"


async def operate(request: dict, *, request_factory=None) -> dict:
    """Inspect without creation; mutate only on an explicit native action.

    The optional factory is a Python test seam, never accepted from wire input.
    Every owner is retained before fallible IO and closed in reverse order.
    """
    reply = {"version": "gui-local-host/v1", "supported": sys.platform == "linux",
             "state": "unknown", "errorCode": None}
    if sys.platform != "linux":
        return {**reply, "errorCode": "platform_unsupported"}
    stage = "inspection"
    try:
        if (type(request) is not dict
                or set(request) - {"action", "workspace", "workspaceAction", "instanceId"}
                or request.get("action") not in {"status", "start", "connect", "stop", "restart", "workspace"}):
            raise ValueError("invalid request")
        action = request["action"]
        defaults = resolve_managed_defaults()
        namespace = defaults.namespace
        service = ManagedServiceKeyV1("coding", namespace.platform_home)
        runtime = str(defaults.platform.runtime)
        paths = resolve_managed_service_paths(namespace, service, runtime_root=runtime)
        deadline = monotonic() + (60 if action == "restart" else 30)
        reply.update(serviceId=service.service_id)
        factory = request_factory or (lambda invocation, descriptor: coding_managed_process_request(
            invocation, descriptor, executable=sys.executable, environment=os.environ))
        async with AsyncExitStack() as owners:
            admission = ManagedNamespaceAdmissionV1(namespace, runtime_root=runtime,
                                                   create_if_missing=action == "start")
            owners.push_async_callback(_settled_native, admission.close)
            try:
                registry = await _settled_native(lambda: admission.open(deadline=deadline, wait_for_lock=True))
            except ManagedStorageError as error:
                if error.code == "not_found" and action in {"status", "connect"}:
                    return {**reply, "state": "not_running"}
                raise
            discovery = ManagedDiscoveryV1(registry, namespace)
            observed = await _settled_native(lambda: discovery.inspect_service(service.service_id, deadline=deadline, wait_for_lock=True))
            if observed is None and action != "start":
                return {**reply, "state": "not_running"}
            if action == "start":
                admitted = ManagedServiceAdmissionV1(admission, service)
                owners.push_async_callback(_settled_native, admitted.close)
                journal = await _settled_native(lambda: admitted.open(deadline=deadline, wait_for_lock=True))
            else:
                journal = ManagedServiceJournalV1(registry, namespace, service, Path(paths.lifecycle), defer_open=True)
                owners.push_async_callback(_settled_native, journal.close)
                await _settled_native(lambda: journal.open(deadline=deadline, wait_for_lock=True))
            state = await _settled_native(lambda: journal.read(deadline=deadline, wait_for_lock=True))
            if state is not None:
                reply.update(instanceId=state.handoff.instance.instance_id,
                             pid=None if state.native_identity is None else state.native_identity.pid)
            if action in {"stop", "restart"}:
                if state is None or request.get("instanceId") != state.handoff.instance.instance_id:
                    return {**reply, "errorCode": "instance_changed"}
                stage = "stop"
                stopper = ManagedServiceStopOperationV1(journal, namespace, service,
                    state.handoff.instance, runtime_root=runtime)
                # Settle this owner before a restart can select a new instance.
                async with AsyncExitStack() as stopping:
                    stopping.push_async_callback(stopper.close)
                    state = await stopper.run(deadline=deadline)
                if not state.cleanly_stopped:
                    return {**reply, "state": "stopping", "errorCode": "cleanup_incomplete"}
                if action == "stop":
                    return {**reply, "state": "not_running", "cleanlyStopped": True}
            if action in {"start", "restart"}:
                stage = "start"
                starter = ManagedServiceCoordinatorV1(journal, namespace, service, runtime_root=runtime,
                    endpoint=ENDPOINT, request_factory=factory, temporary_override=defaults.temporary_override)
                owners.push_async_callback(starter.close)
                connection = await starter.ensure_started(deadline=deadline)
                state = await _settled_native(lambda: journal.read(deadline=deadline, wait_for_lock=True))
            else:
                if state is None or state.cleanly_stopped:
                    return {**reply, "state": "not_running"}
                if state.evidence.process_exited:
                    return {**reply, "state": "exited", "errorCode": "unclean_exit"}
                if state.handoff.stop_requested:
                    return {**reply, "state": "stopping"}
                if state.handoff.phase is not ManagedHandoffPhaseV1.COMMITTED:
                    return {**reply, "state": "unknown" if state.handoff.phase is ManagedHandoffPhaseV1.ABORTING else "starting"}
                stage = "connection"
                connection = ManagedConnectionLeaseV1(journal, namespace, service, state.handoff.instance,
                    runtime_root=runtime, endpoint=ENDPOINT)
                owners.push_async_callback(connection.close)
                await connection.prepare(deadline=deadline)
            if connection.application_id != APPLICATION_ID or connection.execution_client is None:
                return {**reply, "errorCode": "protocol_incompatible"}
            assert state is not None
            reply.update(state="running", instanceId=connection.instance.instance_id,
                         serviceInstanceId=connection.execution_client.service_instance_id,
                         pid=None if state.native_identity is None else state.native_identity.pid)
            reply.update(recordRoot=str(paths.connection))
            if action != "workspace":
                return reply
            from loushang.appserver.protocol import WorkspaceRequestV1

            operation = request.get("workspaceAction")
            if operation == "open-temporary":
                name = TEMPORARY_MUX
            else:
                result = await connection.client.workspace(WorkspaceRequestV1(operation, request.get("workspace")))
                reply["workspaces"] = [
                    {"path": item.path, "scope": item.scope.value, "scopeFingerprint": item.scope_fingerprint}
                    for item in result.workspaces
                ]
                if operation != "open":
                    return reply
                workspace = result.workspaces[0].path
                reply["workspace"] = workspace
                name = project_mux_name(workspace)
            stage = "mux"
            snapshot = await _settled_native(lambda: discovery.snapshot_namespace(deadline=deadline, wait_for_lock=True))
            reservations = {item.name: item.reservation for item in snapshot.muxes if item.service == service}
            live = await connection.client.list_muxes()
            available = sorted(item.name for item in live.mux_spaces if item.name in reservations)
            if name not in available:
                reservation = reservations.get(name)
                if reservation is None:
                    reservation = ManagedMuxReservationV1(name, service, token_hex(16))
                    try:
                        await _settled_native(lambda: registry.reserve_mux(reservation, deadline=deadline, wait_for_lock=True))
                    except ManagedStorageError as error:
                        if error.code != "conflict":
                            raise
                        winner = await _settled_native(lambda: discovery.resolve(name, deadline=deadline, wait_for_lock=True))
                        if winner is None or winner.service != service:
                            raise
                        reservation = winner.reservation
                creation = ManagedMuxCreateOperationV1(registry, journal, namespace, reservation,
                    runtime_root=runtime, endpoint=ENDPOINT, application_id=APPLICATION_ID,
                    request_factory=factory, temporary_override=defaults.temporary_override)
                owners.push_async_callback(creation.close)
                created = await creation.run(deadline=deadline)
                name = created.name
            reply.update(recordRoot=str(paths.connection), muxName=name)
            return reply
    except InvalidAppMessageError:
        return {**reply, "state": "unknown", "errorCode": "protocol_incompatible"}
    except LocalAuthenticationError:
        return {**reply, "state": "unknown", "errorCode": "authentication_failed"}
    except AppConnectionClosedError:
        return {**reply, "state": "unknown", "errorCode": "connection_failed"}
    except AppServiceError as error:
        return {**reply, "state": "unknown", "errorCode": error.code.value}
    except LocalRecordError as error:
        return {**reply, "state": "unknown", "errorCode": error.code.value}
    except ManagedStorageError as error:
        return {**reply, "state": "unknown", "errorCode": f"{stage}_{error.code}"}
    except HostingError as error:
        return {**reply, "state": "unknown", "errorCode": error.category.value}
    except (OSError, ValueError, TimeoutError):
        return {**reply, "state": "unknown", "errorCode": f"{stage}_failed"}


def main() -> None:
    try:
        payload = sys.stdin.buffer.read(16_385)
        if len(payload) > 16_384:
            raise ValueError("request too large")
        result = asyncio.run(operate(json.loads(payload)))
    except Exception:
        # Never expose arbitrary exception strings, invocation records or keys.
        result = {"version": "gui-local-host/v1", "supported": sys.platform == "linux",
                  "state": "unknown", "errorCode": "management_failed"}
    print(json.dumps(result, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
