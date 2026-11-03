from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path
from time import monotonic

import pytest

from loushang.apphost.managed import child as child_module
from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.child import ManagedChildApplicationV1, ManagedChildError

from . import test_managed_bootstrap as bootstrap_fixtures
from . import test_managed_child as fixtures

binding = fixtures.binding
deployment = bootstrap_fixtures.deployment
pytestmark = fixtures.pytestmark


def test_blocked_log_does_not_block_activation_or_application_close(binding):
    journal, _, _, _, control = binding
    entered, release = threading.Event(), threading.Event()
    events = []

    def record(event, code):
        events.append((event, code))
        if event == "starting":
            entered.set()
            assert release.wait(5)

    async def scenario():
        app = fixtures.Application()
        owner = ManagedChildApplicationV1(app, control, diagnostic=record, settlement_timeout=0.1)
        waiter = asyncio.create_task(owner.run())
        try:
            await fixtures.until(lambda: entered.is_set() and owner.accepting)
            with pytest.raises(ManagedChildError, match="cleanup_incomplete"):
                await owner.close()
            assert app.closed.is_set() and owner.cleanup_pending
            assert journal.read().evidence.application_cleanup_completed
            assert events == [("starting", None)]
        finally:
            release.set()
            await asyncio.gather(owner._close_task, return_exceptions=True)
            await owner.close(retry_timeout=2)
            await asyncio.gather(waiter, return_exceptions=True)
        assert [item[0] for item in events] == ["starting", "ready", "stopping", "stopped"]
        assert not owner.cleanup_pending
    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_failed_logging_is_dropped_without_changing_application_result(binding):
    _, _, _, _, control = binding
    calls = []

    def record(event, code):
        calls.append(event)
        raise OSError("secret diagnostic failure")

    async def scenario():
        app = fixtures.Application()
        owner = ManagedChildApplicationV1(app, control, diagnostic=record)
        waiter = asyncio.create_task(owner.run())
        await fixtures.until(lambda: owner.accepting)
        await owner.close()
        await waiter
        assert not owner.cleanup_pending and app.closes == 1 and calls == ["starting"]
    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_cleanup_retry_does_not_emit_stopped_before_success(binding):
    _, _, _, _, control = binding
    events = []

    async def scenario():
        app = fixtures.Application()
        owner = ManagedChildApplicationV1(app, control, diagnostic=lambda event, code: events.append(event))
        waiter = asyncio.create_task(owner.run())
        await fixtures.until(lambda: owner.accepting)
        app.fail_close = True
        with pytest.raises(ManagedChildError):
            await owner.close()
        assert "stopped" not in events
        app.fail_close = False
        await owner.close(retry_timeout=2)
        await asyncio.gather(waiter, return_exceptions=True)
        assert events.count("stopped") == events.count("stopping") == 1
    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_bootstrap_admits_default_logs_only_after_native_binding(deployment, tmp_path):
    _, _, journal, state, paths = deployment
    Path(paths.logs).mkdir(mode=0o700)
    owner, parent = bootstrap_fixtures.make_bootstrap(deployment, tmp_path, diagnostics=True)
    owner.open(deadline=monotonic() + 5)
    app = fixtures.Application()
    child = owner.bind(app)

    async def scenario():
        waiter = asyncio.create_task(owner.run())
        await fixtures.until(lambda: child._observation_task is not None)
        assert not app.prepared.is_set() and not tuple(Path(paths.logs).iterdir())
        deadline = monotonic() + 5
        while True:
            try:
                await asyncio.to_thread(journal.register_native, state.handoff.instance,
                                        state.handoff.attempt_id, owner._observer.identity, deadline=deadline)
                break
            except ManagedStorageError as error:
                if error.code != "busy" or monotonic() >= deadline:
                    raise
                await asyncio.sleep(0.01)  # Same idempotent birth, not another launch.
        await fixtures.until(lambda: child.accepting)
        await child.close()
        assert await waiter == 0
        assert not owner.cleanup_pending

    try:
        asyncio.run(asyncio.wait_for(scenario(), 10))
        events = [json.loads(line) for path in Path(paths.logs).glob("*.jsonl")
                  for line in path.read_bytes().splitlines()]
        assert [item["event"] for item in events] == ["starting", "ready", "stopping", "stopped"]
        assert {item["instanceId"] for item in events} == {state.handoff.instance.instance_id}
        assert all(set(item) == {"v", "event", "instanceId", "code", "sequence"} for item in events)
        assert not journal.read().evidence.process_exited
    finally:
        owner.close()
        parent.close()


@pytest.mark.parametrize("queued", [False, True])
def test_lost_submit_receipt_cannot_enter_diagnostic_callback(binding, monkeypatch, queued):
    _, _, _, _, control = binding
    native = child_module.ThreadPoolExecutor.submit
    calls, submissions = [], []

    def submit(executor, function, *args, **kwargs):
        if function.__name__ == "deliver":
            if queued:
                submissions.append(native(executor, function, *args, **kwargs))
            raise RuntimeError("lost submission receipt")
        return native(executor, function, *args, **kwargs)

    async def scenario():
        owner = ManagedChildApplicationV1(fixtures.Application(), control,
                                          diagnostic=lambda event, code: calls.append(event))
        waiter = asyncio.create_task(owner.run())
        await fixtures.until(lambda: owner.accepting and owner._diagnostics_disabled)
        await owner.close()
        await waiter
        if queued:
            assert len(submissions) == 1
            assert await asyncio.wrap_future(submissions[0]) is False
        assert not calls
        assert not owner.cleanup_pending

    with monkeypatch.context() as patch:
        patch.setattr(child_module.ThreadPoolExecutor, "submit", submit)
        asyncio.run(asyncio.wait_for(scenario(), 10))


def test_cancelled_log_waiter_retains_exact_native_future(binding):
    _, _, _, _, control = binding
    entered, release = threading.Event(), threading.Event()
    calls = []

    def record(event, code):
        calls.append(event)
        entered.set()
        assert release.wait(5)

    async def scenario():
        app = fixtures.Application()
        owner = ManagedChildApplicationV1(app, control, diagnostic=record, settlement_timeout=0.1)
        waiter = asyncio.create_task(owner.run())
        try:
            await fixtures.until(lambda: owner.accepting and entered.is_set())
            original = owner._pending_log
            owner._diagnostic_task.cancel()
            await asyncio.gather(owner._diagnostic_task, return_exceptions=True)
            with pytest.raises(ManagedChildError):
                await owner.close()
            assert owner._pending_log is original and not original.done()
            assert app.closed.is_set() and owner.cleanup_pending
        finally:
            release.set()
            await asyncio.gather(owner._close_task, return_exceptions=True)
            await owner.close(retry_timeout=2)
            await asyncio.gather(waiter, return_exceptions=True)
        assert calls == ["starting"] and not owner.cleanup_pending
    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_late_activation_success_during_close_does_not_log_ready(binding):
    _, _, _, _, control = binding
    events = []

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class LateApplication(fixtures.Application):
            async def activate(self):
                entered.set()
                await release.wait()

        app = LateApplication()
        owner = ManagedChildApplicationV1(app, control, settlement_timeout=0.1,
                                          diagnostic=lambda event, code: events.append(event))
        waiter = asyncio.create_task(owner.run())
        try:
            await entered.wait()
            with pytest.raises(ManagedChildError):
                await owner.close()
            assert "ready" not in events and "stopped" not in events
        finally:
            release.set()
            await asyncio.gather(owner._close_task, return_exceptions=True)
            await owner.close(retry_timeout=2)
            await asyncio.gather(waiter, return_exceptions=True)
        assert events == ["starting", "stopping", "stopped"]
    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_real_log_fsync_releases_service_fence_and_retains_bootstrap_dependencies(deployment, tmp_path, monkeypatch):
    _, _, journal, state, paths = deployment
    Path(paths.logs).mkdir(mode=0o700)
    owner, parent = bootstrap_fixtures.make_bootstrap(deployment, tmp_path, diagnostics=True)
    owner.open(deadline=monotonic() + 5)
    journal.register_native(state.handoff.instance, state.handoff.attempt_id, owner._observer.identity)
    app = fixtures.Application()
    child = owner.bind(app, settlement_timeout=0.1)
    entered, release = threading.Event(), threading.Event()
    native = os.fsync
    path = Path(paths.logs) / "lifecycle-0.jsonl"

    def fsync(fd):
        try:
            target = path.stat()
        except FileNotFoundError:
            target = None
        if target is not None and os.fstat(fd).st_ino == target.st_ino and not entered.is_set():
            entered.set()
            assert release.wait(5)
        return native(fd)

    async def scenario():
        waiter = asyncio.create_task(child.run())
        try:
            await fixtures.until(lambda: entered.is_set() and child.accepting)
            with pytest.raises(ManagedChildError):
                await child.close()
            observed = await asyncio.to_thread(journal.read, deadline=monotonic() + 2, wait_for_lock=True)
            assert observed.handoff.stop_requested and observed.evidence.application_cleanup_completed
            assert app.closed.is_set() and child.cleanup_pending
            assert owner._journal is not None and owner._registry is not None and owner._observer is not None
            with pytest.raises(ManagedStorageError, match="busy"):
                await asyncio.to_thread(owner.close)
        finally:
            release.set()
            await asyncio.gather(child._close_task, return_exceptions=True)
            await child.close(retry_timeout=2)
            await asyncio.gather(waiter, return_exceptions=True)
        await asyncio.to_thread(owner.close)
        assert not owner.cleanup_pending

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "fsync", fsync)
            asyncio.run(asyncio.wait_for(scenario(), 10))
        assert [json.loads(line)["event"] for line in path.read_bytes().splitlines()] == [
            "starting", "ready", "stopping", "stopped",
        ]
    finally:
        release.set()
        owner.close()
        parent.close()


@pytest.mark.parametrize("root_state", ["missing", "unknown-entry"])
def test_unavailable_default_logging_does_not_fail_application(deployment, tmp_path, root_state):
    _, _, journal, state, paths = deployment
    if root_state == "unknown-entry":
        Path(paths.logs).mkdir(mode=0o700)
        (Path(paths.logs) / "foreign").touch(mode=0o600)
    owner, parent = bootstrap_fixtures.make_bootstrap(deployment, tmp_path, diagnostics=True)
    owner.open(deadline=monotonic() + 5)
    journal.register_native(state.handoff.instance, state.handoff.attempt_id, owner._observer.identity)
    app = fixtures.Application()
    child = owner.bind(app)

    async def scenario():
        waiter = asyncio.create_task(owner.run())
        await fixtures.until(lambda: child.accepting and child._diagnostics_disabled)
        await child.close()
        assert await waiter == 0 and not owner.cleanup_pending
        assert app.activations == app.closes == 1

    try:
        asyncio.run(asyncio.wait_for(scenario(), 10))
        assert not tuple(Path(paths.logs).glob("*.jsonl"))
    finally:
        owner.close()
        parent.close()
