from __future__ import annotations

import asyncio
import hashlib
import struct
from pathlib import Path

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
from loushang.hosting._launch_preparation import (
    _ManagedSpawnEffect,
    _ManagedSpawnNotCreated,
    _ManagedSpawnSettledWithoutProcess,
)
from loushang.hosting._win32_process import (
    _Win32CreateSettledWithoutProcess,
    _Win32LockedPathIdentity,
    _Win32SpawnHandles,
)
from loushang.hosting._windows_launch_preparation import (
    _verify_pe_image,
    _WindowsRestrictedLaunchCaptureBackend,
    _WindowsRestrictedLaunchCaptureSpec,
)
from loushang.hosting._windows_process import _WindowsProcessBackend


def _request() -> ProcessLaunchRequest:
    return ProcessLaunchRequest(
        argv=("/admitted/worker.exe",),
        cwd="/admitted/cwd",
        effective_environment=(),
        streams=ProcessStreamSpec(
            stdin=ProcessStdinMode.CLOSED,
            stdout=ProcessStdoutMode.DISCARD,
            stderr=ProcessStderrMode.DISCARD,
        ),
    )


def _spec() -> _WindowsRestrictedLaunchCaptureSpec:
    digest = "1" * 64
    return _WindowsRestrictedLaunchCaptureSpec(
        request=_request(),
        profile_id="windows-restricted-known-dll-pe-v1",
        execution_closure=(
            f"pe-amd64:sha256:{digest}",
            "executable:win32:7:101",
            "cwd:win32:7:202",
            "restricted-token:disable-max-privilege+lua+write-restricted-v1",
            "known-dlls:KERNEL32.DLL",
            "platform:windows-amd64-10.0.20348",
        ),
        executable_sha256=digest,
        executable_volume_serial=7,
        executable_file_id=101,
        cwd_volume_serial=7,
        cwd_file_id=202,
        platform_identity="windows-amd64-10.0.20348",
        platform_imports=("KERNEL32.DLL",),
    )


class _FakeWindowsLaunchApi:
    def __init__(self) -> None:
        self.next_handle = 1
        self.closed: list[int] = []
        self.spawn_calls: list[tuple[object, ...]] = []
        self.transferred = False
        self.empty = False
        self.return_code: int | None = None
        self.fail_stage: str | None = None
        self.fail_close_once: int | None = None

    def platform_identity(self) -> str:
        return "windows-amd64-10.0.20348"

    def open_locked_file(self, path: str) -> int:
        assert path == _request().argv[0]
        return self._allocate("executable")

    def open_locked_directory(self, path: str) -> int:
        assert path == _request().cwd
        return self._allocate("cwd")

    def locked_path_identity(self, handle: int) -> _Win32LockedPathIdentity:
        if handle == 1:
            return _Win32LockedPathIdentity(
                7, 101, 4096, r"\\?\C:\admitted\worker.exe", False
            )
        if handle == 2:
            return _Win32LockedPathIdentity(
                7, 202, 0, r"\\?\C:\admitted\cwd", True
            )
        raise OSError("unknown locked path")

    def open_process_token(self) -> int:
        return self._allocate("source-token")

    def create_restricted_token(self, source_token: int) -> int:
        assert source_token == 3
        return self._allocate("restricted-token")

    def token_is_restricted(self, token: int) -> bool:
        return token == 4

    def create_managed_job(self) -> int:
        return self._allocate("job")

    def managed_job_is_kill_on_close(self, job: int) -> bool:
        return job == 5

    def create_managed_stderr(self) -> int:
        return self._allocate("stderr")

    def close_handle(self, handle: int) -> None:
        if self.fail_close_once == handle:
            self.fail_close_once = None
            raise OSError("injected close failure")
        self.closed.append(handle)
        if handle == 5:
            self.empty = True
            self.return_code = 0xE0000002

    def spawn_restricted(
        self,
        request: ProcessLaunchRequest,
        endpoint_handles: tuple[int, int],
        **kwargs: object,
    ) -> _Win32SpawnHandles:
        begin_effect = kwargs["begin_effect"]
        assert callable(begin_effect)
        self.spawn_calls.append((request, endpoint_handles, kwargs))
        begin_effect()
        if self.fail_stage == "create":
            raise _Win32CreateSettledWithoutProcess(OSError("create failed"))
        return _Win32SpawnHandles(
            process=30,
            job=int(kwargs["job"]),
            stdin_write=None,
            stdout_read=None,
            stderr_read=None,
            cleanup_handles=(31, int(kwargs["stderr_handle"])),
        )

    def spawn(
        self,
        request: ProcessLaunchRequest,
        endpoint_handles: tuple[int, int] | None = None,
    ) -> _Win32SpawnHandles:
        raise AssertionError("managed test must use restricted spawn")

    def read_pipe(self, handle: int, max_bytes: int) -> bytes:
        return b""

    def write_pipe(self, handle: int, data: bytes) -> None:
        return

    def wait_process(self, handle: int) -> int:
        return self.return_code or 0

    def process_return_code(self, handle: int) -> int | None:
        return self.return_code

    def job_is_empty(self, handle: int) -> bool:
        return self.empty

    def terminate_job(self, handle: int, exit_code: int) -> None:
        self.return_code = exit_code
        self.empty = True

    def cancel_synchronous_io(self, thread_id: int) -> None:
        return

    def _allocate(self, stage: str) -> int:
        if self.fail_stage == stage:
            raise OSError(f"injected {stage} failure")
        handle = self.next_handle
        self.next_handle += 1
        return handle


class _Inheritance:
    backend_id = "windows-job-v1"

    def __init__(self, handles: tuple[int, int] = (20, 21)) -> None:
        self.handles = handles
        self.transferred = False

    def claim(self, *, backend_id: str) -> tuple[int, ...]:
        assert backend_id == self.backend_id
        return self.handles

    def mark_transferred(self) -> None:
        self.transferred = True

    async def close(self) -> None:
        return


def test_windows_restricted_capture_attaches_before_partial_acquisition_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _FakeWindowsLaunchApi()
    api.fail_stage = "restricted-token"
    backend = _WindowsRestrictedLaunchCaptureBackend(api=api)
    attached = []
    monkeypatch.setattr(
        "loushang.hosting._windows_launch_preparation._verify_pe_image",
        lambda *args, **kwargs: None,
    )

    async def exercise() -> None:
        with pytest.raises(OSError, match="restricted-token"):
            await backend.capture(
                _spec(),
                attempt_id="windows-acquisition-failure",
                attempt_token=object(),
                on_capture=attached.append,
            )
        assert len(attached) == 1
        assert api.closed == []
        await attached[0].close()

    asyncio.run(exercise())
    assert set(api.closed) == {1, 2, 3}


def test_windows_restricted_material_composes_exact_spawn_and_transfers_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _FakeWindowsLaunchApi()
    capture_backend = _WindowsRestrictedLaunchCaptureBackend(api=api)
    process_backend = _WindowsProcessBackend(api=api)
    inheritance = _Inheritance()
    attached = []
    monkeypatch.setattr(
        "loushang.hosting._windows_launch_preparation._verify_pe_image",
        lambda *args, **kwargs: None,
    )

    async def exercise() -> None:
        material = await capture_backend.capture(
            _spec(),
            attempt_id="windows-success",
            attempt_token=object(),
            on_capture=lambda owner: None,
        )
        await material.verify_current(material.request)
        effect = _ManagedSpawnEffect()

        def on_spawn(process: object) -> None:
            attached.append(process)
            effect.observe_attachment(process)  # type: ignore[arg-type]

        process = await material.spawn(
            process_backend,
            material.request,
            effect=effect,
            on_spawn=on_spawn,
            inheritance=inheritance,
        )
        assert process is attached[0]
        assert inheritance.transferred
        await process_backend.close_process_handles(process)
        await material.close()
        await process_backend.close_backend()

    asyncio.run(exercise())
    assert len(api.spawn_calls) == 1
    _, endpoint_handles, kwargs = api.spawn_calls[0]
    assert endpoint_handles == (20, 21)
    assert kwargs["application_name"] == r"\\?\C:\admitted\worker.exe"
    assert kwargs["cwd"] == r"\\?\C:\admitted\cwd"
    assert kwargs["token"] == 4
    assert kwargs["job"] == 5
    assert kwargs["stderr_handle"] == 6
    assert set(api.closed) == {1, 2, 3, 4, 5, 6, 30, 31}


def test_windows_restricted_create_failure_has_exact_settled_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _FakeWindowsLaunchApi()
    api.fail_stage = None
    capture_backend = _WindowsRestrictedLaunchCaptureBackend(api=api)
    process_backend = _WindowsProcessBackend(api=api)
    monkeypatch.setattr(
        "loushang.hosting._windows_launch_preparation._verify_pe_image",
        lambda *args, **kwargs: None,
    )

    async def exercise() -> None:
        material = await capture_backend.capture(
            _spec(),
            attempt_id="windows-create-failure",
            attempt_token=object(),
            on_capture=lambda owner: None,
        )
        await material.verify_current(material.request)
        effect = _ManagedSpawnEffect()
        api.fail_stage = "create"
        with pytest.raises(_ManagedSpawnSettledWithoutProcess) as failure:
            await material.spawn(
                process_backend,
                material.request,
                effect=effect,
                on_spawn=lambda process: None,
                inheritance=_Inheritance(),
            )
        assert effect.accepts_settled(failure.value)
        await material.close()
        await process_backend.close_backend()

    asyncio.run(exercise())


def test_windows_restricted_handle_collision_fails_before_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _FakeWindowsLaunchApi()
    capture_backend = _WindowsRestrictedLaunchCaptureBackend(api=api)
    process_backend = _WindowsProcessBackend(api=api)
    monkeypatch.setattr(
        "loushang.hosting._windows_launch_preparation._verify_pe_image",
        lambda *args, **kwargs: None,
    )

    async def exercise() -> None:
        material = await capture_backend.capture(
            _spec(),
            attempt_id="windows-collision",
            attempt_token=object(),
            on_capture=lambda owner: None,
        )
        await material.verify_current(material.request)
        effect = _ManagedSpawnEffect()
        with pytest.raises(_ManagedSpawnNotCreated) as failure:
            await material.spawn(
                process_backend,
                material.request,
                effect=effect,
                on_spawn=lambda process: None,
                inheritance=_Inheritance((1, 21)),
            )
        assert effect.accepts(failure.value)
        assert isinstance(failure.value.cause, HostingError)
        assert (
            failure.value.cause.category
            is HostingFailureCategory.ENDPOINT_TRANSFER_FAILED
        )
        await material.close()
        await process_backend.close_backend()

    asyncio.run(exercise())


def test_windows_restricted_close_retries_retained_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _FakeWindowsLaunchApi()
    backend = _WindowsRestrictedLaunchCaptureBackend(api=api)
    monkeypatch.setattr(
        "loushang.hosting._windows_launch_preparation._verify_pe_image",
        lambda *args, **kwargs: None,
    )

    async def exercise() -> None:
        material = await backend.capture(
            _spec(),
            attempt_id="windows-close-retry",
            attempt_token=object(),
            on_capture=lambda owner: None,
        )
        api.fail_close_once = 1
        with pytest.raises(BaseExceptionGroup):
            await material.close()
        assert 1 not in api.closed
        await material.close()
        assert api.closed.count(1) == 1

    asyncio.run(exercise())


def test_windows_restricted_spec_rejects_open_environment_and_imports() -> None:
    original = _spec()
    with pytest.raises(ValueError, match="empty environment"):
        _WindowsRestrictedLaunchCaptureSpec(
            request=ProcessLaunchRequest(
                argv=original.request.argv,
                cwd=original.request.cwd,
                effective_environment=(("PATH", r"C:\Windows"),),
                streams=original.request.streams,
            ),
            profile_id=original.profile_id,
            execution_closure=original.execution_closure,
            executable_sha256=original.executable_sha256,
            executable_volume_serial=original.executable_volume_serial,
            executable_file_id=original.executable_file_id,
            cwd_volume_serial=original.cwd_volume_serial,
            cwd_file_id=original.cwd_file_id,
            platform_identity=original.platform_identity,
            platform_imports=original.platform_imports,
        )
    with pytest.raises(ValueError, match="imports"):
        _WindowsRestrictedLaunchCaptureSpec(
            request=original.request,
            profile_id=original.profile_id,
            execution_closure=original.execution_closure,
            executable_sha256=original.executable_sha256,
            executable_volume_serial=original.executable_volume_serial,
            executable_file_id=original.executable_file_id,
            cwd_volume_serial=original.cwd_volume_serial,
            cwd_file_id=original.cwd_file_id,
            platform_identity=original.platform_identity,
            platform_imports=("EVIL.DLL",),
        )


def test_windows_pe_parser_accepts_exact_amd64_known_dll_closure(
    tmp_path: Path,
) -> None:
    image = tmp_path / "fixture.exe"
    body = _minimal_pe(("KERNEL32.DLL",))
    image.write_bytes(body)

    _verify_pe_image(
        image,
        expected_digest=hashlib.sha256(body).hexdigest(),
        expected_imports=("KERNEL32.DLL",),
    )


@pytest.mark.parametrize("mutation", ("machine", "delay", "import"))
def test_windows_pe_parser_rejects_open_or_wrong_closure(
    tmp_path: Path,
    mutation: str,
) -> None:
    imports = ("EVIL.DLL",) if mutation == "import" else ("KERNEL32.DLL",)
    body = bytearray(_minimal_pe(imports))
    if mutation == "machine":
        struct.pack_into("<H", body, 0x84, 0x014C)
    elif mutation == "delay":
        optional = 0x98
        struct.pack_into("<II", body, optional + 112 + 13 * 8, 0x1100, 32)
    image = tmp_path / f"{mutation}.exe"
    image.write_bytes(body)

    with pytest.raises(HostingError) as failure:
        _verify_pe_image(
            image,
            expected_digest=hashlib.sha256(body).hexdigest(),
            expected_imports=("KERNEL32.DLL",),
        )
    assert failure.value.category is HostingFailureCategory.PREPARATION_FAILED


def _minimal_pe(imports: tuple[str, ...]) -> bytes:
    body = bytearray(0x600)
    body[:2] = b"MZ"
    struct.pack_into("<I", body, 0x3C, 0x80)
    body[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", body, 0x84, 0x8664, 1)
    struct.pack_into("<H", body, 0x94, 240)
    optional = 0x98
    struct.pack_into("<H", body, optional, 0x20B)
    struct.pack_into("<I", body, optional + 60, 0x200)
    struct.pack_into("<I", body, optional + 108, 16)
    struct.pack_into("<II", body, optional + 120, 0x1000, (len(imports) + 1) * 20)
    section = optional + 240
    body[section : section + 8] = b".rdata\0\0"
    struct.pack_into("<IIII", body, section + 8, 0x400, 0x1000, 0x400, 0x200)
    for index, name in enumerate(imports):
        descriptor = 0x200 + index * 20
        name_offset = 0x300 + index * 0x40
        name_rva = 0x1000 + (name_offset - 0x200)
        struct.pack_into("<IIIII", body, descriptor, 1, 0, 0, name_rva, 1)
        encoded = name.encode("ascii") + b"\0"
        body[name_offset : name_offset + len(encoded)] = encoded
    return bytes(body)
