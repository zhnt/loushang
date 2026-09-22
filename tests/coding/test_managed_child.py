from __future__ import annotations

import asyncio

import pytest

from loushang.agent import synthetic_model_transport
from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.child import ManagedChildApplicationV1
from loushang.appserver.local import LocalAppClientConnectionV1, LocalConnectionModeV1
from loushang.appserver.local_record import LocalConnectionDirectoryV1
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    MuxAttachV1,
    MuxCreateV1,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionOpenSpecV1,
    SessionSnapshotRequestV1,
    TurnTextV1,
)
from loushang.coding.hosted_local import CodingLocalCommandV1

from ..apphost.test_managed_child import binding as binding
from ..apphost.test_managed_child import until
from ._hosted_product_child import scripted_stream
from .test_hosted_local import _local_launch, _model


def test_real_coding_child_handoff_keeps_accepted_work_after_starter_and_client_eof(
    binding, tmp_path, monkeypatch,
):
    journal, _, _, parent, control = binding

    async def scenario():
        root = tmp_path.resolve()
        monkeypatch.setenv("LOUSHANG_HOME", str(root / "platform"))
        monkeypatch.setenv("LOUSHANG_RUNTIME_DIR", str(root / "runtime"))
        launch = _local_launch(root)
        entered, release = asyncio.Event(), asyncio.Event()
        calls = 0

        @synthetic_model_transport
        async def held_stream(model, context, options=None):
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return await scripted_stream(model, context, options)

        command = CodingLocalCommandV1(launch, model=_model(), stream_fn=held_stream, tools=[])
        owner = ManagedChildApplicationV1(command, control)
        directory = LocalConnectionDirectoryV1(launch.connection_root)
        client = LocalAppClientConnectionV1(directory, launch.endpoint)
        fresh = LocalAppClientConnectionV1(directory, launch.endpoint)
        stop = LocalAppClientConnectionV1(directory, launch.endpoint, mode=LocalConnectionModeV1.STOP)
        runner = asyncio.create_task(owner.run())
        turn = None
        try:
            await until(lambda: owner.accepting)
            assert journal.read().handoff.phase.value == "committed"
            await client.start()
            mux = await client.client.create_mux(MuxCreateV1("dev"))
            selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
            await client.client.attach_mux(MuxAttachV1(selector))
            scope = launch.application.scopes[0]
            mux = await client.client.open_member(MuxMemberOpenV1(
                selector, SessionOpenSpecV1("coding", "managed-child", scope.scope, scope.fingerprint, "dev"),
            ))
            attachment = await client.client.attach_mux(MuxAttachV1(selector))
            turn = asyncio.create_task(client.client.start_turn(TurnTextV1(
                attachment.attachment_id, attachment.controller_generation, mux.members[0].member_id, "hello",
            )))
            admitted = asyncio.create_task(entered.wait())
            try:
                done, _ = await asyncio.wait({turn, admitted}, return_when=asyncio.FIRST_COMPLETED)
                if turn in done:
                    await turn
                    pytest.fail("turn completed before controlled model release")
            finally:
                admitted.cancel()
                await asyncio.gather(admitted, return_exceptions=True)
            parent.close()  # Actual inherited stream EOF, after durable handoff.
            await client.close()
            await asyncio.gather(turn, return_exceptions=True)
            assert owner.accepting and not command._closing and calls == 1
            await fresh.start()
            while True:
                try:
                    current = await fresh.client.attach_mux(MuxAttachV1(selector))
                    break
                except AppServiceError as error:
                    if error.code is not AppErrorCodeV1.ALREADY_ATTACHED:
                        raise
                    await asyncio.sleep(0.01)
            request = SessionSnapshotRequestV1(
                current.attachment_id, current.controller_generation, mux.members[0].member_id,
            )
            assert (await fresh.client.snapshot_session(request)).running
            release.set()
            while (snapshot := await fresh.client.snapshot_session(request)).running:
                await asyncio.sleep(0.01)
            assert calls == 1 and "真实跨进程回复" in str(snapshot)
            await stop.start()
            assert stop.stop_requested
            await runner
            assert not owner.cleanup_pending and not command.cleanup_pending
            evidence = journal.read().evidence
            assert evidence.application_cleanup_completed
            assert not evidence.process_exited and not evidence.process_scope_settled
        finally:
            release.set()
            await asyncio.gather(client.close(), fresh.close(), stop.close())
            await owner.close(retry_timeout=5)
            await asyncio.gather(runner, return_exceptions=True)
            if turn is not None:
                await asyncio.gather(turn, return_exceptions=True)
            directory.close()
    asyncio.run(asyncio.wait_for(scenario(), 40))


def test_real_coding_prepare_timeout_can_close_while_journal_observation_is_unknown(
    binding, tmp_path, monkeypatch,
):
    journal, _, _, _, control = binding

    async def scenario():
        root = tmp_path.resolve()
        monkeypatch.setenv("LOUSHANG_HOME", str(root / "platform"))
        monkeypatch.setenv("LOUSHANG_RUNTIME_DIR", str(root / "runtime"))
        command = CodingLocalCommandV1(
            _local_launch(root), model=_model(), stream_fn=scripted_stream, tools=[], settlement_timeout=5,
        )
        owner = ManagedChildApplicationV1(command, control, startup_timeout=0.15, settlement_timeout=0.03)
        entered, release = asyncio.Event(), asyncio.Event()
        original_open, original_read = type(command._attempt).open, journal.read

        async def late_open(self):
            entered.set()
            await release.wait()
            return await original_open(self)

        def unavailable(**kwargs):
            raise ManagedStorageError("unavailable")

        monkeypatch.setattr(type(command._attempt), "open", late_open)
        runner = asyncio.create_task(owner.run())
        try:
            await entered.wait()
            monkeypatch.setattr(journal, "read", unavailable)
            await until(lambda: command._closing)
            assert not owner.accepting and owner.cleanup_pending
            release.set()
            await asyncio.gather(runner, return_exceptions=True)
            await until(lambda: not command.cleanup_pending)
            await until(lambda: owner._close_task.done())
            assert owner.cleanup_pending  # Product closed is not persisted proof.
            monkeypatch.setattr(journal, "read", original_read)
            assert not journal.read().evidence.application_cleanup_completed
            await owner.close(retry_timeout=5)
            assert not owner.cleanup_pending
            assert journal.read().evidence.application_cleanup_completed
            assert command._activate_task is None
        finally:
            release.set()
            monkeypatch.setattr(journal, "read", original_read)
            await until(lambda: owner._close_task is None or owner._close_task.done())
            await owner.close(retry_timeout=5)
            await asyncio.gather(runner, return_exceptions=True)
    asyncio.run(asyncio.wait_for(scenario(), 25))
