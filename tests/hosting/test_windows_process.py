from __future__ import annotations

import asyncio
import os
import sys
import threading
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
    create_process_host,
)
from loushang.hosting._process_host import _ProcessHost, _ProcessHostLimits
from loushang.hosting._win32_process import _Win32SpawnHandles
from loushang.hosting._windows_process import _WindowsProcessBackend

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


class _FakeWin32Api:
    def __init__(self) -> None:
        self.spawned: list[ProcessLaunchRequest] = []
        self.writes: list[bytes] = []
        self.termination_codes: list[int] = []
        self.closed: list[int] = []
        self.return_code: int | None = None
        self.empty = False
        self.spawn_entered = threading.Event()
        self.spawn_release = threading.Event()
        self.spawn_release.set()
        self.process_exited = threading.Event()
        self.block_io = False
        self.io_release = threading.Event()
        self.io_entered = threading.Event()
        self.stdout_entered = threading.Event()
        self.all_blocking_lanes_entered = threading.Event()
        self._io_count = 0
        self._io_lock = threading.Lock()
        self.fail_termination = False
        self.close_failures: dict[int, int] = {}
        self.spawn_cleanup_handles: tuple[int, ...] = ()
        self.cancel_releases_io = True
        self.job_close_releases_io = True
        self.job_closed = threading.Event()

    def spawn(self, request: ProcessLaunchRequest) -> _Win32SpawnHandles:
        self.spawn_entered.set()
        self.spawn_release.wait()
        self.spawned.append(request)
        return _Win32SpawnHandles(
            process=11,
            job=12,
            stdin_write=13,
            stdout_read=14,
            stderr_read=15,
            cleanup_handles=self.spawn_cleanup_handles,
        )

    def read_pipe(self, handle: int, max_bytes: int) -> bytes:
        if handle == 14:
            self.stdout_entered.set()
        self._enter_blocking_lane()
        return b""

    def write_pipe(self, handle: int, data: bytes) -> None:
        self._enter_blocking_lane()
        self.writes.append(data)

    def wait_process(self, handle: int) -> int:
        self._enter_blocking_lane()
        self.process_exited.wait()
        assert self.return_code is not None
        return self.return_code

    def process_return_code(self, handle: int) -> int | None:
        return self.return_code

    def job_is_empty(self, handle: int) -> bool:
        return self.empty

    def terminate_job(self, handle: int, exit_code: int) -> None:
        if self.fail_termination:
            raise OSError("TerminateJobObject failed")
        self.termination_codes.append(exit_code)
        self.return_code = exit_code
        self.empty = True
        self.io_release.set()
        self.process_exited.set()

    def close_handle(self, handle: int) -> None:
        failures = self.close_failures.get(handle, 0)
        if failures:
            self.close_failures[handle] = failures - 1
            raise OSError(f"CloseHandle({handle}) failed")
        self.closed.append(handle)
        if handle == 12:
            self.job_closed.set()
            self.return_code = self.return_code or 0xE0000002
            self.empty = True
            if self.job_close_releases_io:
                self.io_release.set()
                self.process_exited.set()

    def cancel_synchronous_io(self, thread_id: int) -> None:
        del thread_id
        if self.cancel_releases_io:
            self.io_release.set()

    def _enter_blocking_lane(self) -> None:
        if not self.block_io:
            return
        with self._io_lock:
            self._io_count += 1
            self.io_entered.set()
            if self._io_count >= 4:
                self.all_blocking_lanes_entered.set()
        self.io_release.wait()


def _request(tmp_path: Path, code: str, *arguments: str) -> ProcessLaunchRequest:
    return ProcessLaunchRequest(
        argv=(sys.executable, "-c", code, *arguments),
        cwd=str(tmp_path.resolve()),
        effective_environment=tuple(os.environ.items()),
        streams=ProcessStreamSpec(
            stdin=ProcessStdinMode.PIPE,
            stdout=ProcessStdoutMode.PIPE,
            stderr=ProcessStderrMode.CAPTURE_TAIL,
        ),
    )


@_async_test
async def test_windows_backend_fake_owns_tree_streams_and_handles(
    tmp_path: Path,
) -> None:
    api = _FakeWin32Api()
    backend = _WindowsProcessBackend(api=api)
    host = _ProcessHost(
        backend,
        limits=_ProcessHostLimits(termination_grace_seconds=0.05),
    )
    request = _request(tmp_path, "pass")
    preparation = _PreparationLease(request)

    lease = await host.start(request, _PreparationPort(preparation))
    await lease.write_stdin(b"payload")
    exit_result = await lease.terminate()
    await lease.close()
    await host.close()

    assert api.spawned == [request]
    assert api.writes == [b"payload"]
    assert api.termination_codes == [0xE0000001]
    assert exit_result.return_code == 0xE0000001
    assert set(api.closed) == {11, 12, 13, 14, 15}
    assert len(api.closed) == len(set(api.closed))
    assert preparation.verify_calls == 1
    assert preparation.close_calls == 1


@pytest.mark.parametrize(
    ("failed_handle", "cleanup_handles"),
    ((12, ()), (16, (16,))),
)
@_async_test
async def test_windows_published_process_retries_failed_close_handle(
    tmp_path: Path,
    failed_handle: int,
    cleanup_handles: tuple[int, ...],
) -> None:
    api = _FakeWin32Api()
    api.spawn_cleanup_handles = cleanup_handles
    api.close_failures[failed_handle] = 1
    backend = _WindowsProcessBackend(api=api)
    host = _ProcessHost(
        backend,
        limits=_ProcessHostLimits(termination_grace_seconds=0.05),
    )
    request = _request(tmp_path, "pass")
    preparation = _PreparationLease(request)
    lease = await host.start(request, _PreparationPort(preparation))

    with pytest.raises(HostingError) as first_close:
        await host.close()

    assert first_close.value.category is HostingFailureCategory.CLEANUP_FAILED
    assert host._state == "faulted"
    assert lease in host._leases
    assert failed_handle not in api.closed
    assert preparation.close_calls == 1

    await host.close()

    assert host._state == "closed"
    assert lease not in host._leases
    expected_handles = {11, 12, 13, 14, 15, *cleanup_handles}
    assert set(api.closed) == expected_handles
    assert len(api.closed) == len(set(api.closed))
    assert preparation.close_calls == 1


@_async_test
async def test_windows_spawn_cancellation_waits_for_attachment_and_reclamation(
    tmp_path: Path,
) -> None:
    api = _FakeWin32Api()
    api.spawn_release.clear()
    backend = _WindowsProcessBackend(api=api)
    host = _ProcessHost(
        backend,
        limits=_ProcessHostLimits(termination_grace_seconds=0.05),
    )
    request = _request(tmp_path, "pass")
    preparation = _PreparationLease(request)
    start = asyncio.create_task(
        host.start(request, _PreparationPort(preparation))
    )
    assert await asyncio.to_thread(api.spawn_entered.wait, 1.0)

    start.cancel()
    api.spawn_release.set()
    with pytest.raises(asyncio.CancelledError):
        await start
    await host.close()

    assert api.termination_codes
    assert set(api.closed) == {11, 12, 13, 14, 15}
    assert preparation.close_calls == 1


@_async_test
async def test_windows_control_close_bypasses_saturated_blocking_io_lanes(
    tmp_path: Path,
) -> None:
    api = _FakeWin32Api()
    api.block_io = True
    backend = _WindowsProcessBackend(max_processes=1, api=api)
    host = _ProcessHost(
        backend,
        limits=_ProcessHostLimits(
            max_processes=1,
            termination_grace_seconds=0.05,
        ),
    )
    request = _request(tmp_path, "pass")
    lease = await host.start(
        request, _PreparationPort(_PreparationLease(request))
    )
    stdout = asyncio.create_task(lease.read_stdout(16))
    write = asyncio.create_task(lease.write_stdin(b"payload"))
    assert await asyncio.to_thread(api.all_blocking_lanes_entered.wait, 1.0)

    await asyncio.wait_for(host.close(), 1.0)
    await asyncio.gather(stdout, write, return_exceptions=True)

    assert api.termination_codes
    assert set(api.closed) == {11, 12, 13, 14, 15}


@_async_test
async def test_windows_close_retains_handles_until_delayed_io_settles(
    tmp_path: Path,
) -> None:
    api = _FakeWin32Api()
    api.block_io = True
    api.cancel_releases_io = False
    api.job_close_releases_io = False
    backend = _WindowsProcessBackend(max_processes=1, api=api)
    request = _request(tmp_path, "pass")
    process = await backend.spawn(
        request,
        on_spawn=lambda attached: None,
    )
    read = asyncio.create_task(process.read_stdout(16))
    await asyncio.to_thread(api.stdout_entered.wait, 1.0)

    close = asyncio.create_task(backend.close_process_handles(process))
    for _ in range(1000):
        if api.job_closed.is_set():
            break
        await asyncio.sleep(0)
    assert api.job_closed.is_set()
    assert 12 in api.closed
    assert 14 not in api.closed
    assert 11 not in api.closed

    api.return_code = 0xE0000002
    api.empty = True
    api.io_release.set()
    api.process_exited.set()
    await close
    await read
    await backend.close_backend()

    assert set(api.closed) == {11, 12, 13, 14, 15}


@_async_test
async def test_windows_cancelled_read_remains_owned_until_close(tmp_path: Path) -> None:
    api = _FakeWin32Api()
    api.block_io = True
    backend = _WindowsProcessBackend(max_processes=1, api=api)
    host = _ProcessHost(
        backend,
        limits=_ProcessHostLimits(
            max_processes=1,
            termination_grace_seconds=0.05,
        ),
    )
    request = _request(tmp_path, "pass")
    lease = await host.start(
        request, _PreparationPort(_PreparationLease(request))
    )
    read = asyncio.create_task(lease.read_stdout(16))
    assert await asyncio.to_thread(api.stdout_entered.wait, 1.0)
    read.cancel()
    with pytest.raises(asyncio.CancelledError):
        await read

    await asyncio.wait_for(host.close(), 1.0)
    assert set(api.closed) == {11, 12, 13, 14, 15}


@_async_test
async def test_windows_termination_failure_retains_job_until_retry(
    tmp_path: Path,
) -> None:
    api = _FakeWin32Api()
    api.block_io = True
    api.fail_termination = True
    backend = _WindowsProcessBackend(max_processes=1, api=api)
    host = _ProcessHost(
        backend,
        limits=_ProcessHostLimits(
            max_processes=1,
            termination_grace_seconds=0.02,
        ),
    )
    request = _request(tmp_path, "pass")
    lease = await host.start(request, _PreparationPort(_PreparationLease(request)))
    api.return_code = 0
    api.process_exited.set()
    stdout = asyncio.create_task(lease.read_stdout(16))
    write = asyncio.create_task(lease.write_stdin(b"payload"))
    assert await asyncio.to_thread(api.all_blocking_lanes_entered.wait, 1.0)

    with pytest.raises(HostingError) as failure:
        await asyncio.wait_for(host.close(), 1.0)
    assert failure.value.category is HostingFailureCategory.CLEANUP_FAILED
    await asyncio.gather(stdout, write, return_exceptions=True)

    assert set(api.closed) == {11, 13, 14, 15}
    assert 12 not in api.closed
    assert host._state == "faulted"
    assert lease in host._leases
    assert api.empty is False

    api.fail_termination = False
    await host.close()
    assert host._state == "closed"
    assert lease not in host._leases
    assert set(api.closed) == {11, 12, 13, 14, 15}


@_async_test
async def test_windows_cancelled_stream_calls_do_not_queue_new_native_io(
    tmp_path: Path,
) -> None:
    api = _FakeWin32Api()
    api.block_io = True
    backend = _WindowsProcessBackend(max_processes=1, api=api)
    host = _ProcessHost(
        backend,
        limits=_ProcessHostLimits(
            max_processes=1,
            termination_grace_seconds=0.05,
        ),
    )
    request = _request(tmp_path, "pass")
    lease = await host.start(request, _PreparationPort(_PreparationLease(request)))
    initial_read = asyncio.create_task(lease.read_stdout(16))
    initial_write = asyncio.create_task(lease.write_stdin(b"first"))
    assert await asyncio.to_thread(api.all_blocking_lanes_entered.wait, 1.0)
    initial_read.cancel()
    initial_write.cancel()
    await asyncio.gather(initial_read, initial_write, return_exceptions=True)

    repeated = [
        asyncio.create_task(lease.read_stdout(16))
        for _ in range(10)
    ] + [
        asyncio.create_task(lease.write_stdin(b"later"))
        for _ in range(10)
    ]
    await asyncio.sleep(0)
    for operation in repeated:
        operation.cancel()
    await asyncio.gather(*repeated, return_exceptions=True)
    with api._io_lock:
        assert api._io_count == 4

    await host.close()


def test_windows_backend_rejects_foreign_transport() -> None:
    backend = _WindowsProcessBackend(api=_FakeWin32Api())
    with pytest.raises(TypeError, match="own process transport"):
        backend.tree_exited(object())  # type: ignore[arg-type]


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects")
@_async_test
async def test_windows_native_factory_runs_exact_request(tmp_path: Path) -> None:
    base = _request(
        tmp_path,
        "import os; print(os.getcwd()); print(os.environ['H2_ONLY'])",
    )
    request = ProcessLaunchRequest(
        argv=base.argv,
        cwd=base.cwd,
        effective_environment=(("H2_ONLY", "exact"),),
        streams=base.streams,
    )
    preparation = _PreparationLease(request)
    observations = _Observations()
    host = create_process_host(observation_sink=observations)
    lease = await host.start(request, _PreparationPort(preparation))

    output = await lease.read_stdout(4096)
    assert (await lease.wait()).return_code == 0
    await lease.close()
    await host.close()

    assert output == f"{tmp_path.resolve()}\r\nexact\r\n".encode()
    assert preparation.close_calls == 1
    assert {item.backend_id for item in observations.items} == {"windows-job-v1"}


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects")
@_async_test
async def test_windows_native_job_reclaims_descendant(tmp_path: Path) -> None:
    marker = tmp_path / "escaped-marker"
    child = (
        "import pathlib,sys,time; time.sleep(2); "
        "pathlib.Path(sys.argv[1]).write_text('leaked')"
    )
    root = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]]); "
        "print('ready', flush=True); time.sleep(60)"
    )
    request = _request(tmp_path, root, child, str(marker))
    host = create_process_host(termination_grace_seconds=0.05)
    lease = await host.start(
        request, _PreparationPort(_PreparationLease(request))
    )

    assert await lease.read_stdout(7) == b"ready\r\n"
    await lease.close()
    await host.close()
    await asyncio.sleep(2.1)

    assert not marker.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows handle lists")
@_async_test
async def test_windows_native_parallel_spawns_exclude_ambient_handles(
    tmp_path: Path,
) -> None:
    import msvcrt

    names = ("sentinel-a", "sentinel-b")
    descriptors = [
        os.open(tmp_path / name, os.O_CREAT | os.O_RDWR) for name in names
    ]
    handles = [msvcrt.get_osfhandle(descriptor) for descriptor in descriptors]
    for handle in handles:
        os.set_handle_inheritable(handle, True)
    code = """
import ctypes
import sys

get_path = ctypes.windll.kernel32.GetFinalPathNameByHandleW
get_path.argtypes = (
    ctypes.c_void_p,
    ctypes.c_wchar_p,
    ctypes.c_ulong,
    ctypes.c_ulong,
)
get_path.restype = ctypes.c_ulong


def is_same_file(value, expected_name):
    buffer = ctypes.create_unicode_buffer(32768)
    length = get_path(ctypes.c_void_p(int(value)), buffer, len(buffer), 0)
    return bool(length) and buffer.value.casefold().endswith(
        "\\\\" + expected_name.casefold()
    )


pairs = zip(sys.argv[1::2], sys.argv[2::2], strict=True)
print("".join("1" if is_same_file(*pair) else "0" for pair in pairs))
"""
    arguments = tuple(
        item
        for handle, name in zip(handles, names, strict=True)
        for item in (str(handle), name)
    )
    requests = [
        _request(tmp_path, code, *arguments)
        for _ in range(2)
    ]
    host = create_process_host(max_processes=2)
    try:
        leases = await asyncio.gather(
            *(
                host.start(
                    request,
                    _PreparationPort(_PreparationLease(request)),
                )
                for request in requests
            )
        )
        outputs = await asyncio.gather(
            *(lease.read_stdout(32) for lease in leases)
        )
        assert outputs == [b"00\r\n", b"00\r\n"]
        await asyncio.gather(*(lease.close() for lease in leases))
    finally:
        await host.close()
        for descriptor in descriptors:
            os.close(descriptor)
