from __future__ import annotations

import ast
from pathlib import Path

HOSTING = Path("src/loushang/hosting")
NATIVE = HOSTING / "_windows_launch_preparation.py"
PROCESS = HOSTING / "_windows_process.py"
WIN32 = HOSTING / "_win32_process.py"
CORE = HOSTING / "_launch_preparation.py"
PUBLIC = (
    HOSTING / "__init__.py",
    HOSTING / "contracts.py",
    HOSTING / "runtime.py",
)
UNIT_TESTS = Path("tests/hosting/test_windows_launch_preparation.py")
NATIVE_TESTS = Path("tests/hosting/test_windows_launch_preparation_native.py")
PLATFORM_TESTS = Path("tests/hosting/test_windows_launch_preparation_platform.py")
WORKFLOW = Path(".github/workflows/hosting-quality.yml")
RECORD = (
    Path("docs/internals/architecture/hosting/validation")
    / "managed-launch-preparation-h6-windows-native.md"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_names(path: Path) -> set[str]:
    return {
        node.name
        for node in ast.parse(_read(path), filename=str(path)).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_h6_3_windows_profile_is_private_exact_and_default_dark() -> None:
    native = _read(NATIVE)
    public = "\n".join(_read(path) for path in PUBLIC)

    for name in (
        "_WindowsRestrictedLaunchCaptureSpec",
        "_WindowsRestrictedLaunchCaptureBackend",
        "_WindowsRestrictedLaunchMaterial",
    ):
        assert name in native
        assert name not in public
    for exact_identity in (
        '"windows-restricted-direct-import-pe-v1"',
        '"restricted-token:disable-max-privilege+lua+write-restricted"',
        '"+disable-administrators-sid-v1"',
        'frozenset({"ADVAPI32.DLL", "KERNEL32.DLL"})',
        "_PE_AMD64_MACHINE",
        "_IMAGE_DIRECTORY_ENTRY_RESOURCE",
        "_IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT",
        "_IMAGE_DIRECTORY_ENTRY_COM_DESCRIPTOR",
    ):
        assert exact_identity in native
    assert "__all__: list[str] = []" in native
    assert "_windows_launch_preparation" not in public


def test_h6_3_spawn_uses_one_restricted_effect_and_exact_owner_transfer() -> None:
    native = _read(NATIVE)
    process = _read(PROCESS)
    win32 = _read(WIN32)
    core = _read(CORE)

    assert "on_capture(material)" in native
    assert native.index("on_capture(material)") < native.index("material._capture()")
    for operation in (
        "open_locked_file",
        "open_locked_directory",
        "open_process_token",
        "create_restricted_token",
        "create_managed_job",
        "create_managed_stderr",
        "managed_job_is_kill_on_close",
    ):
        assert operation in native
        assert operation in win32
    assert "set(endpoint_handles) & set(preparation_handles)" in process
    assert "self._api.spawn_restricted" in process
    assert "begin_effect=effect.begin_effect" in process
    assert "_CreateProcessAsUserW" in win32
    assert "_CreateWellKnownSid" in win32
    assert "_WIN_BUILTIN_ADMINISTRATORS_SID" in win32
    assert "_GetFileInformationByHandleEx" in win32
    assert "_FILE_ID_INFO" in win32
    assert "on_acquired(handle)" in win32
    assert win32.index("begin_effect()") < win32.index("self._CreateProcessAsUserW(")
    assert "_PROC_THREAD_ATTRIBUTE_HANDLE_LIST" in win32
    assert "_PROC_THREAD_ATTRIBUTE_JOB_LIST" in win32
    assert "_Win32CreateSettledWithoutProcess" in win32
    assert "effect.settled_without_process" in process
    assert "_ManagedSpawnSettledWithoutProcess" in core


def test_h6_3_windows_native_oracle_and_report_are_retained() -> None:
    unit_names = _function_names(UNIT_TESTS)
    for name in (
        "test_windows_restricted_capture_attaches_before_every_acquisition_failure",
        "test_windows_restricted_material_composes_exact_spawn_and_transfers_owners",
        "test_windows_restricted_create_failure_has_exact_settled_receipt",
        "test_windows_restricted_setup_failure_has_pre_effect_receipt",
        "test_windows_restricted_post_gate_failure_remains_fenced",
        "test_windows_restricted_post_create_owner_is_reclaimable",
        "test_windows_restricted_handle_collision_fails_before_effect",
        "test_windows_restricted_close_retries_retained_handle",
        "test_windows_restricted_verify_rejects_rebound_ancestor_relation",
        "test_win32_restricted_token_uses_the_exact_profile_flags",
        "test_windows_pe_parser_accepts_exact_amd64_direct_import_profile",
        "test_windows_pe_parser_rejects_open_or_wrong_closure",
    ):
        assert name in unit_names
    native_names = _function_names(NATIVE_TESTS)
    assert {
        "test_windows_restricted_native_locks_identity_and_runs_restricted",
        "test_windows_restricted_native_job_reclaims_descendant",
    } <= native_names
    assert (
        "test_windows_restricted_native_backend_is_exact_platform_or_fails_closed"
        in _function_names(PLATFORM_TESTS)
    )
    workflow = _read(WORKFLOW)
    assert "tests/hosting/test_windows_launch_preparation_native.py" in workflow
    assert "h6-windows-native.xml" in workflow
    assert "verify_pytest_xml.py" in workflow
    assert RECORD.is_file()
