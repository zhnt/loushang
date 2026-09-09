from __future__ import annotations

import asyncio
import time
from dataclasses import replace

import pytest

from loushang.agent import synthetic_model_transport
from loushang.ai.types import TextPart
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
    SessionScopeV1,
    SessionSnapshotRequestV1,
    TurnTextV1,
)
from loushang.coding.hosted_local import CodingLocalCommandV1, CodingLocalLaunchV1

from ._hosted_product_child import scripted_stream
from .test_hosted_bootstrap import _launch


def _local_launch(root):
    return CodingLocalLaunchV1(_launch(root), root / "connections", "workspace")


def _model():
    from loushang.ai.model import Capabilities, Model

    return Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            input=("text",), context_window=128000, max_tokens=4096
        ),
    )


def test_G16_PRODUCT_launch_rejects_shared_storage_and_does_not_create_files(tmp_path):
    launch = _local_launch(tmp_path.resolve())
    for root in (
        launch.application.application_root,
        launch.application.cwd_sessions / "keys",
        launch.application.home_sessions,
        tmp_path.resolve(),
    ):
        with pytest.raises(ValueError):
            replace(launch, connection_root=root)
    assert not tuple(tmp_path.iterdir())
    assert str(tmp_path) not in repr(launch)


@pytest.mark.parametrize("discovery_enabled", [False, True])
def test_G16_PRODUCT_real_coding_retains_disconnected_work_and_recovers_both_scopes(
    tmp_path,
    monkeypatch,
    discovery_enabled,
):
    began = time.monotonic()
    timings = []

    def mark(phase):
        timings.append((phase, round(time.monotonic() - began, 3)))

    async def first_generation():
        root = tmp_path.resolve()
        monkeypatch.setenv("LOUSHANG_HOME", str(root / "platform"))
        monkeypatch.setenv("LOUSHANG_RUNTIME_DIR", str(root / "runtime"))
        launch = replace(_local_launch(root), session_discovery=discovery_enabled)
        hold_entered = asyncio.Event()

        @synthetic_model_transport
        async def observed_stream(model, context, options=None):
            stream = await scripted_stream(model, context, options)
            latest = context.messages[-1]
            if latest.role == "user":
                text = (
                    latest.content
                    if isinstance(latest.content, str)
                    else "".join(
                        part.text
                        for part in latest.content
                        if isinstance(part, TextPart)
                    )
                )
                if text == "hold":
                    hold_entered.set()
            return stream

        command = CodingLocalCommandV1(
            launch, model=_model(), stream_fn=observed_stream, tools=[]
        )
        directory = LocalConnectionDirectoryV1(launch.connection_root)
        first, second, fresh = (
            LocalAppClientConnectionV1(directory, launch.endpoint) for _ in range(3)
        )
        stop = LocalAppClientConnectionV1(
            directory, launch.endpoint, mode=LocalConnectionModeV1.STOP
        )
        turn = None
        identities = []
        old_key = None
        try:
            mark("first_start")
            await command.start()
            mark("first_ready_construct_and_interact")
            old_key = directory.read(launch.endpoint).key
            for connection, scope, name in zip(
                (first, second),
                launch.application.scopes,
                ("dev", "review"),
                strict=True,
            ):
                await connection.start()
                client = connection.client
                mux = await client.create_mux(MuxCreateV1(name))
                selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
                await client.attach_mux(MuxAttachV1(selector))
                mux = await client.open_member(
                    MuxMemberOpenV1(
                        selector,
                        SessionOpenSpecV1(
                            "coding",
                            f"continuity-{name}",
                            scope.scope,
                            scope.fingerprint,
                            name,
                        ),
                    )
                )
                attachment = await client.attach_mux(MuxAttachV1(selector))
                identities.append((mux, attachment))
                if name == "review":
                    await client.start_turn(
                        TurnTextV1(
                            attachment.attachment_id,
                            attachment.controller_generation,
                            mux.members[0].member_id,
                            "hello",
                        )
                    )
            mux, attachment = identities[0]
            turn = asyncio.create_task(
                first.client.start_turn(
                    TurnTextV1(
                        attachment.attachment_id,
                        attachment.controller_generation,
                        mux.members[0].member_id,
                        "hold",
                    )
                )
            )
            # This case tests disconnect during execution, not a cold-start SLO.
            # Model entry remains bounded by this generation's 30-second watchdog.
            entered = asyncio.create_task(hold_entered.wait())
            try:
                done, _ = await asyncio.wait(
                    (entered, turn), return_when=asyncio.FIRST_COMPLETED
                )
                if turn in done:
                    await turn  # Preserve a preflight failure instead of timing out.
                    pytest.fail("held turn completed before disconnect")
            finally:
                entered.cancel()
                await asyncio.gather(entered, return_exceptions=True)
            async with asyncio.timeout(5):
                while not (
                    await first.client.snapshot_session(
                        SessionSnapshotRequestV1(
                            attachment.attachment_id,
                            attachment.controller_generation,
                            mux.members[0].member_id,
                        )
                    )
                ).running:
                    await asyncio.sleep(0.001)
            await first.close()
            await asyncio.gather(turn, return_exceptions=True)
            assert len((await second.client.list_muxes()).mux_spaces) == 2
            await fresh.start()
            async with asyncio.timeout(5):
                while True:
                    try:
                        replacement = await fresh.client.attach_mux(
                            MuxAttachV1(MuxSelectorV1(name="dev"))
                        )
                        break
                    except AppServiceError as error:
                        if error.code is not AppErrorCodeV1.ALREADY_ATTACHED:
                            raise
                        await asyncio.sleep(0.001)
            snapshot = await fresh.client.snapshot_session(
                SessionSnapshotRequestV1(
                    replacement.attachment_id,
                    replacement.controller_generation,
                    mux.members[0].member_id,
                )
            )
            assert snapshot.running
            assert replacement.attachment_id != attachment.attachment_id
            mark("first_stop")
            await stop.start()
            assert stop.stop_requested
            await command.wait_closed()
            assert not command.cleanup_pending
            mark("first_stopped")
        finally:
            await asyncio.gather(
                first.close(), second.close(), fresh.close(), stop.close()
            )
            await command.close(retry_timeout=5)
            if turn is not None:
                await asyncio.gather(turn, return_exceptions=True)
            directory.close()
        mark("first_settled")
        return launch, identities, old_key

    async def recovery_generation(launch, identities, old_key):
        mark("recovery_start")
        recovered = CodingLocalCommandV1(
            launch, model=_model(), stream_fn=scripted_stream, tools=[]
        )
        new_directory = LocalConnectionDirectoryV1(launch.connection_root)
        client = LocalAppClientConnectionV1(new_directory, launch.endpoint)
        try:
            await recovered.start()
            mark("recovery_ready")
            assert new_directory.read(launch.endpoint).key != old_key
            await client.start()
            muxes = (await client.client.list_muxes()).mux_spaces
            assert {mux.mux_space_id for mux in muxes} == {
                mux.mux_space_id for mux, _ in identities
            }
            for mux in muxes:
                attachment = await client.client.attach_mux(
                    MuxAttachV1(MuxSelectorV1(mux_space_id=mux.mux_space_id))
                )
                snapshot = await client.client.snapshot_session(
                    SessionSnapshotRequestV1(
                        attachment.attachment_id,
                        attachment.controller_generation,
                        mux.members[0].member_id,
                    )
                )
                assert (
                    not snapshot.running
                )  # Recover history, never replay the held turn.
                assert snapshot.identity.scope in {
                    SessionScopeV1.CWD,
                    SessionScopeV1.USER_HOME,
                }
                if mux.name == "review":
                    assert "真实跨进程回复" in str(snapshot)
        finally:
            await client.close()
            await recovered.close(retry_timeout=5)
            new_directory.close()
        mark("recovery_settled")

    async def scenario():
        try:
            facts = await asyncio.wait_for(first_generation(), 30)
            # A new application's recovery does not inherit the previous
            # generation's elapsed test time. No operation retry renews a budget.
            await asyncio.wait_for(recovery_generation(*facts), 30)
        except BaseException as error:
            mark("failed")
            error.add_note(f"G16 lifecycle phase timings (seconds): {timings}")
            raise

    asyncio.run(scenario())
