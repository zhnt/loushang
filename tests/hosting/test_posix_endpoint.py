from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
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
from loushang.hosting._posix_endpoint import _PosixEndpointBackend
from loushang.hosting._posix_process import _PosixProcessBackend

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX socketpair")
_P = ParamSpec("_P")


def _async_test(
    function: Callable[_P, Awaitable[None]],
) -> Callable[_P, None]:
    @wraps(function)
    def run(*args: _P.args, **kwargs: _P.kwargs) -> None:
        asyncio.run(function(*args, **kwargs))

    return run


def _request(tmp_path: Path, code: str, *arguments: str) -> ProcessLaunchRequest:
    return ProcessLaunchRequest(
        argv=(sys.executable, "-c", code, *arguments),
        cwd=str(tmp_path.resolve()),
        effective_environment=tuple(os.environ.items()),
        streams=ProcessStreamSpec(
            stdin=ProcessStdinMode.CLOSED,
            stdout=ProcessStdoutMode.DISCARD,
            stderr=ProcessStderrMode.DISCARD,
        ),
    )


@_async_test
async def test_posix_socketpair_transfers_only_child_endpoint_through_stdio(
    tmp_path: Path,
) -> None:
    endpoint_host = _InheritedEndpointHost(_PosixEndpointBackend())
    endpoint_lease = await endpoint_host.create()
    transport = endpoint_lease._pair.transport
    host_descriptor = transport._endpoint.fileno()  # type: ignore[attr-defined]
    child_descriptor = endpoint_lease.inheritance._values[0]  # type: ignore[attr-defined]
    ambient_descriptor = os.open(
        tmp_path / "ambient-sentinel", os.O_CREAT | os.O_RDWR, 0o600
    )
    os.set_inheritable(ambient_descriptor, True)
    request = _request(
        tmp_path,
        (
            "import os,sys; descriptors=map(int,sys.argv[1:]); "
            "data=sys.stdin.buffer.read(4); "
            "states=[]\n"
            "for descriptor in descriptors:\n"
            " try: os.fstat(descriptor)\n"
            " except OSError: states.append(b'0')\n"
            " else: states.append(b'1')\n"
            "sys.stdout.buffer.write(data.upper()+b':' + b''.join(states)); "
            "sys.stdout.buffer.flush()"
        ),
        str(host_descriptor),
        str(child_descriptor),
        str(ambient_descriptor),
    )
    process_backend = _PosixProcessBackend()
    process = await process_backend.spawn(
        request,
        inheritance=endpoint_lease.inheritance,
        on_spawn=lambda attached: None,
    )

    await endpoint_lease.endpoint.write(b"ping")
    assert await endpoint_lease.endpoint.read(64) == b"PING:000"
    assert await process.wait() == 0
    await process_backend.wait_tree(process)
    await process_backend.close_process_handles(process)
    await endpoint_lease.close()
    await endpoint_host.close()
    await process_backend.close_backend()
    os.close(ambient_descriptor)


@_async_test
async def test_posix_endpoint_transfer_rejects_process_pipe_stream_intent(
    tmp_path: Path,
) -> None:
    endpoint_host = _InheritedEndpointHost(_PosixEndpointBackend())
    endpoint_lease = await endpoint_host.create()
    request = ProcessLaunchRequest(
        argv=(sys.executable, "-c", "pass"),
        cwd=str(tmp_path.resolve()),
        effective_environment=tuple(os.environ.items()),
        streams=ProcessStreamSpec(
            stdin=ProcessStdinMode.PIPE,
            stdout=ProcessStdoutMode.PIPE,
            stderr=ProcessStderrMode.DISCARD,
        ),
    )
    backend = _PosixProcessBackend()

    with pytest.raises(HostingError) as failure:
        await backend.spawn(
            request,
            inheritance=endpoint_lease.inheritance,
            on_spawn=lambda attached: None,
        )
    assert failure.value.category is HostingFailureCategory.ENDPOINT_TRANSFER_FAILED

    await endpoint_lease.close()
    await endpoint_host.close()
    await backend.close_backend()


@_async_test
async def test_posix_endpoint_close_unblocks_active_read() -> None:
    host = _InheritedEndpointHost(_PosixEndpointBackend())
    lease = await host.create()
    read = asyncio.create_task(lease.endpoint.read(8))
    await asyncio.sleep(0)

    await asyncio.wait_for(lease.close(), 1.0)
    assert await read == b""
    await host.close()
