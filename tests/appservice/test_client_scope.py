from __future__ import annotations

import asyncio

import pytest

from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    InteractionOutcomeV1,
    InteractionRespondV1,
    MuxAttachV1,
    MuxCloseV1,
    MuxCreateV1,
    MuxDetachV1,
    MuxMemberCloseV1,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionEventKindV1,
    SessionEventV1,
    SessionSnapshotRequestV1,
    TurnTextV1,
)
from loushang.appservice.client_scope import ScopedAppServiceV1

from .test_runtime import _service, _spec


async def _fixture():
    service, legacy, resolver = await _service()
    mux = await legacy.create_mux(MuxCreateV1("dev"))
    selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
    mux = await legacy.open_member(MuxMemberOpenV1(selector, _spec()))
    owner = ScopedAppServiceV1(service, close_timeout=0.05)
    first, second = owner.open_client_scope(), owner.open_client_scope()
    return service, owner, first, second, selector, mux, resolver.sessions[0]


def test_G16_CONTROLLER_exclusive_scope_and_foreign_reads_are_fenced() -> None:
    async def scenario() -> None:
        service, owner, first, second, selector, mux, session = await _fixture()
        attachment = await first.attach_mux(MuxAttachV1(selector))
        with pytest.raises(AppServiceError) as busy:
            await second.attach_mux(MuxAttachV1(selector))
        assert busy.value.code is AppErrorCodeV1.ALREADY_ATTACHED
        with pytest.raises(AppServiceError) as foreign:
            await second.snapshot_session(SessionSnapshotRequestV1(
                attachment.attachment_id, attachment.controller_generation,
                mux.members[0].member_id,
            ))
        assert foreign.value.code is AppErrorCodeV1.STALE_ATTACHMENT
        with pytest.raises(AppServiceError) as foreign_events:
            await second.read_events(
                attachment_id=attachment.attachment_id,
                controller_generation=attachment.controller_generation,
            )
        assert foreign_events.value.code is AppErrorCodeV1.STALE_ATTACHMENT
        refreshed = await first.attach_mux(MuxAttachV1(selector))
        assert refreshed.controller_generation > attachment.controller_generation
        await first.close()
        replacement = await second.attach_mux(MuxAttachV1(selector))
        assert replacement.controller_generation > refreshed.controller_generation
        assert session.closed == 0
        await service.close()

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_ACCEPTED_WORK_scope_loss_does_not_stop_turn_or_delay_reattach() -> None:
    async def scenario() -> None:
        service, owner, first, second, selector, mux, session = await _fixture()
        attachment = await first.attach_mux(MuxAttachV1(selector))
        session.turn_entered, session.turn_release = asyncio.Event(), asyncio.Event()
        request = TurnTextV1(
            attachment.attachment_id, attachment.controller_generation,
            mux.members[0].member_id, "retained",
        )
        waiter = asyncio.create_task(first.start_turn(request))
        await session.turn_entered.wait()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        await first.close()
        replacement = await second.attach_mux(MuxAttachV1(selector))
        assert not session.turn_release.is_set()
        with pytest.raises(AppServiceError) as busy:
            await second.start_turn(TurnTextV1(
                replacement.attachment_id, replacement.controller_generation,
                mux.members[0].member_id, "must not replay",
            ))
        assert busy.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
        assert ("interrupt", "") not in session.calls
        assert owner.pending_counts == (1, 0)
        session.turn_release.set()
        await service.close()

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_REATTACH_late_snapshot_is_reclaimed_after_scope_loss() -> None:
    async def scenario() -> None:
        service, owner, first, second, selector, mux, session = await _fixture()
        session.snapshot_entered, session.snapshot_release = (
            asyncio.Event(), asyncio.Event()
        )
        attaching = asyncio.create_task(first.attach_mux(MuxAttachV1(selector)))
        await session.snapshot_entered.wait()
        attaching.cancel()
        with pytest.raises(asyncio.CancelledError):
            await attaching
        with pytest.raises(AppServiceError) as debt:
            await first.close()
        assert debt.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
        with pytest.raises(AppServiceError) as busy:
            await second.attach_mux(MuxAttachV1(selector))
        assert busy.value.code is AppErrorCodeV1.ALREADY_ATTACHED
        session.snapshot_release.set()
        await first.close()
        replacement = await second.attach_mux(MuxAttachV1(selector))
        assert replacement.controller_generation == 2
        assert len(service._attachments) == 1
        await service.close()

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_CONTROLLER_membership_requires_scope_and_refresh_after_change() -> None:
    async def scenario() -> None:
        service, owner, first, second, selector, mux, session = await _fixture()
        old = await first.attach_mux(MuxAttachV1(selector))
        with pytest.raises(AppServiceError) as foreign:
            await second.open_member(MuxMemberOpenV1(selector, _spec("two")))
        assert foreign.value.code is AppErrorCodeV1.STALE_ATTACHMENT
        changed = await first.open_member(MuxMemberOpenV1(selector, _spec("two")))
        assert len(changed.members) == 2
        with pytest.raises(AppServiceError):
            await first.detach_mux(MuxDetachV1(
                old.attachment_id, old.controller_generation
            ))
        current = await first.attach_mux(MuxAttachV1(selector))
        assert current.mux_space == changed
        await first.detach_mux(MuxDetachV1(
            current.attachment_id, current.controller_generation
        ))
        await second.attach_mux(MuxAttachV1(selector))
        await service.close()

    asyncio.run(asyncio.wait_for(scenario(), 2))


async def _question(session, interaction_id: str = "question-1") -> None:
    session.cursor += 1
    assert session.listener is not None
    await session.listener(SessionEventV1(
        session.identity.session_id, session.cursor,
        SessionEventKindV1.INTERACTION_REQUESTED, "approve?", interaction_id,
    ))


def test_G16_APPROVAL_disconnect_denies_old_question_and_rejects_new_controller() -> None:
    async def scenario() -> None:
        service, owner, first, second, selector, mux, session = await _fixture()
        await first.attach_mux(MuxAttachV1(selector))
        await _question(session)
        await first.close()
        assert ("interaction", ("question-1", InteractionOutcomeV1.DENY)) in session.calls
        current = await second.attach_mux(MuxAttachV1(selector))
        with pytest.raises(AppServiceError) as old:
            await second.respond_interaction(InteractionRespondV1(
                current.attachment_id, current.controller_generation,
                mux.members[0].member_id, "question-1", InteractionOutcomeV1.APPROVE,
            ))
        assert old.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
        await second.close()
        await _question(session, "unattached")
        await owner._interactions.settle_unowned(frozenset({session.identity.session_id}))
        assert ("interaction", ("unattached", InteractionOutcomeV1.DENY)) in session.calls
        await service.close()

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_APPROVAL_refresh_denies_old_and_accepts_only_new_question() -> None:
    async def scenario() -> None:
        service, owner, first, second, selector, mux, session = await _fixture()
        await first.attach_mux(MuxAttachV1(selector))
        await _question(session)
        current = await first.attach_mux(MuxAttachV1(selector))
        await _question(session, "new-question")
        await first.respond_interaction(InteractionRespondV1(
            current.attachment_id, current.controller_generation,
            mux.members[0].member_id, "new-question", InteractionOutcomeV1.APPROVE,
        ))
        assert [call for call in session.calls if call[0] == "interaction"] == [
            ("interaction", ("question-1", InteractionOutcomeV1.DENY)),
            ("interaction", ("new-question", InteractionOutcomeV1.APPROVE)),
        ]
        await service.close()

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_APPROVAL_failed_denial_retains_controller_until_cleanup_retry() -> None:
    async def scenario() -> None:
        service, owner, first, second, selector, mux, session = await _fixture()
        await first.attach_mux(MuxAttachV1(selector))
        await _question(session)
        original = session.respond_interaction

        async def fail(_interaction_id, _outcome):
            raise RuntimeError("private failure")

        session.respond_interaction = fail
        with pytest.raises(AppServiceError):
            await first.close()
        with pytest.raises(AppServiceError) as fenced:
            await second.attach_mux(MuxAttachV1(selector))
        assert fenced.value.code is AppErrorCodeV1.ALREADY_ATTACHED
        session.respond_interaction = original
        await first.close()
        await second.attach_mux(MuxAttachV1(selector))
        await service.close()

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_STOP_eight_scopes_can_settle_without_consuming_denial_slots() -> None:
    async def scenario() -> None:
        service, legacy, resolver = await _service()
        selectors = []
        for index in range(8):
            mux = await legacy.create_mux(MuxCreateV1(f"mux-{index}"))
            selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
            await legacy.open_member(MuxMemberOpenV1(selector, _spec(str(index))))
            selectors.append(selector)
        owner = ScopedAppServiceV1(service)
        for selector, session in zip(selectors, resolver.sessions, strict=True):
            scope = owner.open_client_scope()
            await scope.attach_mux(MuxAttachV1(selector))
            await _question(session)
        with pytest.raises(AppServiceError) as capacity:
            owner.open_client_scope()
        assert capacity.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
        await service.close()
        assert all(session.closed == 1 for session in resolver.sessions)
        assert owner.pending_counts == (0, 0)
        assert not owner._scopes and not owner._controllers

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_STOP_close_mux_does_not_wait_for_its_own_operation() -> None:
    async def scenario() -> None:
        service, owner, first, second, selector, mux, session = await _fixture()
        await first.attach_mux(MuxAttachV1(selector))
        await first.close_mux(MuxCloseV1(selector))
        assert session.closed == 1
        assert not owner._controllers
        await service.close()

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_STOP_failed_denial_still_closes_product_and_retries_safely() -> None:
    async def scenario() -> None:
        service, owner, first, second, selector, mux, session = await _fixture()
        await first.attach_mux(MuxAttachV1(selector))
        await _question(session)

        async def fail(_interaction_id, _outcome):
            raise RuntimeError("denial unavailable")

        session.respond_interaction = fail
        with pytest.raises(AppServiceError) as debt:
            await service.close()
        assert debt.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
        assert session.closed == 1
        await service.close()
        assert not owner._controllers and not owner._scopes
        assert owner.pending_counts == (0, 0)

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_APPROVAL_unowned_denial_debt_blocks_attachment_until_settled() -> None:
    async def scenario() -> None:
        service, owner, first, second, selector, mux, session = await _fixture()
        original = session.respond_interaction

        async def fail(_interaction_id, _outcome):
            raise RuntimeError("denial unavailable")

        session.respond_interaction = fail
        await _question(session)
        with pytest.raises(AppServiceError):
            await owner._interactions.settle_unowned(frozenset({session.identity.session_id}))
        with pytest.raises(AppServiceError):
            await first.attach_mux(MuxAttachV1(selector))
        with pytest.raises(AppServiceError) as fenced:
            await second.attach_mux(MuxAttachV1(selector))
        assert fenced.value.code is AppErrorCodeV1.ALREADY_ATTACHED
        session.respond_interaction = original
        attachment = await first.attach_mux(MuxAttachV1(selector))
        assert attachment.controller_generation == 1
        assert ("interaction", ("question-1", InteractionOutcomeV1.DENY)) in session.calls
        await service.close()

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_APPROVAL_admitted_response_survives_delivery_and_scope_cancellation() -> None:
    async def scenario() -> None:
        service, owner, first, second, selector, mux, session = await _fixture()
        attachment = await first.attach_mux(MuxAttachV1(selector))
        await _question(session)
        entered, release = asyncio.Event(), asyncio.Event()
        original = session.respond_interaction

        async def delayed(interaction_id, outcome):
            entered.set()
            await release.wait()
            return await original(interaction_id, outcome)

        session.respond_interaction = delayed
        responding = asyncio.create_task(first.respond_interaction(InteractionRespondV1(
            attachment.attachment_id, attachment.controller_generation,
            mux.members[0].member_id, "question-1", InteractionOutcomeV1.APPROVE,
        )))
        await entered.wait()
        responding.cancel()
        with pytest.raises(asyncio.CancelledError):
            await responding
        with pytest.raises(AppServiceError) as retained:
            await first.close()
        assert retained.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
        assert owner.pending_counts == (0, 1)
        release.set()
        await first.close()
        await second.attach_mux(MuxAttachV1(selector))
        assert [call for call in session.calls if call[0] == "interaction"] == [
            ("interaction", ("question-1", InteractionOutcomeV1.APPROVE))
        ]
        await service.close()

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_CONTROLLER_loss_before_admission_prevents_product_start() -> None:
    async def scenario() -> None:
        service, owner, first, second, selector, mux, session = await _fixture()
        attachment = await first.attach_mux(MuxAttachV1(selector))
        await service._state_lock.acquire()
        started = asyncio.Event()

        async def attempt():
            started.set()
            return await first.start_turn(TurnTextV1(
                attachment.attachment_id, attachment.controller_generation,
                mux.members[0].member_id, "must not start",
            ))

        waiter = asyncio.create_task(attempt())
        await started.wait()
        with pytest.raises(AppServiceError):
            await first.close()
        service._state_lock.release()
        with pytest.raises(AppServiceError) as fenced:
            await waiter
        assert fenced.value.code is AppErrorCodeV1.SERVICE_CLOSED
        await first.close()
        assert not any(call[0] == "start" for call in session.calls)
        await service.close()

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_ACCEPTED_WORK_member_open_commits_after_scope_delivery_loss() -> None:
    async def scenario() -> None:
        service, legacy, resolver = await _service()
        owner = ScopedAppServiceV1(service, close_timeout=0.05)
        first, second = owner.open_client_scope(), owner.open_client_scope()
        mux = await first.create_mux(MuxCreateV1("dev"))
        selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
        await first.attach_mux(MuxAttachV1(selector))
        resolver.block_title = "delayed"
        opening = asyncio.create_task(first.open_member(MuxMemberOpenV1(
            selector, _spec("delayed")
        )))
        await resolver.entered.wait()
        opening.cancel()
        with pytest.raises(asyncio.CancelledError):
            await opening
        with pytest.raises(AppServiceError):
            await first.close()
        with pytest.raises(AppServiceError) as busy:
            await second.attach_mux(MuxAttachV1(selector))
        assert busy.value.code is AppErrorCodeV1.ALREADY_ATTACHED
        resolver.release.set()
        await first.close()
        attachment = await second.attach_mux(MuxAttachV1(selector))
        assert len(attachment.mux_space.members) == 1
        assert resolver.sessions[0].closed == 0
        assert owner._opening == 0
        await service.close()

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_BOUNDS_mux_and_session_admission_use_local_not_legacy_limits() -> None:
    async def scenario() -> None:
        service, legacy, resolver = await _service()
        owner = ScopedAppServiceV1(service)
        client = owner.open_client_scope()
        muxes = await asyncio.gather(*(
            client.create_mux(MuxCreateV1(f"mux-{index}")) for index in range(32)
        ))
        with pytest.raises(AppServiceError) as full_mux:
            await client.create_mux(MuxCreateV1("overflow"))
        assert full_mux.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
        selector = MuxSelectorV1(mux_space_id=muxes[0].mux_space_id)
        await client.attach_mux(MuxAttachV1(selector))
        for index in range(64):
            await client.open_member(MuxMemberOpenV1(selector, _spec(str(index))))
        with pytest.raises(AppServiceError) as full_session:
            await client.open_member(MuxMemberOpenV1(selector, _spec("overflow")))
        assert full_session.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
        assert len(resolver.requests) == 64
        assert owner._creating == owner._opening == 0
        await service.close()

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_MULTI_MUX_scope_loss_does_not_affect_other_controller_or_turn() -> None:
    async def scenario() -> None:
        service, legacy, resolver = await _service()
        owner = ScopedAppServiceV1(service)
        clients, attachments, waiters = [], [], []
        for index in range(2):
            client = owner.open_client_scope()
            clients.append(client)
            mux = await client.create_mux(MuxCreateV1(f"mux-{index}"))
            selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
            await client.attach_mux(MuxAttachV1(selector))
            await client.open_member(MuxMemberOpenV1(selector, _spec(str(index))))
            attachment = await client.attach_mux(MuxAttachV1(selector))
            attachments.append(attachment)
            session = resolver.sessions[index]
            session.turn_entered, session.turn_release = asyncio.Event(), asyncio.Event()
            waiters.append(asyncio.create_task(client.start_turn(TurnTextV1(
                attachment.attachment_id, attachment.controller_generation,
                attachment.mux_space.members[0].member_id, f"turn-{index}",
            ))))
            await session.turn_entered.wait()
        await clients[0].close()
        assert owner.pending_counts == (2, 0)
        current = attachments[1]
        await resolver.sessions[1].emit(text="still connected")
        events = await clients[1].read_events(
            attachment_id=current.attachment_id,
            controller_generation=current.controller_generation,
        )
        assert [event.event.text for event in events] == ["still connected"]
        for session in resolver.sessions:
            session.turn_release.set()
        await asyncio.gather(*waiters)
        await service.close()

    asyncio.run(asyncio.wait_for(scenario(), 2))


@pytest.mark.parametrize("close_mux", [False, True])
def test_G16_STOP_explicit_member_or_mux_close_settles_retained_turn(close_mux) -> None:
    async def scenario() -> None:
        service, owner, first, second, selector, mux, session = await _fixture()
        attachment = await first.attach_mux(MuxAttachV1(selector))
        session.turn_entered, session.turn_release = asyncio.Event(), asyncio.Event()
        member_id = mux.members[0].member_id
        waiter = asyncio.create_task(first.start_turn(TurnTextV1(
            attachment.attachment_id, attachment.controller_generation,
            member_id, "stop explicitly",
        )))
        await session.turn_entered.wait()
        if close_mux:
            await first.close_mux(MuxCloseV1(selector))
        else:
            await first.close_member(MuxMemberCloseV1(selector, member_id))
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert not session.turn_release.is_set()
        assert session.closed == 1 and owner.pending_counts == (0, 0)
        await service.close()

    asyncio.run(asyncio.wait_for(scenario(), 2))
