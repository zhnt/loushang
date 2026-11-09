"""Separate stage 1B client processes; B has no open/submit recovery path."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from time import monotonic
from uuid import uuid4

from loushang.apphost.managed.contracts import ManagedNamespaceV1, ManagedServiceKeyV1
from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
from loushang.apphost.managed.mux_creation import ManagedMuxCreateOperationV1
from loushang.apphost.managed.paths import resolve_managed_service_paths
from loushang.apphost.managed.registry import ManagedMuxReservationV1, ManagedRegistryV1
from loushang.appserver.local import LocalAppClientConnectionV1
from loushang.appserver.local_record import LocalConnectionDirectoryV1
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    MuxAttachV1,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionOpenSpecV1,
    SessionSnapshotRequestV1,
)
from loushang.coding.managed_process import APPLICATION_ID, ENDPOINT

root, role, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
namespace = ManagedNamespaceV1(str(root / "platform"), os.geteuid(), "a" * 32)
service = ManagedServiceKeyV1("coding", str(root))
paths = resolve_managed_service_paths(namespace, service, runtime_root=str(root / "runtime"))


def emit(kind, **fields):
    print(json.dumps({"kind": kind, "pid": os.getpid(), **fields}), flush=True)


async def until(predicate):
    deadline = monotonic() + 25
    while not predicate():
        assert monotonic() < deadline
        await asyncio.sleep(0.01)


def audit_contains(kind):
    path = root / "execution-audit.jsonl"
    return path.exists() and any(json.loads(line)["kind"] == kind for line in path.read_text().splitlines())


async def client_a():
    registry = ManagedRegistryV1(Path(paths.registry), namespace)
    journal = ManagedServiceJournalV1(registry, namespace, service, Path(paths.lifecycle))

    def no_spawn(*args):
        raise AssertionError("Client A must reuse the existing production Host")

    creation = ManagedMuxCreateOperationV1(registry, journal, namespace,
        ManagedMuxReservationV1("main", service, "b" * 32), runtime_root=str(root / "runtime"),
        endpoint=ENDPOINT, application_id=APPLICATION_ID, request_factory=no_spawn)
    try:
        mux = await creation.run(deadline=monotonic() + 20)
        connection = creation.connection
        client, execution = connection.client, connection.execution_client
        assert execution is not None
        if mode.startswith("stop-"):
            await client_stop(connection, mux)
            return
        selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
        await client.attach_mux(MuxAttachV1(selector))
        scope = connection.scopes[0]
        space = await client.open_member(MuxMemberOpenV1(selector, SessionOpenSpecV1(
            "coding", "stage1b-continuity", scope.scope, scope.fingerprint, "stage1b",
        )))
        attachment = await client.attach_mux(MuxAttachV1(selector))
        control = SessionSnapshotRequestV1(attachment.attachment_id, attachment.controller_generation,
                                          space.members[0].member_id)
        snapshot = await client.snapshot_session(control)
        intent = {"managed_instance": connection.instance.instance_id,
                  "service_instance_id": execution.service_instance_id, "mux_id": mux.mux_space_id,
                  "session_id": snapshot.identity.session_id, "submission_id": uuid4().hex,
                  "attachment_id": attachment.attachment_id, "generation": attachment.controller_generation,
                  "member_id": control.member_id, "a_pid": os.getpid()}
        # Persist before sending, including in the unknown-outcome case.
        (root / "intent.json").write_text(json.dumps(intent))
        if mode == "lost":
            # Real TCP remains writable, but no response bytes can reach the client decoder.
            connection._connection._writer.transport.pause_reading()
        pending = asyncio.create_task(execution.submit_execution(
            control, execution.service_instance_id, intent["submission_id"], "stage1b held task",
        ))
        if mode == "lost":
            await until(lambda: audit_contains("model_entered"))
            assert not pending.done(), "acceptance response unexpectedly reached A"
            emit("a_unknown", **intent, response_received=False)
            os._exit(17)
        accepted = await pending
        await until(lambda: audit_contains("model_entered"))
        running = await execution.get_execution(control, execution.service_instance_id, accepted.state.execution_id)
        assert running.state.status.value == "running"
        emit("a_accepted", **intent, execution_id=accepted.state.execution_id, status="running")
        if mode == "abrupt":
            os._exit(17)
    finally:
        await creation.close()
        journal.close()
        registry.close()


async def client_stop(connection, mux):
    client, execution = connection.client, connection.execution_client
    selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
    scope = connection.scopes[0]
    count = 1 if mode == "stop-single" else 3
    for index in range(count):
        await client.attach_mux(MuxAttachV1(selector))
        space = await client.open_member(MuxMemberOpenV1(selector, SessionOpenSpecV1(
            "coding", f"stop-{index}", scope.scope, scope.fingerprint, f"stop-{index}",
        )))
    attachment = await client.attach_mux(MuxAttachV1(selector))
    control = SessionSnapshotRequestV1(attachment.attachment_id, attachment.controller_generation,
                                      space.members[0].member_id)
    submission = uuid4().hex
    accepted = await execution.submit_execution(control, execution.service_instance_id, submission, "active stop")
    await until(lambda: audit_contains("model_entered"))
    running = await execution.get_execution(control, execution.service_instance_id, accepted.state.execution_id)
    assert running.state.status.value == "running"
    emit("stop_ready", service_instance_id=execution.service_instance_id, submission_id=submission,
         execution_id=running.state.execution_id, session_id=running.identity.session_id,
         sessions=[member.session.session_id for member in space.members], status="running")
    await until(lambda: audit_contains("local_fenced"))
    try:
        await execution.submit_execution(control, execution.service_instance_id, uuid4().hex, "must not execute")
    except Exception as error:
        # Require a real protocol error; an arbitrary transport/test exception
        # cannot satisfy the concurrent admission assertion.
        assert isinstance(error, AppServiceError), repr(error)
        assert error.code is AppErrorCodeV1.SERVICE_CLOSED
        emit("stop_rejected", error=error.code.value)
    else:
        raise AssertionError("Host admitted execution after stop fence")
    finally:
        (root / "release-close").touch()


async def client_b():
    intent = json.loads((root / "intent.json").read_text())
    directory = LocalConnectionDirectoryV1(Path(paths.connection))
    connection = LocalAppClientConnectionV1(directory, ENDPOINT, expected_instance=intent["managed_instance"])
    try:
        await connection.start()
        client, execution = connection.client, connection.execution_client
        assert execution is not None and execution.service_instance_id == intent["service_instance_id"]
        muxes = (await client.list_muxes()).mux_spaces
        assert len(muxes) == 1 and muxes[0].mux_space_id == intent["mux_id"]
        deadline = monotonic() + 10
        while True:
            try:
                attachment = await client.attach_mux(MuxAttachV1(MuxSelectorV1(mux_space_id=intent["mux_id"])))
                break
            except AppServiceError as error:
                if error.code is not AppErrorCodeV1.ALREADY_ATTACHED or monotonic() >= deadline:
                    raise
                await asyncio.sleep(0.01)
        control = SessionSnapshotRequestV1(attachment.attachment_id, attachment.controller_generation, intent["member_id"])
        assert attachment.attachment_id != intent["attachment_id"]
        assert attachment.controller_generation > intent["generation"]
        recovered = await execution.find_execution_by_submission(control, execution.service_instance_id, intent["submission_id"])
        assert recovered is not None and recovered.identity.session_id == intent["session_id"]
        assert recovered.state.status.value == "running"
        # A lookup miss is explicitly unknown, never an invitation to resubmit.
        missing = await execution.find_execution_by_submission(control, execution.service_instance_id, "never-submitted")
        assert missing is None
        snapshot = await client.snapshot_session(control)
        assert snapshot.identity == recovered.identity and snapshot.running
        emit("b_running", service_instance_id=execution.service_instance_id, execution_id=recovered.state.execution_id,
             session_id=snapshot.identity.session_id, submission_id=intent["submission_id"],
             attachment_id=attachment.attachment_id, generation=attachment.controller_generation,
             missing_submission="unknown", status="running")
        deadline = monotonic() + 25
        while True:
            record = await execution.get_execution(control, execution.service_instance_id, recovered.state.execution_id)
            if record.state.status.terminal:
                break
            assert monotonic() < deadline
            await asyncio.sleep(0.01)
        assert record.state.status.value == "succeeded"
        snapshot = await client.snapshot_session(control)
        assert not snapshot.running and snapshot.identity.session_id == intent["session_id"]
        answers = [item.text for item in snapshot.records if item.kind.value == "assistant"]
        assert answers == ["真实跨进程回复\nG14"]
        again = await execution.find_execution_by_submission(control, execution.service_instance_id, intent["submission_id"])
        assert again == record
        emit("b_terminal", service_instance_id=execution.service_instance_id, execution_id=record.state.execution_id,
             session_id=snapshot.identity.session_id, submission_id=intent["submission_id"], status="succeeded", answers=answers)
    finally:
        await connection.close()
        directory.close()


asyncio.run(asyncio.wait_for(client_a() if role == "a" else client_b(), 55))
