"""Opt-in visible Linux desktop acceptance using the stage 1B production child.

Start npm run dev:web in gui/ for the debug binary, then run with
PYTHONPATH=.:src uv run --no-sync --offline python tests/coding/_managed_gui_desktop.py.
The operator submits in GUI A, closes its window while running, inspects GUI B,
then touches the published workspace/finish-after-b gate and closes GUI B.
No provider network or developer Session data is used.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from dataclasses import asdict, replace
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
EVIDENCE = ROOT / ".artifacts/stage1d"


async def run(workspace, supplied):
    (workspace / "desktop-acceptance").touch()
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
            assert await asyncio.wait_for(a.wait(), 180) == 0
            events = audit()
            assert [item["kind"] for item in events] == ["accepted", "model_entered"]
            assert process.poll() is None and not observer.exited()
            evidence["a_exit_at"] = monotonic()
            (workspace / "advance-after-a").touch()
            b = await launch()
            evidence["gui_b_pid"] = b.pid
            publish()
            assert await asyncio.wait_for(b.wait(), 180) == 0
            events = audit()
            assert [item["kind"] for item in events] == ["accepted", "model_entered", "model_progressed", "model_returned"]
            assert events[2]["time"] > evidence["a_exit_at"]
            assert process.poll() is None and not observer.exited()
            evidence["audit"] = events
            stopper = ManagedServiceStopOperationV1(journal, namespace, service, instance, runtime_root=runtime)
            task = asyncio.create_task(stopper.run(deadline=monotonic() + 20))
            while not task.done():
                process.poll()
                await asyncio.sleep(0.01)
            stopped = await task
            assert stopped.cleanly_stopped and process.wait(timeout=5) == 0
            evidence.update(stop=asdict(stopped.evidence), completed=True)
            publish()
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


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="ls1d-") as directory:
        workspace = Path(directory)
        fixture = owners.__wrapped__(workspace, SimpleNamespace())
        try:
            asyncio.run(run(workspace, next(fixture)))
        finally:
            fixture.close()
