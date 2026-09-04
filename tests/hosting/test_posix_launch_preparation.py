from __future__ import annotations

import asyncio
import hashlib
import os
import platform
import shutil
import signal
import stat
import subprocess
import sys
import textwrap
from collections.abc import Awaitable, Callable
from contextlib import suppress
from functools import wraps
from pathlib import Path
from typing import ParamSpec

import pytest

from loushang.hosting import (
    ChildSessionRequest,
    HostingError,
    HostingFailureCategory,
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
    ProcessStreamSpec,
)
from loushang.hosting._child_session_host import _ChildSessionHost
from loushang.hosting._endpoint_host import _InheritedEndpointHost
from loushang.hosting._launch_preparation import (
    _LaunchCapturePort,
    _ManagedLaunchPreparationPort,
    _ManagedLaunchPreparationResult,
    _ManagedSpawnEffect,
    _ManagedSpawnNotCreated,
    _ManagedSpawnSettledWithoutProcess,
)
from loushang.hosting._posix_endpoint import _PosixEndpointBackend
from loushang.hosting._posix_launch_preparation import (
    _PosixStaticContainedLaunchCaptureSpec,
    _PosixStaticLaunchCaptureBackend,
    _PosixStaticLaunchCaptureSpec,
)
from loushang.hosting._posix_process import _PosixProcessBackend
from loushang.hosting._process_host import _ProcessHost, _ProcessHostLimits

pytestmark = pytest.mark.skipif(
    os.name != "posix"
    or not sys.platform.startswith("linux")
    or platform.machine().lower() not in {"amd64", "x86_64"},
    reason="Linux x86_64 sealed-memfd launch preparation",
)
_P = ParamSpec("_P")


def _async_test(
    function: Callable[_P, Awaitable[None]],
) -> Callable[_P, None]:
    @wraps(function)
    def run(*args: _P.args, **kwargs: _P.kwargs) -> None:
        asyncio.run(function(*args, **kwargs))

    return run


class _SemanticLease:
    def __init__(self, request: ProcessLaunchRequest) -> None:
        self.request = request
        self.verify_calls = 0
        self.close_calls = 0

    async def verify_current(self) -> None:
        self.verify_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


class _StaticPreparationPort(_ManagedLaunchPreparationPort):
    def __init__(
        self,
        spec: _PosixStaticLaunchCaptureSpec
        | _PosixStaticContainedLaunchCaptureSpec,
        *,
        pause_after_capture: bool = False,
    ) -> None:
        self.spec = spec
        self.lease = _SemanticLease(spec.request)
        self.captured = asyncio.Event()
        self.release = asyncio.Event()
        if not pause_after_capture:
            self.release.set()

    async def prepare(self, request: ProcessLaunchRequest) -> _SemanticLease:
        raise AssertionError("POSIX static preparation requires managed capture")

    async def prepare_managed(
        self,
        request: ProcessLaunchRequest,
        capture: _LaunchCapturePort,
    ) -> _ManagedLaunchPreparationResult:
        returned = False
        try:
            assert request == self.spec.request
            binding = await capture.capture(self.spec)
            self.captured.set()
            await self.release.wait()
            result = _ManagedLaunchPreparationResult(self.lease, binding)
            returned = True
            return result
        finally:
            if not returned:
                await self.lease.close()


def _native_host(
    process_backend: _PosixProcessBackend | None = None,
    capture_backend: _PosixStaticLaunchCaptureBackend | None = None,
) -> _ChildSessionHost:
    process_backend = process_backend or _PosixProcessBackend()
    return _ChildSessionHost(
        _ProcessHost(
            process_backend,
            limits=_ProcessHostLimits(
                max_processes=1,
                termination_grace_seconds=0.05,
            ),
        ),
        _InheritedEndpointHost(_PosixEndpointBackend(), max_endpoints=1),
        max_sessions=1,
        launch_capture_backend=capture_backend
        or _PosixStaticLaunchCaptureBackend(),
        max_capture_slots=3,
    )


def _compile_static_fixture(path: Path, *, marker: str) -> None:
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.fail("H6.2 native gate requires a C compiler")
    source = path.with_suffix(".c")
    source.write_text(
        """
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
int main(int argc, char **argv) {
    char release;
    if (argc == 2) {
        if (strcmp(argv[1], "--print-argv0") == 0) {
            printf("%s\\n", argv[0]);
            if (fflush(stdout) != 0) return 73;
            return read(STDIN_FILENO, &release, 1) == 1 ? 0 : 74;
        }
        printf("%s\\n", fcntl(atoi(argv[1]), F_GETFD) == -1 ? "closed" : "open");
        if (fflush(stdout) != 0) return 72;
        return read(STDIN_FILENO, &release, 1) == 1 ? 0 : 74;
    }
    struct stat cwd;
    if (stat(".", &cwd) != 0) return 70;
    printf("%s:%llu\\n", MARKER, (unsigned long long)cwd.st_ino);
    if (fflush(stdout) != 0) return 71;
    return read(STDIN_FILENO, &release, 1) == 1 ? 0 : 74;
}
""".replace("MARKER", f'"{marker}"'),
        encoding="utf-8",
    )
    completed = subprocess.run(
        (compiler, "-static", "-O2", "-s", "-o", str(path), str(source)),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(f"H6.2 static fixture compilation failed: {completed.stderr}")


def _compile_containment_launcher(
    path: Path,
    *,
    profile_sha256: str,
) -> None:
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.fail("H6.2 native gate requires a C compiler")
    source = path.with_suffix(".c")
    source.write_text(
        r'''
#include <errno.h>
#include <fcntl.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <asm/unistd.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>

static int close_on_exec(int fd) {
    int flags = fcntl(fd, F_GETFD);
    return flags < 0 ? -1 : fcntl(fd, F_SETFD, flags | FD_CLOEXEC);
}

static int install_profile(void) {
    struct sock_filter filter[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS,
                 offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_X86_64, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS,
                 offsetof(struct seccomp_data, nr)),
        BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, __X32_SYSCALL_BIT, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_socket, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_setsid, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_setpgid, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
    struct sock_fprog program = {
        .len = (unsigned short)(sizeof(filter) / sizeof(filter[0])),
        .filter = filter,
    };
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0) return -1;
    return prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &program);
}

int main(int argc, char **argv) {
    if (argc < 11) return 80;
    if (strcmp(argv[1], "--loushang-protocol") != 0 ||
        strcmp(argv[2], "loushang-static-containment-launch/v1") != 0 ||
        strcmp(argv[3], "--loushang-profile-sha256") != 0 ||
        strcmp(argv[5], "--loushang-payload-fd") != 0 ||
        strcmp(argv[7], "--loushang-preparation-fds") != 0 ||
        strcmp(argv[9], "--") != 0) return 81;
    if (strcmp(argv[4], PROFILE_SHA256) != 0) {
        char release;
        printf("profile-rejected\n");
        if (fflush(stdout) != 0) return 88;
        return read(STDIN_FILENO, &release, 1) == 1 ? 87 : 89;
    }
    int payload = atoi(argv[6]);
    int launcher = -1, listed_payload = -1, cwd = -1;
    if (sscanf(argv[8], "%d,%d,%d", &launcher, &listed_payload, &cwd) != 3 ||
        payload < 0 || payload != listed_payload) return 82;
    if (close_on_exec(launcher) != 0 || close_on_exec(payload) != 0 ||
        close_on_exec(cwd) != 0) return 83;
    if (install_profile() != 0) return 84;
    char executable[64];
    if (snprintf(executable, sizeof(executable), "/proc/self/fd/%d", payload) < 0)
        return 85;
    char *environment[] = {NULL};
    execve(executable, &argv[10], environment);
    return 86;
}
'''.replace("PROFILE_SHA256", f'"{profile_sha256}"'),
        encoding="utf-8",
    )
    completed = subprocess.run(
        (compiler, "-static", "-O2", "-s", "-o", str(path), str(source)),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(
            f"H6.2 containment launcher compilation failed: {completed.stderr}"
        )


def _compile_containment_payload(path: Path, *, marker: str) -> None:
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.fail("H6.2 native gate requires a C compiler")
    source = path.with_suffix(".c")
    source.write_text(
        r'''
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>
int main(int argc, char **argv) {
    if (prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) != 1) return 90;
    errno = 0;
    int descriptor = socket(AF_INET, SOCK_STREAM, 0);
    if (descriptor >= 0 || errno != EPERM) return 91;
    if (argc == 2 && strcmp(argv[1], "--attempt-group-escape") == 0) {
        pid_t child = fork();
        if (child < 0) return 94;
        if (child == 0) {
            int blocked = 1;
            errno = 0;
            if (setsid() != -1 || errno != EPERM) blocked = 0;
            errno = 0;
            if (setpgid(0, 0) != -1 || errno != EPERM) blocked = 0;
            printf("%s:%d\n", blocked ? "escape-blocked" : "escape-open", getpid());
            fflush(stdout);
            if (!blocked) return 95;
            for (;;) pause();
        }
        for (;;) pause();
    }
    struct stat cwd;
    if (stat(".", &cwd) != 0) return 92;
    printf("%s:contained:%llu\n", MARKER, (unsigned long long)cwd.st_ino);
    if (fflush(stdout) != 0) return 93;
    char release;
    return read(STDIN_FILENO, &release, 1) == 1 ? 0 : 96;
}
'''.replace("MARKER", f'"{marker}"'),
        encoding="utf-8",
    )
    completed = subprocess.run(
        (compiler, "-static", "-O2", "-s", "-o", str(path), str(source)),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(f"H6.2 containment payload compilation failed: {completed.stderr}")


def _compile_immediate_exit_fixture(path: Path, *, return_code: int) -> None:
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.fail("H6.2 native gate requires a C compiler")
    source = path.with_suffix(".c")
    source.write_text(
        f"int main(void) {{ return {return_code}; }}\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        (compiler, "-static", "-O2", "-s", "-o", str(path), str(source)),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(f"H6.2 early-exit fixture compilation failed: {completed.stderr}")


def _compile_pausing_fixture(path: Path) -> None:
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.fail("H6.2 native gate requires a C compiler")
    source = path.with_suffix(".c")
    source.write_text(
        "#include <unistd.h>\nint main(void) { for (;;) pause(); }\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        (compiler, "-static", "-O2", "-s", "-o", str(path), str(source)),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(f"H6.2 pausing fixture compilation failed: {completed.stderr}")


def _spec(
    executable: Path,
    cwd: Path,
    *arguments: str,
) -> _PosixStaticLaunchCaptureSpec:
    executable = executable.absolute()
    cwd = cwd.absolute()
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    cwd_stat = cwd.stat()
    request = ProcessLaunchRequest(
        argv=(str(executable), *arguments),
        cwd=str(cwd),
        effective_environment=(),
        streams=ProcessStreamSpec(
            stdin=ProcessStdinMode.CLOSED,
            stdout=ProcessStdoutMode.DISCARD,
            stderr=ProcessStderrMode.CAPTURE_TAIL,
        ),
    )
    return _PosixStaticLaunchCaptureSpec(
        request=request,
        profile_id="posix-static-elf-v1",
        execution_closure=(
            f"static-elf:sha256:{digest}",
            f"cwd:posix:{cwd_stat.st_dev}:{cwd_stat.st_ino}",
            "platform:linux-x86_64-syscall-abi",
        ),
        executable_sha256=digest,
        cwd_device=cwd_stat.st_dev,
        cwd_inode=cwd_stat.st_ino,
    )


def _contained_spec(
    launcher: Path,
    executable: Path,
    cwd: Path,
    *arguments: str,
    profile_sha256: str,
) -> _PosixStaticContainedLaunchCaptureSpec:
    launcher = launcher.absolute()
    executable = executable.absolute()
    cwd = cwd.absolute()
    launcher_digest = hashlib.sha256(launcher.read_bytes()).hexdigest()
    executable_digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    cwd_stat = cwd.stat()
    request = ProcessLaunchRequest(
        argv=(str(executable), *arguments),
        cwd=str(cwd),
        effective_environment=(),
        streams=ProcessStreamSpec(
            stdin=ProcessStdinMode.CLOSED,
            stdout=ProcessStdoutMode.DISCARD,
            stderr=ProcessStderrMode.CAPTURE_TAIL,
        ),
    )
    return _PosixStaticContainedLaunchCaptureSpec(
        request=request,
        profile_id="posix-static-contained-elf-v1",
        execution_closure=(
            f"containment-launcher-static-elf:sha256:{launcher_digest}",
            f"payload-static-elf:sha256:{executable_digest}",
            f"cwd:posix:{cwd_stat.st_dev}:{cwd_stat.st_ino}",
            f"containment-profile:sha256:{profile_sha256}",
            "invocation:loushang-static-containment-launch/v1",
            "platform:linux-x86_64-syscall-abi",
        ),
        launcher_path=str(launcher),
        launcher_sha256=launcher_digest,
        executable_sha256=executable_digest,
        cwd_device=cwd_stat.st_dev,
        cwd_inode=cwd_stat.st_ino,
        containment_profile_sha256=profile_sha256,
    )


async def _read_line(read: Callable[[int], Awaitable[bytes]]) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while size < 4096:
        chunk = await read(min(1024, 4096 - size))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        size += len(chunk)
        if b"\n" in chunk:
            return b"".join(chunks)
    raise AssertionError("native fixture line exceeded its bound")


def _linux_process_identity(pid: int) -> tuple[int, str] | None:
    try:
        body = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    fields = body[body.rfind(")") + 2 :].split()
    return int(fields[19]), fields[0]


@_async_test
async def test_posix_static_profile_pins_executable_and_cwd_across_replacement(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "admitted"
    _compile_static_fixture(executable, marker="admitted")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    spec = _spec(executable, cwd)
    preparation = _StaticPreparationPort(spec, pause_after_capture=True)
    host = _native_host()
    start = asyncio.create_task(
        host.start(ChildSessionRequest(spec.request), preparation)
    )
    await preparation.captured.wait()

    moved_executable = tmp_path / "captured-executable"
    executable.rename(moved_executable)
    _compile_static_fixture(executable, marker="substituted")
    pinned_cwd = tmp_path / "captured-cwd"
    cwd.rename(pinned_cwd)
    cwd.mkdir()
    preparation.release.set()

    lease = await start
    output = await _read_line(lease.endpoint.read)
    await lease.endpoint.write(b"x")
    result = await lease.process.wait()
    await lease.close()
    await host.close()

    assert result.return_code == 0
    assert output == f"admitted:{spec.cwd_inode}\n".encode()
    assert preparation.lease.verify_calls == 1
    assert preparation.lease.close_calls == 1


@_async_test
async def test_posix_static_profile_preserves_original_argv_zero(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "admitted"
    _compile_static_fixture(executable, marker="admitted")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    spec = _spec(executable, cwd, "--print-argv0")
    host = _native_host()

    lease = await host.start(
        ChildSessionRequest(spec.request),
        _StaticPreparationPort(spec),
    )
    assert await _read_line(lease.endpoint.read) == f"{executable}\n".encode()
    await lease.endpoint.write(b"x")
    assert (await lease.process.wait()).return_code == 0
    await lease.close()
    await host.close()


@_async_test
async def test_posix_contained_profile_pins_launcher_payload_and_applies_profile(
    tmp_path: Path,
) -> None:
    profile_sha256 = hashlib.sha256(b"deny-network-and-no-new-privileges").hexdigest()
    launcher = tmp_path / "launcher"
    executable = tmp_path / "payload"
    _compile_containment_launcher(launcher, profile_sha256=profile_sha256)
    _compile_containment_payload(executable, marker="admitted")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    spec = _contained_spec(
        launcher,
        executable,
        cwd,
        profile_sha256=profile_sha256,
    )
    preparation = _StaticPreparationPort(spec, pause_after_capture=True)
    host = _native_host()
    start = asyncio.create_task(
        host.start(ChildSessionRequest(spec.request), preparation)
    )
    await preparation.captured.wait()

    launcher.rename(tmp_path / "captured-launcher")
    executable.rename(tmp_path / "captured-payload")
    _compile_static_fixture(launcher, marker="substituted-launcher")
    _compile_containment_payload(executable, marker="substituted-payload")
    pinned_cwd = tmp_path / "captured-cwd"
    cwd.rename(pinned_cwd)
    cwd.mkdir()
    preparation.release.set()

    lease = await start
    output = await _read_line(lease.endpoint.read)
    await lease.endpoint.write(b"x")
    result = await lease.process.wait()
    await lease.close()
    await host.close()

    assert result.return_code == 0
    assert output == f"admitted:contained:{spec.cwd_inode}\n".encode()
    assert preparation.lease.verify_calls == 1
    assert preparation.lease.close_calls == 1


@_async_test
async def test_posix_contained_profile_blocks_descendant_group_escape(
    tmp_path: Path,
) -> None:
    profile_sha256 = hashlib.sha256(
        b"deny-network-and-process-group-escape"
    ).hexdigest()
    launcher = tmp_path / "launcher"
    executable = tmp_path / "payload"
    _compile_containment_launcher(launcher, profile_sha256=profile_sha256)
    _compile_containment_payload(executable, marker="admitted")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    spec = _contained_spec(
        launcher,
        executable,
        cwd,
        "--attempt-group-escape",
        profile_sha256=profile_sha256,
    )
    host = _native_host()

    lease = await host.start(
        ChildSessionRequest(spec.request),
        _StaticPreparationPort(spec),
    )
    output = await _read_line(lease.endpoint.read)
    marker, raw_pid = output.decode().strip().split(":", maxsplit=1)
    descendant_pid = int(raw_pid)
    assert marker == "escape-blocked"
    assert descendant_pid > 0
    descendant_identity = _linux_process_identity(descendant_pid)
    assert descendant_identity is not None

    await lease.close()
    await host.close()
    deadline = asyncio.get_running_loop().time() + 2.0
    while True:
        current = _linux_process_identity(descendant_pid)
        if (
            current is None
            or current[0] != descendant_identity[0]
            or current[1] == "Z"
        ):
            break
        if asyncio.get_running_loop().time() >= deadline:
            pytest.fail("contained descendant remained live after session close")
        await asyncio.sleep(0.01)


def test_posix_contained_profile_rejects_unproved_launcher_chain(
    tmp_path: Path,
) -> None:
    profile_sha256 = hashlib.sha256(b"required-profile").hexdigest()
    executable = tmp_path / "payload"
    _compile_containment_payload(executable, marker="payload")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    dynamic_launcher = Path(sys.executable).resolve()
    spec = _contained_spec(
        dynamic_launcher,
        executable,
        cwd,
        profile_sha256=profile_sha256,
    )
    backend = _PosixStaticLaunchCaptureBackend()

    async def capture() -> None:
        with pytest.raises(HostingError) as failure:
            await backend.capture(
                spec,
                attempt_id="dynamic-launcher-attempt",
                attempt_token=object(),
                on_capture=lambda material: None,
            )
        assert failure.value.category is HostingFailureCategory.PREPARATION_FAILED

    asyncio.run(capture())


@_async_test
async def test_posix_contained_launcher_rejects_profile_substitution_before_payload(
    tmp_path: Path,
) -> None:
    admitted_profile = hashlib.sha256(b"admitted-profile").hexdigest()
    substituted_profile = hashlib.sha256(b"substituted-profile").hexdigest()
    launcher = tmp_path / "launcher"
    executable = tmp_path / "payload"
    _compile_containment_launcher(launcher, profile_sha256=admitted_profile)
    _compile_containment_payload(executable, marker="must-not-run")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    spec = _contained_spec(
        launcher,
        executable,
        cwd,
        profile_sha256=substituted_profile,
    )
    host = _native_host()

    lease = await host.start(
        ChildSessionRequest(spec.request),
        _StaticPreparationPort(spec),
    )
    assert await _read_line(lease.endpoint.read) == b"profile-rejected\n"
    await lease.endpoint.write(b"x")
    assert (await lease.process.wait()).return_code == 87
    await lease.close()
    await host.close()


@_async_test
async def test_posix_static_profile_rejects_dynamic_loader_closure(
    tmp_path: Path,
) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    executable = Path(sys.executable).resolve()
    spec = _spec(executable, cwd)
    preparation = _StaticPreparationPort(spec)
    host = _native_host()

    with pytest.raises(HostingError) as failure:
        await host.start(ChildSessionRequest(spec.request), preparation)

    assert failure.value.category is HostingFailureCategory.PREPARATION_FAILED
    assert preparation.lease.close_calls == 1
    await host.close()


def test_posix_static_profile_classifies_truncated_elf_header(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "truncated"
    executable.write_bytes(b"\x7fELF\x02\x01" + b"\0" * 49)
    executable.chmod(0o755)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    spec = _spec(executable, cwd)
    backend = _PosixStaticLaunchCaptureBackend()

    async def capture() -> None:
        with pytest.raises(HostingError) as failure:
            await backend.capture(
                spec,
                attempt_id="truncated-elf-attempt",
                attempt_token=object(),
                on_capture=lambda material: None,
            )
        assert failure.value.category is HostingFailureCategory.PREPARATION_FAILED

    asyncio.run(capture())


def test_posix_static_profile_rejects_symlinked_executable(tmp_path: Path) -> None:
    executable = tmp_path / "admitted"
    _compile_static_fixture(executable, marker="admitted")
    symlink = tmp_path / "linked"
    symlink.symlink_to(executable)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    spec = _spec(executable, cwd)
    linked_request = ProcessLaunchRequest(
        argv=(str(symlink),),
        cwd=spec.request.cwd,
        effective_environment=(),
        streams=spec.request.streams,
    )
    linked_spec = _PosixStaticLaunchCaptureSpec(
        request=linked_request,
        profile_id=spec.profile_id,
        execution_closure=spec.execution_closure,
        executable_sha256=spec.executable_sha256,
        cwd_device=spec.cwd_device,
        cwd_inode=spec.cwd_inode,
    )
    backend = _PosixStaticLaunchCaptureBackend()

    async def capture() -> None:
        with pytest.raises(OSError) as failure:
            await backend.capture(
                linked_spec,
                attempt_id="symlink-attempt",
                attempt_token=object(),
                on_capture=lambda material: None,
            )
        assert failure.value.errno is not None

    asyncio.run(capture())


def test_posix_static_profile_requires_empty_environment_and_exact_closure(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "admitted"
    _compile_static_fixture(executable, marker="admitted")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    spec = _spec(executable, cwd)
    with pytest.raises(ValueError, match="empty environment"):
        _PosixStaticLaunchCaptureSpec(
            request=ProcessLaunchRequest(
                argv=spec.request.argv,
                cwd=spec.request.cwd,
                effective_environment=(("PATH", "/tmp"),),
                streams=spec.request.streams,
            ),
            profile_id=spec.profile_id,
            execution_closure=spec.execution_closure,
            executable_sha256=spec.executable_sha256,
            cwd_device=spec.cwd_device,
            cwd_inode=spec.cwd_inode,
        )
    with pytest.raises(ValueError, match="execution closure"):
        _PosixStaticLaunchCaptureSpec(
            request=spec.request,
            profile_id=spec.profile_id,
            execution_closure=("not-the-admitted-closure",),
            executable_sha256=spec.executable_sha256,
            cwd_device=spec.cwd_device,
            cwd_inode=spec.cwd_inode,
        )


def test_posix_static_capture_leaves_descriptors_non_inheritable_until_spawn(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "admitted"
    _compile_static_fixture(executable, marker="admitted")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    spec = _spec(executable, cwd)
    backend = _PosixStaticLaunchCaptureBackend()
    captured = []

    async def capture() -> None:
        material = await backend.capture(
            spec,
            attempt_id="inheritability-attempt",
            attempt_token=object(),
            on_capture=captured.append,
        )
        assert material is captured[0]
        assert os.get_inheritable(material._executable_descriptor) is False
        assert os.get_inheritable(material._cwd_descriptor) is False
        assert stat.S_IMODE(os.fstat(material._executable_descriptor).st_mode) == 0o500
        await material.close()

    asyncio.run(capture())


def test_posix_static_capture_normalizes_closed_stdio_descriptor_numbers(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "admitted"
    _compile_static_fixture(executable, marker="admitted")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    code = textwrap.dedent(
        """
        import asyncio
        import hashlib
        import os
        import sys
        from loushang.hosting import (
            ProcessLaunchRequest,
            ProcessStderrMode,
            ProcessStdinMode,
            ProcessStdoutMode,
            ProcessStreamSpec,
        )
        from loushang.hosting._posix_launch_preparation import (
            _PosixStaticLaunchCaptureBackend,
            _PosixStaticLaunchCaptureSpec,
        )

        executable, cwd = sys.argv[1:]
        digest = hashlib.sha256(open(executable, "rb").read()).hexdigest()
        cwd_stat = os.stat(cwd)
        request = ProcessLaunchRequest(
            argv=(executable,),
            cwd=cwd,
            effective_environment=(),
            streams=ProcessStreamSpec(
                stdin=ProcessStdinMode.CLOSED,
                stdout=ProcessStdoutMode.DISCARD,
                stderr=ProcessStderrMode.CAPTURE_TAIL,
            ),
        )
        spec = _PosixStaticLaunchCaptureSpec(
            request=request,
            profile_id="posix-static-elf-v1",
            execution_closure=(
                f"static-elf:sha256:{digest}",
                f"cwd:posix:{cwd_stat.st_dev}:{cwd_stat.st_ino}",
                "platform:linux-x86_64-syscall-abi",
            ),
            executable_sha256=digest,
            cwd_device=cwd_stat.st_dev,
            cwd_inode=cwd_stat.st_ino,
        )

        async def main():
            material = await _PosixStaticLaunchCaptureBackend().capture(
                spec,
                attempt_id="low-fd-attempt",
                attempt_token=object(),
                on_capture=lambda material: None,
            )
            if min(material._executable_descriptor, material._cwd_descriptor) < 3:
                os._exit(97)
            await material.close()

        asyncio.run(main())
        """
    )

    def close_stdin_and_stdout() -> None:
        for descriptor in (0, 1):
            with suppress(OSError):
                os.close(descriptor)

    completed = subprocess.run(
        (sys.executable, "-c", code, str(executable), str(cwd)),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=close_stdin_and_stdout,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_posix_low_descriptor_duplication_failure_closes_original(
    tmp_path: Path,
) -> None:
    sentinel = tmp_path / "low-descriptor-sentinel"
    sentinel.write_bytes(b"sentinel")
    code = textwrap.dedent(
        """
        import os
        import sys
        import loushang.hosting._posix_launch_preparation as preparation

        os.close(0)
        descriptor = os.open(sys.argv[1], os.O_RDONLY)
        if descriptor != 0:
            raise SystemExit(90)

        def fail_duplicate(*args):
            raise OSError("injected descriptor duplication failure")

        preparation.fcntl.fcntl = fail_duplicate
        try:
            preparation._ensure_preparation_descriptor(descriptor)
        except OSError as error:
            if "injected descriptor duplication failure" not in str(error):
                raise SystemExit(91)
        else:
            raise SystemExit(92)
        try:
            os.fstat(descriptor)
        except OSError:
            raise SystemExit(0)
        raise SystemExit(93)
        """
    )
    completed = subprocess.run(
        (sys.executable, "-c", code, str(sentinel)),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


@_async_test
async def test_posix_static_spawn_closes_unlisted_inheritable_descriptor(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "admitted"
    _compile_static_fixture(executable, marker="admitted")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    sentinel = os.open(tmp_path / "sentinel", os.O_CREAT | os.O_RDWR, 0o600)
    os.set_inheritable(sentinel, True)
    spec = _spec(executable, cwd, str(sentinel))
    host = _native_host()
    try:
        lease = await host.start(
            ChildSessionRequest(spec.request),
            _StaticPreparationPort(spec),
        )
        output = await _read_line(lease.endpoint.read)
        await lease.endpoint.write(b"x")
        result = await lease.process.wait()
        await lease.close()
        assert result.return_code == 0
        assert output == b"closed\n"
    finally:
        await host.close()
        os.close(sentinel)


def test_posix_static_capture_rejects_digest_and_cwd_identity_mismatch(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "admitted"
    _compile_static_fixture(executable, marker="admitted")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    original = _spec(executable, cwd)
    backend = _PosixStaticLaunchCaptureBackend()

    async def capture(
        spec: _PosixStaticLaunchCaptureSpec,
        expected: HostingFailureCategory,
    ) -> None:
        with pytest.raises(HostingError) as failure:
            await backend.capture(
                spec,
                attempt_id="mismatch-attempt",
                attempt_token=object(),
                on_capture=lambda material: None,
            )
        assert failure.value.category is expected

    wrong_digest = "0" * 64
    asyncio.run(
        capture(
            _PosixStaticLaunchCaptureSpec(
                request=original.request,
                profile_id=original.profile_id,
                execution_closure=(
                    f"static-elf:sha256:{wrong_digest}",
                    f"cwd:posix:{original.cwd_device}:{original.cwd_inode}",
                    "platform:linux-x86_64-syscall-abi",
                ),
                executable_sha256=wrong_digest,
                cwd_device=original.cwd_device,
                cwd_inode=original.cwd_inode,
            ),
            HostingFailureCategory.PREPARATION_FAILED,
        )
    )
    asyncio.run(
        capture(
            _PosixStaticLaunchCaptureSpec(
                request=original.request,
                profile_id=original.profile_id,
                execution_closure=(
                    f"static-elf:sha256:{original.executable_sha256}",
                    f"cwd:posix:{original.cwd_device}:{original.cwd_inode + 1}",
                    "platform:linux-x86_64-syscall-abi",
                ),
                executable_sha256=original.executable_sha256,
                cwd_device=original.cwd_device,
                cwd_inode=original.cwd_inode + 1,
            ),
            HostingFailureCategory.PREPARATION_STALE,
        )
    )


def test_posix_static_memfd_failure_closes_open_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "admitted"
    _compile_static_fixture(executable, marker="admitted")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    spec = _spec(executable, cwd)
    source_descriptor = -1
    original_open = os.open

    def observe_open(path: str, flags: int, mode: int = 0o777) -> int:
        nonlocal source_descriptor
        descriptor = original_open(path, flags, mode)
        if path == str(executable):
            source_descriptor = descriptor
        return descriptor

    def fail_memfd() -> int:
        raise OSError("injected memfd failure")

    monkeypatch.setattr(
        "loushang.hosting._posix_launch_preparation.os.open", observe_open
    )
    monkeypatch.setattr(
        "loushang.hosting._posix_launch_preparation._create_memfd", fail_memfd
    )
    backend = _PosixStaticLaunchCaptureBackend()

    async def capture() -> None:
        with pytest.raises(OSError, match="injected memfd failure"):
            await backend.capture(
                spec,
                attempt_id="memfd-failure-attempt",
                attempt_token=object(),
                on_capture=lambda material: None,
            )

    asyncio.run(capture())
    assert source_descriptor >= 0
    with pytest.raises(OSError):
        os.fstat(source_descriptor)


def test_posix_static_native_descriptor_collision_fails_before_effect(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "admitted"
    _compile_static_fixture(executable, marker="admitted")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    spec = _spec(executable, cwd)
    capture_backend = _PosixStaticLaunchCaptureBackend()
    process_backend = _PosixProcessBackend()
    captured = []

    class _CollidingInheritance:
        backend_id = process_backend.backend_id

        def claim(self, *, backend_id: str) -> tuple[int, ...]:
            assert backend_id == self.backend_id
            return (
                captured[0]._executable_descriptor,
                captured[0]._executable_descriptor,
            )

        def mark_transferred(self) -> None:
            raise AssertionError("collision must fail before transfer")

        async def close(self) -> None:
            return

    async def exercise() -> None:
        material = await capture_backend.capture(
            spec,
            attempt_id="collision-attempt",
            attempt_token=object(),
            on_capture=captured.append,
        )
        await material.verify_current(spec.request)
        effect = _ManagedSpawnEffect()
        with pytest.raises(_ManagedSpawnNotCreated) as failure:
            await process_backend._spawn_static_prepared(
                material,
                spec.request,
                effect=effect,
                on_spawn=lambda process: None,
                inheritance=_CollidingInheritance(),
            )
        assert isinstance(failure.value.cause, HostingError)
        assert (
            failure.value.cause.category
            is HostingFailureCategory.ENDPOINT_TRANSFER_FAILED
        )
        assert effect.accepts(failure.value)
        await material.close()

    asyncio.run(exercise())


def test_managed_spawn_effect_accepts_only_its_settled_attempt_receipt() -> None:
    effect = _ManagedSpawnEffect()
    effect.begin_effect()
    failure = effect.settled_without_process(OSError("known exec failure"))

    assert isinstance(failure, _ManagedSpawnSettledWithoutProcess)
    assert effect.accepts_settled(failure)

    other = _ManagedSpawnEffect()
    other.begin_effect()
    assert not other.accepts_settled(failure)
    with pytest.raises(RuntimeError, match="cannot settle"):
        effect.settled_without_process(OSError("duplicate settlement"))


@_async_test
async def test_posix_static_post_create_error_stays_fenced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "pausing"
    _compile_pausing_fixture(executable)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    spec = _spec(executable, cwd)
    process_backend = _PosixProcessBackend()
    capture_backend = _PosixStaticLaunchCaptureBackend()
    original_create = asyncio.create_subprocess_exec
    original_capture = capture_backend.capture
    created: list[asyncio.subprocess.Process] = []
    captured = []

    async def create_then_fail(*args: object, **kwargs: object):
        process = await original_create(*args, **kwargs)  # type: ignore[arg-type]
        created.append(process)
        raise OSError("injected post-create transport failure")

    async def observe_capture(*args: object, **kwargs: object):
        material = await original_capture(*args, **kwargs)  # type: ignore[arg-type]
        captured.append(material)
        return material

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_then_fail)
    monkeypatch.setattr(capture_backend, "capture", observe_capture)
    host = _native_host(process_backend, capture_backend)
    failed_preparation = _StaticPreparationPort(spec)

    try:
        with pytest.raises(HostingError) as failure:
            await host.start(ChildSessionRequest(spec.request), failed_preparation)
        assert failure.value.category is HostingFailureCategory.SPAWN_FAILED
        assert len(created) == 1
        os.killpg(created[0].pid, 0)
        assert host._state == "faulted"
        assert host._process_host._state == "faulted"
        assert failed_preparation.lease.close_calls == 0

        with pytest.raises(HostingError) as retry:
            await host.start(
                ChildSessionRequest(spec.request),
                _StaticPreparationPort(spec),
            )
        assert retry.value.category is HostingFailureCategory.HOST_CLOSED
    finally:
        for process in created:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
            transport = getattr(process, "_transport", None)
            close_transport = getattr(transport, "close", None)
            if callable(close_transport):
                close_transport()
        for material in captured:
            await material.close()
        await failed_preparation.lease.close()


def test_posix_static_close_error_never_retries_reused_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "admitted"
    _compile_static_fixture(executable, marker="admitted")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    spec = _spec(executable, cwd)
    backend = _PosixStaticLaunchCaptureBackend()
    captured = []

    async def exercise() -> None:
        material = await backend.capture(
            spec,
            attempt_id="cleanup-attempt",
            attempt_token=object(),
            on_capture=captured.append,
        )
        executable_descriptor = material._executable_descriptor
        cwd_descriptor = material._cwd_descriptor
        original_close = os.close
        failed = False
        reused_descriptor = -1

        def fail_executable_once(descriptor: int) -> None:
            nonlocal failed, reused_descriptor
            if descriptor == executable_descriptor and not failed:
                failed = True
                original_close(descriptor)
                reused_descriptor = os.open(
                    tmp_path / "reused-sentinel",
                    os.O_CREAT | os.O_RDWR,
                    0o600,
                )
                raise OSError("injected descriptor close failure")
            original_close(descriptor)

        monkeypatch.setattr(
            "loushang.hosting._posix_launch_preparation.os.close",
            fail_executable_once,
        )
        with pytest.raises(BaseExceptionGroup):
            await material.close()
        assert reused_descriptor == executable_descriptor
        assert os.fstat(reused_descriptor).st_ino > 0
        with pytest.raises(OSError):
            os.fstat(cwd_descriptor)
        await material.close()
        assert os.fstat(reused_descriptor).st_ino > 0
        original_close(reused_descriptor)

    asyncio.run(exercise())


@_async_test
async def test_posix_static_native_early_exit_rolls_back_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "early-exit"
    _compile_immediate_exit_fixture(executable, return_code=23)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    spec = _spec(executable, cwd)
    process_backend = _PosixProcessBackend()
    original_spawn = process_backend._spawn_once
    observed_return_codes: list[int] = []

    async def observe_exit(*args: object, **kwargs: object):
        process = await original_spawn(*args, **kwargs)  # type: ignore[arg-type]
        observed_return_codes.append(await process.wait())
        return process

    monkeypatch.setattr(process_backend, "_spawn_once", observe_exit)
    preparation = _StaticPreparationPort(spec)
    host = _native_host(process_backend)

    with pytest.raises(HostingError) as failure:
        await host.start(ChildSessionRequest(spec.request), preparation)
    assert failure.value.category is HostingFailureCategory.CHILD_EXITED_EARLY
    assert observed_return_codes == [23]
    assert preparation.lease.close_calls == 1
    await host.close()


@_async_test
async def test_posix_static_cancellation_after_os_create_reclaims_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "admitted"
    _compile_static_fixture(executable, marker="admitted")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    spec = _spec(executable, cwd)
    process_backend = _PosixProcessBackend()
    original_spawn = process_backend._spawn_once
    created = asyncio.Event()
    release = asyncio.Event()
    processes = []

    async def gated_spawn(*args: object, **kwargs: object):
        process = await original_spawn(*args, **kwargs)  # type: ignore[arg-type]
        processes.append(process)
        created.set()
        await release.wait()
        return process

    monkeypatch.setattr(process_backend, "_spawn_once", gated_spawn)
    preparation = _StaticPreparationPort(spec)
    host = _native_host(process_backend)
    start = asyncio.create_task(
        host.start(ChildSessionRequest(spec.request), preparation)
    )
    await created.wait()

    start.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await start
    await host.close()

    assert len(processes) == 1
    assert not processes[0].group_exists()
    assert preparation.lease.close_calls == 1
