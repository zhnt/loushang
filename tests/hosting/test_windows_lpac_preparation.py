from __future__ import annotations

import asyncio
import ctypes
import os
from collections.abc import Callable
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
from loushang.hosting._launch_preparation import _ManagedSpawnEffect
from loushang.hosting._win32_process import (
    _CREATE_SUSPENDED,
    _EXTENDED_STARTUPINFO_PRESENT,
    _PROC_THREAD_ATTRIBUTE_ALL_APPLICATION_PACKAGES_POLICY,
    _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
    _PROC_THREAD_ATTRIBUTE_JOB_LIST,
    _PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
    _PROCESS_CREATION_ALL_APPLICATION_PACKAGES_OPT_OUT,
    _PROCESS_INFORMATION,
    _CtypesWin32Api,
    _Win32AttributeList,
    _Win32CreateSettledWithoutProcess,
    _Win32LockedPathIdentity,
    _Win32LpacProfile,
    _Win32LpacTokenIdentity,
    _Win32ProfileAlreadyExists,
    _Win32ProfileNotFound,
    _Win32SpawnHandles,
)
from loushang.hosting._windows_launch_preparation import (
    _build_windows_lpac_launch_capture_spec,
    _fingerprint,
    _lpac_grant_targets,
    _lpac_private_grant_targets,
    _lpac_profile_name,
    _lpac_spec_fingerprint,
    _private_state_fingerprint,
    _WindowsLpacLaunchCaptureBackend,
    _WindowsLpacLaunchCaptureSpec,
    _WindowsLpacProfileCollision,
    _WindowsLpacProvisioner,
    _WindowsLpacProvisionSpec,
    _WindowsLpacProvisionWitness,
    _WindowsLpacRuntimeEntry,
)
from loushang.hosting._windows_process import _WindowsProcessBackend


def _request(
    *,
    environment: tuple[tuple[str, str], ...] = (),
) -> ProcessLaunchRequest:
    request = ProcessLaunchRequest(
        argv=(
            r"C:\admitted\runtime\worker.exe"
            if os.name == "nt"
            else "/admitted/runtime/worker.exe",
            "--probe",
        ),
        cwd=(
            r"C:\admitted\runtime\cwd" if os.name == "nt" else "/admitted/runtime/cwd"
        ),
        effective_environment=environment,
        streams=ProcessStreamSpec(
            stdin=ProcessStdinMode.CLOSED,
            stdout=ProcessStdoutMode.DISCARD,
            stderr=ProcessStderrMode.DISCARD,
        ),
    )
    if os.name != "nt":
        object.__setattr__(
            request,
            "argv",
            (r"C:\admitted\runtime\worker.exe", "--probe"),
        )
        object.__setattr__(request, "cwd", r"C:\admitted\runtime\cwd")
    return request


def _provision_spec() -> _WindowsLpacProvisionSpec:
    return _WindowsLpacProvisionSpec(
        request=_request(),
        runtime_root=r"C:\admitted\runtime",
        runtime_entries=(
            _WindowsLpacRuntimeEntry(".", 7, 100, 0, True, None),
            _WindowsLpacRuntimeEntry("cwd", 7, 102, 0, True, None),
            _WindowsLpacRuntimeEntry(
                "worker.exe",
                7,
                101,
                4096,
                False,
                "1" * 64,
            ),
        ),
        executable_relative_path="worker.exe",
        cwd_relative_path="cwd",
        platform_imports=("ADVAPI32.DLL", "KERNEL32.DLL"),
        platform_identity="windows-amd64-10.0.20348",
        attempt_id="attempt-7",
        operation_nonce="2" * 64,
        lifecycle_fingerprint="3" * 64,
    )


class _FakeWindowsLpacApi:
    def __init__(self) -> None:
        self.next_handle = 10
        self.handles: dict[int, str] = {}
        self.closed: list[int] = []
        self.freed_sids: list[int] = []
        self.profile_exists = False
        self.profile_foreign = False
        self.delete_missing = False
        self.private_present = True
        self.scratch_ready = False
        self.purged = False
        self.fail_stage: str | None = None
        self.access: dict[str, tuple[tuple[int, int], ...]] = {}
        self.spawn_calls: list[dict[str, object]] = []
        self.job_empty = False

    def platform_identity(self) -> str:
        return "windows-amd64-10.0.20348"

    def canonical_system_root(self) -> str:
        return r"C:\Windows"

    def create_lpac_profile(
        self,
        profile_name: str,
        *,
        on_acquired: Callable[[_Win32LpacProfile], None],
    ) -> _Win32LpacProfile:
        if self.profile_exists or self.profile_foreign:
            raise _Win32ProfileAlreadyExists(profile_name)
        self._fail("profile-create")
        self.profile_exists = True
        profile = self._profile()
        on_acquired(profile)
        return profile

    def derive_lpac_profile(self, profile_name: str) -> _Win32LpacProfile:
        assert profile_name.startswith("Loushang.Lpac.")
        self._fail("profile-derive")
        return self._profile()

    def delete_lpac_profile(self, profile_name: str) -> None:
        assert profile_name.startswith("Loushang.Lpac.")
        self._fail("profile-delete")
        if self.delete_missing or not self.profile_exists:
            raise _Win32ProfileNotFound(profile_name)
        self.profile_exists = False
        self.private_present = False

    def free_sid(self, sid: int) -> None:
        self.freed_sids.append(sid)

    def grant_lpac_path(
        self,
        path: str,
        sid: int,
        *,
        permissions: int,
        inherit: bool,
    ) -> None:
        assert sid == 500
        self._fail("grant")
        self.access[path] = ((permissions, 3 if inherit else 0),)

    def revoke_lpac_path(self, path: str, sid: int) -> None:
        assert sid == 500
        self._fail("revoke")
        self.access[path] = ()

    def lpac_path_access(
        self,
        path: str,
        sid: int,
    ) -> tuple[tuple[int, int], ...]:
        assert sid == 500
        return self.access.get(path, ())

    def file_stream_names(self, path: str) -> tuple[str, ...]:
        return ("::$DATA",)

    def ensure_lpac_private_scratch(self, private_root: str) -> None:
        assert private_root == r"C:\private\AC"
        self._fail("private-scratch")
        self.scratch_ready = True

    def purge_lpac_private_state(self, private_root: str) -> None:
        assert private_root == r"C:\private\AC"
        self._fail("private-purge")
        self.purged = True

    def open_locked_file(
        self,
        path: str,
        *,
        on_acquired: Callable[[int], None],
    ) -> int:
        return self._open(path, on_acquired)

    def open_locked_directory(
        self,
        path: str,
        *,
        on_acquired: Callable[[int], None],
    ) -> int:
        if path == r"C:\private\AC" and not self.private_present:
            raise FileNotFoundError(path)
        return self._open(path, on_acquired)

    def locked_path_identity(self, handle: int) -> _Win32LockedPathIdentity:
        path = self.handles[handle]
        identities = {
            r"C:\admitted\runtime": _Win32LockedPathIdentity(
                7, 100, 0, r"C:\admitted\runtime", True
            ),
            r"C:\admitted\runtime\cwd": _Win32LockedPathIdentity(
                7, 102, 0, r"C:\admitted\runtime\cwd", True
            ),
            r"C:\admitted\runtime\worker.exe": _Win32LockedPathIdentity(
                7, 101, 4096, r"C:\admitted\runtime\worker.exe", False
            ),
            r"C:\private\AC": _Win32LockedPathIdentity(
                8, 200, 0, r"C:\private\AC", True
            ),
        }
        return identities[path]

    def locked_file_sha256(self, handle: int) -> str:
        assert self.handles[handle].endswith("worker.exe")
        return "1" * 64

    def open_process_token(self) -> int:
        raise AssertionError("LPAC capture does not use a restricted token")

    def create_restricted_token(self, source_token: int) -> int:
        raise AssertionError("LPAC capture does not use a restricted token")

    def create_managed_job(
        self,
        *,
        on_acquired: Callable[[int], None],
    ) -> int:
        handle = self._allocate("job")
        self.handles[handle] = "job"
        on_acquired(handle)
        return handle

    def managed_job_is_kill_on_close(self, job: int) -> bool:
        return self.handles.get(job) == "job"

    def create_managed_stderr(self) -> int:
        handle = self._allocate("stderr")
        self.handles[handle] = "stderr"
        return handle

    def close_handle(self, handle: int) -> None:
        self.closed.append(handle)
        if self.handles.get(handle) == "job":
            self.job_empty = True

    def spawn_lpac(
        self,
        request: ProcessLaunchRequest,
        endpoint_handles: tuple[int, int],
        **kwargs: object,
    ) -> _Win32SpawnHandles:
        begin_effect = kwargs["begin_effect"]
        assert callable(begin_effect)
        begin_effect()
        self.spawn_calls.append(
            {"request": request, "endpoint": endpoint_handles, **kwargs}
        )
        return _Win32SpawnHandles(
            process=80,
            job=int(kwargs["job"]),
            stdin_write=None,
            stdout_read=None,
            stderr_read=None,
            cleanup_handles=(81, int(kwargs["stderr_handle"])),
        )

    def spawn_restricted(self, *args: object, **kwargs: object) -> _Win32SpawnHandles:
        raise AssertionError("LPAC capture does not use restricted spawn")

    def spawn(self, *args: object, **kwargs: object) -> _Win32SpawnHandles:
        raise AssertionError("LPAC capture requires managed spawn")

    def read_pipe(self, handle: int, max_bytes: int) -> bytes:
        return b""

    def write_pipe(self, handle: int, data: bytes) -> None:
        return None

    def wait_process(self, handle: int) -> int:
        return 0

    def process_return_code(self, handle: int) -> int | None:
        return 0

    def job_is_empty(self, handle: int) -> bool:
        return self.job_empty

    def terminate_job(self, handle: int, exit_code: int) -> None:
        self.job_empty = True

    def cancel_synchronous_io(self, thread_id: int) -> None:
        return None

    def _profile(self) -> _Win32LpacProfile:
        return _Win32LpacProfile(
            sid=500,
            sid_text="S-1-15-2-12345",
            private_root=r"C:\private\AC",
        )

    def _open(self, path: str, on_acquired: Callable[[int], None]) -> int:
        self._fail(f"open:{path}")
        handle = self._allocate("open")
        self.handles[handle] = path
        on_acquired(handle)
        return handle

    def _allocate(self, stage: str) -> int:
        self._fail(stage)
        handle = self.next_handle
        self.next_handle += 1
        return handle

    def _fail(self, stage: str) -> None:
        if self.fail_stage == stage:
            raise OSError(f"injected {stage} failure")


def _provisioned(
    monkeypatch: pytest.MonkeyPatch,
    *,
    api: _FakeWindowsLpacApi | None = None,
) -> tuple[
    _FakeWindowsLpacApi,
    _WindowsLpacProvisioner,
    _WindowsLpacProvisionSpec,
    _WindowsLpacProvisionWitness,
]:
    selected = api or _FakeWindowsLpacApi()
    monkeypatch.setattr(
        "loushang.hosting._windows_launch_preparation._verify_lpac_runtime",
        lambda _api, _spec: None,
    )
    owner = _WindowsLpacProvisioner(api=selected)
    spec = _provision_spec()
    witness = owner.create_profile(spec, begin_effect=lambda: None)
    witness = owner.apply_grants(spec, witness, begin_effect=lambda: None)
    witness = owner.verify(spec, witness)
    return selected, owner, spec, witness


def _capture_spec(
    monkeypatch: pytest.MonkeyPatch,
    api: _FakeWindowsLpacApi,
    provision: _WindowsLpacProvisionSpec,
    witness: _WindowsLpacProvisionWitness,
) -> _WindowsLpacLaunchCaptureSpec:
    if os.name != "nt":
        monkeypatch.setattr(Path, "is_absolute", lambda self: True)
    return _build_windows_lpac_launch_capture_spec(
        provision.request,
        provision=provision,
        witness=witness,
        _api=api,
    )


def test_windows_lpac_spec_is_exact_and_rejects_open_inputs() -> None:
    spec = _provision_spec()
    assert _lpac_profile_name(spec).startswith("Loushang.Lpac.")
    assert len(_lpac_profile_name(spec)) == len("Loushang.Lpac.") + 40
    assert _lpac_spec_fingerprint(spec) == _lpac_spec_fingerprint(spec)
    with pytest.raises(ValueError, match="no environment"):
        _WindowsLpacProvisionSpec(
            request=_request(environment=(("SECRET", "sentinel"),)),
            runtime_root=spec.runtime_root,
            runtime_entries=spec.runtime_entries,
            executable_relative_path=spec.executable_relative_path,
            cwd_relative_path=spec.cwd_relative_path,
            platform_imports=spec.platform_imports,
            platform_identity=spec.platform_identity,
            attempt_id=spec.attempt_id,
            operation_nonce=spec.operation_nonce,
            lifecycle_fingerprint=spec.lifecycle_fingerprint,
        )


def test_windows_lpac_provision_cleanup_is_exact_and_replayable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effects: list[str] = []
    api = _FakeWindowsLpacApi()
    monkeypatch.setattr(
        "loushang.hosting._windows_launch_preparation._verify_lpac_runtime",
        lambda _api, _spec: None,
    )
    owner = _WindowsLpacProvisioner(api=api)
    spec = _provision_spec()
    witness = owner.create_profile(spec, begin_effect=lambda: effects.append("create"))
    assert witness.state == "PROFILE_CREATED"
    assert "C:\\" not in repr(witness)
    witness = owner.apply_grants(
        spec,
        witness,
        begin_effect=lambda: effects.append("grant"),
    )
    assert witness.state == "GRANTS_APPLIED"
    assert api.scratch_ready
    root_target, root_permissions, root_inherit = _lpac_grant_targets(spec)[-1]
    assert (root_permissions, root_inherit) == (0x001200A9, True)
    assert api.access[root_target] == ((0x001200A9, 3),)
    private_root, private_temp = _lpac_private_grant_targets(r"C:\private\AC")
    assert private_root == (r"C:\private\AC", 0x001200A0, False)
    assert private_temp == (r"C:\private\AC\Temp", 0x001301FF, True)
    assert api.access[private_root[0]] == ((private_root[1], 0),)
    assert api.access[private_temp[0]] == ((private_temp[1], 3),)
    witness = owner.verify(spec, witness)
    assert witness.state == "VERIFIED"
    witness = owner.revoke_grants(
        spec,
        witness,
        begin_effect=lambda: effects.append("revoke"),
    )
    assert witness.state == "GRANTS_REVOKED"
    assert all(not matches for matches in api.access.values())
    witness = owner.delete_profile(
        spec,
        witness,
        begin_effect=lambda: effects.append("delete"),
    )
    assert witness.state == "PROFILE_DELETED"
    assert api.purged and not api.profile_exists
    settled = owner.settle(spec, witness)
    assert settled.state == "SETTLED"
    api.delete_missing = True
    replay = owner.delete_profile(
        spec,
        witness,
        begin_effect=lambda: effects.append("delete-replay"),
    )
    assert replay.state == "PROFILE_DELETED"
    assert effects == ["create", "grant", "revoke", "delete", "delete-replay"]


def test_windows_lpac_cleanup_witness_recovers_pre_receipt_crash() -> None:
    api = _FakeWindowsLpacApi()
    owner = _WindowsLpacProvisioner(api=api)
    spec = _provision_spec()

    # Product durably reserved the operation, native creation took effect,
    # then the host disappeared before it could publish the normal witness.
    owner.create_profile(spec, begin_effect=lambda: None)
    api.private_present = False
    recovered = owner.recover_cleanup_witness(spec)
    assert recovered.state == "DEBT"
    assert r"C:\private" not in repr(recovered)

    revoked = owner.revoke_grants(spec, recovered, begin_effect=lambda: None)
    assert revoked.state == "GRANTS_REVOKED"
    deleted = owner.delete_profile(spec, revoked, begin_effect=lambda: None)
    assert owner.settle(spec, deleted).state == "SETTLED"


def test_windows_lpac_foreign_profile_is_never_adopted() -> None:
    api = _FakeWindowsLpacApi()
    api.profile_foreign = True
    owner = _WindowsLpacProvisioner(api=api)
    with pytest.raises(_WindowsLpacProfileCollision) as failure:
        owner.create_profile(_provision_spec(), begin_effect=lambda: None)
    assert failure.value.category is HostingFailureCategory.PREPARATION_STALE
    assert not api.freed_sids


def test_windows_lpac_witness_and_dacl_substitution_fail_before_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, owner, spec, witness = _provisioned(monkeypatch)
    wrong = _WindowsLpacProvisionWitness(
        state=witness.state,
        attempt_id="other-attempt",
        operation_nonce=witness.operation_nonce,
        spec_fingerprint=witness.spec_fingerprint,
        profile_fingerprint=witness.profile_fingerprint,
        sid_fingerprint=witness.sid_fingerprint,
        private_state_fingerprint=witness.private_state_fingerprint,
        grant_digest=witness.grant_digest,
        platform_identity=witness.platform_identity,
    )
    effects: list[str] = []
    with pytest.raises(HostingError, match="does not match"):
        owner.revoke_grants(
            spec,
            wrong,
            begin_effect=lambda: effects.append("wrong"),
        )
    wrong_grant = _WindowsLpacProvisionWitness(
        state=witness.state,
        attempt_id=witness.attempt_id,
        operation_nonce=witness.operation_nonce,
        spec_fingerprint=witness.spec_fingerprint,
        profile_fingerprint=witness.profile_fingerprint,
        sid_fingerprint=witness.sid_fingerprint,
        private_state_fingerprint=witness.private_state_fingerprint,
        grant_digest="0" * 64,
        platform_identity=witness.platform_identity,
    )
    with pytest.raises(HostingError, match="does not match"):
        owner.revoke_grants(
            spec,
            wrong_grant,
            begin_effect=lambda: effects.append("grant-witness"),
        )
    root = _lpac_grant_targets(spec)[-1][0]
    api.access[root] = ((0xFFFFFFFF, 3),)
    with pytest.raises(HostingError, match="safely reconciled"):
        owner.revoke_grants(
            spec,
            witness,
            begin_effect=lambda: effects.append("dacl"),
        )
    assert effects == []


def test_windows_lpac_capture_uses_only_fixed_environment_and_exact_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, _, provision, witness = _provisioned(monkeypatch)
    spec = _capture_spec(monkeypatch, api, provision, witness)
    assert type(spec) is _WindowsLpacLaunchCaptureSpec
    assert dict(spec.request.effective_environment) == {
        "LOCALAPPDATA": r"C:\private\AC",
        "SystemRoot": r"C:\Windows",
        "TEMP": r"C:\private\AC\Temp",
        "TMP": r"C:\private\AC\Temp",
    }
    assert all("C:\\private" not in value for value in spec.execution_closure)
    with pytest.raises(HostingError, match="does not match"):
        _build_windows_lpac_launch_capture_spec(
            _request(environment=(("SECRET", "sentinel"),)),
            provision=provision,
            witness=witness,
            _api=api,
        )


def test_windows_lpac_capture_attaches_before_acquisition_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        api, _, provision, witness = _provisioned(monkeypatch)
        spec = _capture_spec(monkeypatch, api, provision, witness)
        api.fail_stage = f"open:{provision.runtime_root}"
        attached: list[object] = []
        with pytest.raises(OSError, match="injected"):
            await _WindowsLpacLaunchCaptureBackend(api=api).capture(
                spec,
                attempt_id="attempt-7",
                attempt_token=object(),
                on_capture=attached.append,
            )
        assert len(attached) == 1
        await attached[0].close()  # type: ignore[attr-defined]

    asyncio.run(run())


class _Endpoint:
    backend_id = "windows-job-v1"

    def __init__(self) -> None:
        self.transferred = False

    def claim(self, *, backend_id: str) -> tuple[int, int]:
        assert backend_id == self.backend_id
        return (70, 71)

    def mark_transferred(self) -> None:
        self.transferred = True

    async def close(self) -> None:
        return None


def test_windows_lpac_material_composes_exact_spawn_and_transfers_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        api, _, provision, witness = _provisioned(monkeypatch)
        spec = _capture_spec(monkeypatch, api, provision, witness)
        material = await _WindowsLpacLaunchCaptureBackend(api=api).capture(
            spec,
            attempt_id="attempt-7",
            attempt_token=object(),
            on_capture=lambda _: None,
        )
        await material.verify_current(spec.request)
        endpoint = _Endpoint()
        process = await material.spawn(
            _WindowsProcessBackend(max_processes=1, api=api),
            spec.request,
            effect=_ManagedSpawnEffect(),
            on_spawn=lambda _: None,
            inheritance=endpoint,
        )
        assert endpoint.transferred
        assert len(api.spawn_calls) == 1
        call = api.spawn_calls[0]
        assert call["endpoint"] == (70, 71)
        assert call["package_sid"] == 500
        assert call["expected_sid_text"] == "S-1-15-2-12345"
        await material.close()
        process.terminate_job(0xE0000006)
        await process.close_handles()

    asyncio.run(run())


class _RawLpacApi(_CtypesWin32Api):
    def __init__(
        self,
        *,
        reject_token: bool = False,
        previous_suspend_count: int = 1,
    ) -> None:
        self.reject_token = reject_token
        self.previous_suspend_count = previous_suspend_count
        self.deleted = 0
        self.effects = 0
        self.resumed = 0
        self.terminated = 0
        self.closed: list[int] = []
        self.creation_flags = 0
        self._DeleteProcThreadAttributeList = self._delete
        self._CreateProcessW = self._create_process
        self._ResumeThread = self._resume

    def _lpac_attribute_list(
        self,
        package_sid: int,
        job: int,
        inherited_handles: tuple[int, int, int],
    ) -> _Win32AttributeList:
        assert package_sid == 500
        assert job == 40
        assert inherited_handles == (10, 11, 41)
        storage = ctypes.create_string_buffer(8)
        return _Win32AttributeList(
            storage=storage,
            pointer=ctypes.cast(storage, ctypes.c_void_p),
            jobs=(ctypes.c_void_p * 1)(job),
            handles=(ctypes.c_void_p * 3)(*inherited_handles),
        )

    def locked_path_identity(self, handle: int) -> _Win32LockedPathIdentity:
        return _Win32LockedPathIdentity(
            7,
            handle,
            0 if handle == 31 else 4096,
            r"C:\admitted\runtime\cwd"
            if handle == 31
            else r"C:\admitted\runtime\worker.exe",
            handle == 31,
        )

    def lpac_process_identity(
        self,
        process: int,
        *,
        job: int,
    ) -> _Win32LpacTokenIdentity:
        assert self.resumed == 0
        return _Win32LpacTokenIdentity(
            sid_text="S-1-15-2-wrong" if self.reject_token else "S-1-15-2-12345",
            capability_count=0,
            is_app_container=True,
            is_lpac=True,
        )

    def terminate_job(self, handle: int, exit_code: int) -> None:
        self.terminated += 1

    def close_handle(self, handle: int) -> None:
        self.closed.append(handle)

    def _create_process(self, *arguments: object) -> int:
        self.creation_flags = int(arguments[5])
        information = ctypes.cast(
            arguments[-1],
            ctypes.POINTER(_PROCESS_INFORMATION),
        ).contents
        information.hProcess = 50
        information.hThread = 51
        return 1

    def _resume(self, thread: int) -> int:
        assert thread == 51
        self.resumed += 1
        return self.previous_suspend_count

    def _delete(self, pointer: ctypes.c_void_p) -> None:
        self.deleted += 1

    def _settle_rejected_lpac_process(
        self,
        *,
        process: int,
        thread: int,
        job: int,
    ) -> None:
        self.terminated += 1
        self.closed.extend((thread, process))


@pytest.mark.parametrize(("aap_member", "expected_lpac"), [(0, True), (1, False)])
def test_win32_lpac_identity_uses_aap_access_semantics(
    aap_member: int,
    expected_lpac: bool,
) -> None:
    api = _RawLpacApi()

    def duplicate(token: int, level: int, output: object) -> int:
        assert (token, level) == (50, 2)
        output._obj.value = 91  # type: ignore[attr-defined]
        return 1

    def create_sid(
        sid_type: int,
        domain: object,
        sid: object,
        size: object,
    ) -> int:
        assert sid_type == 84 and domain is None
        assert sid is not None and size._obj.value == 68  # type: ignore[attr-defined]
        return 1

    def check_membership(
        token: int,
        sid: object,
        flags: int,
        output: object,
    ) -> int:
        assert token == 91 and sid is not None and flags == 1
        output._obj.value = aap_member  # type: ignore[attr-defined]
        return 1

    api._DuplicateToken = duplicate  # type: ignore[method-assign]
    api._CreateWellKnownSid = create_sid  # type: ignore[method-assign]
    api._CheckTokenMembershipEx = check_membership  # type: ignore[method-assign]
    assert api._token_is_lpac(50) is expected_lpac
    assert api.closed == [91]


class _AttributeListApi(_CtypesWin32Api):
    def __init__(self) -> None:
        self.initialize_counts: list[int] = []
        self.attributes: list[int] = []
        self.deleted = 0
        self._InitializeProcThreadAttributeList = self._initialize
        self._UpdateProcThreadAttribute = self._update
        self._DeleteProcThreadAttributeList = self._delete

    def _initialize(
        self,
        pointer: ctypes.c_void_p | None,
        count: int,
        flags: int,
        size: object,
    ) -> int:
        assert flags == 0
        self.initialize_counts.append(count)
        if pointer is None:
            size._obj.value = 256  # type: ignore[attr-defined]
            return 0
        return 1

    def _update(
        self,
        pointer: ctypes.c_void_p,
        flags: int,
        attribute: int,
        value: object,
        value_size: int,
        previous: object,
        return_size: object,
    ) -> int:
        assert pointer and flags == 0 and value and value_size > 0
        assert previous is None and return_size is None
        self.attributes.append(attribute)
        return 1

    def _delete(self, pointer: ctypes.c_void_p) -> None:
        assert pointer
        self.deleted += 1


def test_win32_lpac_attribute_manifest_has_exact_four_entries() -> None:
    api = _AttributeListApi()
    attributes = api._lpac_attribute_list(500, 40, (10, 11, 41))
    try:
        assert api.initialize_counts == [4, 4]
        assert api.attributes == [
            _PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
            _PROC_THREAD_ATTRIBUTE_ALL_APPLICATION_PACKAGES_POLICY,
            _PROC_THREAD_ATTRIBUTE_JOB_LIST,
            _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
        ]
        assert attributes.security_capabilities is not None
        assert attributes.security_capabilities.AppContainerSid == 500
        assert attributes.security_capabilities.CapabilityCount == 0
        assert attributes.all_application_packages_policy is not None
        assert (
            attributes.all_application_packages_policy.value
            == _PROCESS_CREATION_ALL_APPLICATION_PACKAGES_OPT_OUT
        )
    finally:
        api._DeleteProcThreadAttributeList(attributes.pointer)
    assert api.deleted == 1


def test_win32_lpac_spawn_verifies_token_before_resume() -> None:
    api = _RawLpacApi()
    handles = api.spawn_lpac(
        _request(environment=(("SystemRoot", r"C:\Windows"),)),
        (10, 11),
        executable_handle=30,
        cwd_handle=31,
        package_sid=500,
        expected_sid_text="S-1-15-2-12345",
        job=40,
        stderr_handle=41,
        begin_effect=lambda: setattr(api, "effects", api.effects + 1),
    )
    assert handles.process == 50 and handles.job == 40
    assert api.effects == 1 and api.resumed == 1 and api.terminated == 0
    assert api.creation_flags & _CREATE_SUSPENDED
    assert api.creation_flags & _EXTENDED_STARTUPINFO_PRESENT
    assert api.deleted == 1


def test_win32_lpac_spawn_rejects_wrong_token_without_resume() -> None:
    api = _RawLpacApi(reject_token=True)
    with pytest.raises(_Win32CreateSettledWithoutProcess):
        api.spawn_lpac(
            _request(environment=(("SystemRoot", r"C:\Windows"),)),
            (10, 11),
            executable_handle=30,
            cwd_handle=31,
            package_sid=500,
            expected_sid_text="S-1-15-2-12345",
            job=40,
            stderr_handle=41,
            begin_effect=lambda: setattr(api, "effects", api.effects + 1),
        )
    assert api.effects == 1 and api.resumed == 0 and api.terminated == 1
    assert api.closed == [51, 50]


def test_win32_lpac_spawn_rejects_unexpected_suspend_state() -> None:
    api = _RawLpacApi(previous_suspend_count=0)
    with pytest.raises(_Win32CreateSettledWithoutProcess):
        api.spawn_lpac(
            _request(environment=(("SystemRoot", r"C:\Windows"),)),
            (10, 11),
            executable_handle=30,
            cwd_handle=31,
            package_sid=500,
            expected_sid_text="S-1-15-2-12345",
            job=40,
            stderr_handle=41,
            begin_effect=lambda: setattr(api, "effects", api.effects + 1),
        )
    assert api.effects == 1 and api.resumed == 1 and api.terminated == 1
    assert api.closed == [51, 50]


def test_win32_lpac_handle_alias_fails_before_effect() -> None:
    api = _RawLpacApi()
    effects: list[str] = []
    with pytest.raises(Exception) as failure:
        api.spawn_lpac(
            _request(),
            (10, 11),
            executable_handle=30,
            cwd_handle=31,
            package_sid=500,
            expected_sid_text="S-1-15-2-12345",
            job=40,
            stderr_handle=10,
            begin_effect=lambda: effects.append("effect"),
        )
    assert "collide" in str(failure.value.cause)
    assert effects == []


def test_windows_lpac_native_failures_redact_paths_and_sentinels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _FakeWindowsLpacApi()
    api.fail_stage = "profile-create"
    owner = _WindowsLpacProvisioner(api=api)
    sentinel = "secret-path-sentinel"
    with pytest.raises(HostingError) as failure:
        owner.create_profile(_provision_spec(), begin_effect=lambda: None)
    rendered = str(failure.value)
    assert sentinel not in rendered
    assert r"C:\admitted" not in rendered


def test_private_state_fingerprint_is_pathless() -> None:
    api = _FakeWindowsLpacApi()
    fingerprint = _private_state_fingerprint(api, r"C:\private\AC")
    assert fingerprint == _fingerprint(r"8:200:c:\private\ac")
    assert r"C:\private" not in fingerprint
