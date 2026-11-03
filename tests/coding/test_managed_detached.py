from __future__ import annotations

import asyncio
import json
import os
import select
import signal
import socket
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from secrets import token_hex
from time import monotonic

import pytest

from loushang.apphost.managed._files import ManagedStorageError
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
    TranscriptRecordKindV1,
    TurnTextV1,
)
from loushang.coding.managed_bootstrap import CodingManagedApplicationLaunchV1
from loushang.coding.managed_local import CodingManagedLocalLaunchV1
from loushang.hosting.service import LinuxServiceObserverV1

from ..apphost.test_managed_bootstrap import deployment as deployment
from ..hosting._pidfd_signal import send_signal as _send_signal
from .test_hosted_local import _local_launch

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux detached Product")


@pytest.mark.parametrize("exit_mode,controller_failure,late_birth,stop_signal,canonical", [
    ("normal", False, False, None, False), ("abrupt", False, False, None, False),
    ("normal", True, False, None, False), ("normal", False, True, None, False),
    ("normal", False, False, signal.SIGTERM, False), ("normal", False, False, signal.SIGINT, False),
    pytest.param("normal", False, False, None, True, id="canonical-parent-exit"),
    pytest.param("abrupt", False, False, None, True, id="canonical-parent-crash"),
    pytest.param("normal", False, True, signal.SIGTERM, True, id="canonical-late-birth-term"),
])
def test_actual_coding_service_outlives_starter_and_reconnects(deployment, tmp_path, exit_mode, controller_failure, late_birth, stop_signal, canonical):
    _, _, journal, _, paths = deployment
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    address = "lmux-product-test-" + token_hex(16)
    listener.bind("\0" + address)
    listener.listen(1)
    listener.settimeout(15)
    if canonical:
        (tmp_path / "sessions").mkdir(mode=0o700)
    command = [sys.executable, str(Path(__file__).with_name("_managed_product_child.py")), str(tmp_path), address,
               "canonical" if canonical else "legacy"]
    starter = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("_managed_starter.py")), json.dumps(command),
         str(tmp_path), exit_mode, "late" if late_birth else "normal"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    observer, endpoint = None, None

    async def read_state():
        deadline = monotonic() + 3
        while True:
            try:
                return journal.read(deadline=deadline)
            except ManagedStorageError as error:
                if error.code != "busy" or monotonic() >= deadline:
                    raise
                await asyncio.sleep(0.005)

    async def scenario():
        endpoint.setblocking(False)
        reader, writer = await asyncio.open_connection(sock=endpoint)
        launch = _local_launch(tmp_path)
        launch = replace(launch, connection_root=Path(paths.connection),
                         application=replace(launch.application, application_root=Path(paths.application)))
        if canonical:
            launch = CodingManagedLocalLaunchV1(
                CodingManagedApplicationLaunchV1(tmp_path, Path(paths.application), "coding.default", tmp_path / "sessions"),
                Path(paths.connection), launch.endpoint, session_discovery=True,
            )
        directory = LocalConnectionDirectoryV1(launch.connection_root)
        client = LocalAppClientConnectionV1(directory, launch.endpoint)
        fresh = LocalAppClientConnectionV1(directory, launch.endpoint)
        stop = LocalAppClientConnectionV1(directory, launch.endpoint, mode=LocalConnectionModeV1.STOP)
        turn = None
        try:
            assert await reader.readexactly(1) == b"B"
            if late_birth:
                assert (await read_state()).native_identity is None
                gate_deadline = monotonic() + 3
                while True:
                    gate = journal._database._directory.lock("registry.lock", deadline=gate_deadline)
                    try:
                        gate.__enter__()
                        break
                    except ManagedStorageError as error:
                        if error.code != "busy" or monotonic() >= gate_deadline:
                            raise
                        await asyncio.sleep(0.005)
                try:
                    starter.stdin.write(b"R")
                    starter.stdin.flush()
                    # Keep the lock until the starter proves it actually took
                    # the busy branch. Scheduler timing cannot make old code pass.
                    receipt = bytearray()
                    ready = select.poll()
                    ready.register(starter.stdout, select.POLLIN | select.POLLHUP)
                    while b"\n" not in receipt:
                        assert monotonic() < gate_deadline, "no registration contention receipt"
                        if ready.poll(0):
                            chunk = os.read(starter.stdout.fileno(), 64 - len(receipt))
                            assert chunk, "starter exited before observing contention"
                            receipt.extend(chunk)
                            assert len(receipt) < 64
                        else:
                            await asyncio.sleep(0.005)
                    assert receipt == b"registration_busy\n"
                finally:
                    gate.__exit__(None, None, None)
            assert await reader.readexactly(1) == b"R"
            state = await read_state()
            assert state.native_identity == observer.identity
            assert state.handoff.phase.value == "committed"
            if controller_failure:
                writer.write(b"X")
                await writer.drain()
                assert await reader.read() == b""  # Failure must never send D.
                assert await asyncio.to_thread(observer.exited, timeout=8)
                assert "invalid test command" in (tmp_path / "child-diagnostic.log").read_text()
                return
            await client.start()
            mux = await client.client.create_mux(MuxCreateV1("dev"))
            selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
            await client.client.attach_mux(MuxAttachV1(selector))
            scope = launch.application.scopes[0]
            mux = await client.client.open_member(MuxMemberOpenV1(selector, SessionOpenSpecV1(
                "coding", "detached-test", scope.scope, scope.fingerprint, "dev",
            )))
            attached = await client.client.attach_mux(MuxAttachV1(selector))
            turn = asyncio.create_task(client.client.start_turn(TurnTextV1(
                attached.attachment_id, attached.controller_generation, mux.members[0].member_id, "hello",
            )))
            assert await reader.readexactly(1) == b"E"  # Model really entered.
            # Exact test-owned pidfd, not a possibly reused numeric PID. HUP is
            # injected while real accepted work is still held and must survive.
            _send_signal(observer, signal.SIGHUP)
            original = await client.client.snapshot_session(SessionSnapshotRequestV1(
                attached.attachment_id, attached.controller_generation, mux.members[0].member_id,
            ))
            _, errors = await asyncio.to_thread(starter.communicate, b"Q", timeout=5)
            assert starter.returncode == 0, errors.decode(errors="replace")
            assert not observer.exited()
            await client.close()
            await asyncio.gather(turn, return_exceptions=True)
            await fresh.start()
            while True:
                try:
                    attached = await fresh.client.attach_mux(MuxAttachV1(selector))
                    break
                except AppServiceError as error:
                    if error.code is not AppErrorCodeV1.ALREADY_ATTACHED:
                        raise
                    await asyncio.sleep(0.01)
            request = SessionSnapshotRequestV1(
                attached.attachment_id, attached.controller_generation, mux.members[0].member_id,
            )
            running = await fresh.client.snapshot_session(request)
            assert running.running and running.identity == original.identity
            writer.write(b"G")
            await writer.drain()
            while (snapshot := await fresh.client.snapshot_session(request)).running:
                await asyncio.sleep(0.01)
            assert snapshot.identity == original.identity
            assert [record.text for record in snapshot.records if record.kind is TranscriptRecordKindV1.ASSISTANT] == [
                "真实跨进程回复\nG14",
            ]
            writer.write(b"C")
            await writer.drain()
            assert await reader.readline() == b"1\n"
            if stop_signal is None:
                await stop.start()
                assert stop.stop_requested
            else:
                _send_signal(observer, stop_signal)
                _send_signal(observer, stop_signal)  # Never escalates to a kill.
            assert await reader.readexactly(1) == b"D"  # All helper-owned dependencies closed successfully.
            assert await asyncio.to_thread(observer.exited, timeout=8)
            evidence = (await read_state()).evidence
            assert evidence.application_cleanup_completed
            # A pidfd observation is not a persisted scope settlement claim.
            assert not evidence.process_exited and not evidence.process_scope_settled
            if canonical:
                assert len(tuple((tmp_path / "sessions").glob("*.jsonl"))) == 1
                assert not (tmp_path / "cwd-sessions").exists() and not (tmp_path / "home-sessions").exists()
        finally:
            active_failure = sys.exception()
            writer.close()  # Test-only fallback asks the child to close itself.
            results = await asyncio.gather(
                writer.wait_closed(), client.close(), fresh.close(), stop.close(), return_exceptions=True,
            )
            try:
                if turn is not None:
                    await asyncio.gather(turn, return_exceptions=True)
            finally:
                directory.close()
            cleanup = [result for result in results if isinstance(result, BaseException)]
            if cleanup:
                if active_failure is not None:
                    active_failure.add_note(repr(cleanup))
                else:
                    raise BaseExceptionGroup("client cleanup failed", cleanup)

    failure = None
    try:
        poller = select.poll()
        poller.register(starter.stdout, select.POLLIN)
        assert poller.poll(10000), "starter did not report child"
        observer = LinuxServiceObserverV1.capture(int(starter.stdout.readline()))
        endpoint, _ = listener.accept()
        asyncio.run(asyncio.wait_for(scenario(), 35))
    except BaseException as error:
        failure = error
    finally:
        listener.close()
        if endpoint is not None:
            endpoint.close()
        cleanup_errors = []
        try:
            _, starter_errors = starter.communicate(b"Q" if starter.poll() is None else None, timeout=5)
            if starter.returncode != 0:
                cleanup_errors.append(RuntimeError("starter failed: " + starter_errors.decode(errors="replace")[-8192:]))
        except Exception as error:
            cleanup_errors.append(error)
            # Only this test-owned direct Popen may be forcefully reaped; this
            # is failed-test hygiene, never a production graceful-stop path.
            try:
                if starter.poll() is None:
                    starter.terminate()
                try:
                    starter.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    starter.kill()
                    starter.wait(timeout=5)
            except Exception as error:
                cleanup_errors.append(error)
        finally:
            for pipe in (starter.stdin, starter.stdout, starter.stderr):
                if pipe is not None:
                    pipe.close()
        if observer is not None:
            try:
                # On failure, retain the exact observer beyond the private child
                # watchdog. Never delete fixture storage while the child is live.
                deadline = monotonic() + 60
                while not observer.exited(timeout=5):
                    assert monotonic() < deadline, "test child did not exit"
            except Exception as error:
                cleanup_errors.append(error)
            finally:
                observer.close()
        if cleanup_errors:
            if failure is None:
                failure = ExceptionGroup("detached test cleanup failed", cleanup_errors)
            else:
                failure.add_note(repr(cleanup_errors))
    if failure is not None:
        diagnostic = tmp_path / "child-diagnostic.log"
        if diagnostic.is_file():
            failure.add_note(diagnostic.read_text()[-16384:])
        raise failure
