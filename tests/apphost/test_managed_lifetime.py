from __future__ import annotations

import asyncio
import os
import threading
from time import monotonic

import pytest

from loushang.apphost.managed._files import ManagedStorageError

from .test_managed_bootstrap import deployment as deployment
from .test_managed_bootstrap import make_bootstrap
from .test_managed_child import Application, until


@pytest.mark.parametrize("busy_method", ["request_child_stop", "record_child_cleanup"])
def test_transient_stop_receipt_busy_settles_within_original_budget(deployment, tmp_path, monkeypatch, busy_method):
    bootstrap, parent = make_bootstrap(deployment, tmp_path)
    bootstrap.open(deadline=monotonic() + 5)
    app = Application()
    child = bootstrap.bind(app)
    _, _, journal, state, _ = deployment
    journal.register_native(state.handoff.instance, state.handoff.attempt_id, bootstrap._observer.identity)
    original = getattr(bootstrap._journal, busy_method)
    calls = []

    def once_busy(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise ManagedStorageError("busy")
        return original(*args, **kwargs)

    monkeypatch.setattr(bootstrap._journal, busy_method, once_busy)

    async def scenario():
        waiter = asyncio.create_task(bootstrap.run())
        await until(lambda: child.accepting)
        app.closed.set()  # A normal application stop; no injected app failure.
        assert await waiter == 0
        assert len(calls) >= 2 and app.closes == 1
        assert journal.read().evidence.application_cleanup_completed
        assert not bootstrap.cleanup_pending

    try:
        asyncio.run(asyncio.wait_for(scenario(), 10))
    finally:
        parent.close()
        bootstrap.close()


def test_run_call_matrix_and_cancelled_waiters_do_not_stop_service(deployment, tmp_path):
    bootstrap, parent = make_bootstrap(deployment, tmp_path)

    async def before_bind():
        with pytest.raises(ManagedStorageError, match="closed"):
            await bootstrap.run()

    asyncio.run(before_bind())
    bootstrap.open(deadline=monotonic() + 5)
    asyncio.run(before_bind())
    app = Application()
    child = bootstrap.bind(app)
    _, _, journal, state, _ = deployment
    journal.register_native(state.handoff.instance, state.handoff.attempt_id, bootstrap._observer.identity)

    async def scenario():
        first, second = asyncio.create_task(bootstrap.run()), asyncio.create_task(bootstrap.run())
        try:
            await until(lambda: child.accepting)
            parent.close()
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert child.accepting and not app.fenced and app.closes == 0
            await child.close()
            assert await second == 0
            assert await bootstrap.run() == 0
            assert not bootstrap.cleanup_pending and app.closes == app.prepares == app.activations == 1
        finally:
            await child.close(retry_timeout=2)
            await asyncio.gather(first, second, return_exceptions=True)

    try:
        asyncio.run(asyncio.wait_for(scenario(), 10))

        async def different_loop():
            with pytest.raises(ManagedStorageError, match="conflict"):
                await bootstrap.run()

        asyncio.run(different_loop())
    finally:
        parent.close()
        bootstrap.close()


def test_bootstrap_close_native_job_is_not_replaced_after_waiter_cancel(deployment, tmp_path, monkeypatch):
    bootstrap, parent = make_bootstrap(deployment, tmp_path)
    bootstrap.open(deadline=monotonic() + 5)
    child = bootstrap.bind(Application())
    original_close = bootstrap.close
    entered, release = threading.Event(), threading.Event()
    calls = []

    def blocked_close():
        calls.append(1)
        entered.set()
        assert release.wait(5)
        original_close()

    monkeypatch.setattr(bootstrap, "close", blocked_close)

    async def scenario():
        first = asyncio.create_task(bootstrap.run())
        parent.close()  # Pre-commit startup abort, then graceful settlement.
        await until(entered.is_set)
        assert not child.cleanup_pending and bootstrap.cleanup_pending
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(bootstrap.run())
        await asyncio.sleep(0)
        assert calls == [1] and not second.done()
        release.set()
        assert await second == 0 and calls == [1]
        assert not bootstrap.cleanup_pending

    try:
        asyncio.run(asyncio.wait_for(scenario(), 10))
    finally:
        release.set()
        parent.close()
        original_close()


def test_pending_application_cleanup_is_not_replaced_or_closed_underneath(deployment, tmp_path, monkeypatch):
    from loushang.apphost.managed import _lifetime as module

    bootstrap, parent = make_bootstrap(deployment, tmp_path)
    bootstrap.open(deadline=monotonic() + 5)
    gate, entered, pause_gate = asyncio.Event(), asyncio.Event(), asyncio.Queue()

    class SlowApplication(Application):
        async def close(self, *, retry_timeout=None):
            self.closes += 1
            entered.set()
            await gate.wait()
            self.closed.set()

    app = SlowApplication()
    child = bootstrap.bind(app, settlement_timeout=0.02)
    delays = []

    async def pause(delay):
        delays.append(delay)
        await pause_gate.get()

    monkeypatch.setattr(module, "_pause", pause)

    async def scenario():
        waiter = asyncio.create_task(bootstrap.run())
        parent.close()
        await entered.wait()
        await until(lambda: bool(delays))
        original_task = child._application_close
        assert child.cleanup_pending and app.closes == 1 and not bootstrap._closing
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        gate.set()
        pause_gate.put_nowait(None)
        assert await bootstrap.run() == 1
        assert child._application_close is original_task and app.closes == 1
        assert not bootstrap.cleanup_pending

    try:
        asyncio.run(asyncio.wait_for(scenario(), 10))
    finally:
        parent.close()
        bootstrap.close()


def test_driver_publication_failure_is_retryable_without_product_effects(deployment, tmp_path, monkeypatch):
    from loushang.apphost.managed import _lifetime as module

    bootstrap, parent = make_bootstrap(deployment, tmp_path)
    bootstrap.open(deadline=monotonic() + 5)
    app = Application()
    bootstrap.bind(app)
    spawn, pauses = module._spawn, []

    def fail_once(work):
        monkeypatch.setattr(module, "_spawn", spawn)
        work.close()
        raise RuntimeError("task factory rejected before publication")

    async def pause(delay):
        pauses.append(delay)
        assert app.prepares == app.closes == 0
        assert bootstrap.cleanup_pending

    monkeypatch.setattr(module, "_spawn", fail_once)
    monkeypatch.setattr(module, "_pause", pause)

    async def scenario():
        parent.close()
        assert await bootstrap.run() == 1
        assert pauses == [1] and not bootstrap.cleanup_pending

    try:
        asyncio.run(asyncio.wait_for(scenario(), 10))
    finally:
        parent.close()
        bootstrap.close()


def test_native_close_unknown_never_returns_or_closes_reused_fd(deployment, tmp_path, monkeypatch):
    from loushang.apphost.managed import _lifetime as module

    bootstrap, parent = make_bootstrap(deployment, tmp_path)
    bootstrap.open(deadline=monotonic() + 5)
    bootstrap.bind(Application())
    observer_close = bootstrap._observer.close
    pauses, calls, replacement = [], [], []
    gate = asyncio.Queue()

    def uncertain_close():
        calls.append(1)
        observer_close()
        replacement.append(os.open("/dev/null", os.O_RDONLY))
        raise OSError("injected uncertainty after native close")

    async def pause(delay):
        pauses.append(delay)
        await gate.get()

    monkeypatch.setattr(bootstrap._observer, "close", uncertain_close)
    monkeypatch.setattr(module, "_pause", pause)

    async def scenario():
        waiter = asyncio.create_task(bootstrap.run())
        parent.close()
        for index in range(1, 4):
            await until(lambda index=index: len(pauses) == index)
            assert not waiter.done() and bootstrap.cleanup_pending
            assert calls == [1]
            os.fstat(replacement[0])
            if index < 3:
                gate.put_nowait(None)
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        # Test-only teardown of an injected permanent-debt driver, while it is
        # parked at the pause gate. This is not a production exit/cleanup receipt.
        bootstrap._lifetime._task.cancel()
        await asyncio.gather(bootstrap._lifetime._task, return_exceptions=True)

    try:
        asyncio.run(asyncio.wait_for(scenario(), 10))
        with pytest.raises(ManagedStorageError, match="unavailable"):
            bootstrap.close()
        assert calls == [1] and bootstrap.cleanup_pending
    finally:
        parent.close()
        for fd in replacement:
            os.close(fd)


def test_failed_dependency_cleanup_keeps_backoff_and_sticky_failure(deployment, tmp_path, monkeypatch):
    from loushang.apphost.managed import _lifetime as module

    bootstrap, parent = make_bootstrap(deployment, tmp_path)
    bootstrap.open(deadline=monotonic() + 5)
    child = bootstrap.bind(Application())
    original_close = bootstrap.close
    delays, calls = [], []
    release = asyncio.Queue()
    failing = True

    async def pause(delay):
        delays.append(delay)
        await release.get()

    def retryable_close():
        calls.append(1)
        if failing:
            raise ManagedStorageError("unavailable")
        original_close()

    monkeypatch.setattr(module, "_pause", pause)
    monkeypatch.setattr(bootstrap, "close", retryable_close)

    async def scenario():
        nonlocal failing
        first = asyncio.create_task(bootstrap.run())
        parent.close()
        for count in range(1, 8):
            await until(lambda count=count: len(delays) == count)
            assert len(calls) == count and not first.done()
            assert not child.cleanup_pending and bootstrap.cleanup_pending
            if count < 7:
                release.put_nowait(None)
        assert delays == [1, 2, 4, 8, 16, 30, 30]
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        failing = False
        release.put_nowait(None)
        assert await bootstrap.run() == 1
        assert await bootstrap.run() == 1
        assert not bootstrap.cleanup_pending and len(calls) == 8

    try:
        asyncio.run(asyncio.wait_for(scenario(), 10))
    finally:
        parent.close()
        original_close()


def test_cancelled_offload_task_retains_unknown_after_native_callable_finishes(deployment, tmp_path, monkeypatch):
    from loushang.apphost.managed import _lifetime as module

    bootstrap, parent = make_bootstrap(deployment, tmp_path)
    bootstrap.open(deadline=monotonic() + 5)
    bootstrap.bind(Application())
    original_close = bootstrap.close
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    parked, gate = asyncio.Event(), asyncio.Event()
    calls = []

    def blocked_close():
        calls.append(1)
        entered.set()
        assert release.wait(5)
        try:
            original_close()
        finally:
            finished.set()

    async def pause(delay):
        parked.set()
        await gate.wait()

    monkeypatch.setattr(bootstrap, "close", blocked_close)
    monkeypatch.setattr(module, "_pause", pause)

    async def scenario():
        waiter = asyncio.create_task(bootstrap.run())
        parent.close()
        await until(entered.is_set)
        lifetime = bootstrap._lifetime
        original_task = lifetime._close_task
        original_task.cancel()  # Private fault injection, not public waiter cancellation.
        await parked.wait()
        assert lifetime._close_unknown and not waiter.done()
        release.set()
        await until(finished.is_set)
        assert calls == [1] and lifetime._close_task is original_task
        assert not waiter.done() and bootstrap.cleanup_pending
        assert not bootstrap._resources_pending()  # Raw resources alone cannot forge an IO receipt.
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        lifetime._task.cancel()  # Test-only teardown at a known pause gate.
        await asyncio.gather(lifetime._task, return_exceptions=True)

    try:
        asyncio.run(asyncio.wait_for(scenario(), 10))
    finally:
        release.set()
        parent.close()
        with pytest.raises(ManagedStorageError, match="unavailable"):
            original_close()


def test_offload_task_publication_failure_does_not_start_or_duplicate_close(deployment, tmp_path, monkeypatch):
    from loushang.apphost.managed import _lifetime as module

    bootstrap, parent = make_bootstrap(deployment, tmp_path)
    bootstrap.open(deadline=monotonic() + 5)
    child = bootstrap.bind(Application())
    original_close, spawn = bootstrap.close, module._spawn
    schedules, closes, pauses = [], [], []

    def fail_close_publication(work):
        schedules.append(1)
        if len(schedules) == 2:  # Driver first, then the dependency-close task.
            work.close()
            raise RuntimeError("close task publication failed")
        return spawn(work)

    def close():
        closes.append(1)
        original_close()

    async def pause(delay):
        pauses.append(delay)
        assert not child.cleanup_pending and bootstrap.cleanup_pending and not closes

    monkeypatch.setattr(module, "_spawn", fail_close_publication)
    monkeypatch.setattr(module, "_pause", pause)
    monkeypatch.setattr(bootstrap, "close", close)

    async def scenario():
        parent.close()
        assert await bootstrap.run() == 1
        assert pauses == [1] and closes == [1] and len(schedules) == 3

    try:
        asyncio.run(asyncio.wait_for(scenario(), 10))
    finally:
        parent.close()
        original_close()


def test_prepare_waiter_cancel_does_not_stop_and_business_failure_stays_nonzero(deployment, tmp_path):
    bootstrap, parent = make_bootstrap(deployment, tmp_path)
    bootstrap.open(deadline=monotonic() + 5)
    _, _, journal, state, _ = deployment
    journal.register_native(state.handoff.instance, state.handoff.attempt_id, bootstrap._observer.identity)
    gate = asyncio.Event()

    class FailingApplication(Application):
        async def prepare(self, *, deadline=None):
            self.prepares += 1
            self.prepared.set()
            await gate.wait()
            raise RuntimeError("injected Product startup failure")

    app = FailingApplication()
    bootstrap.bind(app)

    async def scenario():
        first = asyncio.create_task(bootstrap.run())
        await app.prepared.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not app.fenced and app.closes == 0 and app.prepares == 1
        gate.set()
        assert await bootstrap.run() == 1
        assert not bootstrap.cleanup_pending and app.closes == 1 and app.activations == 0

    try:
        asyncio.run(asyncio.wait_for(scenario(), 10))
    finally:
        parent.close()
        bootstrap.close()
