from __future__ import annotations

import asyncio
import os
import signal
import sys
from collections.abc import Awaitable, Callable
from functools import wraps
from pathlib import Path
from typing import ParamSpec

import pytest

from loushang.hosting import (
    HostingError,
    HostingFailureCategory,
    HostingObservation,
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
    ProcessStreamSpec,
    _posix_process,
    create_process_host,
)
from loushang.hosting._posix_process import _PosixProcess, _PosixProcessBackend
from loushang.hosting._process_backend import _ProcessInheritance, _ProcessTransport
from loushang.hosting._process_host import _ProcessHost, _ProcessHostLimits

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX process groups")
_P = ParamSpec("_P")


def _async_test(
    function: Callable[_P, Awaitable[None]],
) -> Callable[_P, None]:
    @wraps(function)
    def run(*args: _P.args, **kwargs: _P.kwargs) -> None:
        asyncio.run(function(*args, **kwargs))

    return run


class _PreparationLease:
    def __init__(self, request: ProcessLaunchRequest) -> None:
        self.request = request
        self.verify_calls = 0
        self.close_calls = 0

    async def verify_current(self) -> None:
        self.verify_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


class _PreparationPort:
    def __init__(self, lease: _PreparationLease) -> None:
        self.lease = lease

    async def prepare(self, request: ProcessLaunchRequest) -> _PreparationLease:
        return self.lease


class _Observations:
    def __init__(self) -> None:
        self.items: list[HostingObservation] = []

    def observe(self, observation: HostingObservation) -> None:
        self.items.append(observation)


class _ControllableRawProcess:
    def __init__(self) -> None:
        self.pid = 431
        self.returncode: int | None = None
        self.stdin = None
        self.stdout = None
        self.stderr = None
        self._transport = None


class _AttachedPosixBackend:
    backend_id = "posix-process-group-v1"

    def __init__(self, process: _PosixProcess) -> None:
        self._process = process
        self._delegate = _PosixProcessBackend()
        self.close_backend_calls = 0

    async def spawn(
        self,
        request: ProcessLaunchRequest,
        *,
        on_spawn: Callable[[_ProcessTransport], None],
        inheritance: _ProcessInheritance | None = None,
    ) -> _PosixProcess:
        del request
        assert inheritance is None
        on_spawn(self._process)
        return self._process

    def tree_exited(self, process: _ProcessTransport) -> bool:
        return self._delegate.tree_exited(process)

    async def wait_tree(self, process: _ProcessTransport) -> None:
        await self._delegate.wait_tree(process)

    async def terminate_tree(self, process: _ProcessTransport) -> None:
        await self._delegate.terminate_tree(process)

    async def kill_tree(self, process: _ProcessTransport) -> None:
        await self._delegate.kill_tree(process)

    async def close_process_handles(self, process: _ProcessTransport) -> None:
        await self._delegate.close_process_handles(process)

    async def close_backend(self) -> None:
        self.close_backend_calls += 1


class _DeniedPosixGroup:
    def __init__(self, raw: _ControllableRawProcess) -> None:
        self.raw = raw
        self.live = True
        self.denied = True
        self.calls: list[int] = []

    def killpg(self, process_group_id: int, group_signal: int) -> None:
        assert process_group_id == self.raw.pid
        self.calls.append(group_signal)
        if not self.live:
            raise ProcessLookupError
        if self.denied:
            raise PermissionError("process-group signaling is denied")
        if group_signal != 0:
            self.live = False
            if self.raw.returncode is None:
                self.raw.returncode = -int(group_signal)

    def getpgid(self, process_id: int) -> int:
        assert process_id == self.raw.pid
        raise ProcessLookupError


def _request(
    tmp_path: Path,
    code: str,
    *arguments: str,
    environment: tuple[tuple[str, str], ...] = (),
    stderr: ProcessStderrMode = ProcessStderrMode.CAPTURE_TAIL,
) -> ProcessLaunchRequest:
    return ProcessLaunchRequest(
        argv=(sys.executable, "-c", code, *arguments),
        cwd=str(tmp_path.resolve()),
        effective_environment=environment,
        streams=ProcessStreamSpec(
            stdin=ProcessStdinMode.PIPE,
            stdout=ProcessStdoutMode.PIPE,
            stderr=stderr,
        ),
    )


async def _read_all(read: Callable[[int], Awaitable[bytes]]) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = await read(7)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


@_async_test
async def test_posix_factory_runs_exact_request_and_reports_backend(
    tmp_path: Path,
) -> None:
    observations = _Observations()
    host = create_process_host(observation_sink=observations)
    request = _request(
        tmp_path,
        (
            "import os,sys; "
            "sys.stdout.write(os.getcwd() + '\\n' + os.environ['ONLY'] + '\\n'); "
            "sys.stderr.write('stderr-tail')"
        ),
        environment=(("ONLY", "materialized"),),
    )
    preparation = _PreparationLease(request)

    lease = await host.start(request, _PreparationPort(preparation))
    stdout = await _read_all(lease.read_stdout)
    assert (await lease.wait()).return_code == 0
    await lease.close()
    await host.close()

    assert stdout == f"{tmp_path.resolve()}\nmaterialized\n".encode()
    assert lease.stderr_tail().content == b"stderr-tail"
    assert preparation.verify_calls == 1
    assert preparation.close_calls == 1
    assert {item.backend_id for item in observations.items} == {
        "posix-process-group-v1"
    }


@_async_test
async def test_posix_force_kills_descendant_that_ignores_sigterm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals: list[int] = []
    original_killpg = _posix_process.os.killpg

    def recording_killpg(process_group_id: int, group_signal: int) -> None:
        signals.append(group_signal)
        original_killpg(process_group_id, group_signal)

    monkeypatch.setattr(_posix_process.os, "killpg", recording_killpg)
    marker = tmp_path / "escaped-marker"
    ready = tmp_path / "descendant-ready"
    child = (
        "import os,pathlib,signal,sys,time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "pathlib.Path(sys.argv[2]).write_text('ready'); "
        "time.sleep(0.5); pathlib.Path(sys.argv[1]).write_text('leaked')"
    )
    root = (
        "import pathlib,subprocess,sys,time; "
        "subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2], sys.argv[3]]); "
        "ready=pathlib.Path(sys.argv[3]); "
        "\nwhile not ready.exists(): time.sleep(0.01)\n"
        "print('ready', flush=True); "
        "time.sleep(60)"
    )
    request = _request(
        tmp_path,
        root,
        child,
        str(marker),
        str(ready),
        environment=tuple(os.environ.items()),
    )
    host = create_process_host(termination_grace_seconds=0.05)
    lease = await host.start(
        request, _PreparationPort(_PreparationLease(request))
    )

    assert await lease.read_stdout(6) == b"ready\n"
    await lease.close()
    await host.close()
    await asyncio.sleep(0.6)

    assert signal.SIGTERM in signals
    assert signal.SIGKILL in signals
    assert not marker.exists()


@_async_test
async def test_posix_natural_root_exit_reclaims_lingering_descendant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signal_calls: list[tuple[int, int]] = []
    original_killpg = _posix_process.os.killpg

    def recording_killpg(process_group_id: int, group_signal: int) -> None:
        signal_calls.append((process_group_id, group_signal))
        original_killpg(process_group_id, group_signal)

    monkeypatch.setattr(_posix_process.os, "killpg", recording_killpg)
    marker = tmp_path / "natural-root-marker"
    ready = tmp_path / "natural-descendant-ready"
    child = (
        "import os,pathlib,signal,sys,time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "pathlib.Path(sys.argv[2]).write_text(str(os.getpgrp())); "
        "time.sleep(0.5); pathlib.Path(sys.argv[1]).write_text("
        "f'{os.getpid()}:{os.getpgrp()}')"
    )
    root = (
        "import pathlib,subprocess,sys,time; "
        "subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2], sys.argv[3]]); "
        "ready=pathlib.Path(sys.argv[3]); "
        "\nwhile not ready.exists(): time.sleep(0.01)"
    )
    request = _request(
        tmp_path,
        root,
        child,
        str(marker),
        str(ready),
        environment=tuple(os.environ.items()),
    )
    preparation = _PreparationLease(request)
    host = create_process_host(termination_grace_seconds=0.05)
    lease = await host.start(request, _PreparationPort(preparation))

    assert (await lease.wait()).return_code == 0
    await lease.close()
    await host.close()
    await asyncio.sleep(0.6)

    assert preparation.close_calls == 1
    child_group = int(ready.read_text(encoding="utf-8"))
    lifecycle_signals = [call for call in signal_calls if call[1] != 0]
    assert (child_group, signal.SIGTERM) in lifecycle_signals
    assert (child_group, signal.SIGKILL) in lifecycle_signals
    assert not marker.exists()


@_async_test
async def test_posix_close_fds_rejects_unrelated_inheritable_descriptor(
    tmp_path: Path,
) -> None:
    sentinel = os.open(tmp_path / "sentinel", os.O_CREAT | os.O_RDWR, 0o600)
    os.set_inheritable(sentinel, True)
    code = (
        "import os,sys; "
        "fd=int(sys.argv[1]); "
        "\ntry: os.fstat(fd)\nexcept OSError: print('closed')\n"
        "else: print('inherited')"
    )
    request = _request(tmp_path, code, str(sentinel))
    host = create_process_host()
    try:
        lease = await host.start(
            request, _PreparationPort(_PreparationLease(request))
        )
        assert await _read_all(lease.read_stdout) == b"closed\n"
        await lease.close()
    finally:
        await host.close()
        os.close(sentinel)


@_async_test
async def test_posix_cancellation_after_os_creation_is_reclaimed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _PosixProcessBackend()
    original = backend._spawn_once
    created = asyncio.Event()
    release = asyncio.Event()

    async def gated_spawn(request: ProcessLaunchRequest):
        process = await original(request)
        created.set()
        await release.wait()
        return process

    monkeypatch.setattr(backend, "_spawn_once", gated_spawn)
    host = _ProcessHost(
        backend,
        limits=_ProcessHostLimits(termination_grace_seconds=0.05),
    )
    request = _request(
        tmp_path,
        "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)",
    )
    preparation = _PreparationLease(request)
    start = asyncio.create_task(host.start(request, _PreparationPort(preparation)))
    await created.wait()

    start.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await start
    await host.close()

    assert preparation.close_calls == 1


def test_posix_reaped_leader_pid_reuse_is_not_signalled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ReapedProcess:
        pid = 431
        returncode = 0

    process = _PosixProcess(_ReapedProcess())  # type: ignore[arg-type]
    monkeypatch.setattr(_posix_process.os, "getpgid", lambda pid: pid)

    def reject_signal(process_group_id: int, group_signal: int) -> None:
        raise AssertionError(
            f"reused group {process_group_id} received signal {group_signal}"
        )

    monkeypatch.setattr(_posix_process.os, "killpg", reject_signal)

    assert process.group_exists() is False
    process.signal_group(signal.SIGKILL)


def test_posix_denied_existence_probe_keeps_group_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _LiveProcess:
        pid = 431
        returncode = None

    process = _PosixProcess(_LiveProcess())  # type: ignore[arg-type]
    signals: list[int] = []

    def permission_sensitive_killpg(
        process_group_id: int,
        group_signal: int,
    ) -> None:
        assert process_group_id == 431
        signals.append(group_signal)
        if group_signal == 0:
            raise PermissionError("existence is known but signaling is denied")

    monkeypatch.setattr(_posix_process.os, "killpg", permission_sensitive_killpg)

    process.signal_group(signal.SIGKILL)

    assert signals == [0, signal.SIGKILL]


@_async_test
async def test_posix_pending_root_eperm_retains_owner_for_host_close_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _ControllableRawProcess()
    group = _DeniedPosixGroup(raw)
    monkeypatch.setattr(_posix_process.os, "killpg", group.killpg)
    monkeypatch.setattr(_posix_process.os, "getpgid", group.getpgid)
    process = _PosixProcess(raw)  # type: ignore[arg-type]
    backend = _AttachedPosixBackend(process)
    host = _ProcessHost(
        backend,
        limits=_ProcessHostLimits(termination_grace_seconds=0.01),
    )
    request = _request(tmp_path, "pass")
    preparation = _PreparationLease(request)
    lease = await host.start(request, _PreparationPort(preparation))

    with pytest.raises(HostingError) as denied:
        await asyncio.wait_for(host.close(), 0.5)

    assert denied.value.category is HostingFailureCategory.CLEANUP_FAILED
    assert host._state == "faulted"
    assert lease in host._leases
    assert raw.returncode is None
    assert preparation.close_calls == 0
    assert backend.close_backend_calls == 0
    assert 0 in group.calls
    assert signal.SIGTERM in group.calls
    assert signal.SIGKILL in group.calls

    group.denied = False
    await asyncio.wait_for(host.close(), 0.5)

    assert host._state == "closed"
    assert lease not in host._leases
    assert raw.returncode is not None
    assert preparation.close_calls == 1
    assert backend.close_backend_calls == 1


@_async_test
async def test_posix_lingering_descendant_eperm_retains_owner_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _ControllableRawProcess()
    group = _DeniedPosixGroup(raw)
    monkeypatch.setattr(_posix_process.os, "killpg", group.killpg)
    monkeypatch.setattr(_posix_process.os, "getpgid", group.getpgid)
    process = _PosixProcess(raw)  # type: ignore[arg-type]
    backend = _AttachedPosixBackend(process)
    host = _ProcessHost(
        backend,
        limits=_ProcessHostLimits(termination_grace_seconds=0.01),
    )
    request = _request(tmp_path, "pass")
    preparation = _PreparationLease(request)
    lease = await host.start(request, _PreparationPort(preparation))

    raw.returncode = 0
    assert (await lease.wait()).return_code == 0
    with pytest.raises(HostingError) as denied:
        await asyncio.wait_for(host.close(), 0.5)

    assert denied.value.category is HostingFailureCategory.CLEANUP_FAILED
    assert host._state == "faulted"
    assert lease in host._leases
    assert group.live is True
    assert backend.close_backend_calls == 0

    group.denied = False
    await asyncio.wait_for(host.close(), 0.5)

    assert host._state == "closed"
    assert lease not in host._leases
    assert group.live is False
    assert preparation.close_calls == 1
    assert backend.close_backend_calls == 1


def test_posix_backend_rejects_foreign_transport() -> None:
    backend = _PosixProcessBackend()
    with pytest.raises(TypeError, match="own process transport"):
        backend.tree_exited(object())  # type: ignore[arg-type]


def test_posix_backend_fails_closed_without_session_primitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(_posix_process.os, "setsid")
    with pytest.raises(HostingError) as caught:
        _PosixProcessBackend()
    assert caught.value.category is HostingFailureCategory.PLATFORM_UNSUPPORTED


def test_posix_backend_has_no_root_only_signal_fallback() -> None:
    source = Path("src/loushang/hosting/_posix_process.py").read_text(
        encoding="utf-8"
    )
    assert "process.terminate(" not in source
    assert "os.kill(" not in source
    assert 'getattr(os, "killpg", None)' in source
    assert "start_new_session=True" in source
    assert "close_fds=True" in source
