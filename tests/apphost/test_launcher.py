"""Deterministic launch-owner faults; not native or installed evidence."""

from __future__ import annotations

import asyncio
import sys
from enum import Enum

import pytest

from loushang.apphost.launcher import HostedForegroundClientV1, _ProcessByteTransport
from loushang.appserver.framing import AppConnectionClosedError, AppFramedStreamV1
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    SessionListV1,
    SessionScopeV1,
)
from loushang.appserver.protocol.codec import MAX_MESSAGE_BYTES
from loushang.appserver.protocol.connection_profile import (
    AppConnectionProfileV1,
    connection_hello,
)
from loushang.hosting.contracts import (
    ProcessExit,
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStderrTail,
    ProcessStdinMode,
    ProcessStdoutMode,
    ProcessStreamSpec,
)


class _Lease:
    lease_id = "owned-child"

    def __init__(self):
        hello = connection_hello(AppConnectionProfileV1.STDIO_DISCOVERY)
        self.output = bytearray(len(hello).to_bytes(4, "big") + hello)
        self.exited = asyncio.Event()
        self.calls = []
        self.writes = []
        self.read_sizes = []
        self.return_code = 0
        self.ignore_eof = False

    async def read_stdout(self, size):
        self.read_sizes.append(size)
        if self.output:
            data = bytes(self.output[:size])
            del self.output[:size]
            return data
        await self.exited.wait()
        return b""

    async def read_stderr(self, size):
        raise AssertionError("Hosting owns captured stderr")

    async def write_stdin(self, data):
        self.writes.append(data)
        await asyncio.sleep(0)

    async def close_stdin(self):
        self.calls.append("eof")
        if not self.ignore_eof:
            self.exited.set()

    async def wait(self):
        await self.exited.wait()
        return ProcessExit(self.return_code)

    async def terminate(self):
        self.calls.append("terminate")
        self.return_code = -15
        self.exited.set()
        return ProcessExit(self.return_code)

    async def close(self):
        self.calls.append("close")
        self.exited.set()

    def stderr_tail(self):
        return ProcessStderrTail()


class _Host:
    def __init__(self, lease):
        self.lease = lease
        self.calls = []

    async def start(self, request, preparation):
        self.calls.append("start")
        return self.lease

    async def close(self):
        self.calls.append("close")


def _owner(tmp_path, lease=None, host=None, **options):
    lease = lease or _Lease()
    host = host or _Host(lease)
    request = ProcessLaunchRequest(
        (sys.executable, "trusted-child"),
        str(tmp_path),
        (),
        ProcessStreamSpec(
            ProcessStdinMode.PIPE,
            ProcessStdoutMode.PIPE,
            ProcessStderrMode.CAPTURE_TAIL,
        ),
    )
    owner = HostedForegroundClientV1(
        request, host=host, preparation=object(), **options
    )
    return owner, lease, host


def test_G17_LAUNCH_IO_full_frame_includes_header_and_has_one_bounded_writer():
    async def scenario():
        lease = _Lease()
        transport = _ProcessByteTransport(lease)
        stream = AppFramedStreamV1(transport)
        payload = b"x" * MAX_MESSAGE_BYTES
        await stream.send(payload)
        assert list(map(len, lease.writes)) == [MAX_MESSAGE_BYTES, 4]
        assert b"".join(lease.writes) == len(payload).to_bytes(4, "big") + payload
        await stream.receive()
        assert max(lease.read_sizes) <= 64 * 1024
        await stream.close()
        assert lease.calls == ["eof"]  # Byte adapter cannot close or terminate owner.

    asyncio.run(scenario())


def test_G17_LAUNCH_ready_borrows_clients_and_graceful_close_releases_one_host(
    tmp_path,
):
    async def scenario():
        owner, lease, host = _owner(tmp_path)
        assert owner.discovery_client is None
        await owner.start()
        assert owner.discovery_client is not None
        assert owner.client is not None
        await owner.close()
        await owner.close()
        assert not owner.cleanup_pending and not owner.forced_exit
        assert owner.discovery_client is None
        assert lease.calls.count("terminate") == 0
        assert lease.calls.count("close") == 1 and host.calls == ["start", "close"]

    asyncio.run(scenario())


def test_G17_LAUNCH_cold_hello_uses_owner_budget_not_default_connection_phase(tmp_path):
    async def scenario():
        class ColdLease(_Lease):
            async def read_stdout(self, size):
                if not self.read_sizes:
                    # Exercise the actual default 10-second connection timer;
                    # the explicit owner has admitted a 15-second startup.
                    await asyncio.sleep(10.1)
                return await super().read_stdout(size)

        owner, lease, host = _owner(tmp_path, ColdLease(), startup_timeout=15)
        try:
            await owner.start()
            assert owner.discovery_client is not None
        finally:
            await owner.close()
        assert not owner.cleanup_pending and not owner.process_cleanup_pending
        assert lease.calls.count("close") == host.calls.count("close") == 1

    asyncio.run(scenario())


def test_G17_LAUNCH_spawn_consumes_the_same_hello_deadline(tmp_path, monkeypatch):
    from loushang.appserver.remote_client import RemoteAppClientV1

    async def scenario():
        observed = []
        start = RemoteAppClientV1.start

        async def hello(client, *, timeout=None):
            observed.append(timeout)
            return await start(client, timeout=timeout)

        class Host(_Host):
            async def start(self, *args):
                await asyncio.sleep(0.03)
                return await super().start(*args)

        monkeypatch.setattr(RemoteAppClientV1, "start", hello)
        lease = _Lease()
        owner, _, _ = _owner(tmp_path, lease, Host(lease), startup_timeout=1)
        try:
            await owner.start()
            assert len(observed) == 1 and 0 < observed[0] <= 0.98
            assert owner._client._timeout == 10  # Ordinary phases were not enlarged.
        finally:
            await owner.close()

    asyncio.run(scenario())


def test_G17_LAUNCH_expired_queued_start_cannot_admit_spawn(tmp_path, monkeypatch):
    from loushang.apphost import launcher

    async def scenario():
        owned = launcher._owned
        first = True
        loop = asyncio.get_running_loop()
        clock = loop.time
        elapsed = 0.0
        monkeypatch.setattr(loop, "time", lambda: clock() + elapsed)

        def queued(operation):
            nonlocal first
            if not first:
                return owned(operation)
            first = False

            async def enter_late():
                nonlocal elapsed
                # Cross the owner's clock deadline explicitly. Wall-clock sleep
                # does not prove this boundary on coarse Windows loop clocks.
                elapsed += 2.0
                return await operation()

            return owned(enter_late)

        monkeypatch.setattr(launcher, "_owned", queued)
        owner, lease, host = _owner(tmp_path, startup_timeout=1)
        with pytest.raises(TimeoutError):
            await owner.start()
        assert host.calls == ["close"]
        assert not lease.calls and owner._lease is None
        assert not owner.process_cleanup_pending

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["spawn", "hello"])
def test_G17_LAUNCH_late_completion_cannot_publish_ready_or_admit_new_io(tmp_path, monkeypatch, phase):
    from loushang.appserver.remote_client import RemoteAppClientV1

    async def scenario():
        start = RemoteAppClientV1.start
        loop = asyncio.get_running_loop()
        clock = loop.time
        elapsed = 0.0
        advanced = []
        monkeypatch.setattr(loop, "time", lambda: clock() + elapsed)

        def complete_late():
            nonlocal elapsed
            # Advance the owner's clock without yielding to its timeout callback.
            # A short wall-clock sleep does not establish this on every OS clock.
            elapsed += 2.0
            advanced.append(phase)

        async def hello(client, *, timeout=None):
            await start(client, timeout=timeout)
            complete_late()

        class Host(_Host):
            async def start(self, *args):
                if phase == "spawn":
                    complete_late()
                return await super().start(*args)

        if phase == "hello":
            monkeypatch.setattr(RemoteAppClientV1, "start", hello)
        lease = _Lease()
        owner, _, host = _owner(tmp_path, lease, Host(lease), startup_timeout=1)
        with pytest.raises(TimeoutError):
            await owner.start()
        assert advanced == [phase]  # Prove the intended boundary was exercised.
        assert not owner._ready and owner.discovery_client is None
        assert not owner.cleanup_pending and not owner.process_cleanup_pending
        assert lease.calls.count("close") == host.calls.count("close") == 1
        if phase == "spawn":
            assert not lease.writes and owner._client is None
            # Reclamation may still drain output; no new framed hello reader
            # (which begins with a one-byte read) may be admitted after expiry.
            assert all(size == 64 * 1024 for size in lease.read_sizes)

    asyncio.run(scenario())


def test_G17_LAUNCH_detach_failure_cannot_prevent_eof_or_replay_on_retry(tmp_path):
    async def scenario():
        owner, lease, _ = _owner(tmp_path)
        count = 0

        async def detach():
            nonlocal count
            count += 1
            raise AppServiceError(AppErrorCodeV1.SERVICE_CLOSED)

        await owner.start()
        with pytest.raises(AppServiceError):
            await owner.close(detach=detach)
        with pytest.raises(AppServiceError):
            await owner.close(retry_timeout=0.2)
        assert count == 1 and lease.calls.count("eof") == 1
        assert lease.calls.count("close") == 1
        assert owner.cleanup_pending  # Unknown UI settlement is not a clean close.

    asyncio.run(scenario())


def test_G17_LAUNCH_force_cutoff_is_independent_of_cancel_resistant_detach(tmp_path):
    async def scenario():
        owner, lease, _ = _owner(tmp_path, close_timeout=0.12, graceful_timeout=0.03)
        lease.ignore_eof = True
        entered, release = asyncio.Event(), asyncio.Event()

        async def detach():
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()

        await owner.start()
        try:
            with pytest.raises(AppServiceError) as debt:
                await owner.close(detach=detach)
            assert entered.is_set()
            assert debt.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
            assert lease.calls.count("terminate") == 1
            assert owner.forced_exit and owner.cleanup_pending
        finally:
            release.set()
            await owner.close(retry_timeout=0.3)
        assert lease.calls.count("terminate") == 1
        assert not owner.cleanup_pending

    asyncio.run(scenario())


def test_G17_LAUNCH_unpublished_start_is_reclaimed_before_joining_start(tmp_path):
    async def scenario():
        entered, reclaim = asyncio.Event(), asyncio.Event()
        lease = _Lease()

        class Host(_Host):
            async def start(self, request, preparation):
                entered.set()
                try:
                    await reclaim.wait()
                except asyncio.CancelledError:
                    await reclaim.wait()
                return self.lease

            async def close(self):
                self.calls.append("close")
                reclaim.set()

        owner, _, host = _owner(
            tmp_path, lease, Host(lease), close_timeout=0.2, graceful_timeout=0.05
        )
        started = asyncio.create_task(owner.start())
        await asyncio.wait_for(entered.wait(), 1)
        try:
            await owner.close()
            assert host.calls == ["close"]
            assert not owner.cleanup_pending
            assert owner.discovery_client is None
            assert lease.calls.count("close") == 1  # Late return was retained.
        finally:
            reclaim.set()
            await asyncio.gather(started, return_exceptions=True)
            await owner.close(retry_timeout=0.3)

    asyncio.run(scenario())


def test_G17_LAUNCH_cancel_resistant_hello_retains_sole_reader_until_actual_settlement(
    tmp_path,
):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class Lease(_Lease):
            active = maximum = reads = 0

            async def read_stdout(self, size):
                self.active += 1
                self.maximum = max(self.maximum, self.active)
                self.reads += 1
                try:
                    if self.reads == 1:
                        entered.set()
                        try:
                            await release.wait()
                        except asyncio.CancelledError:
                            await release.wait()
                    return await super().read_stdout(size)
                finally:
                    self.active -= 1

        lease = Lease()
        lease.ignore_eof = True
        owner, _, _ = _owner(tmp_path, lease, close_timeout=0.12, graceful_timeout=0.03)
        started = asyncio.create_task(owner.start())
        await asyncio.wait_for(entered.wait(), 1)
        try:
            with pytest.raises(AppServiceError) as debt:
                await owner.close()
            assert debt.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
            assert lease.calls.count("terminate") == 1
            assert lease.reads == 1 and lease.active == 1
            assert owner.discovery_client is None and owner.cleanup_pending
        finally:
            release.set()
            await asyncio.wait_for(asyncio.gather(started, return_exceptions=True), 1)
            await owner.close(retry_timeout=0.3)
        assert lease.maximum == 1 and not owner.cleanup_pending

    asyncio.run(scenario())


def test_G17_LAUNCH_blocked_frame_writer_cannot_hold_force_cutoff(tmp_path):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class Lease(_Lease):
            async def write_stdin(self, data):
                if len(self.writes) >= 2:
                    entered.set()
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        await release.wait()
                await super().write_stdin(data)

        lease = Lease()
        lease.ignore_eof = True
        owner, _, _ = _owner(tmp_path, lease, close_timeout=0.12, graceful_timeout=0.03)
        await owner.start()
        writer = asyncio.create_task(
            AppFramedStreamV1(owner._transport).send(b"x" * MAX_MESSAGE_BYTES)
        )
        await asyncio.wait_for(entered.wait(), 1)
        assert (
            len(lease.writes[-1]) == MAX_MESSAGE_BYTES
        )  # Tail of an actual frame is blocked.

        async def detach():
            await asyncio.shield(writer)

        try:
            with pytest.raises(AppServiceError):
                await owner.close(detach=detach)
            assert lease.calls.count("terminate") == 1
            assert not writer.done() and owner.cleanup_pending
        finally:
            release.set()
            await asyncio.wait_for(writer, 1)
            await owner.close(retry_timeout=0.3)
        assert lease.calls.count("terminate") == 1
        assert lease.calls.count("close") == 1
        assert not owner.cleanup_pending

    asyncio.run(scenario())


def test_G17_LAUNCH_explicit_retry_does_not_restart_expired_grace(tmp_path):
    async def scenario():
        class Lease(_Lease):
            async def terminate(self):
                self.calls.append("terminate")
                if self.calls.count("terminate") == 1:
                    raise RuntimeError("first termination failed")
                self.exited.set()
                return ProcessExit(-15)

            async def close(self):
                if self.calls.count("terminate") == 1:
                    raise RuntimeError("fallback not yet available")
                await super().close()

        lease = Lease()
        lease.ignore_eof = True
        owner, _, _ = _owner(tmp_path, lease, close_timeout=0.12, graceful_timeout=0.03)
        await owner.start()
        with pytest.raises(AppServiceError):
            await owner.close()
        cutoff = owner._cutoff
        assert lease.calls.count("terminate") == 1
        # Shorter than the original graceful window: retry cannot reopen it.
        await owner.close(retry_timeout=0.02)
        assert owner._cutoff == cutoff
        assert lease.calls.count("terminate") == 2 and not owner.cleanup_pending

    asyncio.run(scenario())


@pytest.mark.parametrize("failed_wait", [False, True])
def test_G17_LAUNCH_hosting_close_remains_reachable_when_exit_or_terminate_fails(
    tmp_path, failed_wait
):
    async def scenario():
        class Lease(_Lease):
            async def wait(self):
                if failed_wait:
                    raise RuntimeError("exit observer failed")
                return await super().wait()

            async def terminate(self):
                self.calls.append("terminate")
                raise RuntimeError("terminate failed, handle close can reclaim")

        lease = Lease()
        lease.ignore_eof = True
        owner, _, host = _owner(
            tmp_path, lease, close_timeout=0.2, graceful_timeout=0.03
        )
        await owner.start()
        try:
            await owner.close()
            assert lease.calls.count("close") == 1 and lease.exited.is_set()
            assert host.calls == ["start", "close"]
            assert owner.forced_exit and not owner.cleanup_pending
            if failed_wait:
                assert owner.process_exit is None
        finally:
            lease.exited.set()

    asyncio.run(scenario())


def test_G17_LAUNCH_IO_concurrent_frames_never_interleave():
    async def scenario():
        lease = _Lease()
        transport = _ProcessByteTransport(lease)
        # Independent framers still share the one transport writer.
        payloads = [byte * MAX_MESSAGE_BYTES for byte in (b"a", b"b")]
        await asyncio.gather(
            *(AppFramedStreamV1(transport).send(payload) for payload in payloads)
        )
        frames = [len(payload).to_bytes(4, "big") + payload for payload in payloads]
        assert b"".join(lease.writes) in (b"".join(frames), b"".join(reversed(frames)))
        assert list(map(len, lease.writes)) == [MAX_MESSAGE_BYTES, 4] * 2
        await transport.close()

    asyncio.run(scenario())


class _OtherProfile(str, Enum):
    STDIO = AppConnectionProfileV1.STDIO.value


@pytest.mark.parametrize(
    "profile",
    [
        AppConnectionProfileV1.STDIO.value,
        AppConnectionProfileV1.STDIO_DISCOVERY.value,
        _OtherProfile.STDIO,
        None,
        True,
    ],
)
def test_G17_LAUNCH_invalid_profile_rejected_before_spawn(tmp_path, profile):
    lease = _Lease()
    host = _Host(lease)
    with pytest.raises(ValueError, match="invalid foreground launch contract"):
        _owner(tmp_path, lease, host, profile=profile)
    assert not host.calls


@pytest.mark.parametrize("field", ["startup_timeout", "close_timeout", "graceful_timeout"])
@pytest.mark.parametrize("value", [True, 0, -1, float("nan"), float("inf"), 61])
def test_G17_LAUNCH_invalid_budgets_rejected_before_spawn(tmp_path, field, value):
    host = _Host(_Lease())
    with pytest.raises(ValueError):
        _owner(tmp_path, host=host, **{field: value})
    assert not host.calls


@pytest.mark.parametrize(
    "options",
    [
        {"startup_timeout": 31},
        {"close_timeout": 21},
        {"graceful_timeout": 11},
        {"close_timeout": 1, "graceful_timeout": 2},
    ],
)
def test_G17_LAUNCH_specific_budget_caps_rejected_before_spawn(tmp_path, options):
    host = _Host(_Lease())
    with pytest.raises(ValueError, match="invalid foreground budgets"):
        _owner(tmp_path, host=host, **options)
    assert not host.calls


def test_G17_LAUNCH_saved_borrowed_ports_reject_after_close_without_wire_writes(tmp_path):
    async def scenario():
        owner, lease, _ = _owner(tmp_path)
        await owner.start()
        client, discovery = owner.client, owner.discovery_client
        assert discovery is not None
        await owner.close()
        writes = list(lease.writes)
        with pytest.raises(AppConnectionClosedError):
            await client.list_muxes()
        with pytest.raises(AppConnectionClosedError):
            await discovery.list_sessions(
                SessionListV1("coding", SessionScopeV1.CWD, "a" * 64)
            )
        with pytest.raises(AppConnectionClosedError):
            _ = owner.client
        assert lease.writes == writes

    asyncio.run(scenario())


def test_G17_LAUNCH_diagnostics_are_bounded_scalars_without_stderr_content(tmp_path):
    async def scenario():
        sentinel = b"/private/workspace API_KEY=sensitive-secret "

        class Lease(_Lease):
            def stderr_tail(self):
                return ProcessStderrTail(sentinel * 2000, True)

        owner, _, _ = _owner(tmp_path, Lease())
        assert owner.diagnostics.stderr_bytes == 0
        await owner.start()
        await owner.close()
        facts = owner.diagnostics
        assert facts.stderr_bytes == 64 * 1024 and facts.stderr_truncated
        assert facts.exit_code == 0 and not facts.forced_exit
        assert "private" not in repr(facts) and "sensitive-secret" not in repr(facts)

    asyncio.run(scenario())


def test_G17_LAUNCH_concurrent_close_retains_one_detach_and_budget(tmp_path):
    async def scenario():
        owner, _, host = _owner(tmp_path, close_timeout=0.3, graceful_timeout=0.1)
        entered, release = asyncio.Event(), asyncio.Event()
        calls = 0

        async def detach():
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()

        await owner.start()
        first = asyncio.create_task(owner.close(detach=detach))
        await asyncio.wait_for(entered.wait(), 1)
        deadline, operation = owner._deadline, owner._close_task
        second = asyncio.create_task(owner.close())
        try:
            with pytest.raises(ValueError, match="still running"):
                await owner.close(retry_timeout=0.1)
            assert owner._deadline == deadline and owner._close_task is operation
            # Cancelling one caller cannot cancel the retained settlement owner.
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            assert not operation.cancelled()
        finally:
            release.set()
            await asyncio.wait_for(second, 1)
        assert calls == 1 and host.calls == ["start", "close"]
        assert not owner.cleanup_pending

    asyncio.run(scenario())


def test_G17_LAUNCH_expired_budget_cannot_publish_new_ordinary_phases(tmp_path):
    async def scenario():
        owner, _, host = _owner(tmp_path, close_timeout=0.06, graceful_timeout=0.01)
        entered, release = asyncio.Event(), asyncio.Event()
        await owner.start()
        client_close = owner._client.close

        async def held_close():
            entered.set()
            await release.wait()
            await client_close()

        owner._client.close = held_close
        try:
            with pytest.raises(AppServiceError):
                await owner.close()
            assert entered.is_set() and "drain" not in owner._phases
            deadline = owner._deadline
            release.set()
            await asyncio.wait_for(owner._phases["client"], 1)
            with pytest.raises(AppServiceError) as error:
                await owner.close()
            assert error.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
            assert owner._deadline == deadline
            assert "drain" not in owner._phases
            # The already-authorized physical watchdog closes the dedicated
            # host independently; repetition does not publish a new drain.
            assert host.calls == ["start", "close"]
            assert not owner.process_cleanup_pending
        finally:
            release.set()
            await owner.close(retry_timeout=0.3)
        assert not owner.cleanup_pending

    asyncio.run(scenario())


@pytest.mark.parametrize("failures", [1, 2])
def test_G17_LAUNCH_retry_only_repeats_failed_phase_once_per_attempt(tmp_path, failures):
    async def scenario():
        class Lease(_Lease):
            closes = 0

            async def close(self):
                self.closes += 1
                if self.closes <= failures:
                    raise RuntimeError("/private/cleanup failed")
                await super().close()

        lease = Lease()
        lease.ignore_eof = True
        owner, _, _ = _owner(tmp_path, lease, close_timeout=0.2, graceful_timeout=0.01)
        await owner.start()
        for attempt in range(failures):
            with pytest.raises(AppServiceError) as debt:
                await owner.close(**({"retry_timeout": 0.2} if attempt else {}))
            assert debt.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
            assert "private" not in str(debt.value)
            assert lease.closes == attempt + 1
            assert lease.calls.count("terminate") == 1
            assert owner.process_cleanup_pending
        await owner.close(retry_timeout=0.2)
        assert lease.closes == failures + 1
        assert lease.calls.count("terminate") == 1
        assert not owner.cleanup_pending
        assert not owner.process_cleanup_pending

    asyncio.run(scenario())
