from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    MuxAttachV1,
    MuxCreateV1,
    MuxMemberCloseV1,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionEventKindV1,
    SessionEventV1,
    SessionIdentityV1,
    SessionSnapshotRequestV1,
    TurnInterruptV1,
    TurnTextV1,
)
from loushang.appservice.client_scope import ScopedAppServiceV1
from loushang.appservice.execution_contract import ExecutionContentEventV1
from loushang.appservice.execution_contract import ExecutionStatusV1 as Status
from loushang.appservice.execution_registry import ExecutionServiceErrorV1
from loushang.appservice.execution_service import HostedExecutionServiceBindingV1
from loushang.appservice.runtime import AppServiceV1

from .test_execution_guard import scenario
from .test_execution_port_conformance import FakeProduct
from .test_runtime import _Ids, _spec


class HostedProduct(FakeProduct):
    def __init__(self, request):
        super().__init__(model=False)
        self.identity = SessionIdentityV1(
            request.product_id, request.continuity_id, request.session_id or "session",
            request.scope, request.scope_fingerprint,
        )
        self.closed = False
        self.close_entered = asyncio.Event()
        self.legacy_calls = []

    def subscribe(self, listener):
        return lambda: None

    async def snapshot(self):
        return (await self.snapshot_execution()).source

    async def start_turn(self, text):
        self.legacy_calls.append(text)

    def interrupt_turn(self):
        self.legacy_calls.append("interrupt")
        return False

    def steer_turn(self, text):
        self.legacy_calls.append(("steer", text))

    def follow_up_turn(self, text):
        self.legacy_calls.append(("follow-up", text))

    async def respond_interaction(self, interaction_id, outcome):
        return True

    async def close(self):
        # Intentionally does not interrupt: AppService must settle first.
        self.close_entered.set()
        self.closed = True


class Resolver:
    def __init__(self):
        self.sessions = []

    async def open_session(self, request):
        product = HostedProduct(request)
        self.sessions.append(product)
        return product


async def fixture(*, supported=True):
    resolver = Resolver()
    service = AppServiceV1(
        product_id="coding", resolver=resolver, id_factory=_Ids(),
        execution=HostedExecutionServiceBindingV1(
            "application", "instance", lambda port: port if supported else None,
        ),
    )
    owner = ScopedAppServiceV1(service)
    first, second = owner.open_client_scope(), owner.open_client_scope()
    mux = await first.create_mux(MuxCreateV1("work"))
    selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
    await first.attach_mux(MuxAttachV1(selector))
    mux = await first.open_member(MuxMemberOpenV1(selector, _spec()))
    attachment = await first.attach_mux(MuxAttachV1(selector))
    control = SessionSnapshotRequestV1(
        attachment.attachment_id, attachment.controller_generation, mux.members[0].member_id
    )
    return service, owner, first, second, selector, control, resolver.sessions[0]


@scenario
async def test_lost_delivery_and_scope_replacement_recover_silent_execution_without_replay():
    service, owner, first, second, selector, control, product = await fixture()
    client = first.execution_client
    accepted = await client.submit_execution(control, "instance", "submission", "silent")
    await product.entered.wait()
    assert owner.pending_counts == (0, 0)
    await first.close()
    current = await second.attach_mux(MuxAttachV1(selector))
    new_control = replace(
        control, attachment_id=current.attachment_id,
        controller_generation=current.controller_generation,
    )
    client = second.execution_client
    found = await client.find_execution_by_submission(new_control, "instance", "submission")
    assert found.state.execution_id == accepted.state.execution_id
    assert found.state.status is Status.RUNNING
    assert not product.closed
    snapshot = await client.snapshot_execution_session(new_control, "instance")
    assert not snapshot.source.source.running  # Silent command, no model events.
    assert snapshot.executions.active.status is Status.RUNNING
    assert await client.submit_execution(new_control, "instance", "submission", "silent") == found
    await service.close()
    assert product.closed
    assert service._execution_registry.active_count == 0


@scenario
async def test_member_close_explicitly_interrupts_and_waits_for_product_cleanup():
    service, owner, first, second, selector, control, product = await fixture()
    record = await first.execution_client.submit_execution(control, "instance", "submission", "silent")
    await product.entered.wait()
    product.quiesce.clear()
    closing = asyncio.create_task(first.close_member(MuxMemberCloseV1(selector, control.member_id)))
    await product.cleaning.wait()
    assert not closing.done()
    assert not product.close_entered.is_set()
    assert service._execution_registry.active_count == 1
    product.quiesce.set()
    await closing
    assert product.closed
    assert service._execution_registry.active_count == 0
    result = service._execution_registry.get(product.identity, record.state.execution_id)
    assert result.state.status is Status.INTERRUPTED
    await service.close()


@scenario
async def test_legacy_wait_cancel_preserves_shared_slot_and_turn_interrupt_scope():
    service, owner, first, second, selector, control, product = await fixture()
    text = TurnTextV1(control.attachment_id, control.controller_generation, control.member_id, "legacy")
    waiter = asyncio.create_task(first.start_turn(text))
    await product.entered.wait()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    with pytest.raises(ExecutionServiceErrorV1):
        await first.execution_client.submit_execution(control, "instance", "submission", "blocked")
    await first.interrupt_turn(TurnInterruptV1(control.attachment_id, control.controller_generation, control.member_id))
    assert product.legacy_calls == ["interrupt"]
    assert not product.cleaning.is_set()
    assert service._execution_registry.reserved_ledger_bytes == 0
    await service.close()
    assert service._execution_registry.active_count == 0


@scenario
async def test_foreign_scope_and_stale_instance_fail_before_ledger_disclosure():
    service, owner, first, second, selector, control, product = await fixture()
    record = await first.execution_client.submit_execution(control, "instance", "submission", "silent")
    with pytest.raises(AppServiceError) as foreign:
        await second.execution_client.get_execution(control, "other-instance", record.state.execution_id)
    assert foreign.value.code is AppErrorCodeV1.STALE_ATTACHMENT
    with pytest.raises(ExecutionServiceErrorV1) as stale:
        await first.execution_client.submit_execution(control, "other-instance", "submission", "different")
    assert str(stale.value) == "service_instance_changed"
    await service.close()


@scenario
async def test_unsupported_product_rejects_without_registering_or_running():
    service, owner, first, second, selector, control, product = await fixture(supported=False)
    with pytest.raises(ExecutionServiceErrorV1) as unsupported:
        await first.execution_client.submit_execution(control, "instance", "submission", "silent")
    assert str(unsupported.value) == "execution_unsupported"
    assert service._execution_registry.active_count == 0
    assert service._execution_registry.reserved_ledger_bytes == 0
    assert not product.entered.is_set()
    await first.start_turn(TurnTextV1(
        control.attachment_id, control.controller_generation, control.member_id, "old API"
    ))
    assert product.legacy_calls == ["old API"]
    await service.close()


@scenario
async def test_execution_reads_consume_covered_legacy_copies_without_eventual_false_lag():
    service, owner, first, second, selector, control, product = await fixture()
    client = first.execution_client
    await client.snapshot_execution_session(control, "instance")
    session = service._sessions[product.identity.session_id]
    for _ in range(300):
        product.cursor += 1
        event = SessionEventV1(product.identity.session_id, product.cursor, SessionEventKindV1.STATUS, "content")
        await session._on_event(event)
        for listener in tuple(product.listeners):
            listener(ExecutionContentEventV1(event))
        events = await client.read_execution_events(control, "instance")
        assert len(events) == 1
    assert service._attachments[control.attachment_id][1].active
    assert service._attachments[control.attachment_id][1].queue.empty()
    await service.close()


@scenario
async def test_snapshot_revalidates_authority_after_product_await():
    service, owner, first, second, selector, control, product = await fixture()
    entered, release = asyncio.Event(), asyncio.Event()
    original = product.snapshot_execution

    async def slow_snapshot():
        entered.set()
        await release.wait()
        return await original()

    product.snapshot_execution = slow_snapshot
    capturing = asyncio.create_task(first.execution_client.snapshot_execution_session(control, "instance"))
    await entered.wait()
    await first.close()
    release.set()
    with pytest.raises(AppServiceError):
        await capturing
    assert not product.listeners
    await service.close()


@scenario
async def test_member_removal_settles_execution_even_when_retaining_session_resources():
    service, owner, first, second, selector, control, product = await fixture()
    record = await first.execution_client.submit_execution(control, "instance", "submission", "silent")
    await product.entered.wait()
    await first.close_member(MuxMemberCloseV1(selector, control.member_id, close_session=False))
    assert not product.closed
    assert service._execution_registry.active_count == 0
    assert service._execution_registry.get(product.identity, record.state.execution_id).state.status is Status.INTERRUPTED
    await service.close()
    assert product.closed


@scenario
async def test_first_application_stop_includes_debt_from_a_previously_removed_member():
    service, owner, first, second, selector, control, product = await fixture()
    original_settle = product.settle

    async def failed_settle():
        product.cleaning.set()
        raise RuntimeError("private cleanup failure")

    product.settle = failed_settle
    record = await first.execution_client.submit_execution(control, "instance", "submission", "silent")
    await product.entered.wait()
    product.release.set()
    await product.cleaning.wait()
    with pytest.raises(AppServiceError):
        await first.close_member(MuxMemberCloseV1(selector, control.member_id))
    assert service._cleanup_debt
    assert not service._sessions
    assert service._execution_registry.active_count == 1
    product.settle = original_settle
    await service.close()
    assert not service._cleanup_debt
    assert service._execution_registry.active_count == 0
    assert product.closed
    assert service._execution_registry.get(product.identity, record.state.execution_id).state.status.terminal
