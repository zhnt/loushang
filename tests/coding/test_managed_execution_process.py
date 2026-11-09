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
from loushang.coding.managed_process import ENDPOINT, coding_managed_process_request
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
            assert len(list(sessions.glob("*.jsonl"))) == 1
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
