from __future__ import annotations

import asyncio
from dataclasses import replace
from threading import Event
from time import monotonic
from types import SimpleNamespace

import pytest

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.contracts import ManagedContractError
from loushang.apphost.managed.stopper import ManagedServiceStopOperationV1

from .test_managed_connection import committed
from .test_managed_starter import owners as owners


def operation(owners, state):
    journal, namespace, service, runtime = owners
    return ManagedServiceStopOperationV1(journal, namespace, service, state.handoff.instance, runtime_root=runtime)


def native(owner, state, monkeypatch):
    flags = {"leader": False, "group": False, "closes": 0, "close_error": False}

    def close():
        flags["closes"] += 1
        if flags["close_error"]:
            raise OSError("lost close receipt")

    def admit(value):
        assert value.native_identity == state.native_identity
        owner._observer = SimpleNamespace(identity=state.native_identity, exited=lambda: flags["leader"], close=close)
        owner._group = SimpleNamespace(exited=lambda: flags["group"])

    monkeypatch.setattr(owner, "_admit", admit)
    return flags


def test_stop_waits_for_scope_and_child_receipt_and_survives_waiter_cancel(owners, monkeypatch):
    journal = owners[0]
    state = committed(owners)
    owner = operation(owners, state)
    flags = native(owner, state, monkeypatch)
    stopped = Event()
    original = journal.request_stop
    requests = []

    def request(*args, **kwargs):
        result = original(*args, **kwargs)
        requests.append(1)
        stopped.set()
        return result

    monkeypatch.setattr(journal, "request_stop", request)

    async def scenario():
        deadline = monotonic() + 5
        waiter = asyncio.create_task(owner.run(deadline=deadline))
        assert await asyncio.to_thread(stopped.wait, 3)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        flags["leader"] = True
        async with asyncio.timeout(3):
            while owner.state is None or not owner.state.evidence.process_exited:
                await asyncio.sleep(0.01)
        assert not owner.state.cleanly_stopped and not owner.state.evidence.process_scope_settled
        flags["group"] = True
        async with asyncio.timeout(3):
            while not owner.state.evidence.process_scope_settled:
                await asyncio.sleep(0.01)
        assert not owner.state.evidence.application_cleanup_completed
        await asyncio.to_thread(journal.record_child_cleanup, state.handoff.instance,
                                state.handoff.attempt_id, state.native_identity)
        result = await owner.run(deadline=deadline)
        assert result.cleanly_stopped and requests == [1]
        with pytest.raises(ManagedStorageError, match="conflict"):
            await owner.run(deadline=deadline + 1)
        await owner.close()
        assert not owner.cleanup_pending and flags["closes"] == 1
        assert journal.read().cleanly_stopped

    asyncio.run(scenario())


def test_timeout_retains_stop_intent_without_fabricating_exit(owners, monkeypatch):
    state = committed(owners)
    owner = operation(owners, state)
    flags = native(owner, state, monkeypatch)

    async def scenario():
        with pytest.raises(ManagedStorageError):
            await owner.run(deadline=monotonic() + 0.15)
        await owner.close()
        assert flags["closes"] == 1 and not owner.cleanup_pending

    asyncio.run(scenario())
    current = owners[0].read()
    assert current.handoff.stop_requested and not current.cleanly_stopped
    assert not current.evidence.process_exited and not current.evidence.application_cleanup_completed


def test_unknown_close_not_retried_as_a_numeric_descriptor(owners, monkeypatch):
    state = committed(owners)
    owner = operation(owners, state)
    flags = native(owner, state, monkeypatch)

    async def scenario():
        with pytest.raises(ManagedStorageError):
            await owner.run(deadline=monotonic() + 0.1)
        flags["close_error"] = True
        with pytest.raises(OSError):
            await owner.close()
        with pytest.raises(ManagedStorageError, match="unavailable"):
            await owner.close()
        assert owner.cleanup_pending and flags["closes"] == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("deadline", [None, True, float("nan"), float("inf"), 0])
def test_invalid_deadline_before_task_or_stop(owners, deadline):
    state = committed(owners)
    owner = operation(owners, state)

    async def scenario():
        with pytest.raises(ManagedContractError):
            await owner.run(deadline=deadline)
        assert owner._task is None
        await owner.close()

    asyncio.run(scenario())
    assert owners[0].read() == state


def test_native_evidence_cannot_change_app_fact_or_mismatch_birth(owners):
    state = committed(owners)
    journal = owners[0]
    journal.request_stop(state.handoff.instance)
    with pytest.raises(ManagedStorageError, match="conflict"):
        journal.record_native_stop(state.handoff.instance, replace(state.native_identity, start_ticks=1),
                                   process_exited=True, process_scope_settled=True, deadline=monotonic() + 2)
    result = journal.record_native_stop(state.handoff.instance, state.native_identity,
                                         process_exited=True, process_scope_settled=True, deadline=monotonic() + 2)
    assert not result.evidence.application_cleanup_completed and not result.cleanly_stopped


@pytest.mark.parametrize("delay_before_native", [False, True])
def test_original_deadline_covers_native_entry_and_result_delivery(owners, monkeypatch, delay_before_native):
    from loushang.apphost.managed import stopper

    state = committed(owners)
    journal = owners[0]
    journal.request_stop(state.handoff.instance)
    journal.record_child_cleanup(state.handoff.instance, state.handoff.attempt_id, state.native_identity)
    state = journal.record_native_stop(state.handoff.instance, state.native_identity,
        process_exited=True, process_scope_settled=True, deadline=monotonic() + 5)
    owner = operation(owners, state)
    expired = False
    operations = []

    def check(deadline):
        if expired:
            raise ManagedStorageError("busy")

    async def receipt(operation):
        nonlocal expired
        if delay_before_native:
            expired = True
        result = operation()
        operations.append(result)
        expired = True
        return result

    monkeypatch.setattr(stopper, "_check_deadline", check)
    monkeypatch.setattr(stopper, "_settled_native", receipt)

    async def scenario():
        deadline = monotonic() + 5
        with pytest.raises(ManagedStorageError, match="busy"):
            await owner.run(deadline=deadline)
        if delay_before_native:
            assert operations == [] and owner.state is None
        else:
            assert operations == [state] and owner.state == state
        await owner.close()
        assert not owner.cleanup_pending

    asyncio.run(scenario())
    assert journal.read() == state
