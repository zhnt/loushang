"""Diagnostic reads must neither change owners nor expose exception content."""

import asyncio
from types import SimpleNamespace as NS

import pytest

from ._lmux_startup_diagnostic import _task, observe_startup


@pytest.mark.parametrize("sink_fails", [False, True])
def test_drive_failure_is_observed_before_cleanup_and_preserves_primary(sink_fails):
    records = []
    primary = KeyboardInterrupt("private error message")

    class Child:
        _startup_deadline = 0.0
        _committed = False
        _failure = None
        _prepare_task = _activate_task = None

        async def _drive(self):
            raise primary

    child = Child()
    application = NS(_start_task=None)

    class Bootstrap:
        def bind(self, app):
            assert app is application
            return child

    original_drive = Child._drive

    def emit(phase, **fields):
        records.append((phase, fields))
        if sink_fails:
            raise RuntimeError("sink failed")

    async def scenario():
        with observe_startup(Bootstrap, emit):
            assert Bootstrap().bind(application) is child
            with pytest.raises(KeyboardInterrupt) as caught:
                await child._drive()
            assert caught.value is primary
            assert [phase for phase, _ in records] == ["startup_drive_failed"]
            assert child._failure is None
        assert Child._drive is original_drive

    asyncio.run(scenario())
    assert [phase for phase, _ in records] == ["startup_drive_failed", "startup_post_return"]
    assert "private error message" not in repr(records)


@pytest.mark.parametrize("state", ["absent", "pending", "cancelled", "done"])
def test_task_exception_is_read_only_when_done_and_not_cancelled(state):
    reads = []
    task = NS(done=lambda: state != "pending", cancelled=lambda: state == "cancelled",
              exception=lambda: reads.append(True))
    assert _task(None if state == "absent" else task)["state"] == state
    assert reads == ([True] if state == "done" else [])


@pytest.mark.parametrize("fault", [None, "primary", "sink", "bind"])
def test_startup_diagnostic_borrows_original_bind_and_preserves_failure(fault):
    events, records = [], []
    secret = "secret-marker-not-for-diagnostics"
    primary = KeyboardInterrupt(secret)
    task = NS(done=lambda: True, cancelled=lambda: False, exception=lambda: ValueError(secret))
    child = NS(_startup_deadline=0.0, _committed=False, _failure=ValueError(secret),
               _prepare_task=task, _activate_task=None)
    application = NS(_start_task=task)

    class Bootstrap:
        def bind(self, value, **kwargs):
            assert value is application and kwargs == {"startup_timeout": 30}
            events.append("bind")
            if fault == "bind":
                raise primary
            return child

    original = Bootstrap.bind

    def emit(phase, **fields):
        assert Bootstrap.bind is original and events[-1] == "entry-returned"
        records.append((phase, fields))
        if fault == "sink":
            raise KeyboardInterrupt("diagnostic sink failed")

    def run():
        with observe_startup(Bootstrap, emit):
            assert Bootstrap().bind(application, startup_timeout=30) is child
            assert records == []
            events.append("entry-returned")
            if fault == "primary":
                raise primary
            return 7

    if fault in {"primary", "bind"}:
        with pytest.raises(KeyboardInterrupt) as caught:
            run()
        assert caught.value is primary
    else:
        assert run() == 7
    assert Bootstrap.bind is original and events.count("bind") == 1
    assert len(records) == (0 if fault == "bind" else 1)
    assert secret not in repr(records)
    if records:
        assert records[0][1]["prepare"] == {"state": "done", "error": {"type": "ValueError", "code": "other"}}
