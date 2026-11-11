"""Production Rust AppClient in distinct processes against the managed Host."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import asdict, replace
from pathlib import Path
from time import monotonic
from uuid import uuid4

import pytest

from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
from loushang.apphost.managed.mux_creation import ManagedMuxCreateOperationV1
from loushang.apphost.managed.paths import (
    resolve_managed_registry_root,
    resolve_managed_service_paths,
)
from loushang.apphost.managed.registry import ManagedMuxReservationV1, ManagedRegistryV1
from loushang.apphost.managed.stopper import ManagedServiceStopOperationV1
from loushang.appserver.protocol import (
    MuxAttachV1,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionOpenSpecV1,
)
from loushang.coding.managed_process import (
    APPLICATION_ID,
    ENDPOINT,
    coding_managed_process_request,
)
from loushang.hosting.service import LinuxServiceObserverV1
from tests.apphost.test_managed_starter import owners as owners
from tests.coding.test_managed_process_entry import _stop_original

pytestmark = [pytest.mark.requires_host_runtime,
              pytest.mark.skipif(sys.platform != "linux", reason="Linux managed GUI client")]
ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "gui/contracts/rust/target/debug/control_probe"


@pytest.mark.parametrize("mode", ["normal", "abrupt", "interrupt"])
def test_managed_rust_client_reconnects_without_replay(owners, tmp_path, mode):
    if not PROBE.is_file():
        pytest.skip("build existing GUI contract probes before native acceptance")
    journal, namespace, service, runtime = owners

    def request(invocation, descriptor):
        original = coding_managed_process_request(invocation, descriptor,
                                                  executable=sys.executable, environment=os.environ)
        return replace(original, argv=(sys.executable, str(Path(__file__).with_name(
            "_managed_execution_host.py")), *original.argv[3:]))

    registry = ManagedRegistryV1(Path(resolve_managed_registry_root(namespace)), namespace)
    paths = resolve_managed_service_paths(namespace, service, runtime_root=runtime)
    journal = ManagedServiceJournalV1(registry, namespace, service, Path(paths.lifecycle))
    creation = ManagedMuxCreateOperationV1(
        registry, journal, namespace, ManagedMuxReservationV1("main", service, "b" * 32),
        runtime_root=runtime, endpoint=ENDPOINT, application_id=APPLICATION_ID, request_factory=request,
    )
    observer = None
    evidence = {"mode": mode}

    def audit():
        path = tmp_path / "execution-audit.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    async def scenario():
        nonlocal observer
        clients, outputs = [], []
        stopper = None
        process = None
        try:
            mux = await creation.run(deadline=monotonic() + 25)
            native = creation._coordinator._starter._process
            process = native._process
            observer = LinuxServiceObserverV1.reopen(native.identity)
            connection = creation.connection
            instance = connection.instance
            service_id = connection.execution_client.service_instance_id
            selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
            await connection.client.attach_mux(MuxAttachV1(selector))
            from loushang.appserver.protocol import WorkspaceRequestV1

            scope, = (await connection.client.workspace(WorkspaceRequestV1("register", str(tmp_path)))).workspaces
            space = await connection.client.open_member(MuxMemberOpenV1(selector, SessionOpenSpecV1(
                "coding", "gui-stage1d", scope.scope, scope.scope_fingerprint, "GUI managed Session",
            )))
            session_id = space.members[0].session.session_id
            record_root = creation._coordinator._starter._layout.paths.connection
            await creation.close()
            submission = uuid4().hex
            evidence.update(host=asdict(native.identity), session_id=session_id,
                            submission_id=submission, service_instance_id=service_id)

            async def spawn(action, text="held managed GUI task"):
                child = await asyncio.create_subprocess_exec(
                    str(PROBE), str(record_root), "5000", "main", session_id, submission, text, action,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                clients.append(child)
                return child

            async def message(child):
                line = await asyncio.wait_for(child.stdout.readline(), 20)
                assert line, (await child.stderr.read()).decode()
                value = json.loads(line)
                outputs.append({"pid": child.pid, **value})
                return value

            a = await spawn("submit-detach" if mode == "normal" else "submit")
            while True:
                value = await message(a)
                if value["type"] == "round" and any(
                    session["executions"]["active"] and session["executions"]["active"]["status"] == "running"
                    for session in value["payload"]["sessions"]):
                    break
            assert any(item["kind"] == "model_entered" for item in audit())
            if mode != "normal":
                a.terminate()
            assert await asyncio.wait_for(a.wait(), 10) == (0 if mode == "normal" else -15)
            assert process.poll() is None and not observer.exited()
            accepted, = [item for item in audit() if item["kind"] == "accepted"]
            evidence["execution_id"] = accepted["execution_id"]
            evidence["a_pid"] = a.pid
            (tmp_path / "advance-after-a").touch()
            deadline = monotonic() + 10
            while not any(item["kind"] == "model_progressed" for item in audit()):
                assert monotonic() < deadline
                await asyncio.sleep(0.01)
            b = await spawn("interrupt" if mode == "interrupt" else "find", accepted["execution_id"])
            initial = await message(b)
            assert initial["type"] == "initial"
            assert initial["payload"]["serviceInstanceId"] == service_id
            snapshot, = initial["payload"]["sessions"]
            assert snapshot["executions"]["identity"]["sessionId"] == session_id
            assert snapshot["executions"]["active"]["executionId"] == accepted["execution_id"]
            receipt = await message(b)
            assert receipt["type"] == "control" and receipt["accepted"]
            assert len({process.pid, a.pid, b.pid, os.getpid()}) == 4
            evidence["b_pid"] = b.pid
            if mode != "interrupt":
                (tmp_path / "finish-after-b").touch()
            while True:
                value = await message(b)
                if value["type"] != "round":
                    continue
                snapshot, = value["payload"]["sessions"]
                terminal = snapshot["executions"]["latestTerminal"]
                if terminal:
                    assert terminal["status"] == ("interrupted" if mode == "interrupt" else "succeeded")
                    assert terminal["executionId"] == accepted["execution_id"]
                    if mode != "interrupt":
                        assert any(item["kind"] == "assistant" and item["text"] == "真实跨进程回复\nG14"
                                   for item in snapshot["source"]["source"]["records"])
                    break
            assert await asyncio.wait_for(b.wait(), 10) == 0, (await b.stderr.read()).decode()
            assert process.poll() is None and not observer.exited()
            assert len([item for item in audit() if item["kind"] == "accepted"]) == 1
            assert len([item for item in audit() if item["kind"] == "model_entered"]) == 1
            evidence["audit"], evidence["rust_output"] = audit(), outputs
            stopper = ManagedServiceStopOperationV1(journal, namespace, service, instance, runtime_root=runtime)
            task = asyncio.create_task(stopper.run(deadline=monotonic() + 20))
            while not task.done():
                process.poll()
                await asyncio.sleep(0.01)
            result = await task
            assert result.cleanly_stopped and process.wait(timeout=5) == 0
            evidence["stop"] = asdict(result.evidence)
        finally:
            (tmp_path / "advance-after-a").touch()
            (tmp_path / "finish-after-b").touch()
            for client in clients:
                if client.returncode is None:
                    client.terminate()
                await asyncio.wait_for(client.wait(), 10)
            if stopper is not None:
                await stopper.close()
            await creation.close()

    try:
        asyncio.run(asyncio.wait_for(scenario(), 100))
        target = ROOT / ".artifacts/stage1d"
        target.mkdir(exist_ok=True)
        (target / f"rust-{mode}.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False))
    finally:
        _stop_original(creation._coordinator._starter, observer)
        journal.close()
        registry.close()
