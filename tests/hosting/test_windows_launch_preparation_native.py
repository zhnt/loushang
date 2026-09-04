from __future__ import annotations

import asyncio
import hashlib
import os
import platform
import shutil
import subprocess
from collections.abc import Awaitable, Callable
from contextlib import suppress
from functools import wraps
from pathlib import Path
from typing import ParamSpec

import pytest

from loushang.hosting import (
    ChildSessionRequest,
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
)
from loushang.hosting._process_host import _ProcessHost, _ProcessHostLimits
from loushang.hosting._win32_process import _CtypesWin32Api
from loushang.hosting._windows_endpoint import _WindowsEndpointBackend
from loushang.hosting._windows_launch_preparation import (
    _WindowsRestrictedLaunchCaptureBackend,
    _WindowsRestrictedLaunchCaptureSpec,
)
from loushang.hosting._windows_process import _WindowsProcessBackend

pytestmark = pytest.mark.skipif(
    os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"},
    reason="Windows AMD64 restricted-token launch preparation",
)
_P = ParamSpec("_P")
_NATIVE_TEST_TIMEOUT_SECONDS = 45.0


def _async_test(
    function: Callable[_P, Awaitable[None]],
) -> Callable[_P, None]:
    @wraps(function)
    def run(*args: _P.args, **kwargs: _P.kwargs) -> None:
        async def bounded() -> None:
            async with asyncio.timeout(_NATIVE_TEST_TIMEOUT_SECONDS):
                await function(*args, **kwargs)

        asyncio.run(bounded())

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


class _RestrictedPreparation(_ManagedLaunchPreparationPort):
    def __init__(
        self,
        spec: _WindowsRestrictedLaunchCaptureSpec,
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
        raise AssertionError("Windows restricted preparation requires managed capture")

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


class _ObservedWin32Api(_CtypesWin32Api):
    def __init__(self) -> None:
        super().__init__()
        self.created_jobs: list[int] = []
        self.job_empty_observations: list[bool] = []

    def create_managed_job(
        self,
        *,
        on_acquired: Callable[[int], None],
    ) -> int:
        def observe(handle: int) -> None:
            self.created_jobs.append(handle)
            on_acquired(handle)

        return super().create_managed_job(on_acquired=observe)

    def job_is_empty(self, handle: int) -> bool:
        empty = super().job_is_empty(handle)
        self.job_empty_observations.append(empty)
        return empty


def _native_host(api: _CtypesWin32Api) -> _ChildSessionHost:
    return _ChildSessionHost(
        _ProcessHost(
            _WindowsProcessBackend(max_processes=1, api=api),
            limits=_ProcessHostLimits(
                max_processes=1,
                termination_grace_seconds=0.1,
            ),
        ),
        _InheritedEndpointHost(
            _WindowsEndpointBackend(max_endpoints=1, api=api),
            max_endpoints=1,
        ),
        max_sessions=1,
        launch_capture_backend=_WindowsRestrictedLaunchCaptureBackend(api=api),
        max_capture_slots=64,
    )


def _spec(
    api: _CtypesWin32Api,
    executable: Path,
    cwd: Path,
    *arguments: str,
) -> _WindowsRestrictedLaunchCaptureSpec:
    executable_handles: list[int] = []
    api.open_locked_file(
        str(executable.resolve()),
        on_acquired=executable_handles.append,
    )
    executable_handle = executable_handles[0]
    try:
        executable_identity = api.locked_path_identity(executable_handle)
    finally:
        api.close_handle(executable_handle)
    cwd_handles: list[int] = []
    api.open_locked_directory(
        str(cwd.resolve()),
        on_acquired=cwd_handles.append,
    )
    cwd_handle = cwd_handles[0]
    try:
        cwd_identity = api.locked_path_identity(cwd_handle)
    finally:
        api.close_handle(cwd_handle)
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    request = ProcessLaunchRequest(
        argv=(str(executable.resolve()), *arguments),
        cwd=str(cwd.resolve()),
        effective_environment=(("SystemRoot", os.environ["SystemRoot"]),),
        streams=ProcessStreamSpec(
            stdin=ProcessStdinMode.CLOSED,
            stdout=ProcessStdoutMode.DISCARD,
            stderr=ProcessStderrMode.DISCARD,
        ),
    )
    platform_identity = api.platform_identity()
    imports = ("ADVAPI32.DLL", "KERNEL32.DLL")
    return _WindowsRestrictedLaunchCaptureSpec(
        request=request,
        profile_id="windows-restricted-direct-import-pe-v1",
        execution_closure=(
            f"pe-amd64:sha256:{digest}",
            "executable:win32:"
            f"{executable_identity.volume_serial}:{executable_identity.file_id}",
            f"cwd:win32:{cwd_identity.volume_serial}:{cwd_identity.file_id}",
            "restricted-token:disable-max-privilege-v1",
            f'environment:SystemRoot={os.environ["SystemRoot"]}',
            f"direct-imports:{','.join(imports)}",
            f"platform:{platform_identity}",
        ),
        executable_sha256=digest,
        executable_volume_serial=executable_identity.volume_serial,
        executable_file_id=executable_identity.file_id,
        cwd_volume_serial=cwd_identity.volume_serial,
        cwd_file_id=cwd_identity.file_id,
        platform_identity=platform_identity,
        platform_imports=imports,
    )


def _compile_fixture(path: Path) -> None:
    compiler = shutil.which("cl")
    escaped_path = str(path.resolve()).replace("\\", "\\\\").replace('"', '\\"')
    source = path.with_suffix(".c")
    source.write_text(
        f"""
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

static int contains(const wchar_t *text, const wchar_t *needle) {{
    for (; *text; ++text) {{
        const wchar_t *left = text;
        const wchar_t *right = needle;
        while (*right && *left == *right) {{ ++left; ++right; }}
        if (!*right) return 1;
    }}
    return 0;
}}

static void emit(const char *body, DWORD size) {{
    DWORD written = 0;
    WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), body, size, &written, 0);
}}

void WINAPI mainCRTStartup(void) {{
    if (contains(GetCommandLineW(), L"--unrestricted-smoke")) {{
        emit("unrestricted\\n", 13);
        ExitProcess(0);
    }}
    HANDLE token = 0;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token))
        ExitProcess(70);
    if (IsTokenRestricted(token)) ExitProcess(75);
    BYTE privilege_storage[1024];
    DWORD privilege_size = sizeof(privilege_storage);
    if (!GetTokenInformation(token, TokenPrivileges, privilege_storage,
                             privilege_size, &privilege_size)) ExitProcess(76);
    TOKEN_PRIVILEGES *privileges = (TOKEN_PRIVILEGES *)privilege_storage;
    if (privileges->PrivilegeCount > 1) ExitProcess(77);
    if (privileges->PrivilegeCount == 1) {{
        LUID change_notify;
        if (!LookupPrivilegeValueW(0, L"SeChangeNotifyPrivilege", &change_notify) ||
            privileges->Privileges[0].Luid.LowPart != change_notify.LowPart ||
            privileges->Privileges[0].Luid.HighPart != change_notify.HighPart)
            ExitProcess(78);
    }}
    CloseHandle(token);

    if (contains(GetCommandLineW(), L"--expect-renamed-cwd")) {{
        wchar_t cwd_path[1024];
        DWORD length = GetCurrentDirectoryW(1024, cwd_path);
        if (!length || length >= 1024 || !contains(cwd_path, L"cwd-renamed"))
            ExitProcess(74);
    }}

    if (contains(GetCommandLineW(), L" child")) {{
        for (;;) Sleep(1000);
    }}
    if (contains(GetCommandLineW(), L"--spawn-child")) {{
        wchar_t command[] = L"\\\"{escaped_path}\\\" child";
        STARTUPINFOW startup = {{0}};
        PROCESS_INFORMATION process = {{0}};
        startup.cb = sizeof(startup);
        if (!CreateProcessW(0, command, 0, 0, FALSE, CREATE_NO_WINDOW,
                            0, 0, &startup, &process)) ExitProcess(71);
        CloseHandle(process.hThread);
        CloseHandle(process.hProcess);
        emit("restricted-child-ready\\n", 23);
    }} else {{
        wchar_t system_root[MAX_PATH];
        DWORD root_length = GetEnvironmentVariableW(
            L"SystemRoot", system_root, MAX_PATH);
        if (!root_length || root_length >= MAX_PATH) ExitProcess(72);
        if (GetEnvironmentVariableW(L"PATH", system_root, MAX_PATH))
            ExitProcess(79);
        emit("restricted\\n", 11);
    }}
    char release = 0;
    DWORD read = 0;
    if (!ReadFile(GetStdHandle(STD_INPUT_HANDLE), &release, 1, &read, 0) ||
        read != 1) ExitProcess(73);
    ExitProcess(0);
}}
""",
        encoding="utf-8",
    )
    arguments = (
        compiler or "cl",
        "/nologo",
        "/O2",
        "/GS-",
        f"/Fe:{path}",
        str(source),
        "/link",
        "/NODEFAULTLIB",
            "/ENTRY:mainCRTStartup",
            "/SUBSYSTEM:CONSOLE",
            "/MANIFEST:NO",
            "kernel32.lib",
        "advapi32.lib",
    )
    command: tuple[str, ...] = arguments
    if compiler is None:
        vswhere = Path(
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        ) / "Microsoft Visual Studio/Installer/vswhere.exe"
        located = subprocess.run(
            (
                str(vswhere),
                "-latest",
                "-products",
                "*",
                "-requires",
                "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                "-property",
                "installationPath",
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        installation = located.stdout.strip()
        vcvars = Path(installation) / "VC/Auxiliary/Build/vcvars64.bat"
        if located.returncode != 0 or not installation or not vcvars.is_file():
            pytest.fail("H6.3 native gate requires the MSVC compiler")
        build_script = path.with_suffix(".build.cmd")
        build_script.write_text(
            "@echo off\n"
            f'call "{vcvars}" >nul\n'
            "if errorlevel 1 exit /b %errorlevel%\n"
            f"{subprocess.list2cmdline(list(arguments))}\n",
            encoding="utf-8",
        )
        command = ("cmd", "/d", "/c", str(build_script))
    completed = subprocess.run(
        command,
        cwd=path.parent,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(f"H6.3 native fixture compilation failed: {completed.stdout}\n{completed.stderr}")
    smoke = subprocess.run(
        (str(path), "--unrestricted-smoke"),
        cwd=path.parent,
        env={},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if smoke.returncode != 0 or smoke.stdout != "unrestricted\n":
        pytest.fail(
            "H6.3 unrestricted empty-environment fixture smoke failed: "
            f"{_return_code(smoke.returncode)}; stdout={smoke.stdout!r}; "
            f"stderr={smoke.stderr!r}"
        )


def _return_code(return_code: int) -> str:
    return f"{return_code} ({return_code & 0xFFFFFFFF:#010x})"


async def _read_line(read: Callable[[int], Awaitable[bytes]]) -> bytes:
    chunks: list[bytes] = []
    for _ in range(16):
        chunk = await read(64)
        if not chunk:
            break
        chunks.append(chunk)
        if b"\n" in chunk:
            break
    return b"".join(chunks)


async def _await_capture_or_start_failure(
    preparation: _RestrictedPreparation,
    start: asyncio.Task[object],
) -> None:
    capture = asyncio.create_task(
        preparation.captured.wait(),
        name="h6-windows-native-capture-observer",
    )
    done, _ = await asyncio.wait(
        (capture, start),
        return_when=asyncio.FIRST_COMPLETED,
    )
    if start in done:
        capture.cancel()
        await start
        raise AssertionError("Windows native start returned before capture pause")
    await capture


@_async_test
async def test_windows_restricted_native_locks_identity_and_runs_restricted(
    tmp_path: Path,
) -> None:
    admitted = tmp_path / "admitted"
    admitted.mkdir()
    executable = admitted / "restricted-fixture.exe"
    _compile_fixture(executable)
    cwd = admitted / "cwd"
    cwd.mkdir()
    api = _CtypesWin32Api()
    spec = _spec(api, executable, cwd, "--expect-renamed-cwd")
    preparation = _RestrictedPreparation(spec, pause_after_capture=True)
    host = _native_host(api)
    start = asyncio.create_task(
        host.start(ChildSessionRequest(spec.request), preparation)
    )
    lease = None
    try:
        await _await_capture_or_start_failure(preparation, start)

        with pytest.raises(OSError):
            executable.write_bytes(b"replacement")
        with pytest.raises(OSError):
            admitted.rename(tmp_path / "admitted-replaced")
        renamed_cwd = admitted / "cwd-renamed"
        cwd.rename(renamed_cwd)
        cwd.mkdir()

        preparation.release.set()
        lease = await start
        ready = await _read_line(lease.endpoint.read)
        if not ready:
            exit_result = await lease.process.wait()
            pytest.fail(
                "restricted fixture exited before ready: "
                f"{_return_code(exit_result.return_code)}"
            )
        assert ready == b"restricted\n"
        await lease.endpoint.write(b"x")
        assert (await lease.process.wait()).return_code == 0
    except BaseException:
        preparation.release.set()
        if lease is None:
            with suppress(BaseException):
                lease = await start
        if lease is not None:
            with suppress(BaseException):
                await lease.close()
        with suppress(BaseException):
            await host.close()
        raise
    await lease.close()
    await host.close()
    assert preparation.lease.verify_calls == 1
    assert preparation.lease.close_calls == 1


@_async_test
async def test_windows_restricted_native_job_reclaims_descendant(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "restricted-tree.exe"
    _compile_fixture(executable)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    api = _ObservedWin32Api()
    spec = _spec(api, executable, cwd, "--spawn-child")
    host = _native_host(api)
    lease = None
    try:
        lease = await host.start(
            ChildSessionRequest(spec.request),
            _RestrictedPreparation(spec),
        )

        ready = await _read_line(lease.endpoint.read)
        if not ready:
            exit_result = await lease.process.wait()
            pytest.fail(
                "restricted descendant fixture exited before ready: "
                f"{_return_code(exit_result.return_code)}"
            )
        assert ready == b"restricted-child-ready\n"
        assert len(api.created_jobs) == 1
        job = api.created_jobs[0]
        assert not api.job_is_empty(job)
        await lease.endpoint.write(b"x")
        assert (await lease.process.wait()).return_code == 0
        assert not api.job_is_empty(job)
        await lease.close()
        lease = None
        assert api.job_empty_observations[-1]
    except BaseException:
        if lease is not None:
            with suppress(BaseException):
                await lease.close()
        with suppress(BaseException):
            await host.close()
        raise
    await host.close()
