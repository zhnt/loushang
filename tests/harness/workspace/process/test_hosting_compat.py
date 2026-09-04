from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.harness.tools.process_hosting import _managed_process_launch_request
from loushang.harness.workspace.process import hosting_compat
from loushang.harness.workspace.process._sealed_executable import (
    _capture_bound_process_directory,
    _capture_sealed_process_executable,
    _contained_process_launch_request,
)
from loushang.harness.workspace.process.host import (
    ProcessHost,
    ProcessHostCapacityError,
    ProcessHostClosedError,
    ProcessHostError,
    ProcessWriteLimitError,
)
from loushang.harness.workspace.process.hosting_compat import (
    HostingCompatibilityUnavailableError,
    HostingProcessHostAdapter,
)
from loushang.harness.workspace.process.local import (
    ProcessContainmentPlan,
    ProcessContainmentPlanner,
)
from loushang.harness.workspace.process.types import ProcessLaunchRequest


def _request(tmp_path: Path, code: str, *arguments: str) -> ProcessLaunchRequest:
    return ProcessLaunchRequest(
        command=(sys.executable, "-c", code, *arguments),
        cwd=str(tmp_path),
        effective_environment=tuple(os.environ.items()),
    )


def test_compat_adapter_preserves_request_stream_exit_and_tail(tmp_path: Path) -> None:
    async def scenario() -> None:
        close_calls = 0

        async def close_containment() -> None:
            nonlocal close_calls
            close_calls += 1

        async def plan(request: ProcessLaunchRequest) -> ProcessContainmentPlan:
            prepared = replace(
                request,
                effective_environment=(("H2_COMPAT", "exact"),),
            )
            return ProcessContainmentPlan(prepared, close=close_containment)

        host = HostingProcessHostAdapter(stderr_max_bytes=4)
        request = _request(
            tmp_path,
            (
                "import os,sys; data=sys.stdin.buffer.read(); "
                "sys.stdout.buffer.write(os.environ['H2_COMPAT'].encode()+data); "
                "sys.stderr.buffer.write(b'0123456789')"
            ),
        )
        handle = await host.start(request, containment_planner=plan)
        await handle.write_stdin(b"-payload")
        await handle.close_stdin()

        assert await handle.read_stdout() == b"exact-payload"
        assert (await handle.wait()).return_code == 0
        assert handle.stderr_tail().content == b"6789"
        assert handle.stderr_tail().truncated is True
        await asyncio.gather(handle.close(), handle.close())
        await host.close()
        assert close_calls == 1

    asyncio.run(scenario())


def test_compat_adapter_preserves_streamed_stderr(tmp_path: Path) -> None:
    async def scenario() -> None:
        request = replace(
            _request(tmp_path, "import sys; sys.stderr.buffer.write(b'raw')"),
            stream_stderr=True,
        )
        host = HostingProcessHostAdapter()
        handle = await host.start(request)
        assert await handle.read_stderr() == b"raw"
        assert (await handle.wait()).return_code == 0
        assert handle.stderr_tail().content == b"raw"
        await host.close()

    asyncio.run(scenario())


def test_compat_adapter_preserves_limit_and_closed_error_shapes(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        host = HostingProcessHostAdapter(
            max_processes=1,
            max_read_bytes=3,
            max_write_bytes=3,
        )
        first = await host.start(_request(tmp_path, "import time; time.sleep(60)"))
        with pytest.raises(ProcessHostCapacityError):
            await host.start(_request(tmp_path, "pass"))
        with pytest.raises(ValueError):
            await first.read_stdout(4)
        with pytest.raises(ProcessWriteLimitError):
            await first.write_stdin(b"four")
        await host.close()
        with pytest.raises(ProcessHostClosedError):
            await host.start(_request(tmp_path, "pass"))

    asyncio.run(scenario())


def test_compat_adapter_rejects_sealed_descriptor_and_closes_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        close_calls = 0

        async def close_plan() -> None:
            nonlocal close_calls
            close_calls += 1

        async def plan(request: ProcessLaunchRequest) -> ProcessContainmentPlan:
            return ProcessContainmentPlan(request, close=close_plan)

        monkeypatch.setattr(
            hosting_compat,
            "_process_inherited_file_descriptors",
            lambda request: (42,),
        )
        host = HostingProcessHostAdapter()
        with pytest.raises(
            HostingCompatibilityUnavailableError,
            match="cannot transfer",
        ):
            await host.start(_request(tmp_path, "pass"), containment_planner=plan)
        await host.close()
        assert close_calls == 1

    asyncio.run(scenario())


def test_compat_adapter_rejects_relative_executable_without_resolving_path(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        request = ProcessLaunchRequest(
            command=("python", "-c", "pass"),
            cwd=str(tmp_path),
            effective_environment=(),
        )
        host = HostingProcessHostAdapter()
        with pytest.raises(
            HostingCompatibilityUnavailableError,
            match="outside the Hosting v1 contract",
        ):
            await host.start(request)
        await host.close()

    asyncio.run(scenario())


def test_compat_adapter_preserves_planner_exceptions_and_wrong_type(
    tmp_path: Path,
) -> None:
    class PlannerFailure(ValueError):
        pass

    async def scenario() -> None:
        async def fail(request: ProcessLaunchRequest) -> ProcessContainmentPlan:
            raise PlannerFailure("planner evidence changed")

        async def wrong(request: ProcessLaunchRequest) -> ProcessContainmentPlan:
            return object()  # type: ignore[return-value]

        for host in (ProcessHost(), HostingProcessHostAdapter()):
            with pytest.raises(PlannerFailure, match="evidence changed"):
                await host.start(_request(tmp_path, "pass"), containment_planner=fail)
            with pytest.raises(TypeError, match="must return ProcessContainmentPlan"):
                await host.start(_request(tmp_path, "pass"), containment_planner=wrong)
            await host.close()

    asyncio.run(scenario())


def test_compat_adapter_matches_current_host_close_during_planning(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        def blocking_planner(
            entered: asyncio.Event,
        ) -> ProcessContainmentPlanner:
            async def block(
                request: ProcessLaunchRequest,
            ) -> ProcessContainmentPlan:
                entered.set()
                await asyncio.Future()
                raise AssertionError("unreachable")

            return block

        for host in (ProcessHost(), HostingProcessHostAdapter()):
            entered = asyncio.Event()
            start = asyncio.create_task(
                host.start(
                    _request(tmp_path, "pass"),
                    containment_planner=blocking_planner(entered),
                )
            )
            await entered.wait()
            await asyncio.wait_for(host.close(), 1.0)
            with pytest.raises(asyncio.CancelledError):
                await start

    asyncio.run(scenario())


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux memfd seals")
def test_compat_adapter_rejects_real_sealed_and_bound_descriptors(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        executable = Path(sys.executable).resolve()
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        runtime = _capture_sealed_process_executable(
            executable,
            expected_digest=digest,
        )
        identity = tmp_path.stat()
        cwd = _capture_bound_process_directory(
            tmp_path,
            expected_identity=(identity.st_dev, identity.st_ino),
        )
        marker = tmp_path / "must-not-run"
        managed = _managed_process_launch_request(
            command=(
                str(executable),
                "-c",
                "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('ran')",
                str(marker),
            ),
            cwd=str(tmp_path),
            effective_environment=tuple(os.environ.items()),
            declared_effects=(),
            authorization_metadata={
                "cwdDevice": cwd.device,
                "cwdInode": cwd.inode,
                "runtimeDigest": digest,
                "runtimeSize": runtime.size,
            },
            pre_start_validator=runtime.verify,
            sealed_executable=runtime,
            bound_cwd_directory=cwd,
        )

        async def close_artifacts() -> None:
            cwd.close()
            runtime.close()

        async def plan(request: ProcessLaunchRequest) -> ProcessContainmentPlan:
            contained = _contained_process_launch_request(
                request,
                command=request.command,
            )
            return ProcessContainmentPlan(contained, close=close_artifacts)

        host = HostingProcessHostAdapter()
        with pytest.raises(HostingCompatibilityUnavailableError):
            await host.start(managed, containment_planner=plan)
        await host.close()

        assert runtime._closed is True
        assert cwd._closed is True
        assert not marker.exists()

    asyncio.run(scenario())


def test_compat_adapter_is_not_the_current_process_host() -> None:
    assert HostingProcessHostAdapter.__module__.endswith("hosting_compat")
    assert issubclass(HostingCompatibilityUnavailableError, ProcessHostError)
