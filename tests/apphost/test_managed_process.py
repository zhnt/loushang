from __future__ import annotations

import asyncio
import signal
import threading
from time import monotonic

import pytest

from loushang.apphost.managed import _process as module
from loushang.apphost.managed._files import ManagedStorageError

from .test_managed_bootstrap import deployment as deployment
from .test_managed_bootstrap import make_bootstrap
from .test_managed_child import Application


@pytest.fixture
def handlers(monkeypatch):
    original = {signal.SIGINT: lambda *args: None, signal.SIGTERM: signal.SIG_IGN, signal.SIGHUP: signal.SIG_DFL}
    current, changes = dict(original), []

    def setter(kind, value):
        previous = current[kind]
        current[kind] = value
        changes.append((kind, value))
        return previous

    monkeypatch.setattr(module.signal, "getsignal", current.__getitem__)
    monkeypatch.setattr(module.signal, "signal", setter)
    return original, current, changes, setter


def assert_policy(bootstrap, handlers):
    current = handlers[1]
    assert current[signal.SIGINT] == current[signal.SIGTERM] == bootstrap._process._signal
    assert current[signal.SIGHUP] == signal.SIG_IGN


def test_process_joins_all_resources_and_keeps_process_policy(deployment, tmp_path, handlers):
    bootstrap, parent = make_bootstrap(deployment, tmp_path)
    bootstrap.open(deadline=monotonic() + 5)
    app = Application()
    bootstrap.bind(app)
    parent.close()
    try:
        assert bootstrap.run_process() == 0
        assert_policy(bootstrap, handlers)
        assert len(handlers[2]) == 3
        process = bootstrap._process
        assert process._loop.is_closed() and not process.cleanup_pending
        assert not asyncio.all_tasks(process._loop)
        assert process._waiter.done() and process._signal_waiter.done()
        assert not bootstrap.cleanup_pending and app.closes == 1
        with pytest.raises(ManagedStorageError, match="closed"):
            bootstrap.run_process()
    finally:
        bootstrap.close()


def test_process_preconditions_reject_before_runner_or_signal_effects(deployment, tmp_path, handlers, monkeypatch):
    bootstrap, parent = make_bootstrap(deployment, tmp_path)
    try:
        with pytest.raises(ManagedStorageError, match="closed"):
            bootstrap.run_process()
        bootstrap.open(deadline=monotonic() + 5)
        with pytest.raises(ManagedStorageError, match="closed"):
            bootstrap.run_process()
        child = bootstrap.bind(Application())
        failures = []

        def other_thread():
            try:
                bootstrap.run_process()
            except ManagedStorageError as error:
                failures.append(error.code)

        thread = threading.Thread(target=other_thread)
        thread.start()
        thread.join(2)
        assert not thread.is_alive() and failures == ["unsupported"]

        async def existing_loop():
            with pytest.raises(ManagedStorageError, match="busy"):
                bootstrap.run_process()
            await child.close()
            assert await bootstrap.run() == 1  # Child was stopped before its runner started.

        asyncio.run(existing_loop())
        with pytest.raises(ManagedStorageError, match="closed"):
            bootstrap.run_process()
        assert bootstrap._process is None and handlers[2] == []
    finally:
        parent.close()
        bootstrap.close()


def test_cancelled_process_waiter_rejoins_one_application(deployment, tmp_path, handlers):
    bootstrap, parent = make_bootstrap(deployment, tmp_path)
    bootstrap.open(deadline=monotonic() + 5)
    _, _, journal, state, _ = deployment
    journal.register_native(state.handoff.instance, state.handoff.attempt_id, bootstrap._observer.identity)
    original_waiters = []

    class CancelWaiter(Application):
        async def activate(self):
            await super().activate()
            original_waiters.append(bootstrap._process._waiter)
            bootstrap._process._waiter.cancel()
            bootstrap._process._signal(signal.SIGTERM, None)

    app = CancelWaiter()
    bootstrap.bind(app)
    try:
        assert bootstrap.run_process() == 0
        assert len(original_waiters) == 1 and original_waiters[0].cancelled()
        assert bootstrap._process._waiter is not original_waiters[0]
        assert app.prepares == app.activations == app.closes == 1
        assert not bootstrap.cleanup_pending
        assert_policy(bootstrap, handlers)
    finally:
        parent.close()
        bootstrap.close()


def test_failed_bootstrap_waiter_is_rejoined_without_replaying_product(deployment, tmp_path, handlers, monkeypatch):
    bootstrap, parent = make_bootstrap(deployment, tmp_path)
    bootstrap.open(deadline=monotonic() + 5)
    app = Application()
    bootstrap.bind(app)
    original_run, calls = bootstrap.run, []

    async def fail_once():
        calls.append(1)
        if len(calls) == 1:
            raise ManagedStorageError("busy")
        return await original_run()

    monkeypatch.setattr(bootstrap, "run", fail_once)
    try:
        assert bootstrap.run_process() == 1
        assert calls == [1, 1] and app.prepares == app.activations == 0 and app.closes == 1
        assert not bootstrap.cleanup_pending
        assert_policy(bootstrap, handlers)
    finally:
        parent.close()
        bootstrap.close()


def test_signals_during_cleanup_preserve_exact_task_deadline_and_single_close(deployment, tmp_path, handlers):
    bootstrap, parent = make_bootstrap(deployment, tmp_path)
    bootstrap.open(deadline=monotonic() + 5)
    _, _, journal, state, _ = deployment
    journal.register_native(state.handoff.instance, state.handoff.attempt_id, bootstrap._observer.identity)
    captured = []

    class HeldClose(Application):
        async def activate(self):
            await super().activate()
            handlers[1][signal.SIGINT](signal.SIGINT, None)

        async def close(self, *, retry_timeout=None):
            self.closes += 1
            task, deadline = bootstrap._process._stop_task, child._close_deadline
            gate = asyncio.Event()
            handlers[1][signal.SIGTERM](signal.SIGTERM, None)
            handlers[1][signal.SIGINT](signal.SIGINT, None)
            asyncio.get_running_loop().call_soon(gate.set)
            await gate.wait()
            captured.append((task is bootstrap._process._stop_task, deadline == child._close_deadline, self.closes))
            self.closed.set()

    app = HeldClose()
    child = bootstrap.bind(app)
    try:
        assert bootstrap.run_process() == 0
        assert captured == [(True, True, 1)] and not bootstrap.cleanup_pending
    finally:
        parent.close()
        bootstrap.close()


def test_cancelled_process_serve_does_not_abandon_pending_stop_waiter(deployment, tmp_path, handlers, monkeypatch):
    bootstrap, parent = make_bootstrap(deployment, tmp_path)
    bootstrap.open(deadline=monotonic() + 5)
    _, _, journal, state, _ = deployment
    journal.register_native(state.handoff.instance, state.handoff.attempt_id, bootstrap._observer.identity)
    entered, release = asyncio.Event(), asyncio.Event()
    probes, checks = [], []

    class SignalStop(Application):
        async def activate(self):
            await super().activate()
            handlers[1][signal.SIGTERM](signal.SIGTERM, None)

    child = bootstrap.bind(SignalStop())
    real_close, real_run = child.close, bootstrap.run

    async def held_stop(*, retry_timeout=None):
        await real_close(retry_timeout=retry_timeout)
        if asyncio.current_task() is bootstrap._process._stop_task:
            entered.set()
            await release.wait()  # Actual resource cleanup done; exact wrapper remains pending.

    async def probe():
        from .test_managed_child import until

        await entered.wait()
        await until(lambda: bootstrap._process._waiter.done())
        process = bootstrap._process
        original_serve, original_stop = process._serve_task, process._stop_task
        original_serve.cancel()
        await until(lambda: process._serve_task is not original_serve)
        checks.append((process._stop_task is original_stop, not original_stop.cancelled(), not process._ending))
        release.set()

    async def observed_run():
        probes.append(asyncio.create_task(probe()))
        return await real_run()

    monkeypatch.setattr(child, "close", held_stop)
    monkeypatch.setattr(bootstrap, "run", observed_run)
    try:
        assert bootstrap.run_process() == 0
        assert checks == [(True, True, True)] and len(probes) == 1
        assert probes[0].done() and not probes[0].cancelled()
        assert not bootstrap.cleanup_pending
        assert_policy(bootstrap, handlers)
    finally:
        parent.close()
        bootstrap.close()


def test_stop_before_driver_never_prepares_or_activates(deployment, tmp_path, handlers, monkeypatch):
    bootstrap, parent = make_bootstrap(deployment, tmp_path)
    bootstrap.open(deadline=monotonic() + 5)
    app = Application()
    bootstrap.bind(app)
    _, current, _, setter = handlers
    injected = False

    def change(kind, value):
        nonlocal injected
        result = setter(kind, value)
        if not injected and kind == signal.SIGHUP:
            injected = True
            current[signal.SIGTERM](signal.SIGTERM, None)
            current[signal.SIGINT](signal.SIGINT, None)
        return result

    monkeypatch.setattr(module.signal, "signal", change)
    try:
        assert bootstrap.run_process() == 1  # Stopped before startup admission, not a ready service.
        assert injected and app.prepares == app.activations == 0 and app.closes == 1
        assert_policy(bootstrap, handlers)
        assert not bootstrap.cleanup_pending
        assert bootstrap._process._stop_task.done()
    finally:
        parent.close()
        bootstrap.close()


class Parked(BaseException):
    """Test-only escape from an intentionally nonreturning maintenance state."""


@pytest.mark.parametrize("fault", ["initialize", "runner_close", "install_int", "install_term", "install_hup"])
def test_partial_process_resource_failure_retains_unknown_without_retry(deployment, tmp_path, handlers, monkeypatch, fault):
    bootstrap, parent = make_bootstrap(deployment, tmp_path)
    bootstrap.open(deadline=monotonic() + 5)
    app = Application()
    child = bootstrap.bind(app)
    real_runner, _, current, _, setter = module.asyncio.Runner, *handlers
    calls = []
    target = {"install_int": signal.SIGINT, "install_term": signal.SIGTERM, "install_hup": signal.SIGHUP}.get(fault)
    injected = False

    class Runner(real_runner):
        def get_loop(self):
            loop = super().get_loop()
            if fault == "initialize":
                raise RuntimeError("failure after loop creation")
            return loop

        def close(self):
            calls.append("close")
            super().close()
            if fault == "runner_close":
                raise RuntimeError("failure after runner close")

    def install(kind, value):
        nonlocal injected
        result = setter(kind, value)
        if kind == target and not injected:
            injected = True
            raise OSError("handler install failed after effect")
        return result

    def park():
        raise Parked()

    monkeypatch.setattr(module.asyncio, "Runner", Runner)
    monkeypatch.setattr(module.signal, "signal", install)
    monkeypatch.setattr(module, "_park", park)
    parent.close()
    try:
        with pytest.raises(Parked):
            bootstrap.run_process()
        process = bootstrap._process
        assert process.unknown and process.cleanup_pending and bootstrap.cleanup_pending
        assert process._runner is not None and process._loop is not None
        with pytest.raises(ManagedStorageError, match="closed"):
            bootstrap.run_process()
        if fault == "initialize":
            assert app.prepares == app.closes == 0 and calls == []
        else:
            assert not bootstrap._resources_pending() and calls == ["close"]
            assert process._loop.is_closed()
            process._signal(signal.SIGTERM, None)  # Closing-loop window is harmless.
        assert current[signal.SIGINT] == current[signal.SIGTERM] == process._signal
        assert current[signal.SIGHUP] == signal.SIG_IGN
        assert_policy(bootstrap, handlers)
        if target is not None:
            assert injected and process._protection_unknown
            assert app.prepares == app.activations == 0 and app.closes == 1
    finally:
        # Explicit teardown of precisely known injected test resources; the
        # production owner retains unknown and never reports a successful exit.
        monkeypatch.setattr(module.asyncio, "Runner", real_runner)
        if child.cleanup_pending:
            asyncio.run(child.close(retry_timeout=2))
        with pytest.raises(ManagedStorageError, match="unavailable"):
            bootstrap.close()
        if not bootstrap._process._loop.is_closed():
            real_runner.close(bootstrap._process._runner)
