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
from loushang.hosting._posix_process import _PosixProcessBackend
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
