from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from loushang.harness.environment import HostEnvironment, LocalHostEnvironmentProbe
from loushang.harness.sandbox import (
    LinuxBubblewrapBackend,
    SandboxScopeRequest,
    SandboxUnavailableError,
)
from loushang.harness.workspace.exec import (
    ExecOutputChunk,
    ExecRequest,
    ExecResult,
    materialize_exec_request,
)
from loushang.harness.workspace.process import ProcessLaunchRequest


def _linux_environment() -> HostEnvironment:
    return HostEnvironment(
        os_family="linux",
        platform_name="linux",
        architecture="x86_64",
    )


def _fake_bwrap(tmp_path: Path) -> Path:
    path = tmp_path / "bwrap"
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _proxy_bwrap(tmp_path: Path) -> Path:
    path = tmp_path / "proxy-bwrap"
    path.write_text(
        """#!/usr/bin/python3
import os
import sys

separator = sys.argv.index("--")
if "--chdir" in sys.argv[:separator]:
    index = sys.argv.index("--chdir")
    os.chdir(sys.argv[index + 1])
command = sys.argv[separator + 1:]
os.execvp(command[0], command)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _successful_probe(
    argv: tuple[str, ...],
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    assert "--unshare-user" in argv
    assert "--unshare-net" in argv
    assert timeout_seconds > 0
    return subprocess.CompletedProcess(argv, 0, "", "")


def test_linux_backend_is_not_applicable_without_resolving_bwrap(
    tmp_path: Path,
) -> None:
    del tmp_path

    def unexpected_finder(name: str) -> str | None:
        raise AssertionError(f"must not resolve {name} off Linux")

    backend = LinuxBubblewrapBackend(executable_finder=unexpected_finder)
    status = backend.probe(
        HostEnvironment(
            os_family="macos",
            platform_name="darwin",
            architecture="arm64",
        )
    )

    assert status.state == "not_applicable"


def test_linux_backend_probe_distinguishes_missing_and_unusable_namespaces(
    tmp_path: Path,
) -> None:
    missing = LinuxBubblewrapBackend(executable_finder=lambda _: None)
    assert missing.probe(_linux_environment()).state == "unavailable"
    assert "not found" in (missing.probe(_linux_environment()).reason or "")

    def failed_probe(
        argv: tuple[str, ...],
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]:
        del timeout_seconds
        return subprocess.CompletedProcess(
            argv,
            1,
            "",
            "bwrap: user namespaces are disabled",
        )

    unavailable = LinuxBubblewrapBackend(
        bwrap_path=_fake_bwrap(tmp_path),
        probe_runner=failed_probe,
    ).probe(_linux_environment())

    assert unavailable.state == "unavailable"
    assert "user namespaces are disabled" in (unavailable.reason or "")


def test_linux_backend_probe_reports_enforcement_capabilities(tmp_path: Path) -> None:
    status = LinuxBubblewrapBackend(
        bwrap_path=_fake_bwrap(tmp_path),
        probe_runner=_successful_probe,
    ).probe(_linux_environment())

    assert status.state == "available"
    assert status.enforced_capabilities == frozenset(
        {
            "filesystem_roots",
            "filesystem_denied_roots",
            "network_isolation",
            "private_temporary_directory",
            "subprocess_inheritance",
        }
    )


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="asserts the Linux-only bubblewrap backend command shape",
)
def test_linux_scope_wraps_the_materialized_request_and_common_exec_backend(
    tmp_path: Path,
) -> None:
    captured: list[ExecRequest] = []
    updates: list[ExecOutputChunk] = []

    async def local_backend(request, *, signal=None, on_update=None):
        del signal
        captured.append(request)
        chunk = ExecOutputChunk(stream="stdout", text="sandboxed\n")
        if on_update is not None:
            update = on_update(chunk)
            if asyncio.iscoroutine(update):
                await update
        return ExecResult(exit_code=0, stdout=chunk.text, output_chunks=(chunk,))

    bwrap_path = _fake_bwrap(tmp_path)
    backend = LinuxBubblewrapBackend(
        bwrap_path=bwrap_path,
        probe_runner=_successful_probe,
        local_backend=local_backend,
    )
    assert backend.probe(_linux_environment()).state == "available"
    writable = tmp_path / "writable"
    writable.mkdir()
    denied = tmp_path / "secret"
    denied.write_text("secret", encoding="utf-8")
    platform_denied = Path("/etc/hosts")

    async def scenario() -> None:
        scope = await backend.open_scope(
            SandboxScopeRequest(
                cwd=tmp_path,
                readable_roots=(tmp_path,),
                writable_roots=(writable,),
                denied_roots=(denied, platform_denied),
                network="restricted",
            )
        )

        async def on_update(chunk: ExecOutputChunk) -> None:
            updates.append(chunk)

        request = materialize_exec_request(
            ExecRequest(
                command=("/usr/bin/python3", "-c", "print('ok')"),
                cwd=str(tmp_path),
                env=(("VISIBLE", "yes"),),
                timeout_seconds=7,
                stdin="input",
            ),
            environ={"BASE": "value"},
        )
        result = await scope(request, on_update=on_update)
        await scope.close()

        assert result.stdout == "sandboxed\n"
        assert scope.descriptor.state == "enforcing"
        assert "network_isolation" in scope.descriptor.enforced_capabilities

    asyncio.run(scenario())

    wrapped = captured[0]
    assert wrapped.command[0] == str(bwrap_path)
    assert "--ro-bind" in wrapped.command
    assert ("--bind", str(writable), str(writable)) == _argument_window(
        wrapped.command, "--bind", str(writable)
    )
    assert ("--ro-bind", "/dev/null", str(denied)) == _argument_window(
        wrapped.command, "--ro-bind", "/dev/null", str(denied)
    )
    assert (
        "--ro-bind",
        "/dev/null",
        str(platform_denied),
    ) == _argument_window(
        wrapped.command,
        "--ro-bind",
        "/dev/null",
        str(platform_denied),
    )
    assert "--unshare-net" in wrapped.command
    assert wrapped.command[-3:] == (
        "/usr/bin/python3",
        "-c",
        "print('ok')",
    )
    assert wrapped.timeout_seconds == 7
    assert wrapped.stdin == "input"
    assert dict(wrapped.effective_environment or ()) == {
        "BASE": "value",
        "VISIBLE": "yes",
    }
    assert updates == [ExecOutputChunk(stream="stdout", text="sandboxed\n")]


def test_linux_hosted_plan_reuses_the_one_shot_bubblewrap_command_builder(
    tmp_path: Path,
) -> None:
    captured: list[ExecRequest] = []

    async def local_backend(request, **kwargs):
        del kwargs
        captured.append(request)
        return ExecResult(exit_code=0)

    backend = LinuxBubblewrapBackend(
        bwrap_path=_fake_bwrap(tmp_path),
        probe_runner=_successful_probe,
        local_backend=local_backend,
    )
    backend.probe(_linux_environment())
    scope_request = SandboxScopeRequest(
        cwd=tmp_path,
        readable_roots=(tmp_path,),
        writable_roots=(tmp_path,),
        network="restricted",
    )
    environment = (("MODE", "test"),)

    async def scenario() -> None:
        scope = await backend.open_scope(scope_request)
        await scope(
            ExecRequest(
                command=("server", "--stdio"),
                cwd=str(tmp_path),
                effective_environment=environment,
            )
        )
        plan = await backend._plan_hosted_process(
            ProcessLaunchRequest(
                command=("server", "--stdio"),
                cwd=str(tmp_path),
                effective_environment=environment,
            ),
            scope_request,
        )

        assert plan.request.command == captured[0].command
        assert plan.request.cwd == str(tmp_path)
        assert plan.request.effective_environment == environment
        await plan.close()
        await scope.close()

    asyncio.run(scenario())


def test_linux_scope_allowed_network_does_not_claim_or_add_isolation(
    tmp_path: Path,
) -> None:
    captured: list[ExecRequest] = []

    async def local_backend(request, **kwargs):
        del kwargs
        captured.append(request)
        return ExecResult(exit_code=0)

    backend = LinuxBubblewrapBackend(
        bwrap_path=_fake_bwrap(tmp_path),
        probe_runner=_successful_probe,
        local_backend=local_backend,
    )
    backend.probe(_linux_environment())

    async def scenario() -> None:
        scope = await backend.open_scope(
            SandboxScopeRequest(
                cwd=tmp_path,
                readable_roots=(tmp_path,),
                network="allowed",
            )
        )
        assert "network_isolation" not in scope.descriptor.enforced_capabilities
        await scope(
            materialize_exec_request(
                ExecRequest(command=("/usr/bin/true",), cwd=str(tmp_path)),
                environ={},
            )
        )

    asyncio.run(scenario())

    assert "--unshare-net" not in captured[0].command


def test_linux_scope_preserves_streaming_environment_stdin_and_timeout(
    tmp_path: Path,
) -> None:
    backend = LinuxBubblewrapBackend(
        bwrap_path=_proxy_bwrap(tmp_path),
        probe_runner=_successful_probe,
    )
    backend.probe(_linux_environment())
    updates: list[ExecOutputChunk] = []

    async def scenario() -> None:
        scope = await backend.open_scope(
            SandboxScopeRequest(
                cwd=tmp_path,
                readable_roots=(tmp_path,),
                writable_roots=(tmp_path,),
            )
        )

        async def on_update(chunk: ExecOutputChunk) -> None:
            updates.append(chunk)

        streamed = await scope(
            materialize_exec_request(
                ExecRequest(
                    command=(
                        "/usr/bin/python3",
                        "-c",
                        (
                            "import os, sys; "
                            "print(os.environ['SANDBOX_TEST'], flush=True); "
                            "print(sys.stdin.read(), file=sys.stderr, flush=True)"
                        ),
                    ),
                    cwd=str(tmp_path),
                    env=(("SANDBOX_TEST", "visible"),),
                    stdin="input",
                ),
                environ={},
            ),
            on_update=on_update,
        )
        timed_out = await scope(
            materialize_exec_request(
                ExecRequest(
                    command=("/usr/bin/python3", "-c", "import time; time.sleep(10)"),
                    cwd=str(tmp_path),
                    timeout_seconds=0.05,
                ),
                environ={},
            )
        )
        await scope.close()

        assert streamed.stdout == "visible\n"
        assert streamed.stderr == "input\n"
        assert timed_out.timed_out is True
        assert timed_out.exit_code != 0

    asyncio.run(scenario())

    assert updates == [
        ExecOutputChunk(stream="stdout", text="visible\n"),
        ExecOutputChunk(stream="stderr", text="input\n"),
    ]


def test_linux_scope_preserves_abort_signal(tmp_path: Path) -> None:
    backend = LinuxBubblewrapBackend(
        bwrap_path=_proxy_bwrap(tmp_path),
        probe_runner=_successful_probe,
    )
    backend.probe(_linux_environment())

    class _Signal:
        aborted = False

    async def scenario() -> None:
        scope = await backend.open_scope(
            SandboxScopeRequest(
                cwd=tmp_path,
                readable_roots=(tmp_path,),
            )
        )
        signal = _Signal()

        async def abort() -> None:
            await asyncio.sleep(0.05)
            signal.aborted = True

        abort_task = asyncio.create_task(abort())
        result = await scope(
            materialize_exec_request(
                ExecRequest(
                    command=("/usr/bin/python3", "-c", "import time; time.sleep(10)"),
                    cwd=str(tmp_path),
                ),
                environ={},
            ),
            signal=signal,
        )
        await abort_task
        await scope.close()

        assert result.cancelled is True
        assert result.exit_code != 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("request_factory", "message"),
    [
        (
            lambda root: SandboxScopeRequest(
                cwd=root,
                readable_roots=(root / "other",),
            ),
            "cwd is outside",
        ),
        (
            lambda root: SandboxScopeRequest(
                cwd=root,
                readable_roots=(root,),
                denied_roots=(root,),
            ),
            "cwd conflicts",
        ),
        (
            lambda root: SandboxScopeRequest(
                cwd=root,
                readable_roots=(root,),
                denied_roots=(root / "missing",),
            ),
            "missing denied roots",
        ),
    ],
)
def test_linux_scope_rejects_requests_it_cannot_fully_enforce(
    tmp_path: Path,
    request_factory,
    message: str,
) -> None:
    backend = LinuxBubblewrapBackend(
        bwrap_path=_fake_bwrap(tmp_path),
        probe_runner=_successful_probe,
    )
    backend.probe(_linux_environment())

    with pytest.raises(SandboxUnavailableError, match=message):
        asyncio.run(backend.open_scope(request_factory(tmp_path)))


def test_linux_bubblewrap_enforces_roots_when_host_supports_namespaces(
    tmp_path: Path,
) -> None:
    backend = LinuxBubblewrapBackend()
    status = backend.probe(LocalHostEnvironmentProbe().detect())
    if status.state != "available":
        pytest.skip(status.reason or "bubblewrap is unavailable")

    writable = tmp_path / "writable"
    writable.mkdir()
    readonly = tmp_path / "readonly"
    readonly.mkdir()
    allowed = readonly / "allowed.txt"
    allowed.write_text("visible", encoding="utf-8")
    denied = readonly / "denied.txt"
    denied.write_text("hidden", encoding="utf-8")

    script = """
import pathlib
import subprocess

root = pathlib.Path.cwd()
print((root / "readonly" / "allowed.txt").read_text())
try:
    (root / "readonly" / "denied.txt").read_text()
except OSError:
    print("denied-read")
(root / "writable" / "created.txt").write_text("created")
try:
    (root / "readonly" / "blocked.txt").write_text("blocked")
except OSError:
    print("denied-write")
child = subprocess.run(
    ["/usr/bin/python3", "-c", "import pathlib; "
     "pathlib.Path('writable/child.txt').write_text('child')"],
    check=False,
)
print(f"child={child.returncode}")
"""

    async def scenario() -> ExecResult:
        scope = await backend.open_scope(
            SandboxScopeRequest(
                cwd=tmp_path,
                readable_roots=(tmp_path,),
                writable_roots=(writable,),
                denied_roots=(denied,),
                network="denied",
            )
        )
        try:
            return await scope(
                materialize_exec_request(
                    ExecRequest(
                        command=("/usr/bin/python3", "-c", script),
                        cwd=str(tmp_path),
                        timeout_seconds=10,
                    )
                )
            )
        finally:
            await scope.close()
            await backend.close()

    result = asyncio.run(scenario())

    assert result.exit_code == 0, result.stderr
    assert result.stdout.splitlines() == [
        "visible",
        "denied-read",
        "denied-write",
        "child=0",
    ]
    assert (writable / "created.txt").read_text(encoding="utf-8") == "created"
    assert (writable / "child.txt").read_text(encoding="utf-8") == "child"
    assert not (readonly / "blocked.txt").exists()


def _argument_window(
    command: tuple[str, ...],
    option: str,
    source: str,
    target: str | None = None,
) -> tuple[str, str, str]:
    for index in range(len(command) - 2):
        window = command[index : index + 3]
        if window[:2] == (option, source) and (target is None or window[2] == target):
            return window
    raise AssertionError(f"missing command window: {option} {source}")
