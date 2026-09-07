from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from loushang.appserver.framing import AppFramedStreamV1, AsyncioStreamTransportV1
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    InteractionOutcomeV1,
    MuxCreateV1,
    MuxSelectorV1,
    SessionOpenSpecV1,
    SessionScopeV1,
    TurnInterruptV1,
)
from loushang.appserver.remote_client import StdioAppClientV1
from loushang.coding.cli.hosted import parse_launch
from loushang.harnesstui.mux.profile import open_hosted_mux_profile


def _argv(root: Path) -> list[str]:
    return [
        "--workspace",
        str(root),
        "--application-root",
        str(root / "applications"),
        "--cwd-sessions",
        str(root / "cwd-sessions"),
        "--home-sessions",
        str(root / "home-sessions"),
    ]


def _environment(root: Path) -> dict[str, str]:
    return {
        **os.environ,
        "LOUSHANG_HOME": str(root / "platform"),
        "LOUSHANG_RUNTIME_DIR": str(root / "runtime"),
        "LOUSHANG_TMPDIR": str(root / "scratch"),
    }


def _installed_command() -> str:
    command = Path(sys.executable).parent / (
        "loushang-hosted.exe" if os.name == "nt" else "loushang-hosted"
    )
    assert command.is_file(), "the installed hosted console script must exist"
    return str(command)


@asynccontextmanager
async def _child(
    root: Path, *, installed: bool = False, fail_dispose: bool = False
) -> AsyncIterator[StdioAppClientV1]:
    executable = (
        [_installed_command()]
        if installed
        else [sys.executable, str(Path(__file__).with_name("_hosted_product_child.py"))]
    )
    process = await asyncio.create_subprocess_exec(
        *executable,
        *_argv(root),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={
            **_environment(root),
            "LOUSHANG_G14_TEST_FAIL_DISPOSE": "1" if fail_dispose else "0",
        },
    )
    assert (
        process.stdin is not None
        and process.stdout is not None
        and process.stderr is not None
    )
    errors = asyncio.create_task(process.stderr.read())
    client = StdioAppClientV1(
        AppFramedStreamV1(AsyncioStreamTransportV1(process.stdout, process.stdin)),
        # This parent budget includes cold Product imports and G13 recovery,
        # unlike the child's hello deadline after it has become ready.
        phase_timeout=30,
    )
    try:
        await asyncio.wait_for(client.start(), 35)
        yield client
        await client.close()
        code = await asyncio.wait_for(process.wait(), 15)
        stderr = await errors
        assert code == (1 if fail_dispose else 0), stderr.decode(errors="replace")
        if fail_dispose:
            assert b"hosted_cleanup_incomplete" in stderr
            assert b"private-disposal-sentinel" not in stderr
        else:
            assert stderr == b"", stderr.decode(errors="replace")
    except BaseException as error:
        if process.returncode is None:
            process.kill()
            await asyncio.wait_for(process.wait(), 10)
        stderr = await errors
        if stderr:
            error.add_note(
                "Hosted child stderr:\n" + stderr[-16_384:].decode(errors="replace")
            )
        raise
    finally:
        if process.returncode is None:
            process.kill()
            await asyncio.wait_for(process.wait(), 10)
        process.stdin.close()
        await client.close()
        await asyncio.gather(errors, return_exceptions=True)


def test_G14_PRODUCT_installed_entrypoint_help_startup_and_clean_eof(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        help_process = await asyncio.create_subprocess_exec(
            _installed_command(),
            "--help",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_environment(tmp_path),
        )
        try:
            stdout, stderr = await asyncio.wait_for(help_process.communicate(), 15)
            assert help_process.returncode == 0 and stderr == b""
            assert b"--application-root" in stdout and b"--describe" in stdout
        finally:
            if help_process.returncode is None:
                help_process.kill()
                await help_process.wait()
        async with _child(tmp_path, installed=True) as client:
            assert (await client.list_muxes()).mux_spaces == ()

    asyncio.run(asyncio.wait_for(scenario(), 50))


def test_G14_OWNERSHIP_second_installed_writer_fails_before_ready(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with _child(tmp_path, installed=True) as first:
            second = await asyncio.create_subprocess_exec(
                _installed_command(),
                *_argv(tmp_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_environment(tmp_path),
            )
            try:
                stdout, stderr = await asyncio.wait_for(second.communicate(b""), 30)
                assert second.returncode == 1
                assert stdout == b"", "failed recovery must never publish ready"
                assert stderr.strip() == b"hosted_application_failed"
                assert (await first.list_muxes()).mux_spaces == ()
            finally:
                if second.returncode is None:
                    second.kill()
                    await second.wait()

    asyncio.run(asyncio.wait_for(scenario(), 70))


@pytest.mark.parametrize("scope_kind", [SessionScopeV1.CWD, SessionScopeV1.USER_HOME])
def test_G14_RECOVERY_real_product_subprocess_restores_mux_session_and_transcript(
    tmp_path: Path,
    scope_kind: SessionScopeV1,
) -> None:
    async def scenario() -> None:
        launch, _ = parse_launch(_argv(tmp_path))
        scope = next(scope for scope in launch.scopes if scope.scope is scope_kind)
        selector = MuxSelectorV1(name="dev")
        async with _child(tmp_path) as client:
            mux = await client.create_mux(MuxCreateV1("dev"))
            controller = await open_hosted_mux_profile(client, selector=selector)
            state = await controller.open_member(
                SessionOpenSpecV1(
                    "coding",
                    "continuity-1",
                    scope_kind,
                    scope.fingerprint,
                    "Coding",
                )
            )
            window = state.active_window
            assert window is not None
            await controller.submit("你好，真实会话")
            saw_delta = False
            for _ in range(30):
                state = await controller.poll()
                saw_delta |= bool(window.assistant_draft)
                if len(window.records) == 2 and not window.running:
                    break
            assert saw_delta, (
                "streamed text must reach the existing Harnesstui controller"
            )
            assert [record.text for record in window.records] == [
                "你好，真实会话",
                "真实跨进程回复\nG14",
            ]
            old_attachment = state.attachment_id
            old_generation = state.controller_generation
            old_member, old_session = window.member_id, window.session_id
            await controller.close()

        assert len(tuple(scope.session_dir.glob("*.jsonl"))) == 1
        async with _child(tmp_path) as fresh_client:
            restored = await open_hosted_mux_profile(fresh_client, selector=selector)
            state = restored.state
            assert state is not None and state.active_window is not None
            window = state.active_window
            assert state.mux_space_id == mux.mux_space_id
            assert (window.member_id, window.session_id) == (old_member, old_session)
            assert state.attachment_id != old_attachment
            assert [record.text for record in window.records] == [
                "你好，真实会话",
                "真实跨进程回复\nG14",
            ]
            assert not window.running and window.pending_interaction_id is None
            with pytest.raises(AppServiceError) as stale:
                await fresh_client.interrupt_turn(
                    TurnInterruptV1(old_attachment, old_generation, old_member)
                )
            assert stale.value.code is AppErrorCodeV1.STALE_ATTACHMENT
            await restored.close()

    asyncio.run(asyncio.wait_for(scenario(), 90))


async def _open_cwd_member(client, root: Path):
    launch, _ = parse_launch(_argv(root))
    await client.create_mux(MuxCreateV1("dev"))
    controller = await open_hosted_mux_profile(
        client, selector=MuxSelectorV1(name="dev")
    )
    state = await controller.open_member(
        SessionOpenSpecV1(
            "coding",
            "continuity-1",
            SessionScopeV1.CWD,
            launch.scopes[0].fingerprint,
            "Coding",
        )
    )
    assert state.active_window is not None
    return controller, state.active_window


async def _poll_until(controller, predicate):
    async with asyncio.timeout(15):
        while not predicate():
            state = await controller.poll()
            assert not state.snapshot_required
            await asyncio.sleep(0.01)


@pytest.mark.parametrize(
    "outcome", [InteractionOutcomeV1.APPROVE, InteractionOutcomeV1.DENY]
)
def test_G14_CONTROL_real_policy_approval_gates_safe_tool_execution(
    tmp_path: Path, outcome
) -> None:
    config = tmp_path / ".loushang"
    config.mkdir()
    (config / "settings.json").write_text(
        json.dumps({"tools": {"ask_tools": ["g14_preview"]}})
    )

    async def scenario() -> None:
        async with _child(tmp_path) as client:
            controller, window = await _open_cwd_member(client, tmp_path)
            turn = asyncio.create_task(controller.submit("approval"))
            try:
                await _poll_until(
                    controller,
                    lambda: (
                        window.pending_interaction_id is not None
                        or (turn.done() and not window.running)
                    ),
                )
                assert window.pending_interaction_id is not None, window.records
                assert not turn.done()
                assert "g14_preview" in window.pending_interaction_text
                await controller.respond_interaction(
                    window.pending_interaction_id, outcome
                )
                await asyncio.wait_for(turn, 15)
                await _poll_until(
                    controller,
                    lambda: (
                        not window.running and window.pending_interaction_id is None
                    ),
                )
                result = "\n".join(record.text for record in window.records)
                assert ("APPROVED_PREVIEW_EXECUTED" in result) == (
                    outcome is InteractionOutcomeV1.APPROVE
                )
            finally:
                if not turn.done():
                    await controller.interrupt()
                await asyncio.gather(turn, return_exceptions=True)
            await controller.close()

    asyncio.run(asyncio.wait_for(scenario(), 60))


@pytest.mark.parametrize("disconnect", [False, True])
def test_G14_OWNERSHIP_real_running_turn_interrupt_or_eof_then_restart(
    tmp_path: Path, disconnect: bool
) -> None:
    async def scenario() -> None:
        async with _child(tmp_path) as client:
            controller, window = await _open_cwd_member(client, tmp_path)
            turn = asyncio.create_task(controller.submit("hold"))
            await _poll_until(controller, lambda: window.assistant_draft == "waiting")
            assert not turn.done()
            identity = window.session_id
            if disconnect:
                await client.close()
                with pytest.raises(AppServiceError):
                    await turn
            else:
                await controller.interrupt()
                await asyncio.wait_for(turn, 15)
                await _poll_until(controller, lambda: not window.running)
                await controller.close()
        async with _child(tmp_path) as fresh:
            restored = await open_hosted_mux_profile(
                fresh, selector=MuxSelectorV1(name="dev")
            )
            assert (
                restored.state is not None and restored.state.active_window is not None
            )
            window = restored.state.active_window
            assert window.session_id == identity
            assert window.records[0].text == "hold"
            assert not window.running and window.pending_interaction_id is None
            await restored.close()

    asyncio.run(asyncio.wait_for(scenario(), 90))


def test_G14_OWNERSHIP_fatal_cleanup_is_nonzero_and_fresh_process_can_recover(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with _child(tmp_path, fail_dispose=True) as client:
            controller, window = await _open_cwd_member(client, tmp_path)
            session_id = window.session_id
            await controller.submit("persist before failed cleanup")
            # EOF will hit the injected real AgentSession disposal failure.
            # The parent must observe nonzero exit, never a hanging asyncio join.
        async with _child(tmp_path) as fresh:
            restored = await open_hosted_mux_profile(
                fresh, selector=MuxSelectorV1(name="dev")
            )
            assert (
                restored.state is not None and restored.state.active_window is not None
            )
            window = restored.state.active_window
            assert window.session_id == session_id
            assert window.records[0].text == "persist before failed cleanup"
            await restored.close()

    asyncio.run(asyncio.wait_for(scenario(), 90))


def test_G14_OWNERSHIP_eof_during_approval_does_not_restore_authority(
    tmp_path: Path,
) -> None:
    config = tmp_path / ".loushang"
    config.mkdir()
    (config / "settings.json").write_text(
        json.dumps({"tools": {"ask_tools": ["g14_preview"]}})
    )

    async def scenario() -> None:
        async with _child(tmp_path) as client:
            controller, window = await _open_cwd_member(client, tmp_path)
            turn = asyncio.create_task(controller.submit("approval"))
            try:
                await _poll_until(
                    controller, lambda: window.pending_interaction_id is not None
                )
                assert not turn.done()
                identity = window.session_id
                await client.close()
                with pytest.raises(AppServiceError):
                    await turn
            finally:
                await client.close()
                await asyncio.gather(turn, return_exceptions=True)
        async with _child(tmp_path) as fresh:
            restored = await open_hosted_mux_profile(
                fresh, selector=MuxSelectorV1(name="dev")
            )
            assert restored.state is not None
            window = restored.state.active_window
            assert window is not None and window.session_id == identity
            assert not window.running and window.pending_interaction_id is None
            assert all(
                "APPROVED_PREVIEW_EXECUTED" not in record.text
                for record in window.records
            )
            await restored.close()

    asyncio.run(asyncio.wait_for(scenario(), 90))
