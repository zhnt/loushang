from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from functools import wraps
from pathlib import Path
from typing import ParamSpec

import pytest

from loushang.hosting import (
    HostingError,
    HostingFailureCategory,
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
    ProcessStreamSpec,
)
from loushang.hosting._endpoint_host import _InheritedEndpointHost
from loushang.hosting._win32_process import (
    _CtypesWin32Api,
    _Win32AttributeList,
    _Win32SpawnHandles,
)
from loushang.hosting._windows_endpoint import _WindowsEndpointBackend
from loushang.hosting._windows_process import _WindowsProcessBackend

from ._windows_handle_probe import WindowsHandleIdentityProbe

_P = ParamSpec("_P")


def _async_test(
    function: Callable[_P, Awaitable[None]],
) -> Callable[_P, None]:
    @wraps(function)
    def run(*args: _P.args, **kwargs: _P.kwargs) -> None:
        asyncio.run(function(*args, **kwargs))

    return run


class _EndpointApi:
    def __init__(self) -> None:
        self.pipes = iter(((11, 12), (13, 14)))
        self.reads: list[bytes] = [b"reply"]
        self.writes: list[tuple[int, bytes]] = []
        self.cancelled: list[int] = []
        self.closed: list[int] = []
        self.read_entered = threading.Event()
        self.read_release = threading.Event()
        self.block_read = False
        self.read_calls = 0
        self.write_entered = threading.Event()
        self.write_release = threading.Event()
        self.block_write = False

    def create_pipe(self, *, child_reads: bool) -> tuple[int, int]:
        if child_reads:
            assert not self.closed
        return next(self.pipes)

    def read_pipe(self, handle: int, max_bytes: int) -> bytes:
        assert handle == 13
        self.read_calls += 1
        self.read_entered.set()
        if self.block_read:
            self.read_release.wait()
        return self.reads.pop(0)[:max_bytes] if self.reads else b""

    def write_pipe(self, handle: int, data: bytes) -> None:
        self.write_entered.set()
        if self.block_write:
            self.write_release.wait()
        self.writes.append((handle, data))

    def cancel_synchronous_io(self, thread_id: int) -> None:
        self.cancelled.append(thread_id)
        self.read_release.set()
        self.write_release.set()

    def close_handle(self, handle: int) -> None:
        self.closed.append(handle)


class _ProcessApi:
    def __init__(self) -> None:
        self.endpoint_handles: tuple[int, int] | None = None
        self.closed: list[int] = []
        self.return_code: int | None = None
        self.empty = False

    def spawn(
        self,
        request: ProcessLaunchRequest,
        endpoint_handles: tuple[int, int] | None = None,
    ) -> _Win32SpawnHandles:
        self.endpoint_handles = endpoint_handles
        return _Win32SpawnHandles(21, 22, None, None, None)

    def read_pipe(self, handle: int, max_bytes: int) -> bytes:
        raise AssertionError("process stdout and stderr are not owned")

    def write_pipe(self, handle: int, data: bytes) -> None:
        raise AssertionError("process stdin is not owned")

    def wait_process(self, handle: int) -> int:
        return 0

    def process_return_code(self, handle: int) -> int | None:
        return self.return_code

    def job_is_empty(self, handle: int) -> bool:
        return self.empty

    def terminate_job(self, handle: int, exit_code: int) -> None:
        self.return_code = exit_code
        self.empty = True

    def close_handle(self, handle: int) -> None:
        self.closed.append(handle)


def _request(tmp_path: Path) -> ProcessLaunchRequest:
    return ProcessLaunchRequest(
        argv=(str((tmp_path / "child.exe").resolve()),),
        cwd=str(tmp_path.resolve()),
        effective_environment=(),
        streams=ProcessStreamSpec(
            stdin=ProcessStdinMode.CLOSED,
            stdout=ProcessStdoutMode.DISCARD,
            stderr=ProcessStderrMode.DISCARD,
        ),
    )


class _FaultEndpointApi(_EndpointApi):
    def __init__(
        self,
        *,
        fail_pipe: int | None = None,
        fail_close_once: int | None = None,
        fail_close_always: int | None = None,
    ) -> None:
        super().__init__()
        self.fail_pipe = fail_pipe
        self.fail_close_once = fail_close_once
        self.fail_close_always = fail_close_always
        self.pipe_calls = 0

    def create_pipe(self, *, child_reads: bool) -> tuple[int, int]:
        self.pipe_calls += 1
        if self.pipe_calls == self.fail_pipe:
            raise OSError("CreatePipe failed")
        return super().create_pipe(child_reads=child_reads)

    def close_handle(self, handle: int) -> None:
        if handle == self.fail_close_always:
            raise OSError(f"close {handle} failed")
        if handle == self.fail_close_once:
            self.fail_close_once = None
            raise OSError(f"close {handle} failed once")
        super().close_handle(handle)


@_async_test
async def test_windows_pair_has_exact_direction_and_single_use_transfer(
    tmp_path: Path,
) -> None:
    endpoint_api = _EndpointApi()
    endpoint_host = _InheritedEndpointHost(
        _WindowsEndpointBackend(api=endpoint_api)
    )
    endpoint_lease = await endpoint_host.create()

    await endpoint_lease.endpoint.write(b"request")
    assert await endpoint_lease.endpoint.read(8) == b"reply"
    assert endpoint_api.writes == [(12, b"request")]

    process_api = _ProcessApi()
    process_backend = _WindowsProcessBackend(api=process_api)
    process = await process_backend.spawn(
        _request(tmp_path),
        inheritance=endpoint_lease.inheritance,
        on_spawn=lambda attached: None,
    )

    assert process_api.endpoint_handles == (11, 14)
    assert endpoint_api.closed == [11, 14]
    process_api.return_code = 0
    process_api.empty = True
    assert await process.wait() == 0
    await process_backend.close_process_handles(process)
    await endpoint_lease.close()
    await process_backend.close_backend()
    await endpoint_host.close()

    assert set(endpoint_api.closed) == {11, 12, 13, 14}
    assert endpoint_api.cancelled == []
    assert set(process_api.closed) == {21, 22}


@_async_test
async def test_windows_endpoint_close_unblocks_owned_read() -> None:
    api = _EndpointApi()
    api.block_read = True
    host = _InheritedEndpointHost(_WindowsEndpointBackend(api=api))
    lease = await host.create()
    read = asyncio.create_task(lease.endpoint.read(8))
    assert await asyncio.to_thread(api.read_entered.wait, 1.0)
    read.cancel()

    await asyncio.wait_for(lease.close(), 1.0)
    with pytest.raises(asyncio.CancelledError):
        await read
    await host.close()

    assert len(api.cancelled) == 1
    assert set(api.closed) == {11, 12, 13, 14}


@_async_test
async def test_windows_endpoint_cancellation_keeps_one_operation_per_direction() -> None:
    api = _EndpointApi()
    api.block_read = True
    api.block_write = True
    host = _InheritedEndpointHost(_WindowsEndpointBackend(api=api))
    lease = await host.create()

    reads = [asyncio.create_task(lease.endpoint.read(8)) for _ in range(20)]
    writes = [
        asyncio.create_task(lease.endpoint.write(str(index).encode()))
        for index in range(20)
    ]
    assert await asyncio.to_thread(api.read_entered.wait, 1.0)
    assert await asyncio.to_thread(api.write_entered.wait, 1.0)
    for operation in (*reads, *writes):
        operation.cancel()
    await asyncio.gather(*reads, *writes, return_exceptions=True)

    assert api.read_calls == 1
    assert len(api.writes) == 0
    await asyncio.wait_for(lease.close(), 1.0)
    await host.close()
    assert len(api.writes) == 1


@_async_test
async def test_windows_endpoint_second_pipe_failure_closes_first_pair() -> None:
    api = _FaultEndpointApi(fail_pipe=2)
    host = _InheritedEndpointHost(_WindowsEndpointBackend(api=api))

    with pytest.raises(HostingError) as failure:
        await host.create()
    assert failure.value.category is HostingFailureCategory.ENDPOINT_UNAVAILABLE
    await host.close()

    assert set(api.closed) == {11, 12}


@_async_test
async def test_windows_acquisition_cleanup_debt_is_retried_by_backend_close() -> None:
    api = _FaultEndpointApi(fail_pipe=2, fail_close_once=11)
    backend = _WindowsEndpointBackend(api=api)

    with pytest.raises(HostingError) as failure:
        await backend.create_pair(on_create=lambda pair: None)

    assert failure.value.category is HostingFailureCategory.ENDPOINT_UNAVAILABLE
    assert isinstance(failure.value.__cause__, HostingError)
    assert failure.value.__cause__.category is HostingFailureCategory.CLEANUP_FAILED
    assert api.closed == [12]

    await backend.close_backend()
    assert api.closed == [12, 11]


@_async_test
async def test_windows_child_handle_transfer_close_retries_only_owned_handles() -> None:
    api = _FaultEndpointApi(fail_close_once=11)
    host = _InheritedEndpointHost(_WindowsEndpointBackend(api=api))
    lease = await host.create()

    assert lease.inheritance.claim(backend_id="windows-job-v1") == (11, 14)
    with pytest.raises(HostingError) as failure:
        lease.inheritance.mark_transferred()
    assert failure.value.category is HostingFailureCategory.ENDPOINT_TRANSFER_FAILED
    assert api.closed == [14]

    await lease.inheritance.close()
    await lease.close()
    await host.close()
    assert api.closed.count(11) == 1
    assert api.closed.count(14) == 1


@_async_test
async def test_windows_attachment_primary_survives_cleanup_failure() -> None:
    api = _FaultEndpointApi(fail_close_always=12)
    backend = _WindowsEndpointBackend(api=api)

    def reject(pair: object) -> None:
        del pair
        raise ValueError("attachment rejected")

    with pytest.raises(ValueError, match="attachment rejected") as failure:
        await backend.create_pair(on_create=reject)  # type: ignore[arg-type]
    assert isinstance(failure.value.__cause__, HostingError)
    assert failure.value.__cause__.category is HostingFailureCategory.CLEANUP_FAILED
    api.fail_close_always = None
    await backend.close_backend()
    assert api.closed.count(12) == 1


@pytest.mark.skipif(os.name != "nt", reason="native Windows endpoint")
@pytest.mark.parametrize(
    "leaked_index", [None, 0, 1, 2],
    ids=["isolated", "leaked-parent-read", "leaked-parent-write", "leaked-sentinel"],
)
@_async_test
async def test_native_windows_endpoint_process_round_trip(
    tmp_path: Path, leaked_index: int | None,
) -> None:
    import msvcrt
    import sys

    request = ProcessLaunchRequest(
        argv=(
            sys.executable,
            "-c",
            (
                "import sys; sys.stdout.buffer.write(b'READY'); "
                "sys.stdout.buffer.flush(); "
                "data=sys.stdin.buffer.read(4); "
                "sys.stdout.buffer.write(data.upper()); "
                "sys.stdout.buffer.flush()"
            ),
        ),
        cwd=str(tmp_path.resolve()),
        effective_environment=tuple(os.environ.items()),
        streams=ProcessStreamSpec(
            stdin=ProcessStdinMode.CLOSED,
            stdout=ProcessStdoutMode.DISCARD,
            stderr=ProcessStderrMode.DISCARD,
        ),
    )
    async with AsyncExitStack() as cleanup:
        endpoint_host = _InheritedEndpointHost(_WindowsEndpointBackend())
        cleanup.push_async_callback(endpoint_host.close)
        endpoint_lease = await endpoint_host.create()
        cleanup.push_async_callback(endpoint_lease.close)
        sentinel_descriptor = os.open(
            tmp_path / "h3-ambient-sentinel", os.O_CREAT | os.O_RDWR
        )
        cleanup.callback(os.close, sentinel_descriptor)
        sentinel_handle = msvcrt.get_osfhandle(sentinel_descriptor)
        os.set_handle_inheritable(sentinel_handle, True)
        transport = endpoint_lease._pair.transport
        hidden_handles = (
            transport._read_handle,  # type: ignore[attr-defined]
            transport._write_handle,  # type: ignore[attr-defined]
            sentinel_handle,
        )

        class _LeakingApi(_CtypesWin32Api):
            """Native positive control: deliberately violate the exact allowlist."""

            def _attribute_list(
                self, job: int, inherited_handles: tuple[int, int, int],
            ) -> _Win32AttributeList:
                assert leaked_index is not None
                leaked = hidden_handles[leaked_index]
                os.set_handle_inheritable(leaked, True)
                return super()._attribute_list(
                    job, (*inherited_handles, leaked),  # type: ignore[arg-type]
                )

        process_backend = _WindowsProcessBackend(
            api=None if leaked_index is None else _LeakingApi()
        )
        cleanup.push_async_callback(process_backend.close_backend)

        async def read_exactly(size: int) -> bytes:
            data = b""
            while len(data) < size:
                chunk = await endpoint_lease.endpoint.read(size - len(data))
                assert chunk, "child exited before the endpoint handshake completed"
                data += chunk
            return data

        async with asyncio.timeout(20):
            process = await process_backend.spawn(
                request,
                inheritance=endpoint_lease.inheritance,
                on_spawn=lambda attached: cleanup.push_async_callback(
                    process_backend.close_process_handles, attached
                ),
            )
            assert await read_exactly(5) == b"READY"
            # The child remains blocked on stdin throughout object comparison.
            # HANDLE numbers are process-local; validity alone is not leakage.
            assert process._process_handle is not None
            probe = WindowsHandleIdentityProbe()
            matches = tuple(
                probe.matches(process._process_handle, handle, handle)
                for handle in hidden_handles
            )
            assert matches == tuple(index == leaked_index for index in range(3))
            await endpoint_lease.endpoint.write(b"ping")
            assert await read_exactly(4) == b"PING"
            assert await process.wait() == 0
            await process_backend.wait_tree(process)


@pytest.mark.skipif(os.name != "nt", reason="native Windows endpoint")
@_async_test
async def test_native_windows_close_cancels_blocked_read_and_write() -> None:
    host = _InheritedEndpointHost(
        _WindowsEndpointBackend(io_settlement_seconds=2.0),
        max_write_bytes=1024 * 1024,
    )
    lease = await host.create()
    read = asyncio.create_task(lease.endpoint.read(8))
    write = asyncio.create_task(lease.endpoint.write(b"x" * (1024 * 1024)))
    await asyncio.sleep(0.1)
    assert not read.done()
    assert not write.done()

    await asyncio.wait_for(lease.close(), 5.0)
    assert await read == b""
    with pytest.raises(HostingError) as write_closed:
        await write
    assert write_closed.value.category is HostingFailureCategory.PEER_CLOSED
    await host.close()
