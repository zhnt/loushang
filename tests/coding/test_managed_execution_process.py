"""Linux production Host and two real clients, with deterministic provider gates."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import asdict, replace
from pathlib import Path
from time import monotonic

import pytest

from loushang.apphost.managed.coordinator import ManagedServiceCoordinatorV1
from loushang.apphost.managed.stopper import ManagedServiceStopOperationV1
from loushang.coding.hosted.managed.process import (
    ENDPOINT,
    coding_managed_process_request,
)
from loushang.hosting.service import LinuxServiceObserverV1
from tests.apphost.test_managed_starter import owners as owners
from tests.coding.test_managed_process_entry import _stop_original

pytestmark = [
    pytest.mark.requires_host_runtime,
    pytest.mark.skipif(sys.platform != "linux", reason="Linux managed processes"),
]


@pytest.mark.parametrize("mode", ["normal", "abrupt", "lost"])
def test_execution_survives_client_process_and_recovers(owners, tmp_path, mode):
    journal, namespace, service, runtime = owners
    sessions = Path(namespace.platform_home) / "data/sessions"
    launches = []

    def request(invocation, descriptor):
        launches.append(invocation)
        original = coding_managed_process_request(
            invocation, descriptor, executable=sys.executable, environment=os.environ,
        )
        return replace(original, argv=(sys.executable, str(Path(__file__).with_name(
            "_managed_execution_host.py")), *original.argv[3:]))

    coordinators = [ManagedServiceCoordinatorV1(
        journal, namespace, service, runtime_root=runtime, endpoint=ENDPOINT, request_factory=request,
    ) for _ in range(2)]
    observer = None
    evidence = {"mode": mode, "test_pid": os.getpid()}

    def audit():
        path = tmp_path / "execution-audit.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    async def scenario():
        nonlocal observer
        clients = []
        stopper = None

        async def spawn(role):
            child = await asyncio.create_subprocess_exec(
                sys.executable, str(Path(__file__).with_name("_managed_execution_client.py")),
                str(tmp_path), role, mode, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            clients.append(child)
            return child

        async def message(child):
            line = await asyncio.wait_for(child.stdout.readline(), 30)
            assert line, (await child.stderr.read()).decode()
            return json.loads(line)

        try:
            first = await coordinators[0].ensure_started(deadline=monotonic() + 25)
            native = coordinators[0]._starter._process
            process = native._process
            observer = LinuxServiceObserverV1.reopen(native.identity)
            evidence["host_identity"] = asdict(native.identity)
            assert process.pid != os.getpid()
            assert first.execution_client is not None
            instance = first.instance
            service_id = first.execution_client.service_instance_id
            second = await coordinators[1].ensure_started(deadline=monotonic() + 10)
            assert second.instance == instance and second.execution_client.service_instance_id == service_id
            assert len(launches) == 1 and coordinators[1]._starter._process is None
            await asyncio.gather(*(item.close() for item in coordinators))
            assert process.poll() is None and not observer.exited()

            a = await spawn("a")
            receipt = await message(a)
            evidence["a"] = receipt
            assert await asyncio.wait_for(a.wait(), 10) == (0 if mode == "normal" else 17)
            assert receipt["service_instance_id"] == service_id
            assert process.poll() is None and not observer.exited()
            evidence["a_returncode"] = a.returncode
            evidence["a_exited_at"] = monotonic()
            assert "model_returned" not in [item["kind"] for item in audit()]
            (tmp_path / "advance-after-a").touch()
            deadline = monotonic() + 10
            while "model_progressed" not in [item["kind"] for item in audit()]:
                assert monotonic() < deadline and process.poll() is None
                await asyncio.sleep(0.01)
            accepted, = [item for item in audit() if item["kind"] == "accepted"]
            if mode != "lost":
                assert receipt["execution_id"] == accepted["execution_id"]
            else:
                assert receipt["response_received"] is False and "execution_id" not in receipt
            b = await spawn("b")
            running = await message(b)
            evidence["b_running"] = running
            evidence["b_running_at"] = monotonic()
            assert running["kind"] == "b_running" and running["status"] == "running"
            for key in ("execution_id", "session_id", "submission_id", "service_instance_id"):
                assert running[key] == accepted[key]
            assert len({os.getpid(), process.pid, a.pid, b.pid}) == 4
            assert running["missing_submission"] == "unknown"
            assert process.poll() is None and not observer.exited()
            (tmp_path / "finish-after-b").touch()
            terminal = await message(b)
            evidence["b_terminal"] = terminal
            assert terminal["kind"] == "b_terminal" and terminal["status"] == "succeeded"
            for key in ("execution_id", "session_id", "submission_id", "service_instance_id"):
                assert terminal[key] == running[key]
            assert await asyncio.wait_for(b.wait(), 10) == 0, (await b.stderr.read()).decode()
            evidence["b_returncode"] = b.returncode
            events = audit()
            assert [item["kind"] for item in events] == [
                "accepted", "model_entered", "model_progressed", "model_returned",
            ]
            assert all(item["pid"] == process.pid for item in events)
            assert events[2]["time"] > evidence["a_exited_at"]
            assert len(list(sessions.rglob("*.jsonl"))) == 1
            evidence["audit"] = events
            stopper = ManagedServiceStopOperationV1(journal, namespace, service, instance, runtime_root=runtime)
            stopping = asyncio.create_task(stopper.run(deadline=monotonic() + 20))
            while not stopping.done():
                process.poll()  # Reap our child so native group settlement can complete.
                await asyncio.sleep(0.01)
            stopped = await stopping
            assert stopped.cleanly_stopped and journal.read().cleanly_stopped
            assert process.wait(timeout=5) == 0 and observer.exited()
            evidence["stop_evidence"] = asdict(stopped.evidence)
            evidence["host_returncode"] = process.returncode
        finally:
            (tmp_path / "advance-after-a").touch()
            (tmp_path / "finish-after-b").touch()
            for child in clients:
                if child.returncode is None:
                    child.terminate()
                await asyncio.wait_for(child.wait(), 10)
            if stopper is not None:
                await stopper.close()
            await asyncio.gather(*(item.close() for item in coordinators))

    try:
        asyncio.run(asyncio.wait_for(scenario(), 100))
        destination = os.environ.get("LOUSHANG_STAGE1B_EVIDENCE_DIR")
        if destination:
            Path(destination).mkdir(parents=True, exist_ok=True)
            (Path(destination) / f"{mode}.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    finally:
        native = coordinators[0]._starter._process
        if observer is None and native is not None and native._process is not None and native._process.poll() is None:
            observer = LinuxServiceObserverV1.reopen(native.identity)
        _stop_original(coordinators[0]._starter, observer)
        _stop_original(coordinators[1]._starter)


@pytest.mark.parametrize("linked", [False, True], ids=["default", "linked-project"])
def test_managed_image_upload_execution_and_transcript_restore(owners, tmp_path, linked):
    import base64
    from hashlib import sha256

    from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
    from loushang.apphost.managed.mux_creation import ManagedMuxCreateOperationV1
    from loushang.apphost.managed.paths import resolve_managed_service_paths
    from loushang.apphost.managed.registry import (
        ManagedMuxReservationV1,
        ManagedRegistryV1,
    )
    from loushang.appserver.execution.model import (
        ExecutionErrorCodeV1,
        ExecutionServiceErrorV1,
        ResourceRefV1,
    )
    from loushang.appserver.execution.resources import SessionResourceQueryV1
    from loushang.appserver.protocol import (
        AppErrorCodeV1,
        AppServiceError,
        InteractionOutcomeV1,
        InteractionRespondV1,
        MuxAttachV1,
        MuxMemberOpenV1,
        MuxSelectorV1,
        SessionEventKindV1,
        SessionOpenSpecV1,
        SessionSnapshotRequestV1,
        WorkspaceRequestV1,
    )
    from loushang.coding.hosted.managed.process import APPLICATION_ID

    journal, namespace, service, runtime = owners
    paths = resolve_managed_service_paths(namespace, service, runtime_root=runtime)
    registry = ManagedRegistryV1(Path(paths.registry), namespace)
    journal = ManagedServiceJournalV1(registry, namespace, service, Path(paths.lifecycle))
    image64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jCx0AAAAASUVORK5CYII="
    image = base64.b64decode(image64)
    digest = sha256(image).hexdigest()
    (tmp_path / "image-model").touch()

    def request(invocation, descriptor):
        original = coding_managed_process_request(
            invocation, descriptor, executable=sys.executable, environment=os.environ,
        )
        return replace(original, argv=(sys.executable, str(Path(__file__).with_name(
            "_managed_execution_host.py")), *original.argv[3:]))

    async def scenario():
        creations = []
        stopper = None

        async def connect():
            creation = ManagedMuxCreateOperationV1(
                registry, journal, namespace, ManagedMuxReservationV1("main", service, "b" * 32),
                runtime_root=runtime, endpoint=ENDPOINT, application_id=APPLICATION_ID,
                request_factory=request,
            )
            mux = await creation.run(deadline=monotonic() + 20)
            native = creation._coordinator._starter._process
            creations.append((creation, LinuxServiceObserverV1.reopen(native.identity)))
            connection = creation.connection
            execution = connection.execution_client
            assert execution is not None
            selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
            attachment = await connection.client.attach_mux(MuxAttachV1(selector))
            return creation, connection, execution, selector, attachment

        try:
            creation, connection, execution, selector, _ = await connect()
            project = tmp_path / "project"
            if linked:
                project.mkdir()
            workspace_request = (WorkspaceRequestV1("register", str(project)) if linked else
                                 WorkspaceRequestV1("open-workspace", workspace_id="default"))
            scope, = (await connection.client.workspace(workspace_request)).workspaces
            space = await connection.client.open_member(MuxMemberOpenV1(selector, SessionOpenSpecV1(
                "coding", "image-continuity", scope.scope, scope.scope_fingerprint, "Images",
            )))
            attachment = await connection.client.attach_mux(MuxAttachV1(selector))
            control = SessionSnapshotRequestV1(attachment.attachment_id, attachment.controller_generation,
                                               space.members[0].member_id)
            instance = execution.service_instance_id
            refs = (ResourceRefV1(digest, digest),)
            with pytest.raises(AppServiceError) as unavailable:
                await execution.submit_execution(control, instance, "missing", "", refs)
            assert unavailable.value.code is AppErrorCodeV1.RESOURCE_UNAVAILABLE
            for offset, data in ((0, image[:8]), (8, image[8:])):
                reply = await execution.session_resource(control, instance, SessionResourceQueryV1(
                    "upload", digest, offset, len(image), "image/png", base64.b64encode(data).decode(),
                ))
                assert bool(reply.resources) is bool(offset)
            assert not (await execution.session_resource(
                control, instance, SessionResourceQueryV1("list")
            )).resources, "an upload alone must not associate the image with history"
            accepted = await execution.submit_execution(control, instance, "image-submission", "", refs)
            with pytest.raises(ExecutionServiceErrorV1) as conflict:
                await execution.submit_execution(control, instance, "image-submission", "",
                                                 (ResourceRefV1(digest, "f" * 64),))
            assert conflict.value.code is ExecutionErrorCodeV1.SUBMISSION_CONFLICT

            async with asyncio.timeout(20):
                while True:
                    result = await execution.get_execution(control, instance, accepted.state.execution_id)
                    if result.state.status.terminal:
                        assert result.state.status.value == "succeeded", result
                        break
                    await asyncio.sleep(0.05)
            snapshot = await execution.snapshot_execution_session(control, instance)
            record, = [record for record in snapshot.source.source.records if record.resource_ids]
            assert record.record_id and record.resource_ids == (digest,)
            assert record.submission_id == "image-submission"
            assert any(item["kind"] == "model_images" and item["images"] == item["provider_payload_images"] == [digest] for item in (
                json.loads(line) for line in (tmp_path / "execution-audit.jsonl").read_text().splitlines()
            ))
            asset_root = Path(namespace.platform_home) / "data"
            assert len([path for path in asset_root.rglob(digest) if path.parent.name == "objects"]) == 1

            stopper = ManagedServiceStopOperationV1(journal, namespace, service, connection.instance, runtime_root=runtime)
            process = creation._coordinator._starter._process._process
            await creation.close()
            stop = asyncio.create_task(stopper.run(deadline=monotonic() + 20))
            while not stop.done():
                process.poll()
                await asyncio.sleep(0.01)
            assert (await stop).cleanly_stopped

            (tmp_path / "image-model").unlink()
            _, restored_connection, reopened, _, restored = await connect()
            restored_control = SessionSnapshotRequestV1(restored.attachment_id, restored.controller_generation,
                                                        restored.mux_space.members[0].member_id)
            new_instance = reopened.service_instance_id
            assert new_instance != instance
            restored_snapshot = await reopened.snapshot_execution_session(restored_control, new_instance)
            assert record in restored_snapshot.source.source.records
            listing = await reopened.session_resource(restored_control, new_instance, SessionResourceQueryV1("list"))
            assert [item.id for item in listing.resources] == [digest]
            loaded = await reopened.session_resource(restored_control, new_instance, SessionResourceQueryV1("read", digest))
            assert loaded.data == image64
            with pytest.raises(AppServiceError) as committed:
                await reopened.submit_execution(restored_control, new_instance, "image-submission", "", refs)
            assert committed.value.code is AppErrorCodeV1.RESOURCE_INPUT_COMMITTED
            with pytest.raises(ExecutionServiceErrorV1) as historical_conflict:
                await reopened.submit_execution(restored_control, new_instance, "image-submission", "different")
            assert historical_conflict.value.code is ExecutionErrorCodeV1.SUBMISSION_CONFLICT
            with pytest.raises(AppServiceError) as unsupported:
                await reopened.submit_execution(restored_control, new_instance, "unsupported", "", refs)
            assert unsupported.value.code is AppErrorCodeV1.IMAGE_INPUT_UNSUPPORTED
            file_data = "attached source only\n".encode()
            file_id = sha256(file_data).hexdigest()
            file_ref = ResourceRefV1(file_id, file_id)
            uploaded = await reopened.session_resource(restored_control, new_instance, SessionResourceQueryV1(
                "upload", file_id, 0, len(file_data), "text/plain",
                base64.b64encode(file_data).decode(), name="example.py",
            ))
            assert uploaded.resources[0].name == "example.py"
            file_submission = await reopened.submit_execution(
                restored_control, new_instance, "file-submission", f"read-session-file {file_id}", (file_ref,),
            )
            async with asyncio.timeout(20):
                while True:
                    result = await reopened.get_execution(restored_control, new_instance, file_submission.state.execution_id)
                    if result.state.status.terminal:
                        assert result.state.status.value == "succeeded", result
                        break
                    await asyncio.sleep(0.05)
            updated = await reopened.snapshot_execution_session(restored_control, new_instance)
            assert any(record.resource_ids == (file_id,) for record in updated.source.source.records)
            assert any(json.loads(row["text"])["text"] == file_data.decode()
                       for row in map(json.loads, (tmp_path / "execution-audit.jsonl").read_text().splitlines())
                       if row["kind"] == "model_received_file")
            if linked:
                directory = project / "folder"
                directory.mkdir()
                (directory / "nested.txt").write_text("host reference file contents")
                result = await reopened.session_resource(
                    restored_control, new_instance, SessionResourceQueryV1("reference", path=str(directory)),
                )
                resource, = result.resources
                assert resource.kind == "directory" and resource.source == "host_reference"
                assert resource.name == "folder"
                control_client = restored_connection.client

                async def operate(action):
                    receipt = await reopened.submit_execution(
                        restored_control, new_instance, f"host-reference-{action}",
                        f"host-resource-{action} {resource.id}", (ResourceRefV1(resource.id, resource.id),),
                    )
                    approvals = set()
                    async with asyncio.timeout(12):
                        while True:
                            for envelope in await control_client.read_events(
                                attachment_id=restored_control.attachment_id,
                                controller_generation=restored_control.controller_generation,
                            ):
                                event = envelope.event
                                if event.kind is SessionEventKindV1.INTERACTION_REQUESTED and event.interaction_id not in approvals:
                                    await control_client.respond_interaction(InteractionRespondV1(
                                        restored_control.attachment_id, restored_control.controller_generation,
                                        restored_control.member_id, event.interaction_id, InteractionOutcomeV1.APPROVE,
                                    ))
                                    approvals.add(event.interaction_id)
                            result = await reopened.get_execution(restored_control, new_instance, receipt.state.execution_id)
                            if result.state.status.terminal:
                                assert result.state.status.value == "succeeded", result
                                assert approvals, f"{action} bypassed Workspace approval"
                                return
                            await asyncio.sleep(0.05)

                await operate("read")
                await operate("write")
                assert (directory / "written.txt").read_text() == "allowed edit"
                assert any("host reference file contents" in row["text"]
                           for row in map(json.loads, (tmp_path / "execution-audit.jsonl").read_text().splitlines())
                           if row.get("tool") == "resource_read")
                directory.rename(project / "moved")
                with pytest.raises(AppServiceError) as unavailable_reference:
                    await reopened.submit_execution(
                        restored_control, new_instance, "host-reference-moved", "",
                        (ResourceRefV1(resource.id, resource.id),),
                    )
                assert unavailable_reference.value.code is AppErrorCodeV1.RESOURCE_UNAVAILABLE
            transcript = next((Path(namespace.platform_home) / "data/sessions").rglob("*.jsonl"))
            assert image64 not in transcript.read_text()
        finally:
            for creation, observer in creations:
                await creation.close()
                _stop_original(creation._coordinator._starter, observer)
            if stopper is not None:
                await stopper.close()

    try:
        asyncio.run(asyncio.wait_for(scenario(), 90))
    finally:
        journal.close()
        registry.close()
