from __future__ import annotations

import asyncio

import pytest

from loushang.appserver.local import LocalAppClientConnectionV1, LocalAppServerV1
from loushang.appserver.local_record import (
    LocalConnectionDirectoryV1,
    LocalRecordScopeV1,
)
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    InteractionOutcomeV1,
    InteractionRespondV1,
    MuxAttachV1,
    MuxCreateV1,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionEventKindV1,
    SessionEventV1,
    SessionScopeV1,
    SessionSnapshotRequestV1,
    TurnTextV1,
)
from loushang.appservice.client_scope import ScopedAppServiceV1

from .test_runtime import FINGERPRINT, _service, _spec


async def _until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


def test_G16_LOCAL_NATIVE_multi_mux_eof_retains_execution_and_reattach_fences_old_authority(tmp_path):
    async def scenario():
        service, _, resolver = await _service()
        scopes = ScopedAppServiceV1(service)
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        server = LocalAppServerV1(
            directory, "workspace", application_id="application", product_id="coding",
            scopes=(LocalRecordScopeV1(SessionScopeV1.CWD, FINGERPRINT),),
            scope_factory=scopes.open_client_scope,
            request_stop=lambda _: pytest.fail("disconnect requested application stop"),
        )
        clients = [LocalAppClientConnectionV1(directory, "workspace") for _ in range(3)]
        turns = []
        try:
            await server.start()
            await clients[0].start()
            await clients[1].start()
            first, second = clients[0].client, clients[1].client
            selectors, attachments, muxes = [], [], []
            for client, name in ((first, "dev"), (second, "review")):
                mux = await client.create_mux(MuxCreateV1(name))
                selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
                await client.attach_mux(MuxAttachV1(selector))
                mux = await client.open_member(MuxMemberOpenV1(selector, _spec(name)))
                attachments.append(await client.attach_mux(MuxAttachV1(selector)))
                selectors.append(selector)
                muxes.append(mux)
            with pytest.raises(AppServiceError) as busy:
                await second.attach_mux(MuxAttachV1(selectors[0]))
            assert busy.value.code is AppErrorCodeV1.ALREADY_ATTACHED
            for client, attachment, mux, session in zip((first, second), attachments, muxes, resolver.sessions, strict=True):
                session.turn_entered, session.turn_release = asyncio.Event(), asyncio.Event()
                turns.append(asyncio.create_task(client.start_turn(TurnTextV1(
                    attachment.attachment_id, attachment.controller_generation, mux.members[0].member_id, "retained"
                ))))
                await session.turn_entered.wait()
            await clients[0].close()
            with pytest.raises(AppServiceError):
                await turns[0]
            await _until(lambda: server.connection_counts == (0, 1))
            assert scopes.pending_counts == (2, 0)
            assert not turns[1].done()
            assert all(("interrupt", "") not in session.calls and session.closed == 0 for session in resolver.sessions)
            await clients[2].start()
            fresh = await clients[2].client.attach_mux(MuxAttachV1(selectors[0]))
            assert fresh.controller_generation > attachments[0].controller_generation
            assert fresh.attachment_id != attachments[0].attachment_id
            with pytest.raises(AppServiceError) as stale:
                await clients[2].client.snapshot_session(SessionSnapshotRequestV1(
                    attachments[0].attachment_id, attachments[0].controller_generation, muxes[0].members[0].member_id
                ))
            assert stale.value.code is AppErrorCodeV1.STALE_ATTACHMENT
            snapshot = await clients[2].client.snapshot_session(SessionSnapshotRequestV1(
                fresh.attachment_id, fresh.controller_generation, muxes[0].members[0].member_id
            ))
            assert snapshot.identity == resolver.sessions[0].identity
            assert resolver.sessions[0].calls.count(("start", "retained")) == 1
            for session in resolver.sessions:
                session.turn_release.set()
            await turns[1]
            await _until(lambda: scopes.pending_counts == (0, 0))
        finally:
            for session in resolver.sessions:
                if session.turn_release is not None:
                    session.turn_release.set()
            await asyncio.gather(*(client.close() for client in clients))
            await asyncio.gather(*turns, return_exceptions=True)
            await server.close()
            await service.close()
            directory.close()
    asyncio.run(asyncio.wait_for(scenario(), 15))


def test_G16_LOCAL_NATIVE_disconnect_denies_old_approval_before_regrant(tmp_path):
    async def scenario():
        service, legacy, resolver = await _service()
        mux = await legacy.create_mux(MuxCreateV1("dev"))
        selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
        mux = await legacy.open_member(MuxMemberOpenV1(selector, _spec()))
        scopes = ScopedAppServiceV1(service)
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        server = LocalAppServerV1(
            directory, "workspace", application_id="application", product_id="coding",
            scopes=(LocalRecordScopeV1(SessionScopeV1.CWD, FINGERPRINT),),
            scope_factory=scopes.open_client_scope, request_stop=lambda _: pytest.fail("unexpected stop"),
        )
        first, second = (LocalAppClientConnectionV1(directory, "workspace") for _ in range(2))
        try:
            await server.start()
            await first.start()
            old = await first.client.attach_mux(MuxAttachV1(selector))
            session = resolver.sessions[0]
            await session.listener(SessionEventV1(
                session.identity.session_id, 1, SessionEventKindV1.INTERACTION_REQUESTED,
                interaction_id="question", text="approve?",
            ))
            await first.close()
            await _until(lambda: server.connection_counts == (0, 0))
            assert ("interaction", ("question", InteractionOutcomeV1.DENY)) in session.calls
            await second.start()
            fresh = await second.client.attach_mux(MuxAttachV1(selector))
            for attachment in (old, fresh):
                with pytest.raises(AppServiceError):
                    await second.client.respond_interaction(InteractionRespondV1(
                        attachment.attachment_id, attachment.controller_generation,
                        mux.members[0].member_id, "question", InteractionOutcomeV1.APPROVE,
                    ))
            assert ("interaction", ("question", InteractionOutcomeV1.APPROVE)) not in session.calls
        finally:
            await first.close()
            await second.close()
            await server.close()
            await service.close()
            directory.close()
    asyncio.run(asyncio.wait_for(scenario(), 10))
