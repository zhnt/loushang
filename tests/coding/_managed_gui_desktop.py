"""Opt-in visible Linux desktop acceptance using the stage 1B production child.

Start npm run dev:web in gui/ for the debug binary, then run with
PYTHONPATH=.:src uv run --no-sync --offline python tests/coding/_managed_gui_desktop.py.
The operator follows desktop.json steps and submits gui-final-1 through 4.
The coordinator acknowledges visual results with ack-first/ack-reconnect/ack-final.
No GUI input or execution submission is performed by this helper.
No provider network or developer Session data is used.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
from loushang.apphost.managed.mux_creation import ManagedMuxCreateOperationV1
from loushang.apphost.managed.paths import resolve_managed_service_paths
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
from tests.apphost.test_managed_starter import owners
from tests.coding.test_managed_process_entry import _stop_original

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / ".artifacts/stage1d" / ("manual-" + datetime.now().strftime("%Y%m%d-%H%M%S"))


async def run(workspace, supplied):
    (workspace / "desktop-acceptance").touch()
    (workspace / "desktop-scenario-v2").touch()
    _, namespace, service, runtime = supplied
    paths = resolve_managed_service_paths(namespace, service, runtime_root=runtime)
    registry = ManagedRegistryV1(Path(paths.registry), namespace)
    journal = ManagedServiceJournalV1(registry, namespace, service, Path(paths.lifecycle))

    def request(invocation, descriptor):
        original = coding_managed_process_request(invocation, descriptor,
                                                  executable=sys.executable, environment=os.environ)
        return replace(original, argv=(sys.executable, str(Path(__file__).with_name(
            "_managed_execution_host.py")), *original.argv[3:]))

    creation = ManagedMuxCreateOperationV1(registry, journal, namespace,
        ManagedMuxReservationV1("main", service, "b" * 32), runtime_root=runtime, endpoint=ENDPOINT,
        application_id=APPLICATION_ID, request_factory=request)
    observer, stopper = None, None
    clients = []
    evidence = {"workspace": str(workspace)}

    def publish():
        (EVIDENCE / "desktop.json").write_text(json.dumps(evidence, indent=2))

    async def wait_for(predicate, label):
        evidence["step"] = label
        publish()
        deadline = monotonic() + 900
        while not predicate():
            assert monotonic() < deadline, f"manual step timed out: {label}"
            assert process.poll() is None, "Host exited during manual acceptance"
            await asyncio.sleep(0.2)

    def audit():
        file = workspace / "execution-audit.jsonl"
        return [json.loads(line) for line in file.read_text().splitlines()] if file.exists() else []

    async def launch():
        child = await asyncio.create_subprocess_exec(
            str(ROOT / "gui/src-tauri/target/debug/harness-gui"),
            "--loushang-app-record-root", str(paths.connection), "--loushang-mux-name", "main",
            stdout=log, stderr=log,
        )
        clients.append(child)
        return child

    EVIDENCE.mkdir(exist_ok=True)
    with (EVIDENCE / "desktop.log").open("w") as log:
        try:
            mux = await creation.run(deadline=monotonic() + 25)
            native = creation._coordinator._starter._process
            process = native._process
            observer = LinuxServiceObserverV1.reopen(native.identity)
            connection = creation.connection
            instance = connection.instance
            selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
            await connection.client.attach_mux(MuxAttachV1(selector))
            scope = connection.scopes[0]
            space = await connection.client.open_member(MuxMemberOpenV1(selector, SessionOpenSpecV1(
                "coding", "desktop-stage1d", scope.scope, scope.fingerprint, "Managed desktop acceptance",
            )))
            evidence.update(host=asdict(native.identity), service_instance_id=connection.execution_client.service_instance_id,
                            session_id=space.members[0].session.session_id, mux_id=mux.mux_space_id)
            await creation.close()
            a = await launch()
            evidence["gui_a_pid"] = a.pid
            publish()
            def events(kind):
                return [item for item in audit() if item["kind"] == kind]

            def terminal(number, status):
                accepted = events("accepted")
                return len(accepted) >= number and any(
                    item["execution_id"] == accepted[number - 1]["execution_id"] and item["status"] == status
                    for item in events("execution_terminal"))

            await wait_for(lambda: len(events("model_entered")) == 1, "submit gui-final-1 in GUI A")
            assert events("model_entered")[0]["input"] == "gui-final-1"
            await asyncio.sleep(3)
            (workspace / "release-1").touch()
            await wait_for(lambda: terminal(1, "succeeded"), "first execution completing")
            await wait_for(lambda: (workspace / "ack-first").exists(), "confirm first reply visually, then submit gui-final-2")
            await wait_for(lambda: len(events("model_entered")) == 2, "submit gui-final-2 in GUI A")
            assert events("model_entered")[1]["input"] == "gui-final-2"
            await wait_for(lambda: a.returncode is not None, "close GUI A while second task is running")
            assert a.returncode == 0
            assert not terminal(2, "succeeded") and not events("interrupt")
            assert process.poll() is None and not observer.exited()
            evidence["a_exit_at"] = monotonic()
            (workspace / "release-2").touch()
            await wait_for(lambda: terminal(2, "succeeded"), "second task completing after GUI A exit")
            assert next(item for item in events("model_progressed") if item["number"] == 2)["time"] > evidence["a_exit_at"]
            b = await launch()
            evidence["gui_b_pid"] = b.pid
            evidence["b_started_at"] = monotonic()
            publish()
            original = events("accepted")[1]
            await wait_for(lambda: any(item["time"] > evidence["b_started_at"]
                and item["session_id"] == evidence["session_id"]
                and item["execution_id"] == original["execution_id"]
                and item["status"] == "succeeded" for item in events("snapshot_read")), "GUI B reading original Session and Execution")
            await wait_for(lambda: (workspace / "ack-reconnect").exists(), "confirm restored replies, then submit gui-final-3")
            await wait_for(lambda: len(events("model_entered")) == 3, "submit gui-final-3 in GUI B and click stop")
            assert events("model_entered")[2]["input"] == "gui-final-3"
            await wait_for(lambda: terminal(3, "interrupted"), "click GUI stop for third execution")
            third = events("accepted")[2]
            assert any(item["execution_id"] == third["execution_id"] for item in events("interrupt"))
            assert any(item["number"] == 3 for item in events("model_cancelled"))
            assert process.poll() is None and not observer.exited()
            await wait_for(lambda: len(events("model_entered")) == 4, "submit gui-final-4 after interruption")
            assert events("model_entered")[3]["input"] == "gui-final-4"
            await asyncio.sleep(3)
            (workspace / "release-4").touch()
            await wait_for(lambda: terminal(4, "succeeded"), "fourth execution completing")
            await wait_for(lambda: (workspace / "ack-final").exists(), "confirm fourth reply visually and close GUI B")
            await wait_for(lambda: b.returncode is not None, "close GUI B")
            assert b.returncode == 0
            accepted = events("accepted")
            assert len(accepted) == 4 and len(events("model_entered")) == 4
            assert len({item["submission_id"] for item in accepted}) == 4
            assert len({item["execution_id"] for item in accepted}) == 4
            assert {item["session_id"] for item in accepted} == {evidence["session_id"]}
            assert {item["service_instance_id"] for item in accepted} == {evidence["service_instance_id"]}
            assert len(events("agent_created")) == 1
            evidence["audit"] = audit()
            stopper = ManagedServiceStopOperationV1(journal, namespace, service, instance, runtime_root=runtime)
            task = asyncio.create_task(stopper.run(deadline=monotonic() + 20))
            while not task.done():
                process.poll()
                await asyncio.sleep(0.01)
            stopped = await task
            assert stopped.cleanly_stopped and process.wait(timeout=5) == 0
            evidence.update(stop=asdict(stopped.evidence), completed=True)
            publish()
        except BaseException as error:
            evidence["failure"] = repr(error)
            publish()
            raise
        finally:
            (workspace / "advance-after-a").touch()
            (workspace / "finish-after-b").touch()
            for child in clients:
                if child.returncode is None:
                    child.terminate()
                await child.wait()
            if stopper is not None:
                await stopper.close()
            await creation.close()
            _stop_original(creation._coordinator._starter, observer)
            journal.close()
            registry.close()
            for name in ("execution-audit.jsonl", "host-diagnostic.log"):
                if (workspace / name).exists():
                    shutil.copy2(workspace / name, EVIDENCE / name)


if __name__ == "__main__":
    print(f"Evidence: {EVIDENCE}", flush=True)
    with tempfile.TemporaryDirectory(prefix="ls1d-") as directory:
        workspace = Path(directory)
        fixture = owners.__wrapped__(workspace, SimpleNamespace())
        try:
            asyncio.run(run(workspace, next(fixture)))
        finally:
            fixture.close()
