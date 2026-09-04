from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from loushang.hosting import (
    ChildSessionRequest,
    HostingObservation,
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
    ProcessStreamSpec,
    create_child_session_host,
    create_process_host,
)
from loushang.hosting._endpoint_host import _InheritedEndpointHost
from loushang.hosting._endpoint_platform import _select_endpoint_backend


class _Preparation:
    def __init__(self, request: ProcessLaunchRequest) -> None:
        self.request = request

    async def verify_current(self) -> None:
        return

    async def close(self) -> None:
        return


class _PreparationPort:
    def __init__(self, request: ProcessLaunchRequest) -> None:
        self._preparation = _Preparation(request)

    async def prepare(self, request: ProcessLaunchRequest) -> _Preparation:
        return self._preparation


class _Observations:
    def __init__(self) -> None:
        self.items: list[HostingObservation] = []

    def observe(self, observation: HostingObservation) -> None:
        self.items.append(observation)


def test_ci_executes_expected_native_backend(tmp_path: Path) -> None:
    expected = os.environ.get("LOUSHANG_HOSTING_EXPECTED_BACKEND")
    expected_endpoint = os.environ.get("LOUSHANG_HOSTING_EXPECTED_ENDPOINT")
    if expected is None or expected_endpoint is None:
        pytest.skip("native backend sentinel is asserted by the CI matrix")
    expected_os = {
        "posix-process-group-v1": "posix",
        "windows-job-v1": "nt",
    }
    assert expected in expected_os
    assert os.name == expected_os[expected]
    assert expected_endpoint == {
        "posix": "posix-socketpair-v1",
        "nt": "windows-anonymous-pipes-v1",
    }[os.name]

    async def scenario() -> None:
        observations = _Observations()
        request = ProcessLaunchRequest(
            argv=(sys.executable, "-c", "print('native')"),
            cwd=str(tmp_path.resolve()),
            effective_environment=tuple(os.environ.items()),
            streams=ProcessStreamSpec(
                stdin=ProcessStdinMode.CLOSED,
                stdout=ProcessStdoutMode.PIPE,
                stderr=ProcessStderrMode.DISCARD,
            ),
        )
        host = create_process_host(observation_sink=observations)
        lease = await host.start(request, _PreparationPort(request))
        assert await lease.read_stdout(32) in {b"native\n", b"native\r\n"}
        assert (await lease.wait()).return_code == 0
        await lease.close()
        await host.close()
        assert {item.backend_id for item in observations.items} == {expected}

        endpoint_backend = _select_endpoint_backend(max_endpoints=1)
        assert endpoint_backend.backend_id == expected_endpoint
        endpoint_host = _InheritedEndpointHost(endpoint_backend, max_endpoints=1)
        endpoint = await endpoint_host.create()
        await endpoint.close()
        await endpoint_host.close()

        session_observations = _Observations()
        session_request = ProcessLaunchRequest(
            argv=(
                sys.executable,
                "-c",
                (
                    "import sys; data=sys.stdin.buffer.read(4); "
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
        session_host = create_child_session_host(
            max_sessions=1,
            observation_sink=session_observations,
        )
        session = await session_host.start(
            ChildSessionRequest(session_request),
            _PreparationPort(session_request),
        )
        await session.endpoint.write(b"ping")
        assert await session.endpoint.read(4) == b"PING"
        assert (await session.process.wait()).return_code == 0
        await session.close()
        await session_host.close()
        assert {item.backend_id for item in session_observations.items} == {
            expected,
            expected_endpoint,
            f"{expected}+{expected_endpoint}",
        }
        assert {
            item.session_id
            for item in session_observations.items
            if item.session_id is not None
        } == {session.session_id}

    asyncio.run(scenario())
