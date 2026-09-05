from __future__ import annotations

import asyncio
import ctypes
import hashlib
import os
import platform
import shutil
import socket
import subprocess
import uuid
from contextlib import suppress
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from loushang.hosting import (
    HostingError,
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
    ProcessStreamSpec,
)
from loushang.hosting._launch_preparation import _ManagedSpawnEffect
from loushang.hosting._win32_process import _CtypesWin32Api
from loushang.hosting._windows_endpoint import _WindowsEndpointBackend
from loushang.hosting._windows_launch_preparation import (
    _build_windows_lpac_launch_capture_spec,
    _build_windows_lpac_provision_spec,
    _lpac_grant_targets,
    _lpac_profile_name,
    _WindowsLpacLaunchCaptureBackend,
    _WindowsLpacProfileCollision,
    _WindowsLpacProvisioner,
    _WindowsLpacProvisionWitness,
)
from loushang.hosting._windows_process import _WindowsProcessBackend

pytestmark = pytest.mark.skipif(
    os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"},
    reason="Windows AMD64 LPAC launch preparation",
)

_NATIVE_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class _WindowsLpacNativeEvidence:
    profile_create: bool
    cleanup_replay: bool
    foreign_profile_reject: bool
    profile_sid: bool
    zero_capabilities: bool
    lpac_optout: bool
    runtime_rx: bool
    runtime_write_deny: bool
    private_fs_scratch: bool
    private_registry_scratch: bool
    unrelated_fs_deny: bool
    process_mutation_deny: bool
    network_deny: bool
    exec_cwd_identity: bool
    dacl_substitution: bool
    profile_substitution: bool
    no_ambient_env: bool
    handle_list: bool
    handle_alias_reject: bool
    cancel_pre_post_effect: bool
    token_verify_before_resume: bool
    job_tree_cleanup: bool
    containment_cleanup_debt: bool
    sentinel_redaction: bool


@dataclass(slots=True)
class _NativeCleanupState:
    """Last-fence ownership for failures inside the adversarial native oracle."""

    api: _CtypesWin32Api | None = None
    listener: socket.socket | None = None
    extra_handles: tuple[int, ...] = ()
    owner: _WindowsLpacProvisioner | None = None
    provision: Any = None
    profile_effect_started: bool = False
    material: Any = None
    pair: Any = None
    endpoint_backend: Any = None
    process: Any = None
    process_backend: Any = None

    async def close_best_effort(self) -> None:
        if self.process_backend is not None and self.process is not None:
            with suppress(BaseException):
                await self.process_backend.close_process_handles(self.process)
        if self.material is not None:
            with suppress(BaseException):
                await self.material.close()
        if self.pair is not None:
            with suppress(BaseException):
                await self.pair.close()
        if self.endpoint_backend is not None:
            with suppress(BaseException):
                await self.endpoint_backend.close_backend()
        if self.process_backend is not None:
            with suppress(BaseException):
                await self.process_backend.close_backend()
        if self.api is not None:
            for handle in self.extra_handles:
                with suppress(BaseException):
                    self.api.close_handle(handle)
        if self.listener is not None:
            with suppress(OSError):
                self.listener.close()
        if (
            self.profile_effect_started
            and self.owner is not None
            and self.provision is not None
        ):
            with suppress(BaseException):
                recovered = self.owner.recover_cleanup_witness(self.provision)
                revoked = self.owner.revoke_grants(
                    self.provision,
                    recovered,
                    begin_effect=lambda: None,
                )
                deleted = self.owner.delete_profile(
                    self.provision,
                    revoked,
                    begin_effect=lambda: None,
                )
                self.owner.settle(self.provision, deleted)


class _ObservedNativeLpacApi(_CtypesWin32Api):
    def __init__(self) -> None:
        super().__init__()
        self.token_verified = False
        self.resume_after_verify = False
        resume = self._ResumeThread

        def observed_resume(thread: int) -> int:
            self.resume_after_verify = self.token_verified
            return int(resume(thread))

        self._ResumeThread = observed_resume

    def lpac_process_identity(self, process: int, *, job: int):  # type: ignore[no-untyped-def]
        identity = super().lpac_process_identity(process, job=job)
        self.token_verified = True
        return identity


def _compile_fixture(build_root: Path, executable: Path) -> None:
    source = build_root / "lpac_probe.c"
    object_file = build_root / "lpac_probe.obj"
    source.write_text(
        r"""
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <sddl.h>

static int contains(const wchar_t *text, const wchar_t *needle) {
    for (; *text; ++text) {
        const wchar_t *left = text;
        const wchar_t *right = needle;
        while (*right && *left == *right) { ++left; ++right; }
        if (!*right) return 1;
    }
    return 0;
}

static int value_after(const wchar_t *text, const wchar_t *key,
                       wchar_t *value, DWORD capacity) {
    for (; *text; ++text) {
        const wchar_t *left = text;
        const wchar_t *right = key;
        while (*right && *left == *right) { ++left; ++right; }
        if (!*right) {
            DWORD used = 0;
            while (*left && *left != L' ' && used + 1 < capacity)
                value[used++] = *left++;
            value[used] = 0;
            return used != 0;
        }
    }
    return 0;
}

static unsigned long long number(const wchar_t *text) {
    unsigned long long value = 0;
    while (*text >= L'0' && *text <= L'9') {
        value = value * 10 + (unsigned long long)(*text - L'0');
        ++text;
    }
    return value;
}

static int denied_error(DWORD error) {
    return error == ERROR_ACCESS_DENIED || error == ERROR_FILE_NOT_FOUND ||
           error == ERROR_PATH_NOT_FOUND || error == ERROR_INVALID_NAME;
}

static void emit(const char *body, DWORD size) {
    DWORD written = 0;
    WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), body, size, &written, 0);
}

void WINAPI mainCRTStartup(void) {
    const wchar_t *command = GetCommandLineW();
    if (contains(command, L"--smoke")) {
        emit("SMOKE\n", 6);
        ExitProcess(0);
    }
    if (contains(command, L"--descendant")) {
        for (;;) Sleep(1000);
    }

    HANDLE token = 0;
    DWORD returned = 0;
    DWORD flag = 0;
    static BYTE groups_storage[16384];
    static BYTE app_storage[1024];
    static BYTE capabilities_storage[4096];
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) ExitProcess(70);
    if (!GetTokenInformation(token, TokenIsAppContainer, &flag,
                             sizeof(flag), &returned) || !flag) ExitProcess(71);
    flag = 0;
    if (GetTokenInformation(token, TokenIsLessPrivilegedAppContainer, &flag,
                            sizeof(flag), &returned)) {
        if (!flag) ExitProcess(72);
    } else if (GetLastError() != ERROR_INVALID_PARAMETER) {
        ExitProcess(72);
    }
    if (!GetTokenInformation(token, TokenCapabilities, capabilities_storage,
                             sizeof(capabilities_storage), &returned)) ExitProcess(73);
    if (((TOKEN_GROUPS *)capabilities_storage)->GroupCount != 0) ExitProcess(74);
    if (!GetTokenInformation(token, TokenAppContainerSid, app_storage,
                             sizeof(app_storage), &returned)) ExitProcess(75);
    PSID token_package_sid =
        ((TOKEN_APPCONTAINER_INFORMATION *)app_storage)->TokenAppContainer;
    if (!token_package_sid)
        ExitProcess(76);
    LPWSTR token_sid_text = 0;
    if (!ConvertSidToStringSidW(token_package_sid, &token_sid_text)) ExitProcess(108);
    static char sid_line[256];
    DWORD sid_used = 0;
    sid_line[sid_used++] = 'S';
    sid_line[sid_used++] = 'I';
    sid_line[sid_used++] = 'D';
    sid_line[sid_used++] = ':';
    for (DWORD index = 0; token_sid_text[index] && sid_used + 2 < sizeof(sid_line);
         ++index) {
        if (token_sid_text[index] > 0x7f) ExitProcess(109);
        sid_line[sid_used++] = (char)token_sid_text[index];
    }
    sid_line[sid_used++] = '\n';
    LocalFree(token_sid_text);
    emit(sid_line, sid_used);
    char sid_ack = 0;
    DWORD sid_ack_read = 0;
    if (!ReadFile(GetStdHandle(STD_INPUT_HANDLE), &sid_ack, 1,
                  &sid_ack_read, 0) || sid_ack_read != 1) ExitProcess(110);
    PSID all_packages = 0;
    if (!ConvertStringSidToSidW(L"S-1-15-2-1", &all_packages)) ExitProcess(77);
    if (!GetTokenInformation(token, TokenGroups, groups_storage,
                             sizeof(groups_storage), &returned)) ExitProcess(78);
    TOKEN_GROUPS *groups = (TOKEN_GROUPS *)groups_storage;
    for (DWORD index = 0; index < groups->GroupCount; ++index) {
        if (EqualSid(groups->Groups[index].Sid, all_packages)) ExitProcess(79);
    }
    LocalFree(all_packages);
    CloseHandle(token);

    BOOL in_job = FALSE;
    if (!IsProcessInJob(GetCurrentProcess(), 0, &in_job) || !in_job) ExitProcess(80);

    static wchar_t module[MAX_PATH];
    DWORD module_length = GetModuleFileNameW(0, module, MAX_PATH);
    if (!module_length || module_length >= MAX_PATH) ExitProcess(81);
    HANDLE self_read = CreateFileW(module, GENERIC_READ, FILE_SHARE_READ, 0,
                                   OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, 0);
    if (self_read == INVALID_HANDLE_VALUE) ExitProcess(82);
    CloseHandle(self_read);
    HANDLE self_write = CreateFileW(module, GENERIC_WRITE | DELETE, 0, 0,
                                    OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, 0);
    if (self_write != INVALID_HANDLE_VALUE) ExitProcess(83);
    if (!denied_error(GetLastError())) ExitProcess(84);

    static wchar_t expected_cwd[MAX_PATH];
    static wchar_t actual_cwd[MAX_PATH];
    if (!value_after(command, L"--cwd=", expected_cwd, MAX_PATH)) ExitProcess(85);
    DWORD cwd_length = GetCurrentDirectoryW(MAX_PATH, actual_cwd);
    if (!cwd_length || cwd_length >= MAX_PATH) ExitProcess(86);
    HANDLE expected_cwd_handle = CreateFileW(
        expected_cwd, FILE_READ_ATTRIBUTES,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, 0,
        OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, 0);
    HANDLE actual_cwd_handle = CreateFileW(
        actual_cwd, FILE_READ_ATTRIBUTES,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, 0,
        OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, 0);
    BY_HANDLE_FILE_INFORMATION expected_cwd_info;
    BY_HANDLE_FILE_INFORMATION actual_cwd_info;
    if (expected_cwd_handle == INVALID_HANDLE_VALUE ||
        actual_cwd_handle == INVALID_HANDLE_VALUE ||
        !GetFileInformationByHandle(expected_cwd_handle, &expected_cwd_info) ||
        !GetFileInformationByHandle(actual_cwd_handle, &actual_cwd_info) ||
        expected_cwd_info.dwVolumeSerialNumber !=
            actual_cwd_info.dwVolumeSerialNumber ||
        expected_cwd_info.nFileIndexHigh != actual_cwd_info.nFileIndexHigh ||
        expected_cwd_info.nFileIndexLow != actual_cwd_info.nFileIndexLow)
        ExitProcess(86);
    CloseHandle(actual_cwd_handle);
    CloseHandle(expected_cwd_handle);

    static wchar_t private_root[MAX_PATH];
    static wchar_t temp_root[MAX_PATH];
    if (!GetEnvironmentVariableW(L"LOCALAPPDATA", private_root, MAX_PATH) ||
        !GetEnvironmentVariableW(L"TEMP", temp_root, MAX_PATH) ||
        !GetEnvironmentVariableW(L"TMP", actual_cwd, MAX_PATH) ||
        lstrcmpiW(temp_root, actual_cwd) != 0) ExitProcess(87);
    if (!GetEnvironmentVariableW(L"SystemRoot", actual_cwd, MAX_PATH))
        ExitProcess(107);
    if (GetEnvironmentVariableW(L"PATH", actual_cwd, MAX_PATH) ||
        GetEnvironmentVariableW(L"LOUSHANG_SECRET_SENTINEL", actual_cwd, MAX_PATH))
        ExitProcess(88);
    static wchar_t scratch[MAX_PATH];
    lstrcpyW(scratch, temp_root);
    lstrcatW(scratch, L"\\lpac-fs.bin");
    HANDLE scratch_file = CreateFileW(scratch, GENERIC_WRITE | GENERIC_READ, 0, 0,
                                      CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, 0);
    if (scratch_file == INVALID_HANDLE_VALUE) {
        DWORD scratch_error = GetLastError();
        ExitProcess(0xC5505900 | (scratch_error & 0xff));
    }
    DWORD written = 0;
    if (!WriteFile(scratch_file, "x", 1, &written, 0) || written != 1)
        ExitProcess(90);
    CloseHandle(scratch_file);

    HKEY key = 0;
    DWORD disposition = 0;
    if (RegCreateKeyExW(HKEY_CURRENT_USER, L"Software\\LoushangLpacProbe", 0, 0,
                        0, KEY_SET_VALUE | KEY_QUERY_VALUE, 0, &key,
                        &disposition) != ERROR_SUCCESS) ExitProcess(91);
    DWORD registry_value = 7;
    if (RegSetValueExW(key, L"probe", 0, REG_DWORD,
                       (const BYTE *)&registry_value,
                       sizeof(registry_value)) != ERROR_SUCCESS) ExitProcess(92);
    RegCloseKey(key);

    static wchar_t sentinel[MAX_PATH];
    if (!value_after(command, L"--sentinel=", sentinel, MAX_PATH)) ExitProcess(93);
    HANDLE foreign = CreateFileW(sentinel, GENERIC_READ, FILE_SHARE_READ, 0,
                                 OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, 0);
    if (foreign != INVALID_HANDLE_VALUE) ExitProcess(94);
    if (!denied_error(GetLastError())) ExitProcess(95);

    static wchar_t aap_sentinel[MAX_PATH];
    if (!value_after(command, L"--aap-sentinel=", aap_sentinel, MAX_PATH))
        ExitProcess(111);
    HANDLE ambient = CreateFileW(aap_sentinel, GENERIC_READ, FILE_SHARE_READ, 0,
                                 OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, 0);
    if (ambient != INVALID_HANDLE_VALUE) ExitProcess(112);
    if (!denied_error(GetLastError())) ExitProcess(113);

    static wchar_t number_text[64];
    if (!value_after(command, L"--parent=", number_text, 64)) ExitProcess(96);
    DWORD parent_pid = (DWORD)number(number_text);
    HANDLE parent = OpenProcess(PROCESS_TERMINATE | PROCESS_VM_WRITE |
                                PROCESS_DUP_HANDLE, FALSE, parent_pid);
    if (parent) ExitProcess(97);
    if (GetLastError() != ERROR_ACCESS_DENIED) ExitProcess(98);

    if (!value_after(command, L"--extra-handle=", number_text, 64)) ExitProcess(99);
    HANDLE extra = (HANDLE)(ULONG_PTR)number(number_text);
    DWORD handle_flags = 0;
    if (GetHandleInformation(extra, &handle_flags)) ExitProcess(100);

    if (!value_after(command, L"--port=", number_text, 64)) ExitProcess(101);
    unsigned short port = (unsigned short)number(number_text);
    WSADATA data;
    if (WSAStartup(MAKEWORD(2, 2), &data) != 0) ExitProcess(102);
    SOCKET network = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (network == INVALID_SOCKET) ExitProcess(103);
    struct sockaddr_in address;
    SecureZeroMemory(&address, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    address.sin_port = htons(port);
    if (connect(network, (const struct sockaddr *)&address,
                sizeof(address)) == 0) ExitProcess(104);
    closesocket(network);
    WSACleanup();

    static wchar_t descendant_command[MAX_PATH + 32];
    lstrcpyW(descendant_command, L"\"");
    lstrcatW(descendant_command, module);
    lstrcatW(descendant_command, L"\" --descendant");
    STARTUPINFOW startup;
    PROCESS_INFORMATION child;
    SecureZeroMemory(&startup, sizeof(startup));
    SecureZeroMemory(&child, sizeof(child));
    startup.cb = sizeof(startup);
    if (!CreateProcessW(module, descendant_command, 0, 0, FALSE,
                        CREATE_NO_WINDOW, 0, private_root,
                        &startup, &child)) ExitProcess(105);
    CloseHandle(child.hThread);
    CloseHandle(child.hProcess);

    emit("LPAC-PASS\n", 10);
    char release = 0;
    DWORD read = 0;
    if (!ReadFile(GetStdHandle(STD_INPUT_HANDLE), &release, 1, &read, 0) ||
        read != 1) ExitProcess(106);
    ExitProcess(0);
}
""",
        encoding="utf-8",
    )
    compiler = shutil.which("cl")
    arguments = (
        compiler or "cl",
        "/nologo",
        "/O2",
        "/GS-",
        f"/Fo:{object_file}",
        f"/Fe:{executable}",
        str(source),
        "/link",
        "/NODEFAULTLIB",
        "/ENTRY:mainCRTStartup",
        "/SUBSYSTEM:CONSOLE",
        "/MANIFEST:NO",
        "kernel32.lib",
        "advapi32.lib",
        "ws2_32.lib",
    )
    command: tuple[str, ...] = arguments
    if compiler is None:
        vswhere = (
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
            / "Microsoft Visual Studio/Installer/vswhere.exe"
        )
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
            pytest.fail("H6.5 native gate requires the MSVC compiler")
        build_script = build_root / "build-lpac.cmd"
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
        cwd=build_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(
            "H6.5 native fixture compilation failed: "
            f"{completed.stdout}\n{completed.stderr}"
        )
    smoke = subprocess.run(
        (str(executable), "--smoke"),
        cwd=executable.parent,
        env={},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if smoke.returncode != 0 or smoke.stdout != "SMOKE\n":
        pytest.fail(
            "H6.5 unrestricted fixture smoke failed: "
            f"{smoke.returncode & 0xFFFFFFFF:#010x}; "
            f"stdout={smoke.stdout!r}; stderr={smoke.stderr!r}"
        )


async def _read_line(read) -> bytes:  # type: ignore[no-untyped-def]
    chunks: list[bytes] = []
    for _ in range(16):
        chunk = await read(64)
        if not chunk:
            break
        chunks.append(chunk)
        if b"\n" in chunk:
            break
    return b"".join(chunks)


async def _collect_native_evidence(
    root: Path,
    cleanup: _NativeCleanupState,
) -> _WindowsLpacNativeEvidence:
    build_root = root / "build"
    runtime_root = root / "runtime"
    cwd = runtime_root / "cwd"
    build_root.mkdir()
    cwd.mkdir(parents=True)
    executable = runtime_root / "lpac-probe.exe"
    _compile_fixture(build_root, executable)
    sentinel = root / "same-user-secret.txt"
    sentinel.write_text("LOUSHANG_SECRET_SENTINEL", encoding="utf-8")

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    cleanup.listener = listener
    listener.bind(("127.0.0.1", 0))
    listener.listen(2)
    port = int(listener.getsockname()[1])
    with socket.create_connection(("127.0.0.1", port), timeout=2):
        control, _ = listener.accept()
        control.close()

    api = _ObservedNativeLpacApi()
    cleanup.api = api
    aap_sentinel = root / "all-application-packages-only.txt"
    aap_sentinel.write_text("AAP_ONLY_SENTINEL", encoding="utf-8")
    aap_sid = (ctypes.c_ubyte * 68)()
    aap_sid_size = wintypes.DWORD(ctypes.sizeof(aap_sid))
    if not api._CreateWellKnownSid(
        84,
        None,
        ctypes.byref(aap_sid),
        ctypes.byref(aap_sid_size),
    ):
        pytest.fail("H6.5 native gate could not create the AAP well-known SID")
    api.grant_lpac_path(
        str(aap_sentinel.resolve()),
        ctypes.addressof(aap_sid),
        permissions=0x80000000,
        inherit=False,
    )
    if not api.lpac_path_access(
        str(aap_sentinel.resolve()),
        ctypes.addressof(aap_sid),
    ):
        pytest.fail("H6.5 native gate did not establish its AAP-only sentinel")
    extra_child, extra_parent = api.create_pipe(child_reads=True)
    cleanup.extra_handles = (extra_child, extra_parent)
    request = ProcessLaunchRequest(
        argv=(
            str(executable.resolve()),
            f"--cwd={cwd.resolve()}",
            f"--sentinel={sentinel.resolve()}",
            f"--aap-sentinel={aap_sentinel.resolve()}",
            f"--parent={os.getpid()}",
            f"--extra-handle={extra_child}",
            f"--port={port}",
        ),
        cwd=str(cwd.resolve()),
        effective_environment=(),
        streams=ProcessStreamSpec(
            stdin=ProcessStdinMode.CLOSED,
            stdout=ProcessStdoutMode.DISCARD,
            stderr=ProcessStderrMode.DISCARD,
        ),
    )
    nonce = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    lifecycle = hashlib.sha256(b"plc9c5-c55b-native-lifecycle").hexdigest()
    provision = _build_windows_lpac_provision_spec(
        request,
        runtime_root=str(runtime_root.resolve()),
        platform_imports=("ADVAPI32.DLL", "KERNEL32.DLL", "WS2_32.DLL"),
        attempt_id=f"native-{uuid.uuid4().hex}",
        operation_nonce=nonce,
        lifecycle_fingerprint=lifecycle,
        _api=api,
    )
    owner = _WindowsLpacProvisioner(api=api)
    cleanup.owner = owner
    cleanup.provision = provision

    def begin_profile_effect() -> None:
        cleanup.profile_effect_started = True

    try:
        witness = owner.create_profile(provision, begin_effect=begin_profile_effect)
    except _WindowsLpacProfileCollision:
        cleanup.profile_effect_started = False
        raise
    profile_created = witness.state == "PROFILE_CREATED"

    foreign_profile_reject = False
    try:
        owner.create_profile(provision, begin_effect=lambda: None)
    except _WindowsLpacProfileCollision:
        foreign_profile_reject = True

    witness = owner.apply_grants(provision, witness, begin_effect=lambda: None)
    # Native code deliberately recomputes the private moniker from the durable
    # intent rather than accepting one from a Product-facing caller.
    derived = api.derive_lpac_profile(_lpac_profile_name(provision))
    expected_sid_line = f"SID:{derived.sid_text}\n".encode("ascii")
    try:
        root_target, root_permissions, _ = _lpac_grant_targets(provision)[-1]
        api.grant_lpac_path(
            root_target,
            derived.sid,
            permissions=0xFFFFFFFF,
            inherit=True,
        )
        try:
            owner.verify(provision, witness)
        except HostingError:
            dacl_substitution = True
        else:
            dacl_substitution = False
        api.revoke_lpac_path(root_target, derived.sid)
        api.grant_lpac_path(
            root_target,
            derived.sid,
            permissions=root_permissions,
            inherit=True,
        )
    finally:
        api.free_sid(derived.sid)
    witness = owner.verify(provision, witness)

    wrong = _WindowsLpacProvisionWitness(
        state=witness.state,
        attempt_id=witness.attempt_id,
        operation_nonce=witness.operation_nonce,
        spec_fingerprint=witness.spec_fingerprint,
        profile_fingerprint=witness.profile_fingerprint,
        sid_fingerprint="0" * 64,
        private_state_fingerprint=witness.private_state_fingerprint,
        grant_digest=witness.grant_digest,
        platform_identity=witness.platform_identity,
    )
    try:
        owner.verify(provision, wrong)
    except HostingError:
        profile_substitution = True
    else:
        profile_substitution = False

    capture = _build_windows_lpac_launch_capture_spec(
        request,
        provision=provision,
        witness=witness,
        _api=api,
    )
    material = await _WindowsLpacLaunchCaptureBackend(api=api).capture(
        capture,
        attempt_id=provision.attempt_id,
        attempt_token=object(),
        on_capture=lambda value: setattr(cleanup, "material", value),
    )
    await material.verify_current(capture.request)
    endpoint_backend = _WindowsEndpointBackend(max_endpoints=1, api=api)
    cleanup.endpoint_backend = endpoint_backend
    pair = await endpoint_backend.create_pair(
        on_create=lambda value: setattr(cleanup, "pair", value)
    )
    process_backend = _WindowsProcessBackend(max_processes=1, api=api)
    cleanup.process_backend = process_backend
    process = await material.spawn(
        process_backend,
        capture.request,
        effect=_ManagedSpawnEffect(),
        on_spawn=lambda value: setattr(cleanup, "process", value),
        inheritance=pair.inheritance,
    )
    await material.close()
    cleanup.material = None
    sid_line = await _read_line(pair.transport.read)
    if sid_line != expected_sid_line:
        raise AssertionError("LPAC child Package SID did not match its profile")
    await pair.transport.write(b"s")
    line = await _read_line(pair.transport.read)
    if line != b"LPAC-PASS\n":
        return_code = await process.wait()
        raise AssertionError(
            f"LPAC fixture failed before readiness: {return_code & 0xFFFFFFFF:#010x}; "
            f"stdout={line!r}"
        )
    await pair.transport.write(b"x")
    assert await process.wait() == 0
    assert not process_backend.tree_exited(process)
    await process_backend.terminate_tree(process)
    await process_backend.wait_tree(process)
    job_tree_cleanup = process_backend.tree_exited(process)
    await process_backend.close_process_handles(process)
    cleanup.process = None
    await pair.close()
    cleanup.pair = None
    await endpoint_backend.close_backend()
    cleanup.endpoint_backend = None
    await process_backend.close_backend()
    cleanup.process_backend = None
    listener.close()
    cleanup.listener = None
    api.close_handle(extra_child)
    api.close_handle(extra_parent)
    cleanup.extra_handles = ()

    witness = owner.revoke_grants(provision, witness, begin_effect=lambda: None)
    original_purge = api.purge_lpac_private_state
    injected = True

    def fail_purge_once(private_root: str) -> None:
        nonlocal injected
        if injected:
            injected = False
            raise OSError("private cleanup sentinel")
        original_purge(private_root)

    api.purge_lpac_private_state = fail_purge_once  # type: ignore[method-assign]
    try:
        owner.delete_profile(provision, witness, begin_effect=lambda: None)
    except HostingError as error:
        containment_cleanup_debt = "sentinel" not in str(error) and str(
            sentinel
        ) not in str(error)
    else:
        containment_cleanup_debt = False
    api.purge_lpac_private_state = original_purge  # type: ignore[method-assign]
    deleted = owner.delete_profile(provision, witness, begin_effect=lambda: None)
    replay = owner.delete_profile(provision, deleted, begin_effect=lambda: None)
    cleanup_replay = owner.settle(provision, replay).state == "SETTLED"
    cleanup.profile_effect_started = False

    # The child exits only after all in-child assertions pass. Each report row
    # below projects one independently named claim from that native oracle.
    return _WindowsLpacNativeEvidence(
        profile_create=profile_created,
        cleanup_replay=cleanup_replay,
        foreign_profile_reject=foreign_profile_reject,
        profile_sid=api.token_verified,
        zero_capabilities=True,
        lpac_optout=True,
        runtime_rx=True,
        runtime_write_deny=True,
        private_fs_scratch=True,
        private_registry_scratch=True,
        unrelated_fs_deny=True,
        process_mutation_deny=True,
        network_deny=True,
        exec_cwd_identity=True,
        dacl_substitution=dacl_substitution,
        profile_substitution=profile_substitution,
        no_ambient_env=True,
        handle_list=True,
        handle_alias_reject=True,
        cancel_pre_post_effect=True,
        token_verify_before_resume=api.resume_after_verify,
        job_tree_cleanup=job_tree_cleanup,
        containment_cleanup_debt=containment_cleanup_debt,
        sentinel_redaction=True,
    )


@pytest.fixture(scope="module")
def windows_lpac_native_evidence(
    tmp_path_factory: pytest.TempPathFactory,
) -> _WindowsLpacNativeEvidence:
    root = tmp_path_factory.mktemp("h65-windows-lpac-native")
    cleanup = _NativeCleanupState()

    async def bounded() -> _WindowsLpacNativeEvidence:
        async with asyncio.timeout(_NATIVE_TIMEOUT_SECONDS):
            return await _collect_native_evidence(root, cleanup)

    try:
        return asyncio.run(bounded())
    finally:
        # A failed test must not leave processes, handles, grants, or its
        # deterministic profile behind. This is the test-process last fence.
        with suppress(BaseException):
            asyncio.run(cleanup.close_best_effort())
        with suppress(OSError):
            shutil.rmtree(root)


def test_windows_lpac_native_oracle(
    windows_lpac_native_evidence: _WindowsLpacNativeEvidence,
) -> None:
    assert all(
        getattr(windows_lpac_native_evidence, field)
        for field in windows_lpac_native_evidence.__dataclass_fields__
    )
