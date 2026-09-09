from __future__ import annotations

import asyncio

import pytest

from loushang.appserver.protocol import AppErrorCodeV1, AppFailureV1, AppServiceError
from loushang.appservice.execution_contract import ExecutionOutcomeV1
from loushang.appservice.execution_contract import ExecutionStatusV1 as Status
from loushang.appservice.execution_registry import (
    RECORD_RESERVATION_BYTES,
    ExecutionLimitsV1,
    ExecutionRegistryV1,
    ExecutionServiceErrorV1,
)
from loushang.appservice.execution_registry import (
    ExecutionErrorCodeV1 as Code,
)

from .test_execution_guard import scenario
from .test_execution_port_conformance import FakeProduct


def registry(**limits):
    return ExecutionRegistryV1(
        application_id="app", service_instance_id="instance",
        limits=ExecutionLimitsV1(**limits),
    )


@scenario
async def test_duplicate_at_full_capacity_and_conflict_have_no_second_product_effect():
    owner, product = registry(active=1, submissions=1), FakeProduct(model=False)
    binding = owner.bind(product)
    first = owner.submit(binding, " exact ", "submission")
    assert first.state.status is Status.ACCEPTED
    assert owner.submit(binding, " exact ", "submission") == first
    await product.entered.wait()
    running = owner.find(product.identity, "submission")
    assert running.state.status is Status.RUNNING
    assert owner.submit(binding, " exact ", "submission") == running
    with pytest.raises(ExecutionServiceErrorV1) as conflict:
        owner.submit(binding, "exact", "submission")
    assert conflict.value.code is Code.SUBMISSION_CONFLICT
    with pytest.raises(ExecutionServiceErrorV1) as busy:
        owner.submit(binding, "next", "second")
    assert busy.value.code is Code.BUSY
    product.release.set()
    await owner.wait(binding, first)
    assert owner.active_count == 0
    assert owner.get(product.identity, first.state.execution_id).state.status is Status.SUCCEEDED
    with pytest.raises(ExecutionServiceErrorV1) as full:
        owner.submit(binding, "next", "second")
    assert full.value.code is Code.LEDGER_FULL
    # Legacy has a separate terminal cache and does not consume submission capacity.
    legacy = owner.submit(binding, "legacy", None)
    await owner.wait(binding, legacy)
    assert owner.reserved_ledger_bytes == RECORD_RESERVATION_BYTES
    await owner.close_binding(binding)


@scenario
async def test_cancelled_communication_and_registry_waiter_do_not_release_execution():
    owner, product = registry(), FakeProduct(model=False)
    binding = owner.bind(product)
    product.quiesce.clear()
    record = owner.submit(binding, "silent", "submission")
    await product.entered.wait()
    communication = asyncio.create_task(owner.wait(binding, record))
    communication.cancel()
    with pytest.raises(asyncio.CancelledError):
        await communication
    assert owner.active_count == 1
    assert owner.find(product.identity, "submission").state.status is Status.RUNNING
    # Even accidental cancellation of an internal waiter retains cleanup debt.
    invocation = binding.active
    invocation.task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await invocation.task
    assert owner.active_count == 1
    closing = asyncio.create_task(owner.close_binding(binding))
    await product.cleaning.wait()
    assert not closing.done()
    assert owner.active_count == 1
    assert owner.find(product.identity, "submission").state.interrupt_requested
    product.quiesce.set()
    await closing
    assert owner.active_count == 0
    assert owner.find(product.identity, "submission").state.status is Status.INTERRUPTED


@scenario
async def test_cleanup_failure_keeps_slot_and_retry_does_not_replay():
    owner, product = registry(), FakeProduct(model=False)
    binding = owner.bind(product)
    original_settle = product.settle

    async def failed_settle():
        raise RuntimeError("private failure")

    product.settle = failed_settle
    record = owner.submit(binding, "once", "submission")
    await product.entered.wait()
    product.release.set()
    with pytest.raises(AppServiceError):
        await owner.wait(binding, record)
    assert owner.active_count == 1
    with pytest.raises(AppServiceError):
        await owner.close_binding(binding)
    assert owner.find(product.identity, "submission").state.status is Status.RUNNING
    product.settle = original_settle
    await owner.close_binding(binding)
    assert owner.active_count == 0
    assert owner.find(product.identity, "submission").state.status is Status.SUCCEEDED


@scenario
async def test_pre_entry_interrupt_preserves_source_baseline():
    owner, product = registry(), FakeProduct(model=False)
    binding = owner.bind(product)
    record = owner.submit(binding, "never run", "submission")
    owner.interrupt(binding, record.state.execution_id)
    assert (await owner.wait(binding, record)).status is Status.INTERRUPTED
    assert not product.entered.is_set()
    assert binding.view.quiescent.execution_id is None
    assert binding.view.latest_terminal.execution_id == record.state.execution_id
    await owner.close_binding(binding)


@scenario
async def test_reopened_binding_has_empty_projection_and_retained_canonical_history():
    owner, product = registry(), FakeProduct(model=False)
    first = owner.bind(product)
    record = owner.submit(first, "once", "submission")
    product.release.set()
    await owner.wait(first, record)
    await owner.close_binding(first)
    replacement = FakeProduct(model=False)
    second = owner.bind(replacement)
    assert first.view.binding is not second.view.binding
    assert second.view.revision == 0
    assert second.view.latest_terminal is None
    assert second.view.quiescent.execution_id is None
    assert owner.submit(second, "once", "submission").state.execution_id == record.state.execution_id
    assert not replacement.entered.is_set()
    with pytest.raises(ExecutionServiceErrorV1) as changed:
        owner.require_instance("replacement-instance")
    assert changed.value.code is Code.INSTANCE_CHANGED
    await owner.close_binding(second)


@scenario
async def test_maximum_terminal_record_was_reserved_and_legacy_eviction_is_independent():
    owner = registry(ledger_bytes=RECORD_RESERVATION_BYTES, recent_legacy=1)
    product = FakeProduct(model=False)
    binding = owner.bind(product)
    record = owner.submit(binding, "input", "s" * 128)
    original_run = product.run

    async def largest_failure(control):
        await original_run(control)
        return ExecutionOutcomeV1(Status.FAILED, "e" * 128,
                                  AppFailureV1(AppErrorCodeV1.OPERATION_UNAVAILABLE))

    product.run = largest_failure
    product.release.set()
    await owner.wait(binding, record)
    assert owner.get(product.identity, record.state.execution_id).state.outcome.error_code == "e" * 128
    product.run = original_run
    legacy_a = owner.submit(binding, "A", None)
    await owner.wait(binding, legacy_a)
    legacy_b = owner.submit(binding, "B", None)
    await owner.wait(binding, legacy_b)
    with pytest.raises(ExecutionServiceErrorV1) as gone:
        owner.get(product.identity, legacy_a.state.execution_id)
    assert gone.value.code is Code.NOT_RETAINED
    assert owner.find(product.identity, "s" * 128) is not None
    assert owner.active_count == 0
    await owner.close_binding(binding)


def test_task_construction_failure_rolls_back_all_reservations(monkeypatch):
    async def run():
        owner, product = registry(), FakeProduct(model=False)
        binding = owner.bind(product)
        create_task = asyncio.create_task

        def fail(*args, **kwargs):
            raise RuntimeError("task creation failed")

        monkeypatch.setattr(asyncio, "create_task", fail)
        with pytest.raises(RuntimeError):
            owner.submit(binding, "no effect", "submission")
        assert owner.active_count == owner.reserved_ledger_bytes == 0
        assert owner.find(product.identity, "submission") is None
        assert binding.view.revision == 0
        monkeypatch.setattr(asyncio, "create_task", create_task)
        record = owner.submit(binding, "allowed", "submission")
        product.release.set()
        await owner.wait(binding, record)
        await owner.close_binding(binding)

    asyncio.run(run())


@scenario
async def test_incomplete_product_port_is_rejected_before_any_execution_effect():
    owner, product = registry(), FakeProduct(model=False)
    product.wait_execution = None
    with pytest.raises(ExecutionServiceErrorV1) as unsupported:
        owner.bind(product)
    assert unsupported.value.code is Code.UNSUPPORTED
    assert product.guard.state is None
    assert owner.active_count == 0


@scenario
async def test_cancelled_metadata_listener_cannot_abandon_accepted_execution():
    owner, product = registry(), FakeProduct(model=False)
    binding = owner.bind(product)

    def cancelled_listener(event):
        raise asyncio.CancelledError()

    binding.subscribe(cancelled_listener)
    record = owner.submit(binding, "once", "submission")
    await product.entered.wait()
    product.release.set()
    assert (await owner.wait(binding, record)).status is Status.SUCCEEDED
    assert owner.active_count == 0
    await owner.close_binding(binding)


@scenario
async def test_stopping_after_internal_driver_cancelled_before_entry_needs_no_product_retry():
    owner, product = registry(), FakeProduct(model=False)
    binding = owner.bind(product)
    record = owner.submit(binding, "never run", "submission")
    binding.active.task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await binding.active.task
    await owner.close_binding(binding)
    assert owner.active_count == 0
    assert not product.entered.is_set()
    assert binding.view.quiescent.execution_id is None
    assert owner.get(product.identity, record.state.execution_id).state.status is Status.INTERRUPTED
