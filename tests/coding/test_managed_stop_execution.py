"""Real Linux stop admission, execution settlement and retained cleanup debt."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import asdict, replace
from pathlib import Path
from time import monotonic

import pytest

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.connection import ManagedConnectionLeaseV1
from loushang.apphost.managed.coordinator import ManagedServiceCoordinatorV1
from loushang.apphost.managed.stopper import ManagedServiceStopOperationV1
from loushang.coding.managed_process import ENDPOINT, coding_managed_process_request
from loushang.hosting.service import LinuxServiceObserverV1
from tests.apphost.test_managed_starter import owners as owners
from tests.coding.test_managed_process_entry import _stop_original

pytestmark = [pytest.mark.requires_host_runtime,
              pytest.mark.skipif(sys.platform != "linux", reason="Linux managed stop")]


@pytest.mark.parametrize("mode", ["single", "multi", "failure", "timeout"])
def test_stop_settles_real_execution_and_all_sessions(owners, tmp_path, mode):
    journal, namespace, service, runtime = owners
    (tmp_path / "stop-scenario.json").write_text(json.dumps({"mode": mode}))

    def request(invocation, descriptor):
        original = coding_managed_process_request(invocation, descriptor,
                                                  executable=sys.executable, environment=os.environ)
        return replace(original, argv=(sys.executable, str(Path(__file__).with_name(
            "_managed_execution_host.py")), *original.argv[3:]))

    coordinator = ManagedServiceCoordinatorV1(journal, namespace, service, runtime_root=runtime,
                                             endpoint=ENDPOINT, request_factory=request)
    observer = None
    evidence = {"mode": mode, "test_pid": os.getpid()}

    def events():
        path = tmp_path / "execution-audit.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    async def scenario():
        nonlocal observer
        client = None
        stops = []
        tasks = []

        def schedule(work):
            task = asyncio.create_task(work)
            tasks.append(task)
            return task
        try:
            connection = await coordinator.ensure_started(deadline=monotonic() + 25)
            instance = connection.instance
            native = coordinator._starter._process
            process = native._process
            observer = LinuxServiceObserverV1.reopen(native.identity)
            evidence["host_identity"] = asdict(native.identity)
            await coordinator.close()
            client = await asyncio.create_subprocess_exec(
                sys.executable, str(Path(__file__).with_name("_managed_execution_client.py")),
                str(tmp_path), "a", "stop-" + mode,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )

            async def message():
                line = await asyncio.wait_for(client.stdout.readline(), 30)
                assert line, (await client.stderr.read()).decode()
                return json.loads(line)

            ready = await message()
            assert ready["kind"] == "stop_ready" and ready["status"] == "running"
            assert len({ready["pid"], process.pid, os.getpid()}) == 3
            assert len(ready["sessions"]) == (1 if mode == "single" else 3)
            evidence["client"] = ready
            evidence["stop_requested_at"] = monotonic()

            def stop():
                value = ManagedServiceStopOperationV1(journal, namespace, service, instance, runtime_root=runtime)
                stops.append(value)
                return value

            deadline = monotonic() + (3 if mode in {"failure", "timeout"} else 20)
            first = stop()
            task = schedule(first.run(deadline=deadline))
            rejected = await message()
            assert rejected["kind"] == "stop_rejected"
            evidence["concurrent_request"] = rejected
            assert await asyncio.wait_for(client.wait(), 10) == 0, (await client.stderr.read()).decode()
            if mode in {"failure", "timeout"}:
                with pytest.raises(ManagedStorageError):
                    await task
                state = journal.read()
                assert state.handoff.stop_requested and not state.cleanly_stopped
                assert not state.evidence.application_cleanup_completed and not state.evidence.process_exited
                assert process.poll() is None and not observer.exited()
                debt_events = events()
                assert any(item["kind"] == "model_cancelled" for item in debt_events)
                if mode == "failure":
                    assert any(item["kind"] == "injected_close_failure" for item in debt_events)
                    assert len([item for item in debt_events if item["kind"] == "session_owner_end"]) == 2
                else:
                    assert not any(item["kind"] == "execution_terminal" for item in debt_events)
                evidence["during_debt"] = asdict(state.evidence)
                await first.close()
                (tmp_path / "release-failure").touch()
                first = stop()
                deadline = monotonic() + 25
                task = schedule(first.run(deadline=deadline))
            # Repeated callers share one stop intent and cannot release twice.
            duplicate = schedule(first.run(deadline=deadline))
            another = schedule(stop().run(deadline=monotonic() + 25))
            while not task.done() or not another.done():
                process.poll()
                await asyncio.sleep(0.01)
            results = await asyncio.gather(task, duplicate, another)
            assert all(result.cleanly_stopped for result in results)
            # Production lifetime retains a nonzero outcome after a real
            # application-cleanup failure, even when its later retry succeeds.
            assert process.wait(timeout=5) == (1 if mode == "failure" else 0)
            assert observer.exited()
            before = events()
            assert (await stop().run(deadline=monotonic() + 5)).cleanly_stopped
            assert events() == before
            stopped_connection = ManagedConnectionLeaseV1(
                journal, namespace, service, instance, runtime_root=runtime, endpoint=ENDPOINT,
            )
            try:
                with pytest.raises(ManagedStorageError, match="unavailable"):
                    await stopped_connection.prepare(deadline=monotonic() + 5)
            finally:
                await stopped_connection.close()
            evidence["stopped_connection"] = "unavailable"
            final = journal.read()
            assert final.cleanly_stopped and final.native_identity == native.identity
            evidence["stop_evidence"] = asdict(final.evidence)
            evidence["host_returncode"] = process.returncode
            evidence["audit"] = before
            names = [item["kind"] for item in before]
            assert names.count("accepted") == names.count("model_entered") == 1
            assert names.count("model_cancelled") == names.count("model_settled") == 1
            assert names.index("local_fenced") < names.index("interrupt") < names.index("model_cancelled")
            terminal, = [item for item in before if item["kind"] == "execution_terminal"]
            assert terminal["execution_id"] == ready["execution_id"]
            assert terminal["status"] == "interrupted" and terminal["active_released"]
            assert names.index("model_settled") < names.index("execution_terminal")
            for session_id in ready["sessions"]:
                local = [item["kind"] for item in before if item.get("session_id") == session_id]
                for label in ("session_owner", "adapter", "lease_runtime", "lease", "product", "agent_dispose"):
                    assert local.count(label + "_end") == 1, (session_id, label, local)
                    # The failed session-owner operation is retried; actual
                    # resource release bodies must still execute exactly once.
                    if label != "session_owner":
                        assert local.count(label + "_begin") == 1, (label, local)
                assert local.index("lease_end") < local.index("agent_dispose_begin")
                assert local.index("agent_dispose_end") < local.index("adapter_end") < local.index("session_owner_end")
                if session_id == ready["session_id"]:
                    assert local.index("execution_terminal") < local.index("adapter_begin")
            assert names.count("local_closed") == 1
            assert any(item["kind"] == "apphost_shutdown" and item["completed"] for item in before)
            for label in ("catalog", "product_factory", "continuity_lease"):
                assert names.count(label + "_begin") == names.count(label + "_end") == 1
            assert names.index("local_fenced") < names.index("registry_fenced") < names.index("interrupt")
            assert names.index("apphost_shutdown") < names.index("product_factory_end")
            assert names.index("product_factory_end") < names.index("continuity_lease_begin")
            assert names.index("continuity_lease_end") < names.index("local_closed")
            assert any(item["kind"] == "continuity_report" and item["completed"] and item["lease_released"]
                       for item in before)
        finally:
            (tmp_path / "release-close").touch()
            (tmp_path / "release-failure").touch()
            if client is not None:
                if client.returncode is None:
                    client.terminate()
                await asyncio.wait_for(client.wait(), 10)
            while any(not task.done() for task in tasks):
                if coordinator._starter._process is not None:
                    coordinator._starter._process._process.poll()
                await asyncio.sleep(0.01)
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.gather(*(item.close() for item in stops))
            await coordinator.close()

    try:
        asyncio.run(asyncio.wait_for(scenario(), 100))
        destination = os.environ.get("LOUSHANG_STAGE1C_EVIDENCE_DIR")
        if destination:
            Path(destination).mkdir(parents=True, exist_ok=True)
            (Path(destination) / f"{mode}.json").write_text(json.dumps(evidence, indent=2) + "\n")
    finally:
        native = coordinator._starter._process
        if observer is None and native is not None and native._process is not None and native._process.poll() is None:
            observer = LinuxServiceObserverV1.reopen(native.identity)
        _stop_original(coordinator._starter, observer)
