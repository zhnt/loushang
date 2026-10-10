from __future__ import annotations

import asyncio
import csv
import ctypes
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from base64 import urlsafe_b64encode
from collections.abc import Iterator
from ctypes import wintypes
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from struct import pack_into
from time import monotonic
from unittest.mock import patch

import pytest

import loushang.coding.package_installation_private_data as arch_private_data_module
import loushang.coding.package_legacy_windows_receipt as windows_receipt_module
import loushang.coding.package_private_data_windows_backup as windows_backup_module
import loushang.coding.package_private_data_windows_backup_expiry_owner as windows_expiry_module
import loushang.coding.package_private_data_windows_deletion_owner as windows_deletion_module
import loushang.coding.package_private_data_windows_restore_owner as windows_restore_module
import loushang.coding.package_product_backup_types as backup_types_module
import loushang.coding.package_product_worker_windows_payload as windows_payload_module
from loushang.ai.model import Capabilities, Model
from loushang.coding._plugin_lifecycle import (
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding._product_worker_canary import (
    CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID,
)
from loushang.coding.arch.cache import (
    ImportFactCache,
    ImportFactCacheNamespace,
    ImportFactCacheSnapshot,
    import_cache_root_id,
)
from loushang.coding.bootstrap import (
    create_agent_session,
    create_agent_session_runtime,
    create_services,
)
from loushang.coding.cli.package_cutover import main as cutover_cli_main
from loushang.coding.cli.package_gc import main as gc_cli_main
from loushang.coding.cli.package_worker_windows_candidate import (
    main as windows_worker_candidate_main,
)
from loushang.coding.package_arch_private_cache import (
    write_coding_arch_private_windows_snapshot,
)
from loushang.coding.package_cutover_backup import (
    inspect_coding_package_cutover_backup,
)
from loushang.coding.package_epoch_layout import resolve_coding_package_epoch_layout
from loushang.coding.package_external_worker_wheel import (
    CodingExternalWorkerWheelError,
    CodingWindowsExternalWorkerWheelCatalog,
)
from loushang.coding.package_installation_private_data import (
    coding_arch_installation_private_data_root,
    inspect_coding_windows_arch_installation_root,
    prepare_coding_product_arch_private_data_root,
)
from loushang.coding.package_legacy_builtin_acceptance import (
    CodingLegacyBuiltinOnlyAcceptanceError,
    accept_coding_first_b_builtin_only,
    read_coding_first_b_builtin_only_acceptance,
)
from loushang.coding.package_legacy_builtin_adoption import (
    adopt_coding_first_b_builtin_only,
)
from loushang.coding.package_legacy_builtin_review import (
    admit_coding_builtin_only_snapshot,
    review_coding_first_b_builtin_only,
)
from loushang.coding.package_legacy_installation_inventory import (
    read_coding_legacy_installation_inventory,
)
from loushang.coding.package_legacy_snapshot_member import (
    CodingFirstBLegacyStateObserver,
    CodingLegacySnapshotError,
    list_coding_first_b_snapshot_domain_members,
    read_coding_first_b_snapshot_member,
)
from loushang.coding.package_legacy_windows_receipt import (
    CodingWindowsPrivateReceiptError,
    write_windows_private_receipt,
)
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
    prepare_and_cutover_coding_package_store_from_legacy,
    prepare_coding_package_cutover_roots,
    reopen_coding_package_cutover,
)
from loushang.coding.package_private_data_backup_records import (
    backup_id,
    backup_parent,
)
from loushang.coding.package_private_data_windows_backup import (
    CodingWindowsArchPrivateDataBackupOwner,
)
from loushang.coding.package_private_data_windows_backup_client import (
    open_coding_windows_arch_backup_candidate_client,
)
from loushang.coding.package_private_data_windows_confirmation import (
    CodingWindowsArchPrivateDataConfirmationOwner,
)
from loushang.coding.package_private_data_windows_deletion_journal import (
    CodingWindowsArchPrivateDataDeletionJournal,
    windows_arch_deletion_receipt_id,
)
from loushang.coding.package_private_data_windows_deletion_owner import (
    CodingWindowsArchPrivateDataDeletionOwner,
)
from loushang.coding.package_private_data_windows_preview import (
    CodingWindowsArchPrivateDataReadPreview,
)
from loushang.coding.package_private_data_windows_restore_preview import (
    CodingWindowsArchPrivateDataRestorePreview,
)
from loushang.coding.package_product_runtime import (
    CodingFencedProductApplicationSelection,
    admit_coding_external_worker_wheel,
    bootstrap_coding_builtin_product_plugins,
    open_coding_builtin_product_runtime_owner,
    open_coding_fenced_product_application_owner,
    open_coding_package_product_state,
)
from loushang.coding.package_product_worker_activation_state import (
    open_coding_windows_product_worker_activation_state_store,
)
from loushang.coding.package_product_worker_native_approval import (
    CodingWorkerNativeApprovalError,
    CodingWorkerNativeReleaseApprovalV1,
)
from loushang.coding.package_product_worker_opt_in import (
    CodingWorkerOptInJournalError,
)
from loushang.coding.package_product_worker_opt_in_owner import (
    CodingWorkerProductOptInError,
)
from loushang.coding.package_product_worker_policy import (
    CodingWorkerOptInV1,
    coding_worker_session_scope_id,
)
from loushang.coding.package_product_worker_provider import (
    CodingWorkerProviderCandidateError,
    coding_worker_query_capability_provider,
    prepare_coding_selected_worker_provider_candidate,
)
from loushang.coding.package_product_worker_query_consumer import (
    CODING_WORKER_QUERY_DEFINITION,
    bind_coding_worker_query_consumer,
)
from loushang.coding.package_product_worker_receipt import CodingWorkerReceiptError
from loushang.coding.package_product_worker_windows_activation_state_journal import (
    CodingWindowsWorkerActivationStateJournal,
)
from loushang.coding.package_product_worker_windows_backend_release import (
    review_coding_windows_worker_backend_release,
)
from loushang.coding.package_product_worker_windows_cleanup_evidence import (
    CodingWindowsWorkerCleanupEvidenceAuthority,
)
from loushang.coding.package_product_worker_windows_crash_c5_settlement import (
    settle_coding_windows_product_worker_crash_c5,
)
from loushang.coding.package_product_worker_windows_crash_cleanup_review import (
    review_coding_windows_product_worker_crash_cleanup,
)
from loushang.coding.package_product_worker_windows_crash_lease_repair import (
    repair_coding_windows_product_worker_crash_orphan_runtime,
    review_coding_windows_product_worker_crash_lease_repair,
)
from loushang.coding.package_product_worker_windows_crash_native_settlement import (
    settle_coding_windows_product_worker_crash_native,
)
from loushang.coding.package_product_worker_windows_crash_recovery import (
    recover_coding_windows_product_worker_crash_attempt,
)
from loushang.coding.package_product_worker_windows_crash_stage_retirement import (
    retire_coding_windows_product_worker_crash_stage,
)
from loushang.coding.package_product_worker_windows_crash_stage_review import (
    review_coding_windows_product_worker_crash_stage,
)
from loushang.coding.package_product_worker_windows_crash_supervisor_settlement import (
    settle_coding_windows_product_worker_crash_supervisor,
)
from loushang.coding.package_product_worker_windows_gc_history import (
    CodingWindowsWorkerGcHistoryAuthority,
)
from loushang.coding.package_product_worker_windows_installed_backend import (
    CodingWindowsWorkerInstalledBackendError,
    CodingWindowsWorkerInstalledBackendReader,
    install_coding_windows_worker_backend_release,
    read_coding_windows_worker_installed_backend_release,
)
from loushang.coding.package_product_worker_windows_launch_intent import (
    CodingWindowsWorkerLaunchIntentError,
    CodingWindowsWorkerLaunchIntentV1,
    commit_coding_windows_product_worker_launch_intent,
    inspect_coding_windows_product_worker_launch_intents,
    read_coding_windows_product_worker_launch_intent,
)
from loushang.coding.package_product_worker_windows_native_approval_journal import (
    CodingWindowsWorkerNativeApprovalJournal,
)
from loushang.coding.package_product_worker_windows_native_approval_owner import (
    CodingWindowsWorkerNativeApprovalOwner,
)
from loushang.coding.package_product_worker_windows_opt_in_journal import (
    CodingWindowsWorkerOptInJournal,
)
from loushang.coding.package_product_worker_windows_opt_in_owner import (
    CodingWindowsWorkerProductOptInOwner,
)
from loushang.coding.package_product_worker_windows_orphan_review import (
    repair_coding_windows_product_worker_clean_exit_orphan_runtime,
    review_coding_windows_product_worker_orphan_runtime,
)
from loushang.coding.package_product_worker_windows_partial_stage_retirement import (
    retire_coding_windows_product_worker_partial_stage,
)
from loushang.coding.package_product_worker_windows_partial_stage_review import (
    review_coding_windows_product_worker_partial_stage,
)
from loushang.coding.package_product_worker_windows_payload import (
    CodingWindowsWorkerPayloadMaterializationError,
    bind_coding_windows_product_worker_launch_request,
    materialize_coding_windows_product_worker_payload,
    plan_coding_windows_product_worker_pending_launch,
)
from loushang.coding.package_product_worker_windows_payload_inventory import (
    inspect_coding_windows_product_worker_payload_attempts,
)
from loushang.coding.package_product_worker_windows_provisioning import (
    inspect_coding_windows_product_worker_provisioning_attempts,
    open_coding_windows_product_worker_provisioning_state_store,
)
from loushang.coding.package_product_worker_windows_receipt import (
    open_coding_windows_product_selected_worker_receipt_owner,
    read_coding_windows_product_worker_receipt_record,
)
from loushang.coding.package_product_worker_windows_receipt_journal import (
    CodingWindowsWorkerReceiptJournal,
)
from loushang.coding.package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAdmissionError,
    inspect_coding_windows_product_worker_attempt_gc_observations,
    inspect_coding_windows_product_worker_attempt_references,
    inspect_coding_windows_product_worker_offline_recovery,
    inspect_coding_windows_product_worker_recovery_inventory,
)
from loushang.coding.package_product_worker_windows_stage_retirement import (
    retire_coding_windows_product_worker_complete_stage,
)
from loushang.coding.package_product_worker_windows_stage_review import (
    CodingWindowsWorkerStageReviewError,
    review_coding_windows_product_worker_complete_stage,
)
from loushang.coding.package_product_worker_windows_supervisor_journal import (
    open_coding_windows_product_worker_supervisor_journal,
)
from loushang.coding.session_manager import SessionManager
from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product.product_gc_executor import (
    PackageProductGcExecutionError,
    PackageProductRootGcCommandV1,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_root_gc_runtime import (
    open_windows_local_wheel_product_root_gc,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
    PackageProductRuntimeRequestV1,
)
from loushang.harness.package_product.product_worker_candidate import (
    verify_product_selected_worker_candidate,
)
from loushang.harness.plugin_management import PluginManagementQueryV1
from loushang.harness.plugin_management.application import (
    PluginManagementReadModelProjector,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.package_gc_target import (
    resolve_plugin_package_gc_root_target,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionReceiptV1,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.plugin_management.service import PluginManagementService
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.offline_restore import (
    PackageOfflineRestoreError,
    PackageOfflineRestoreOwner,
    PackageOfflineRestoreRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_offline_restore import (
    PackageWindowsOfflineRestoreMaterializer,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_pre_fence_registration import (
    PackageWindowsPreFenceRegistrationOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleIntentV1,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelDependencyV1,
    PackageProductLocalWorkerAdmissionV1,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
    PackageWindowsCurrentEpochCutoverCoordinationOwner,
    prepare_windows_product_private_directory_chain,
)
from loushang.harness.resources.packages.product_windows_pre_b_snapshot import (
    read_windows_product_pre_b_snapshot,
)
from loushang.harness.sandbox.package_windows_legacy_runtime import (
    PackageWindowsLegacyRuntimeActivationOwner,
)
from loushang.harness.transcript.directory import AgentTranscriptDirectoryRuntime
from loushang.harness.worker import (
    ManagedWorkerLaunchRequestV1,
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
    WorkerBindingError,
    WorkerLaunchIdentityV1,
    WorkerRuntimeBindingV1,
    WorkerSupervisor,
    WorkerSupervisorJournalError,
)
from loushang.harness.worker._native_profile_bridge import (
    _bind_windows_lpac_contained_product_worker_profile,
    _windows_lpac_provisioning_identity,
    _WindowsLpacProductWorkerProfilePlan,
    _WindowsNativeContainmentSettlementWitness,
)
from loushang.harness.worker.facet_proxy import CapabilityWorkerFacetProxyError
from loushang.harness.worker.hosting_adapter import (
    HostingManagedWorkerSessionAdapter,
)
from loushang.harness.worker.product_activation import (
    WorkerCleanupSettlementV2,
    _AttemptKey,
    _initial_state,
)
from loushang.hosting._windows_lpac_runtime import (
    _create_windows_lpac_child_session_host,
)
from loushang.hosting.windows_backend_material import (
    WINDOWS_LPAC_PLATFORM_IMPORTS,
    verify_windows_backend_material_expectation,
)
from loushang.plugin._coding_local_worker_wheel import (
    build_coding_local_worker_candidate_wheel,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows-native contract")


def _grant_windows_world_read(path: Path) -> None:
    """Tamper a native DACL through an extended-length path."""

    with WindowsPrivateDirectoryAcl() as acl:
        descriptor = ctypes.c_void_p()
        try:
            sddl = (
                "D:P"
                + "".join(
                    f"(A;;FA;;;{sid})" for sid in sorted({acl._user_sid, "S-1-5-18"})
                )
                + "(A;;FR;;;WD)"
            )
            assert acl._security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(descriptor), None
            )
            present = wintypes.BOOL()
            defaulted = wintypes.BOOL()
            dacl = ctypes.c_void_p()
            assert acl._security.GetSecurityDescriptorDacl(
                descriptor,
                ctypes.byref(present),
                ctypes.byref(dacl),
                ctypes.byref(defaulted),
            )
            assert present.value and dacl.value
            change = acl._security.SetNamedSecurityInfoW
            change.argtypes = (
                wintypes.LPWSTR,
                ctypes.c_int,
                wintypes.DWORD,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
            )
            change.restype = wintypes.DWORD
            result = change(
                "\\\\?\\" + str(path), 1, 0x80000004, None, None, dacl, None
            )
            assert result == 0, f"SetNamedSecurityInfoW failed: {result}"
        finally:
            if descriptor.value is not None:
                assert not acl._kernel.LocalFree(descriptor)


def _compile_windows_query_worker(build_root: Path, executable: Path) -> None:
    """Build the same bounded protocol fixture used by the Linux Product gate."""

    source = (
        Path(__file__).resolve().parents[1] / "fixtures/worker/contained_query_worker.c"
    )
    compiler = shutil.which("cl")
    arguments = (
        compiler or "cl",
        "/nologo",
        "/O2",
        "/MT",
        f"/Fo:{build_root / 'contained_query_worker.obj'}",
        f"/Fe:{executable}",
        str(source),
        "/link",
        "/SUBSYSTEM:CONSOLE",
        "/MANIFEST:NO",
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
            capture_output=True,
            text=True,
            check=False,
        )
        installation = located.stdout.strip()
        vcvars = Path(installation) / "VC/Auxiliary/Build/vcvars64.bat"
        if located.returncode != 0 or not installation or not vcvars.is_file():
            pytest.fail("Windows Worker native gate requires the MSVC compiler")
        build_script = build_root / "build-query-worker.cmd"
        build_script.write_text(
            "@echo off\n"
            f'call "{vcvars}" >nul\n'
            "if errorlevel 1 exit /b %errorlevel%\n"
            f"{subprocess.list2cmdline(list(arguments))}\n",
            encoding="utf-8",
        )
        command = ("cmd", "/d", "/c", str(build_script))
    compiled = subprocess.run(
        command,
        cwd=build_root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if compiled.returncode != 0:
        pytest.fail(
            "Windows Worker native fixture compilation failed: "
            f"{compiled.stdout}\n{compiled.stderr}"
        )
    smoke = subprocess.run(
        (str(executable),),
        cwd=executable.parent,
        env={},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert smoke.returncode == 10, smoke.stderr


def test_windows_worker_candidate_requires_explicit_windows_product_flag(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    with pytest.raises(RuntimeError, match="Windows Product Session route"):
        open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
            worker_candidates=True,
        )
    assert list(workspace.iterdir()) == []


@pytest.mark.parametrize(
    "legacy_kind",
    (
        "global_settings",
        "project_settings",
        "custom_global_settings",
        "custom_project_settings",
        "desired_state",
        "package_lock",
    ),
)
def test_windows_public_ordinary_session_preserves_pre_b_without_writing(
    tmp_path: Path, legacy_kind: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    if legacy_kind == "global_settings":
        (tmp_path / "global-settings.json").write_text(
            json.dumps({"disabled_plugins": ["coding.base"]}), encoding="utf-8"
        )
    elif legacy_kind == "project_settings":
        settings = workspace / ".loushang" / "settings.json"
        settings.parent.mkdir()
        settings.write_text(
            json.dumps({"disabled_plugins": ["coding.base"]}), encoding="utf-8"
        )
    elif legacy_kind == "custom_global_settings":
        custom_global_settings = tmp_path / "custom-global" / "settings.json"
        custom_global_settings.parent.mkdir()
        custom_global_settings.write_text(
            json.dumps({"disabled_plugins": ["coding.base"]}), encoding="utf-8"
        )
    elif legacy_kind == "custom_project_settings":
        custom_project_settings = workspace / "custom-project" / "settings.json"
        custom_project_settings.parent.mkdir()
        custom_project_settings.write_text(
            json.dumps({"disabled_plugins": ["coding.base"]}), encoding="utf-8"
        )
    elif legacy_kind == "desired_state":
        lifecycle.root.mkdir(parents=True)
        lifecycle.desired_state.write_bytes(b"old Desired State must survive\n")
    else:
        lifecycle.package_root.mkdir(parents=True)
        (lifecycle.package_root / "package-lock.json").write_bytes(
            b"old Package lock must survive\n"
        )
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=False
        )
    )
    services = None
    if legacy_kind in {"custom_global_settings", "custom_project_settings"}:
        services = create_services(
            settings_manager=SettingsManager(
                global_settings_path=(
                    custom_global_settings
                    if legacy_kind == "custom_global_settings"
                    else tmp_path / "custom-global" / "settings.json"
                ),
                project_settings_path=(
                    custom_project_settings
                    if legacy_kind == "custom_project_settings"
                    else workspace / "custom-project" / "settings.json"
                ),
            )
        )

    def snapshot() -> tuple[tuple[str, bytes | None], ...]:
        return tuple(
            sorted(
                (
                    path.relative_to(tmp_path).as_posix(),
                    path.read_bytes() if path.is_file() else None,
                )
                for path in tmp_path.rglob("*")
            )
        )

    before = snapshot()
    with (
        patch(
            "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
        patch(
            "loushang.coding.package_product_runtime.default_global_settings_path",
            return_value=tmp_path / "global-settings.json",
        ),
    ):
        with pytest.raises(RuntimeError, match="pre-B workspace is unsupported"):
            create_agent_session(session_manager=manager, services=services)
    assert snapshot() == before


def test_windows_explicit_unadmitted_selection_keeps_fresh_product_closed(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=False
        )
    )
    selection = CodingFencedProductApplicationSelection()
    with (
        patch(
            "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
        patch(
            "loushang.coding.package_product_runtime.default_global_settings_path",
            return_value=tmp_path / "global-settings.json",
        ),
    ):
        assert selection.factory_for_session(manager) is None
    selection.close()
    assert not lifecycle.root.exists()
    assert not lifecycle.package_root.exists()


def _windows_ordinary_test_model() -> Model:
    return Model(
        id="plc9-windows-ordinary",
        name="PLC9 Windows Ordinary",
        provider="test",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )


def test_windows_public_ordinary_session_enters_fresh_b_product(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=False
        )
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    with (
        patch(
            "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
        patch(
            "loushang.coding.package_product_runtime.default_global_settings_path",
            return_value=tmp_path / "global-settings.json",
        ),
        patch("loushang.coding.package_product_runtime.version", return_value="2.0.0"),
        patch(
            "loushang.coding.bootstrap.prepare_managed_coding_base_plugin_assembly",
            side_effect=AssertionError("legacy base assembly"),
        ),
        patch(
            "loushang.coding.bootstrap._default_package_materializer",
            side_effect=AssertionError("legacy package materializer"),
        ),
    ):
        session = create_agent_session(
            session_manager=manager,
            model=_windows_ordinary_test_model(),
            services=create_services(settings_manager=settings),
            composition_set="coding-standard",
        )
        try:
            assert session.package_product_lifecycle_mode == "enforced"
            assert session.package_product_binding_id is not None
            assert session._package_controller.get_package_materializer() is None
        finally:
            asyncio.run(session.dispose())
    assert reopen_coding_package_cutover(lifecycle).disposition == "fenced"
    assert not lifecycle.desired_state.exists()
    assert not (lifecycle.package_root / "package-lock.json").exists()


def test_windows_public_runtime_session_enters_fresh_b_product(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    with (
        patch(
            "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
        patch(
            "loushang.coding.package_product_runtime.default_global_settings_path",
            return_value=tmp_path / "global-settings.json",
        ),
        patch("loushang.coding.package_product_runtime.version", return_value="2.0.0"),
        patch(
            "loushang.coding.bootstrap.prepare_managed_coding_base_plugin_assembly",
            side_effect=AssertionError("legacy base assembly"),
        ),
        patch(
            "loushang.coding.bootstrap._default_package_materializer",
            side_effect=AssertionError("legacy package materializer"),
        ),
    ):
        runtime = create_agent_session_runtime(
            session_dir=tmp_path / "runtime-sessions",
            model=_windows_ordinary_test_model(),
            services=create_services(settings_manager=settings),
        )

        async def create_and_close() -> None:
            try:
                session = await runtime.create_session(cwd=str(workspace))
                assert session.package_product_lifecycle_mode == "enforced"
                assert session.package_product_binding_id is not None
                assert session._package_controller.get_package_materializer() is None
            finally:
                await runtime.dispose_session_runtime()

        asyncio.run(create_and_close())
    assert reopen_coding_package_cutover(lifecycle).disposition == "fenced"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native orphan lock")
def test_windows_ordinary_orphan_repair_refuses_worker_evidence(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=False
        )
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    with (
        patch(
            "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
        patch(
            "loushang.coding.package_product_runtime.default_global_settings_path",
            return_value=tmp_path / "global-settings.json",
        ),
        patch("loushang.coding.package_product_runtime.version", return_value="2.0.0"),
    ):
        selection = CodingFencedProductApplicationSelection(windows_candidate=True)
        try:
            factory = selection.factory_for_session(manager, settings_manager=settings)
            assert factory is not None
            factory.dispose_unbound_runtime()
        finally:
            selection.close()

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    runtime_id = (
        "coding-session:"
        + sha256(manager.get_header().conversation_id.encode()).hexdigest()
    )
    child = "\n".join(
        (
            "import os, sys",
            "from pathlib import Path",
            "from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import PackageEpochFenceJournal",
            "from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import PackageWindowsEpochRuntimeLeaseRegistry",
            "registry = PackageWindowsEpochRuntimeLeaseRegistry(control_root=Path(sys.argv[1]), fences=PackageEpochFenceJournal(Path(sys.argv[2])), store_id=sys.argv[3])",
            "registry.register(runtime_id=sys.argv[4], runtime_protocol_epoch=2)",
            "os._exit(0)",
        )
    )
    subprocess.run(
        [
            sys.executable,
            "-c",
            child,
            str(epoch.control_root),
            str(epoch.control_root / "epoch.jsonl"),
            epoch.store_id,
            runtime_id,
        ],
        check=True,
        timeout=30,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    try:
        registry = owner.epoch_runtime.registry
        (orphan,) = registry.review_orphans(store_id=registry.store_id)
        assert orphan.runtime_id == runtime_id
        worker_evidence = (
            owner.runtime_owner.product_owner.state_root / "worker-start-gates.jsonl"
        )
        worker_evidence.write_bytes(b"")
        try:
            with pytest.raises(
                RuntimeError, match="Worker recovery requires explicit review"
            ):
                owner.factory_for_session(manager)
            assert registry.review_orphans(store_id=registry.store_id) == (orphan,)
        finally:
            worker_evidence.unlink()
        factory = owner.factory_for_session(manager)
        factory.dispose_unbound_runtime()
        assert registry.review_orphans(store_id=registry.store_id) == ()
    finally:
        owner.close()


def test_windows_candidate_ordinary_session_uses_fresh_b_product(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=False
        )
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    with (
        patch(
            "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
        patch(
            "loushang.coding.package_product_runtime.default_global_settings_path",
            return_value=tmp_path / "global-settings.json",
        ),
        patch("loushang.coding.package_product_runtime.version", return_value="2.0.0"),
        patch(
            "loushang.coding.bootstrap.prepare_managed_coding_base_plugin_assembly",
            side_effect=AssertionError("legacy base assembly"),
        ),
        patch(
            "loushang.coding.bootstrap._default_package_materializer",
            side_effect=AssertionError("legacy package materializer"),
        ),
    ):
        selection = CodingFencedProductApplicationSelection(
            windows_candidate=True, worker_candidates=True
        )
        try:
            factory = selection.factory_for_session(manager, settings_manager=settings)
            assert factory is not None
            worker_owner = selection.product_owner_for_factory(factory)
            assert isinstance(worker_owner, WindowsLocalWheelProductSessionOwner)
            assert worker_owner.management is factory.management
            foreign_selection = CodingFencedProductApplicationSelection(
                windows_candidate=True, worker_candidates=True
            )
            try:
                foreign_manager = asyncio.run(
                    SessionManager.new(
                        session_dir=tmp_path / "foreign-sessions",
                        cwd=str(workspace),
                        session_id="plc9-windows-foreign-owner",
                        persist=False,
                    )
                )
                foreign_factory = foreign_selection.factory_for_session(
                    foreign_manager, settings_manager=settings
                )
                assert foreign_factory is not None
                try:
                    with pytest.raises(RuntimeError, match="owner changed"):
                        selection.product_owner_for_factory(foreign_factory)
                finally:
                    foreign_factory.dispose_unbound_runtime()
            finally:
                foreign_selection.close()
            session = create_agent_session(
                session_manager=manager,
                model=Model(
                    id="plc9-windows-candidate",
                    name="PLC9 Windows Candidate",
                    provider="test",
                    endpoint="anthropic-messages",
                    capabilities=Capabilities(
                        reasoning=True,
                        input=("text",),
                        context_window=128000,
                        max_tokens=4096,
                    ),
                ),
                services=create_services(settings_manager=settings),
                composition_set="coding-standard",
                package_product_runtime_factory=factory,
            )
            try:
                assert session.package_product_lifecycle_mode == "enforced"
                assert session.package_product_binding_id is not None
                assert session._package_controller.get_package_materializer() is None
            finally:
                asyncio.run(session.dispose())
        finally:
            selection.close()
        assert reopen_coding_package_cutover(lifecycle).disposition == "fenced"
        assert not lifecycle.desired_state.exists()
        assert not (lifecycle.package_root / "package-lock.json").exists()
        resumed = CodingFencedProductApplicationSelection(windows_candidate=True)
        try:
            factory = resumed.factory_for_session(manager, settings_manager=settings)
            assert factory is not None
            binding = factory.create(
                PackageProductRuntimeRequestV1(
                    product_id="coding",
                    session_id=manager.get_header().conversation_id,
                    cwd=str(workspace),
                )
            )
            try:
                runtime = binding.activate()
                for plugin_id in (
                    "coding.base",
                    "coding.lsp.default",
                    "coding.arch.default",
                ):
                    assert (
                        runtime.capture_selected_plugin_manifest_for(
                            plugin_id, max_files=64, max_total_bytes=1024 * 1024
                        )
                        .verified_manifest()
                        .name
                        == plugin_id
                    )
            finally:
                binding.dispose_runtime()
        finally:
            resumed.close()
        owner = open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
            windows_candidate=True,
        )
        try:
            product = owner.runtime_owner.product_owner
            arch = next(
                item
                for item in product.desired_state.snapshot().installations
                if item.installation_key.plugin_id == "coding.arch.default"
            )
            disabled = product.management.submit(
                PluginManagementCommandV1(
                    action="disable",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id="operator:windows-fresh-disable-arch",
                        idempotency_key="operator:windows-fresh-disable-arch",
                        expected_inventory_revision=(
                            product.desired_state.snapshot().inventory_revision
                        ),
                        installation_key=arch.installation_key,
                        desired_state="installed_disabled",
                        package_revision=None,
                        actor_id="operator",
                        policy_revision=product.desired_policy_revision,
                    ),
                )
            )
            assert disabled.result is not None
            assert disabled.result.disposition == "succeeded"
        finally:
            owner.close()
        after_operator = CodingFencedProductApplicationSelection(windows_candidate=True)
        try:
            factory = after_operator.factory_for_session(
                manager, settings_manager=settings
            )
            assert factory is not None
            factory.dispose_unbound_runtime()
        finally:
            after_operator.close()
        owner = open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
            windows_candidate=True,
        )
        try:
            selected = owner.runtime_owner.product_owner.desired_state.snapshot()
            assert (
                next(
                    item.selection.desired_state
                    for item in selected.installations
                    if item.installation_key.plugin_id == "coding.arch.default"
                )
                == "installed_disabled"
            )
        finally:
            owner.close()


def _write_native_arch_cache(root: Path, workspace: Path) -> Path:
    cache_path = root / "import-facts-v1.json"
    cache = ImportFactCache(
        cache_path,
        max_bytes=4096,
        private_writer=write_coding_arch_private_windows_snapshot,
    )
    cache.replace(
        ImportFactCacheSnapshot(
            namespace=ImportFactCacheNamespace(
                root_id=import_cache_root_id(workspace),
                language="python",
                provider_version=1,
                package_prefix=None,
            ),
            module_index=(),
            entries=(),
        )
    )
    assert cache.last_error is None
    return cache_path


def _create_native_directory_stream(directory: Path) -> str:
    stream_path = str(directory) + ":hidden:$DATA"
    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    handle = create_file(
        stream_path,
        0x40000000,  # GENERIC_WRITE
        0x00000007,  # FILE_SHARE_READ | WRITE | DELETE
        None,
        4,  # OPEN_ALWAYS
        0x02000000,  # FILE_FLAG_BACKUP_SEMANTICS
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        raise getattr(ctypes, "WinError")(getattr(ctypes, "get_last_error")())
    assert close_handle(wintypes.HANDLE(handle))
    return stream_path


def test_windows_arch_private_data_uses_product_selected_native_acl(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        lifecycle,
        settings,
        workspace=workspace,
        namespace_id="f" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    arch_key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=lifecycle.scope_id,
        plugin_id="coding.arch.default",
    )
    product_state_root = (
        resolve_coding_package_epoch_layout(lifecycle).control_root / "product-state"
    )
    assert (
        inspect_coding_windows_arch_installation_root(
            lifecycle, arch_key, state_root=product_state_root
        )
        is None
    )
    assert not (lifecycle.package_root / "installation-private-data").exists()
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=False
        )
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    try:
        preview = CodingWindowsArchPrivateDataReadPreview(
            lifecycle, owner.runtime_owner.product_owner
        )
        assert preview.snapshot_for(arch_key).target_id.startswith("absent:")
        assert not (lifecycle.package_root / "installation-private-data").exists()
        factory = owner.factory_for_session(manager)
        binding = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding",
                session_id=manager.get_header().conversation_id,
                cwd=str(workspace),
            )
        )
        try:
            runtime = binding.activate()
            write_receipt = arch_private_data_module.write_windows_private_receipt
            interrupted = False

            def interrupt_first_root_receipt(path: Path, payload: bytes) -> None:
                nonlocal interrupted
                if (
                    path.name.startswith("arch-private-root-")
                    and not path.name.endswith(".intent.json")
                    and not interrupted
                ):
                    interrupted = True
                    raise RuntimeError("injected Arch root receipt interruption")
                write_receipt(path, payload)

            with patch.object(
                arch_private_data_module,
                "write_windows_private_receipt",
                interrupt_first_root_receipt,
            ):
                with pytest.raises(
                    RuntimeError, match="injected Arch root receipt interruption"
                ):
                    prepare_coding_product_arch_private_data_root(
                        lifecycle,
                        runtime,
                        session_id=manager.get_header().conversation_id,
                    )
            assert interrupted
            (pending_root,) = tuple(
                (lifecycle.package_root / "installation-private-data").iterdir()
            )
            pending_identity = pending_root.stat().st_dev, pending_root.stat().st_ino
            assert tuple(pending_root.iterdir()) == ()
            with pytest.raises(ValueError, match="receipt is incomplete"):
                inspect_coding_windows_arch_installation_root(
                    lifecycle, arch_key, state_root=product_state_root
                )
            root = prepare_coding_product_arch_private_data_root(
                lifecycle,
                runtime,
                session_id=manager.get_header().conversation_id,
            )
            assert root.parent.parent == pending_root
            assert (pending_root.stat().st_dev, pending_root.stat().st_ino) == (
                pending_identity
            )
            assert (
                inspect_coding_windows_arch_installation_root(
                    lifecycle, arch_key, state_root=product_state_root
                )
                == pending_identity
            )
            assert root.is_relative_to(lifecycle.package_root)
            assert root.is_dir()
            with (
                WindowsPrivateDirectoryAcl() as acl,
                WindowsPrivateDirectoryAcl(inherit_children=True) as session_acl,
            ):
                current = lifecycle.package_root
                for name in (None, *root.relative_to(current).parts):
                    if name is not None:
                        current /= name
                    descriptor = open_windows_directory(current, read_control=True)
                    try:
                        (session_acl if current == root else acl).validate(descriptor)
                    finally:
                        os.close(descriptor)
                cache_name = _write_native_arch_cache(root, workspace).name
                session_fd = open_windows_directory(root, read_control=True)
                try:
                    cache_fd = open_windows_regular_file_at(
                        session_fd,
                        cache_name,
                        create_new=False,
                        write=False,
                        read_control=True,
                    )
                    try:
                        session_acl.validate(cache_fd, inherited_file=True)
                    finally:
                        os.close(cache_fd)
                finally:
                    os.close(session_fd)
            installation_root = root.parent.parent
            original_root = installation_root.with_name(
                installation_root.name + ".original"
            )
            installation_root.rename(original_root)
            try:
                prepare_windows_product_private_directory_chain(
                    lifecycle.package_root,
                    "installation-private-data",
                    installation_root.name,
                )
                with pytest.raises(ValueError, match="Installation root changed"):
                    prepare_coding_product_arch_private_data_root(
                        lifecycle,
                        runtime,
                        session_id=manager.get_header().conversation_id,
                    )
                assert tuple(installation_root.iterdir()) == ()
            finally:
                installation_root.rmdir()
                original_root.rename(installation_root)
            assert (
                prepare_coding_product_arch_private_data_root(
                    lifecycle,
                    runtime,
                    session_id=manager.get_header().conversation_id,
                )
                == root
            )
            installation_parent = installation_root.parent
            original_parent = installation_parent.with_name(
                installation_parent.name + ".original"
            )
            installation_parent.rename(original_parent)
            try:
                prepare_windows_product_private_directory_chain(
                    lifecycle.package_root, "installation-private-data"
                )
                moved_root = installation_parent / installation_root.name
                (original_parent / installation_root.name).rename(moved_root)
                try:
                    assert (
                        moved_root.stat().st_dev,
                        moved_root.stat().st_ino,
                    ) == pending_identity
                    before = tuple(root.iterdir())
                    with pytest.raises(
                        ValueError,
                        match="Installation root changed|private-data root receipt changed",
                    ):
                        inspect_coding_windows_arch_installation_root(
                            lifecycle, arch_key, state_root=product_state_root
                        )
                    with pytest.raises(
                        ValueError,
                        match="Installation root changed|private-data root receipt changed",
                    ):
                        prepare_coding_product_arch_private_data_root(
                            lifecycle,
                            runtime,
                            session_id=manager.get_header().conversation_id,
                        )
                    assert tuple(root.iterdir()) == before
                finally:
                    moved_root.rename(original_parent / installation_root.name)
            finally:
                if installation_parent.exists():
                    installation_parent.rmdir()
                original_parent.rename(installation_parent)
            _grant_windows_world_read(root)
            before = tuple(root.iterdir())
            with pytest.raises(OSError):
                prepare_coding_product_arch_private_data_root(
                    lifecycle,
                    runtime,
                    session_id=manager.get_header().conversation_id,
                )
            assert tuple(root.iterdir()) == before
        finally:
            binding.dispose_runtime()
    finally:
        owner.close()


def test_windows_arch_private_data_confirmation_accepts_absent_target(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        lifecycle,
        settings,
        workspace=workspace,
        namespace_id="d" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    try:
        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=lifecycle.scope_id,
            plugin_id="coding.arch.default",
        )
        confirmations = CodingWindowsArchPrivateDataConfirmationOwner(
            lifecycle, owner.runtime_owner.product_owner
        )
        plan = confirmations.plan_for(key)
        assert plan.target_id.startswith("absent:")
        confirmation = PluginPrivateDataDeletionConfirmationV1(
            plan_fingerprint=plan.fingerprint,
            confirmation_id="arch-private-data:windows-absent",
        )
        confirmations.record_confirmation(
            plan,
            confirmation,
            actor_id="local-operator:windows-test",
            policy_revision="windows-private-data-test:1",
        )
        assert confirmations.is_confirmed(plan, confirmation)
        assert not coding_arch_installation_private_data_root(lifecycle, key).exists()
        product = owner.runtime_owner.product_owner
        journal = CodingWindowsArchPrivateDataDeletionJournal(lifecycle, product)
        target = CodingWindowsArchPrivateDataReadPreview(
            lifecycle, product
        ).snapshot_for(key)
        with journal.transaction() as transaction:
            with pytest.raises(ValueError, match="requires Product removal"):
                transaction.record_start(plan, confirmation, target)
        selected = product.desired_state.snapshot()
        removed = product.management.submit(
            PluginManagementCommandV1(
                action="remove",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator:windows-absent-arch-delete",
                    idempotency_key="operator:windows-absent-arch-delete",
                    expected_inventory_revision=selected.inventory_revision,
                    installation_key=key,
                    desired_state="absent",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision="operator:1",
                ),
            )
        )
        assert removed.result is not None
        assert removed.result.disposition == "succeeded"
        with journal.transaction() as transaction:
            unissued = PluginPrivateDataDeletionConfirmationV1(
                plan_fingerprint=plan.fingerprint,
                confirmation_id="arch-private-data:windows-unissued",
            )
            with pytest.raises(ValueError, match="confirmation is missing"):
                transaction.record_start(plan, unissued, target)
            with patch(
                "loushang.coding.package_legacy_windows_receipt.windows_rename_at",
                side_effect=OSError("injected deletion-start publication interruption"),
            ):
                with pytest.raises(OSError, match="publication interruption"):
                    transaction.record_start(plan, confirmation, target)
            with pytest.raises(ValueError, match="needs recovery"):
                transaction.events()
            started = transaction.record_start(plan, confirmation, target)
            assert transaction.current_start() == started
            assert transaction.record_start(plan, confirmation, target) == started
    finally:
        owner.close()
    reopened = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    try:
        journal = CodingWindowsArchPrivateDataDeletionJournal(
            lifecycle, reopened.runtime_owner.product_owner
        )
        with journal.transaction() as transaction:
            assert transaction.current_start() == started
            receipt = PluginPrivateDataDeletionReceiptV1(
                installation_key=key,
                owner_id=plan.owner_id,
                target_id=plan.target_id,
                plan_fingerprint=plan.fingerprint,
                confirmation_id=confirmation.confirmation_id,
                receipt_id=windows_arch_deletion_receipt_id(plan, confirmation),
                disposition="already_absent",
            )
            assert transaction.record_completion(started, receipt).receipt == receipt
            assert transaction.current_start() is None
            assert transaction.receipt_for(plan, confirmation) == receipt
    finally:
        reopened.close()


def test_windows_arch_private_data_deletion_recovers_after_rename(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        lifecycle,
        settings,
        workspace=workspace,
        namespace_id="c" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=lifecycle.scope_id,
        plugin_id="coding.arch.default",
    )
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=False
        )
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    try:
        binding = owner.factory_for_session(manager).create(
            PackageProductRuntimeRequestV1(
                product_id="coding",
                session_id=manager.get_header().conversation_id,
                cwd=str(workspace),
            )
        )
        try:
            runtime = binding.activate()
            session_root = prepare_coding_product_arch_private_data_root(
                lifecycle,
                runtime,
                session_id=manager.get_header().conversation_id,
            )
            cache_path = _write_native_arch_cache(session_root, workspace)
            assert cache_path.is_file()
            cache_bytes = cache_path.read_bytes()
        finally:
            binding.dispose_runtime()
    finally:
        owner.close()

    root = coding_arch_installation_private_data_root(lifecycle, key)
    candidate_client = open_coding_windows_arch_backup_candidate_client(
        workspace,
        layout=lifecycle,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    backup = candidate_client.retain()
    plan = candidate_client.deletion_preview()
    confirmation = PluginPrivateDataDeletionConfirmationV1(
        plan_fingerprint=plan.fingerprint,
        confirmation_id="arch-private-data:windows-present-retry",
    )
    with pytest.raises(ValueError, match="deletion command is foreign"):
        candidate_client.deletion_confirm(
            replace(plan, owner_id="coding.foreign"),
            confirmation,
            actor_id="local-operator:windows-test",
            policy_revision="windows-private-data-test:1",
        )
    candidate_client.deletion_confirm(
        plan,
        confirmation,
        actor_id="local-operator:windows-test",
        policy_revision="windows-private-data-test:1",
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    try:
        product = owner.runtime_owner.product_owner
        assert isinstance(product, WindowsLocalWheelProductSessionOwner)
        selected = product.desired_state.snapshot()
        removed = product.management.submit(
            PluginManagementCommandV1(
                action="remove",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator:windows-present-arch-delete",
                    idempotency_key="operator:windows-present-arch-delete",
                    expected_inventory_revision=selected.inventory_revision,
                    installation_key=key,
                    desired_state="absent",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision="operator:1",
                ),
            )
        )
        assert removed.result is not None
        assert removed.result.disposition == "succeeded"
        deletion = CodingWindowsArchPrivateDataDeletionOwner(lifecycle, product)
        with patch.object(
            windows_deletion_module,
            "windows_delete_open_entry",
            side_effect=OSError("injected Windows member deletion interruption"),
        ):
            with pytest.raises(OSError, match="member deletion interruption"):
                deletion.delete_confirmed(plan, confirmation)
        assert not root.exists()
        with CodingWindowsArchPrivateDataDeletionJournal(
            lifecycle, product
        ).transaction() as transaction:
            pending = transaction.current_start()
            assert pending is not None
            assert pending.phase == "renamed"
    finally:
        owner.close()

    receipt = candidate_client.delete_confirmed(plan, confirmation)
    assert receipt.disposition == "deleted"
    assert candidate_client.delete_confirmed(plan, confirmation) == receipt
    reopened = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    try:
        product = reopened.runtime_owner.product_owner
        assert isinstance(product, WindowsLocalWheelProductSessionOwner)
        assert not root.exists()
        assert (
            inspect_coding_windows_arch_installation_root(
                lifecycle, key, state_root=product.state_root
            )
            is None
        )
        restore_plan = CodingWindowsArchPrivateDataRestorePreview(
            lifecycle, product
        ).preview(key, backup.backup_id)
        assert restore_plan.deletion_receipt_id == receipt.receipt_id
        assert restore_plan.target_state == "absent"
    finally:
        reopened.close()
    assert (
        candidate_client.restore_preview(backup.backup_id).deletion_receipt_id
        == receipt.receipt_id
    )
    with patch.object(
        windows_restore_module,
        "windows_rename_open_directory_at",
        side_effect=OSError("injected Windows restore rename interruption"),
    ):
        with pytest.raises(OSError, match="restore rename interruption"):
            candidate_client.restore(restore_plan)
    assert not root.exists()
    assert len(list(root.parent.glob(".arch-restore-*.staging"))) == 1
    unrelated_owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    try:
        unrelated_product = unrelated_owner.runtime_owner.product_owner
        current_desired = unrelated_product.desired_state.snapshot()
        base = next(
            item
            for item in current_desired.installations
            if item.installation_key.plugin_id == "coding.base"
        )
        changed_unrelated = unrelated_product.management.submit(
            PluginManagementCommandV1(
                action="disable",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator:windows-restore-disable-other-plugin",
                    idempotency_key="operator:windows-restore-disable-other-plugin",
                    expected_inventory_revision=current_desired.inventory_revision,
                    installation_key=base.installation_key,
                    desired_state="installed_disabled",
                    package_revision=None,
                    actor_id=unrelated_product.actor_id,
                    policy_revision=unrelated_product.desired_policy_revision,
                ),
            )
        )
        assert changed_unrelated.result is not None
        assert changed_unrelated.result.disposition == "succeeded"
    finally:
        unrelated_owner.close()
    with patch.object(
        windows_restore_module,
        "_publish_windows_arch_restored_root_receipt",
        side_effect=OSError("injected Windows restore receipt interruption"),
    ):
        with pytest.raises(OSError, match="restore receipt interruption"):
            candidate_client.restore(restore_plan)
    assert root.is_dir()
    assert cache_path.read_bytes() == cache_bytes
    restored = candidate_client.restore(restore_plan)
    assert restored.disposition == "restored"
    assert restored.backup_id == backup.backup_id
    assert candidate_client.restore(restore_plan).disposition == "already_present"
    assert cache_path.read_bytes() == cache_bytes
    confirmation = candidate_client.restore_confirm(restore_plan)
    assert candidate_client.restore_confirm(restore_plan) == confirmation
    assert (
        candidate_client.restore_confirm_verify(
            restore_plan, confirmation.confirmation_id
        )
        == confirmation
    )
    expiry_plan = candidate_client.backup_expiry_preview(
        backup.backup_id, confirmation.confirmation_id
    )
    assert expiry_plan.backup_receipt_id == backup.receipt_id
    assert expiry_plan.confirmation_id == confirmation.confirmation_id
    assert expiry_plan.restored_target_id.startswith("present:")
    cache_path.write_bytes(b"tampered after Windows restore")
    with pytest.raises(ValueError, match="restored root changed"):
        candidate_client.restore(restore_plan)
    with pytest.raises(ValueError, match="restored bytes changed"):
        candidate_client.restore_confirm_verify(
            restore_plan, confirmation.confirmation_id
        )
    with pytest.raises(ValueError, match="restored bytes changed"):
        candidate_client.backup_expiry_preview(
            backup.backup_id, confirmation.confirmation_id
        )


def test_windows_arch_backup_expiry_recovers_across_native_effects(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        lifecycle,
        settings,
        workspace=workspace,
        namespace_id="c" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=lifecycle.scope_id,
        plugin_id="coding.arch.default",
    )
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=False
        )
    )
    application = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    try:
        binding = application.factory_for_session(manager).create(
            PackageProductRuntimeRequestV1(
                product_id="coding",
                session_id=manager.get_header().conversation_id,
                cwd=str(workspace),
            )
        )
        try:
            runtime = binding.activate()
            session_root = prepare_coding_product_arch_private_data_root(
                lifecycle, runtime, session_id=manager.get_header().conversation_id
            )
            cache_path = _write_native_arch_cache(session_root, workspace)
            cache_bytes = cache_path.read_bytes()
        finally:
            binding.dispose_runtime()
    finally:
        application.close()

    application = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    try:
        product = application.runtime_owner.product_owner
        assert isinstance(product, WindowsLocalWheelProductSessionOwner)
        backup = CodingWindowsArchPrivateDataBackupOwner(lifecycle, product).retain(key)
        confirmations = CodingWindowsArchPrivateDataConfirmationOwner(
            lifecycle, product
        )
        deletion_plan = confirmations.plan_for(key)
        deletion_confirmation = PluginPrivateDataDeletionConfirmationV1(
            plan_fingerprint=deletion_plan.fingerprint,
            confirmation_id="arch-private-data:windows-expiry-retry",
        )
        confirmations.record_confirmation(
            deletion_plan,
            deletion_confirmation,
            actor_id="local-operator:windows-test",
            policy_revision="windows-private-data-test:1",
        )
        selected = product.desired_state.snapshot()
        removed = product.management.submit(
            PluginManagementCommandV1(
                action="remove",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator:windows-expiry-arch-delete",
                    idempotency_key="operator:windows-expiry-arch-delete",
                    expected_inventory_revision=selected.inventory_revision,
                    installation_key=key,
                    desired_state="absent",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision="operator:1",
                ),
            )
        )
        assert removed.result is not None
        assert removed.result.disposition == "succeeded"
        receipt = CodingWindowsArchPrivateDataDeletionOwner(
            lifecycle, product
        ).delete_confirmed(deletion_plan, deletion_confirmation)
        assert receipt.disposition == "deleted"
    finally:
        application.close()

    client = open_coding_windows_arch_backup_candidate_client(
        workspace,
        layout=lifecycle,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    restore_plan = client.restore_preview(backup.backup_id)
    assert client.restore(restore_plan).disposition == "restored"
    restore_confirmation = client.restore_confirm(restore_plan)
    expiry_plan = client.backup_expiry_preview(
        backup.backup_id, restore_confirmation.confirmation_id
    )
    expiry_confirmation = client.backup_expiry_confirm(
        expiry_plan, actor_id="operator:windows-expiry", policy_revision="test:1"
    )
    assert (
        client.backup_expiry_confirm(
            expiry_plan, actor_id="operator:windows-expiry", policy_revision="test:1"
        )
        == expiry_confirmation
    )
    archive_path = backup_parent(lifecycle, key) / backup.backup_id
    assert archive_path.is_dir()
    with patch.object(
        windows_expiry_module,
        "windows_rename_open_directory_at",
        side_effect=OSError("injected Windows expiry rename interruption"),
    ):
        with pytest.raises(OSError, match="expiry rename interruption"):
            client.backup_expire(expiry_plan, expiry_confirmation)
    assert archive_path.is_dir()
    assert client.status().status == "expiry_pending"
    with patch.object(
        windows_expiry_module,
        "windows_delete_open_entry",
        side_effect=OSError("injected Windows expiry deletion interruption"),
    ):
        with pytest.raises(OSError, match="expiry deletion interruption"):
            client.backup_expire(expiry_plan, expiry_confirmation)
    assert not archive_path.exists()
    assert len(list(archive_path.parent.glob(".expiring-*"))) == 1
    assert client.status().status == "expiry_pending"
    remove_tombstone = windows_expiry_module._remove_tombstone

    def interrupt_after_delete(*args: object) -> None:
        remove_tombstone(*args)  # type: ignore[arg-type]
        raise OSError("injected Windows expiry receipt interruption")

    with patch.object(
        windows_expiry_module, "_remove_tombstone", side_effect=interrupt_after_delete
    ):
        with pytest.raises(OSError, match="expiry receipt interruption"):
            client.backup_expire(expiry_plan, expiry_confirmation)
    assert not archive_path.exists()
    assert not list(archive_path.parent.glob(".expiring-*"))
    expiry_receipt = client.backup_expire(expiry_plan, expiry_confirmation)
    assert expiry_receipt.backup_id == backup.backup_id
    assert client.backup_expire(expiry_plan, expiry_confirmation) == expiry_receipt
    assert not archive_path.exists()
    assert not list(archive_path.parent.glob(".expiring-*"))
    assert cache_path.read_bytes() == cache_bytes
    status = client.status()
    assert status.status == "expired"
    assert status.expiry_receipt_id == expiry_receipt.receipt_id


def test_windows_arch_private_data_reopens_same_installation_in_new_process(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        lifecycle,
        settings,
        workspace=workspace,
        namespace_id="e" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions-first",
            cwd=str(workspace),
            persist=False,
        )
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    arch_key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=lifecycle.scope_id,
        plugin_id="coding.arch.default",
    )
    try:
        binding = owner.factory_for_session(manager).create(
            PackageProductRuntimeRequestV1(
                product_id="coding",
                session_id=manager.get_header().conversation_id,
                cwd=str(workspace),
            )
        )
        try:
            first_root = prepare_coding_product_arch_private_data_root(
                lifecycle,
                binding.activate(),
                session_id=manager.get_header().conversation_id,
            )
            first_cache = _write_native_arch_cache(first_root, workspace)
            with pytest.raises(ValueError, match="runtime is active"):
                CodingWindowsArchPrivateDataReadPreview(
                    lifecycle, owner.runtime_owner.product_owner
                ).snapshot_for(arch_key)
            assert (
                CodingWindowsArchPrivateDataBackupOwner(
                    lifecycle, owner.runtime_owner.product_owner
                )
                .snapshot()
                .records[0]
                .status
                == "unknown"
            )
        finally:
            binding.dispose_runtime()
    finally:
        owner.close()
    installation_root = first_root.parent.parent
    before = installation_root.stat()
    script = """
import asyncio
import json
import sys
from pathlib import Path

from loushang.coding._plugin_lifecycle import resolve_ephemeral_coding_plugin_lifecycle_state_layout
from loushang.coding.package_installation_private_data import prepare_coding_product_arch_private_data_root
from loushang.coding.package_product_runtime import open_coding_fenced_product_application_owner
from loushang.coding.session_manager import SessionManager
from loushang.harness.package_product.product_runtime import PackageProductRuntimeRequestV1

workspace = Path(sys.argv[1])
test_root = Path(sys.argv[2])
layout = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
    test_root / "session-state", cwd=workspace
)
manager = asyncio.run(SessionManager.new(
    session_dir=test_root / "sessions-reopen", cwd=str(workspace), persist=False
))
owner = open_coding_fenced_product_application_owner(
    layout,
    workspace=workspace,
    runtime_version="2.0.0",
    runtime_protocol_epoch=2,
    windows_candidate=True,
)
try:
    binding = owner.factory_for_session(manager).create(PackageProductRuntimeRequestV1(
        product_id="coding",
        session_id=manager.get_header().conversation_id,
        cwd=str(workspace),
    ))
    try:
        root = prepare_coding_product_arch_private_data_root(
            layout, binding.activate(), session_id=manager.get_header().conversation_id
        )
        metadata = root.parent.parent.stat()
        print(json.dumps({
            "identity": [metadata.st_dev, metadata.st_ino],
            "path": str(root),
        }))
    finally:
        binding.dispose_runtime()
finally:
    owner.close()
"""
    reopened = subprocess.run(
        (sys.executable, "-c", script, str(workspace), str(tmp_path)),
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert reopened.returncode == 0, reopened.stderr
    result = json.loads(reopened.stdout)
    assert result["identity"] == [before.st_dev, before.st_ino]
    second_root = Path(result["path"])
    assert second_root.parent.parent == installation_root
    assert second_root != first_root
    assert first_root.is_dir() and second_root.is_dir()
    reopened_owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    try:
        preview = CodingWindowsArchPrivateDataReadPreview(
            lifecycle, reopened_owner.runtime_owner.product_owner
        )
        snapshot = preview.snapshot_for(arch_key)
        assert snapshot.target_id.startswith("present:")
        assert {member.relative_path for member in snapshot.members} == {
            "sessions",
            "sessions/" + first_root.name,
            "sessions/" + first_root.name + "/" + first_cache.name,
            "sessions/" + second_root.name,
        }
        backup = CodingWindowsArchPrivateDataBackupOwner(
            lifecycle, reopened_owner.runtime_owner.product_owner
        )
        assert not backup_parent(lifecycle, arch_key).exists()
        assert backup.snapshot().records[0].status == "unknown"
        assert not backup_parent(lifecycle, arch_key).exists()
        with patch.object(
            windows_backup_module,
            "_copy_members",
            side_effect=OSError("injected backup copy interruption"),
        ):
            with pytest.raises(OSError, match="copy interruption"):
                backup.retain(arch_key)
        assert backup.snapshot().records[0].status == "unknown"
        stage_files = (
            backup_parent(lifecycle, arch_key)
            / (backup_id(arch_key, snapshot) + ".staging")
            / "files"
        )
        staged_session = prepare_windows_product_private_directory_chain(
            stage_files, "sessions", first_root.name, inherit_leaf=True
        )
        partial_file = staged_session / first_cache.name
        with WindowsPrivateDirectoryAcl(inherit_children=True) as stage_acl:
            stage_fd = open_windows_directory(staged_session, read_control=True)
            try:
                stage_acl.validate(stage_fd)
                partial_fd = open_windows_regular_file_at(
                    stage_fd,
                    partial_file.name,
                    create_new=True,
                    write=True,
                    security_descriptor=stage_acl.security_descriptor,
                    read_control=True,
                )
                try:
                    stage_acl.validate(partial_fd)
                    assert os.write(partial_fd, b"wrong prefix") == len(b"wrong prefix")
                finally:
                    os.close(partial_fd)
            finally:
                os.close(stage_fd)
        with pytest.raises(ValueError, match="stage file changed"):
            backup.retain(arch_key)
        partial_file.write_bytes(first_cache.read_bytes()[:16])
        with patch.object(
            windows_backup_module,
            "windows_rename_at",
            side_effect=OSError("injected backup publication interruption"),
        ):
            with pytest.raises(OSError, match="publication interruption"):
                backup.retain(arch_key)
        assert partial_file.read_bytes() == first_cache.read_bytes()
        retained = backup.retain(arch_key)
        assert retained.source_target_id == snapshot.target_id
        assert retained.file_count == 1
        assert backup.verify(arch_key, retained.backup_id) == retained
        assert backup.retain(arch_key) == retained
        assert backup.snapshot().records[0].status == "retained"
        candidate_client = open_coding_windows_arch_backup_candidate_client(
            workspace,
            layout=lifecycle,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )
        assert candidate_client.status().status == "retained"
        assert candidate_client.verify(retained.backup_id) == retained
        assert candidate_client.retain() == retained
        product_owner = reopened_owner.runtime_owner.product_owner
        confirmation_owner = CodingWindowsArchPrivateDataConfirmationOwner(
            lifecycle, product_owner
        )
        deletion_plan = confirmation_owner.plan_for(arch_key)
        confirmation = PluginPrivateDataDeletionConfirmationV1(
            plan_fingerprint=deletion_plan.fingerprint,
            confirmation_id="arch-private-data:windows-confirmation",
        )
        confirmed = confirmation_owner.record_confirmation(
            deletion_plan,
            confirmation,
            actor_id="local-operator:windows-test",
            policy_revision="windows-private-data-test:1",
        )
        assert (
            confirmation_owner.record_confirmation(
                deletion_plan,
                confirmation,
                actor_id="local-operator:windows-test",
                policy_revision="windows-private-data-test:1",
            )
            == confirmed
        )
        assert confirmation_owner.is_confirmed(deletion_plan, confirmation)
        interrupted_confirmation = PluginPrivateDataDeletionConfirmationV1(
            plan_fingerprint=deletion_plan.fingerprint,
            confirmation_id="arch-private-data:windows-interrupted",
        )
        with patch(
            "loushang.coding.package_legacy_windows_receipt.windows_rename_at",
            side_effect=OSError("injected confirmation publication interruption"),
        ):
            with pytest.raises(OSError, match="publication interruption"):
                confirmation_owner.record_confirmation(
                    deletion_plan,
                    interrupted_confirmation,
                    actor_id="local-operator:windows-test",
                    policy_revision="windows-private-data-test:1",
                )
        with pytest.raises(CodingWindowsPrivateReceiptError, match="unpublished stage"):
            confirmation_owner.is_confirmed(deletion_plan, interrupted_confirmation)
        confirmation_owner.record_confirmation(
            deletion_plan,
            interrupted_confirmation,
            actor_id="local-operator:windows-test",
            policy_revision="windows-private-data-test:1",
        )
        assert confirmation_owner.is_confirmed(deletion_plan, interrupted_confirmation)
        projection = PluginManagementReadModelProjector(
            desired_state=product_owner.desired_state,
            operations=product_owner.management,
            backup_retention=backup,
        ).snapshot(
            PluginManagementQueryV1(
                correlation_id="windows-arch-backup-retention",
                product_id="coding",
                installation_scope="workspace",
                scope_id=lifecycle.scope_id,
                plugin_ids=("coding.arch.default",),
            )
        )
        assert projection.installations[0].backup_retention is not None
        assert projection.installations[0].backup_retention.status == "retained"
        held_source = first_cache.with_name(first_cache.name + ".held")
        first_cache.rename(held_source)
        try:
            assert backup.verify(arch_key, retained.backup_id) == retained
            assert backup.snapshot().records[0].status == "retained"
        finally:
            held_source.rename(first_cache)
        unfinished_stage = backup_parent(lifecycle, arch_key) / (
            retained.backup_id + ".staging"
        )
        unfinished_stage.mkdir()
        try:
            with pytest.raises(ValueError, match="stage needs recovery"):
                backup.verify(arch_key, retained.backup_id)
            with pytest.raises(ValueError, match="stage needs recovery"):
                backup.retain(arch_key)
            assert backup.snapshot().records[0].status == "unknown"
        finally:
            unfinished_stage.rmdir()
        named_stream = str(first_cache) + ":hidden"
        with open(named_stream, "wb") as stream:
            stream.write(b"hidden private data")
        try:
            with pytest.raises(ValueError, match="named stream"):
                preview.snapshot_for(arch_key)
        finally:
            os.remove(named_stream)
        directory_stream = _create_native_directory_stream(first_root.parent)
        try:
            with pytest.raises(ValueError, match="directory has a named stream"):
                preview.snapshot_for(arch_key)
        finally:
            os.remove(directory_stream)
        kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
        get_attributes = kernel32.GetFileAttributesW
        get_attributes.argtypes = (wintypes.LPCWSTR,)
        get_attributes.restype = wintypes.DWORD
        set_attributes = kernel32.SetFileAttributesW
        set_attributes.argtypes = (wintypes.LPCWSTR, wintypes.DWORD)
        set_attributes.restype = wintypes.BOOL
        original_attributes = get_attributes(str(first_cache))
        assert original_attributes != 0xFFFFFFFF
        assert set_attributes(str(first_cache), original_attributes | 0x00000002)
        try:
            with pytest.raises(ValueError, match="attributes are unsupported"):
                preview.snapshot_for(arch_key)
        finally:
            assert set_attributes(str(first_cache), original_attributes)
        _grant_windows_world_read(first_cache)
        with pytest.raises(OSError):
            preview.snapshot_for(arch_key)
        assert backup.verify(arch_key, retained.backup_id) == retained
        assert backup.snapshot().records[0].status == "retained"
        archived_file = (
            backup_parent(lifecycle, arch_key)
            / retained.backup_id
            / "files"
            / "sessions"
            / first_root.name
            / first_cache.name
        )
        archived_file.write_bytes(b"changed archive bytes")
        with pytest.raises(ValueError, match="backup files changed"):
            backup.verify(arch_key, retained.backup_id)
        assert backup.snapshot().records[0].status == "unknown"
        assert candidate_client.status().status == "unknown"
        confirmation_path = confirmation_owner._record_path(confirmation)
        confirmation_stream = str(confirmation_path) + ":hidden"
        with open(confirmation_stream, "wb") as stream:
            stream.write(b"hidden confirmation bytes")
        try:
            with pytest.raises(CodingWindowsPrivateReceiptError, match="named stream"):
                confirmation_owner.is_confirmed(deletion_plan, confirmation)
        finally:
            os.remove(confirmation_stream)
        confirmation_attributes = get_attributes(str(confirmation_path))
        assert confirmation_attributes != 0xFFFFFFFF
        assert set_attributes(
            str(confirmation_path), confirmation_attributes | 0x00000002
        )
        try:
            with pytest.raises(CodingWindowsPrivateReceiptError, match="attributes"):
                confirmation_owner.is_confirmed(deletion_plan, confirmation)
        finally:
            assert set_attributes(str(confirmation_path), confirmation_attributes)
        _grant_windows_world_read(confirmation_path)
        with pytest.raises(OSError):
            confirmation_owner.is_confirmed(deletion_plan, confirmation)
    finally:
        reopened_owner.close()
    held_workspace = workspace.with_name("workspace-held")
    workspace.rename(held_workspace)
    workspace.mkdir()
    try:
        with pytest.raises(ValueError, match="workspace changed"):
            candidate_client.status()
    finally:
        workspace.rmdir()
        held_workspace.rename(workspace)


def test_windows_candidate_ordinary_session_refuses_old_desired_before_writes(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    lifecycle.root.mkdir(parents=True)
    old_bytes = b"old Desired State must survive\n"
    lifecycle.desired_state.write_bytes(old_bytes)
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=False
        )
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    selection = CodingFencedProductApplicationSelection(windows_candidate=True)
    try:
        with (
            patch(
                "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
                return_value=lifecycle,
            ),
            pytest.raises(RuntimeError, match="pre-B workspace is unsupported"),
        ):
            selection.factory_for_session(manager, settings_manager=settings)
    finally:
        selection.close()
    assert lifecycle.desired_state.read_bytes() == old_bytes
    assert not (
        resolve_coding_package_epoch_layout(lifecycle).control_root / "epoch.jsonl"
    ).exists()


def test_windows_candidate_ordinary_session_reopens_fresh_b_across_processes(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    script = """
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

from loushang.coding._plugin_lifecycle import resolve_ephemeral_coding_plugin_lifecycle_state_layout
from loushang.coding.package_product_runtime import CodingFencedProductApplicationSelection
from loushang.coding.session_manager import SessionManager
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product.product_runtime import PackageProductRuntimeRequestV1

workspace = Path(sys.argv[1])
test_root = Path(sys.argv[2])
phase = sys.argv[3]
lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
    test_root / "session-state", cwd=workspace
)
manager = asyncio.run(SessionManager.new(
    session_dir=test_root / ("sessions-" + phase), cwd=str(workspace), persist=False
))
settings = SettingsManager(
    global_settings_path=test_root / "global-settings.json",
    project_settings_path=workspace / ".loushang" / "settings.json",
)
with (
    patch(
        "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
        return_value=lifecycle,
    ),
    patch(
        "loushang.coding.package_product_runtime.default_global_settings_path",
        return_value=test_root / "global-settings.json",
    ),
    patch("loushang.coding.package_product_runtime.version", return_value="2.0.0"),
):
    selection = CodingFencedProductApplicationSelection(windows_candidate=True)
    try:
        factory = selection.factory_for_session(manager, settings_manager=settings)
        binding = factory.create(PackageProductRuntimeRequestV1(
            product_id="coding",
            session_id=manager.get_header().conversation_id,
            cwd=str(workspace),
        ))
        try:
            runtime = binding.activate()
            names = [
                runtime.capture_selected_plugin_manifest_for(
                    plugin_id, max_files=64, max_total_bytes=1024 * 1024
                ).verified_manifest().name
                for plugin_id in (
                    "coding.base", "coding.lsp.default", "coding.arch.default"
                )
            ]
            print(json.dumps(names))
        finally:
            binding.dispose_runtime()
    finally:
        selection.close()
"""

    def run(phase: str) -> list[str]:
        completed = subprocess.run(
            (
                sys.executable,
                "-c",
                script,
                str(workspace),
                str(tmp_path),
                phase,
            ),
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)

    expected = ["coding.base", "coding.lsp.default", "coding.arch.default"]
    assert run("first") == expected
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    fence_journal = epoch.control_root / "epoch.jsonl"
    desired = epoch.control_root / "product-state" / "desired-state.jsonl"
    first_fence = fence_journal.read_bytes()
    before = desired.read_bytes()
    assert first_fence
    assert before
    assert run("reopen") == expected
    assert fence_journal.read_bytes() == first_fence
    assert desired.read_bytes() == before


def test_windows_candidate_ordinary_session_recovers_after_bootstrap_process_exit(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    script = """
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

from loushang.coding._plugin_lifecycle import resolve_ephemeral_coding_plugin_lifecycle_state_layout
from loushang.coding.package_product_runtime import CodingFencedProductApplicationSelection
from loushang.coding.session_manager import SessionManager
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product.product_runtime import PackageProductRuntimeRequestV1
from loushang.harness.plugin_management.service import PluginManagementService

workspace = Path(sys.argv[1])
test_root = Path(sys.argv[2])
phase = sys.argv[3]
lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
    test_root / "session-state", cwd=workspace
)
manager = asyncio.run(SessionManager.new(
    session_dir=test_root / ("sessions-" + phase), cwd=str(workspace), persist=False
))
settings = SettingsManager(
    global_settings_path=test_root / "global-settings.json",
    project_settings_path=workspace / ".loushang" / "settings.json",
)
with (
    patch(
        "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
        return_value=lifecycle,
    ),
    patch(
        "loushang.coding.package_product_runtime.default_global_settings_path",
        return_value=test_root / "global-settings.json",
    ),
    patch("loushang.coding.package_product_runtime.version", return_value="2.0.0"),
):
    selection = CodingFencedProductApplicationSelection(windows_candidate=True)
    if phase == "crash":
        original_submit = PluginManagementService.submit

        def exit_before_first_enable(service, command):
            if command.action == "enable":
                os._exit(52)
            return original_submit(service, command)

        with patch.object(PluginManagementService, "submit", exit_before_first_enable):
            selection.factory_for_session(manager, settings_manager=settings)
        raise AssertionError("bootstrap never reached the first enable")
    try:
        factory = selection.factory_for_session(manager, settings_manager=settings)
        binding = factory.create(PackageProductRuntimeRequestV1(
            product_id="coding",
            session_id=manager.get_header().conversation_id,
            cwd=str(workspace),
        ))
        try:
            runtime = binding.activate()
            names = [
                runtime.capture_selected_plugin_manifest_for(
                    plugin_id, max_files=64, max_total_bytes=1024 * 1024
                ).verified_manifest().name
                for plugin_id in (
                    "coding.base", "coding.lsp.default", "coding.arch.default"
                )
            ]
            print(json.dumps(names))
        finally:
            binding.dispose_runtime()
    finally:
        selection.close()
"""

    def run(phase: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            (sys.executable, "-c", script, str(workspace), str(tmp_path), phase),
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    crashed = run("crash")
    assert crashed.returncode == 52, crashed.stderr
    assert crashed.stdout == ""
    assert reopen_coding_package_cutover(lifecycle).disposition == "fenced"
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    fence = (epoch.control_root / "epoch.jsonl").read_bytes()
    desired_path = epoch.control_root / "product-state" / "desired-state.jsonl"
    assert fence
    assert desired_path.read_bytes()
    expected = ["coding.base", "coding.lsp.default", "coding.arch.default"]
    recovered = run("recover")
    assert recovered.returncode == 0, recovered.stderr
    assert json.loads(recovered.stdout) == expected
    settled = desired_path.read_bytes()
    reopened = run("reopen")
    assert reopened.returncode == 0, reopened.stderr
    assert json.loads(reopened.stdout) == expected
    assert (epoch.control_root / "epoch.jsonl").read_bytes() == fence
    assert desired_path.read_bytes() == settled


def test_windows_candidate_ordinary_session_retries_interrupted_fresh_bootstrap(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=False
        )
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    original_submit = PluginManagementService.submit
    interrupted = False

    def interrupt_once(
        service: PluginManagementService, command: PluginManagementCommandV1
    ):
        nonlocal interrupted
        if command.action == "enable" and not interrupted:
            interrupted = True
            raise RuntimeError("injected first enable interruption")
        return original_submit(service, command)

    with (
        patch(
            "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
        patch(
            "loushang.coding.package_product_runtime.default_global_settings_path",
            return_value=tmp_path / "global-settings.json",
        ),
        patch("loushang.coding.package_product_runtime.version", return_value="2.0.0"),
    ):
        first = CodingFencedProductApplicationSelection(windows_candidate=True)
        try:
            with (
                patch.object(PluginManagementService, "submit", interrupt_once),
                pytest.raises(RuntimeError, match="injected first enable interruption"),
            ):
                first.factory_for_session(manager, settings_manager=settings)
        finally:
            first.close()
        assert interrupted
        assert reopen_coding_package_cutover(lifecycle).disposition == "fenced"
        retry = CodingFencedProductApplicationSelection(windows_candidate=True)
        try:
            factory = retry.factory_for_session(manager, settings_manager=settings)
            assert factory is not None
            binding = factory.create(
                PackageProductRuntimeRequestV1(
                    product_id="coding",
                    session_id=manager.get_header().conversation_id,
                    cwd=str(workspace),
                )
            )
            try:
                runtime = binding.activate()
                for plugin_id in (
                    "coding.base",
                    "coding.lsp.default",
                    "coding.arch.default",
                ):
                    assert (
                        runtime.capture_selected_plugin_manifest_for(
                            plugin_id, max_files=64, max_total_bytes=1024 * 1024
                        )
                        .verified_manifest()
                        .name
                        == plugin_id
                    )
            finally:
                binding.dispose_runtime()
        finally:
            retry.close()


def _assert_windows_product_worker_native_approval_journal(
    product: WindowsLocalWheelProductSessionOwner,
) -> None:
    """Prove inert approval history custody without admitting a release."""

    path = product.state_root / "worker-native-release-approvals.jsonl"
    journal = CodingWindowsWorkerNativeApprovalJournal(
        path, scope_id=product.policy.project_scope_id
    )
    owner = CodingWindowsWorkerNativeApprovalOwner(product)
    assert owner.current() is None
    assert not path.exists()
    assert not path.with_name(path.name + ".lock").exists()
    with pytest.raises(CodingWorkerNativeApprovalError) as absent:
        owner.revoke(operation_id="windows-native-absent", expected_generation=0)
    assert absent.value.code == "coding_worker_native_approval_absent"
    assert owner.current() is None
    assert not path.exists()
    synthetic = CodingWorkerNativeReleaseApprovalV1(
        wheel_sha256="a" * 64,
        catalog_sha256="b" * 64,
        launcher_sha256="c" * 64,
        profile_sha256="d" * 64,
    )
    with product.gc_gate.guard():
        product.assert_root_gc_authority_current()
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            approved = journal.change(
                directory_fd=root,
                operation_id="windows-native-approval-1",
                expected_generation=0,
                action="approve",
                approval=synthetic,
            )
            assert journal.current(directory_fd=root) == approved
            assert (
                journal.change(
                    directory_fd=root,
                    operation_id="windows-native-approval-1",
                    expected_generation=0,
                    action="approve",
                    approval=synthetic,
                )
                == approved
            )
            with pytest.raises(CodingWorkerNativeApprovalError) as stale:
                journal.change(
                    directory_fd=root,
                    operation_id="windows-native-stale",
                    expected_generation=0,
                    action="revoke",
                    approval=None,
                )
            assert stale.value.code == "coding_worker_native_approval_stale"
    assert owner.current() == approved
    revoked = owner.revoke(
        operation_id="windows-native-revoke-2", expected_generation=1
    )
    assert revoked.action == "revoke"
    assert revoked.generation == 2
    assert (
        owner.revoke(operation_id="windows-native-revoke-2", expected_generation=1)
        == revoked
    )
    assert owner.current() == revoked
    held = path.with_name(path.name + ".held")
    path.replace(held)
    try:
        with pytest.raises(CodingWorkerNativeApprovalError) as missing_history:
            owner.current()
        assert missing_history.value.code == "coding_worker_native_approval_orphan_lock"
    finally:
        held.replace(path)
    assert owner.current() == revoked
    with product.gc_gate.guard():
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            foreign = CodingWindowsWorkerNativeApprovalJournal(
                path, scope_id="workspace:foreign"
            )
            with pytest.raises(CodingWorkerNativeApprovalError) as wrong_scope:
                foreign.current(directory_fd=root)
            assert wrong_scope.value.code == "coding_worker_native_approval_corrupt"


def _assert_windows_product_worker_opt_in_journal(
    product: WindowsLocalWheelProductSessionOwner,
    selected: PackageProductSelectedPluginManifestV1,
) -> None:
    """Exercise inert decisions under the pinned Windows Product state root."""

    candidate = verify_product_selected_worker_candidate(
        selected, contribution_id="query-provider", native_platform="windows-amd64"
    )
    path = product.state_root / "worker-opt-in.jsonl"
    journal = CodingWindowsWorkerOptInJournal(
        path, scope_id=product.policy.project_scope_id
    )
    owner = CodingWindowsWorkerProductOptInOwner(product)
    assert owner.current(candidate.plugin_id) is None
    with pytest.raises(CodingWorkerOptInJournalError) as absent:
        owner.revoke(
            plugin_id=candidate.plugin_id,
            operation_id="windows-opt-in-absent",
            expected_generation=0,
        )
    assert absent.value.code == "coding_worker_opt_in_absent"
    assert owner.current(candidate.plugin_id) is None
    with product.gc_gate.guard():
        product.assert_root_gc_authority_current()
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            assert journal.current(candidate.plugin_id, directory_fd=root) is None
            assert journal.history_read_only(directory_fd=root) == ()
            assert not path.exists()
            opt_in = CodingWorkerOptInV1(
                plugin_id=candidate.plugin_id,
                contribution_id=candidate.contribution_id,
                owner_id=candidate.owner_id,
                artifact_digest=selected.snapshot.root_ref.artifact_digest,
                native_platform="windows-amd64",
                owner_selection_generation=1,
                kill_switch_generation=0,
                require_worker=False,
            )
            allow = journal.change(
                directory_fd=root,
                plugin_id=candidate.plugin_id,
                operation_id="windows-opt-in-allow-1",
                expected_generation=0,
                action="allow",
                opt_in=opt_in,
            )
            assert journal.current(candidate.plugin_id, directory_fd=root) == allow
            assert journal.history_read_only(directory_fd=root) == (allow,)
            assert (
                journal.change(
                    directory_fd=root,
                    plugin_id=candidate.plugin_id,
                    operation_id="windows-opt-in-allow-1",
                    expected_generation=0,
                    action="allow",
                    opt_in=opt_in,
                )
                == allow
            )
            with pytest.raises(CodingWorkerOptInJournalError) as stale:
                journal.change(
                    directory_fd=root,
                    plugin_id=candidate.plugin_id,
                    operation_id="windows-opt-in-stale",
                    expected_generation=0,
                    action="revoke",
                    opt_in=None,
                )
            assert stale.value.code == "coding_worker_opt_in_stale"
        product.assert_root_gc_authority_current()
    assert owner.current(candidate.plugin_id) == allow
    revoked = owner.revoke(
        plugin_id=candidate.plugin_id,
        operation_id="windows-opt-in-revoke-2",
        expected_generation=1,
    )
    assert revoked.generation == 2
    assert revoked.kill_switch_generation == 1
    assert revoked.opt_in is None
    assert (
        owner.revoke(
            plugin_id=candidate.plugin_id,
            operation_id="windows-opt-in-revoke-2",
            expected_generation=1,
        )
        == revoked
    )
    held = path.with_name(path.name + ".held")
    path.replace(held)
    try:
        with pytest.raises(CodingWorkerOptInJournalError) as missing_history:
            owner.current(candidate.plugin_id)
        assert missing_history.value.code == "coding_worker_opt_in_orphan_lock"
    finally:
        held.replace(path)
    assert owner.current(candidate.plugin_id) == revoked
    reopened = CodingWindowsWorkerOptInJournal(
        path, scope_id=product.policy.project_scope_id
    )
    with product.gc_gate.guard():
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            assert reopened.current(candidate.plugin_id, directory_fd=root) == revoked
            assert reopened.history_read_only(directory_fd=root) == (
                allow,
                revoked,
            )
            foreign = CodingWindowsWorkerOptInJournal(
                path, scope_id="workspace:foreign"
            )
            with pytest.raises(CodingWorkerOptInJournalError) as wrong_scope:
                foreign.current(candidate.plugin_id, directory_fd=root)
            assert wrong_scope.value.code == "coding_worker_opt_in_corrupt"
            replaced_root = CodingWindowsWorkerOptInJournal(
                path.parent.parent / "worker-opt-in.jsonl",
                scope_id=product.policy.project_scope_id,
            )
            with pytest.raises(CodingWorkerOptInJournalError) as wrong_root:
                replaced_root.current(candidate.plugin_id, directory_fd=root)
            assert wrong_root.value.code == "coding_worker_opt_in_state_root_changed"


def _assert_windows_product_worker_provisioning_state(
    product: WindowsLocalWheelProductSessionOwner,
    product_runtime: PackageProductRuntimeBindingV1,
    selected: PackageProductSelectedPluginManifestV1,
    tmp_path: Path,
    *,
    prior_settled_attempt_id: str | None = None,
) -> None:
    """Exercise rooted CAS through a real selected Windows Product owner."""

    candidate = verify_product_selected_worker_candidate(
        selected, contribution_id="query-provider", native_platform="windows-amd64"
    )
    manifest = selected.verified_manifest()
    configuration = manifest.contribution_index.items[0].worker_configuration
    assert configuration is not None
    prefix = manifest.root_relative_path.as_posix()
    member = (
        configuration.entrypoint
        if prefix == "."
        else f"{prefix}/{configuration.entrypoint}"
    )
    executable_bytes = dict(selected.snapshot.files)[member]
    package_root = tmp_path / "provisioning-worker-runtime"
    executable_path = package_root / configuration.entrypoint
    executable_path.parent.mkdir(parents=True)
    executable_path.write_bytes(executable_bytes)
    runtime = WorkerRuntimeBindingV1.capture(
        package_root=package_root, configuration=configuration
    )

    def validate_current() -> None:
        if executable_path.read_bytes() != executable_bytes:
            raise RuntimeError("Worker runtime bytes changed")

    assert product_runtime.session_id is not None
    session_scope_id = coding_worker_session_scope_id(product_runtime.session_id)
    assert session_scope_id != product.policy.project_scope_id
    identity = WorkerLaunchIdentityV1(
        plugin_id=candidate.plugin_id,
        plugin_revision_digest=selected.snapshot.root_ref.artifact_digest,
        contribution_id=candidate.contribution_id,
        owner_id=candidate.owner_id,
        product_id="coding",
        scope_id=session_scope_id,
        owner_generation=1,
        declaration_fingerprint=candidate.declaration_fingerprint,
        worker_configuration_fingerprint=candidate.worker_configuration_fingerprint,
        attempt_id="5" * 32,
        supervisor_epoch=1,
        session_nonce="6" * 64,
    )
    request = ManagedWorkerLaunchRequestV1(
        identity=identity, runtime=runtime, validate_current=validate_current
    )
    native_profile_id = "windows-lpac-contained-pe-v1"
    catalog_revision = "native-catalog-1"
    launcher_digest = "a" * 64
    profile_digest = "b" * 64
    closure = ProductWorkerActivationPolicyV1.native_policy_closure_fingerprint(
        native_profile_catalog_revision=catalog_revision,
        native_profile_id=native_profile_id,
        payload_sha256=runtime.executable_digest,
        containment_launcher_sha256=launcher_digest,
        containment_profile_sha256=profile_digest,
    )
    policy = ProductWorkerActivationPolicyV1(
        product_id="coding",
        product_runtime_id=product_runtime.product_runtime_id or "",
        product_scope_id=session_scope_id,
        session_id=product_runtime.session_id or "",
        session_route="new",
        selected_locator_fingerprint=None,
        selected_locator_revision="new-session",
        plugin_id=candidate.plugin_id,
        plugin_revision_digest=selected.snapshot.root_ref.artifact_digest,
        contribution_id=candidate.contribution_id,
        reservation_fingerprint=candidate.reservation_fingerprint,
        declaration_fingerprint=candidate.declaration_fingerprint,
        worker_configuration_fingerprint=candidate.worker_configuration_fingerprint,
        declared_required=candidate.declared_required,
        effective_required=candidate.declared_required,
        enabled=True,
        allowed_product_ids=("coding",),
        allowed_contribution_ids=(candidate.contribution_id,),
        requested_owner="hosting",
        owner_selection_generation=identity.owner_generation,
        no_fallback=True,
        native_profile_id=native_profile_id,
        native_profile_catalog_revision=catalog_revision,
        allowed_native_profile_ids=(native_profile_id,),
        expected_native_policy_closure_fingerprint=closure,
        product_policy_revision="worker-candidate-1",
        kill_switch_generation=1,
    )
    receipt = ProductWorkerActivationReceiptV1(
        policy=policy, issue_sequence=1, issue_nonce="windows-product-candidate"
    )
    synthetic_intent = CodingWindowsWorkerLaunchIntentV1(
        attempt_id=identity.attempt_id,
        stage_identity=(runtime.cwd_device, runtime.cwd_inode),
        receipt_fingerprint=receipt.fingerprint,
        request_fingerprint=request.fingerprint,
        identity_fingerprint=identity.fingerprint,
        runtime_fingerprint=runtime.fingerprint,
        payload_digest=runtime.executable_digest,
        owner_id=identity.owner_id,
        supervisor_epoch=identity.supervisor_epoch,
    )
    write_windows_private_receipt(
        product.state_root / f"worker-launch-intent-{identity.attempt_id}.json",
        synthetic_intent.to_bytes(),
    )
    plan = _WindowsLpacProductWorkerProfilePlan(
        worker_request_fingerprint=request.fingerprint,
        native_profile_catalog_revision=catalog_revision,
        containment_launcher_sha256=launcher_digest,
        containment_profile_sha256=profile_digest,
        expected_native_policy_closure_fingerprint=closure,
        operation_nonce="c" * 64,
        lifecycle_fingerprint="d" * 64,
    )
    changed_receipt = replace(
        receipt,
        policy=replace(policy, reservation_fingerprint="e" * 64),
    )
    project_scope_receipt = replace(
        receipt,
        policy=replace(policy, product_scope_id=product.policy.project_scope_id),
    )
    with pytest.raises(ValueError, match="requires enabled Hosting policy"):
        replace(receipt, policy=replace(policy, enabled=False))
    with pytest.raises(ValueError, match="provisioning binding is invalid"):
        open_coding_windows_product_worker_provisioning_state_store(
            product,
            runtime=product_runtime,
            selected=selected,
            receipt=changed_receipt,
            worker_request=request,
            plan=plan,
        )
    with pytest.raises(ValueError, match="provisioning binding is invalid"):
        open_coding_windows_product_worker_provisioning_state_store(
            product,
            runtime=product_runtime,
            selected=selected,
            receipt=project_scope_receipt,
            worker_request=request,
            plan=plan,
        )
    store = open_coding_windows_product_worker_provisioning_state_store(
        product,
        runtime=product_runtime,
        selected=selected,
        receipt=receipt,
        worker_request=request,
        plan=plan,
    )
    assert store.path.parent == product.state_root
    assert store.load() is None
    assert not store.path.exists()
    document = {
        **_windows_lpac_provisioning_identity(
            receipt=receipt, worker_request=request, plan=plan
        ),
        "phase": "reserved",
        "stateRevision": 1,
        "witness": None,
    }
    assert store.compare_and_swap(expected_revision=0, document=document)
    inventory = inspect_coding_windows_product_worker_provisioning_attempts(product)
    expected_attempts = {identity.attempt_id}
    if prior_settled_attempt_id is not None:
        expected_attempts.add(prior_settled_attempt_id)
    assert {item.attempt_id for item in inventory} == expected_attempts
    current_attempt = next(
        item for item in inventory if item.attempt_id == identity.attempt_id
    )
    assert current_attempt.identity["jobObjectName"] == (
        "Global\\LoushangWorker-" + plan.operation_nonce
    )
    assert current_attempt.identity["executableRelativePath"] == (
        request.runtime.executable.relative_to(request.runtime.package_root).as_posix()
    )
    assert current_attempt.phase == "reserved"
    assert current_attempt.unsettled
    assert current_attempt.settlement_fingerprint is None
    if prior_settled_attempt_id is not None:
        prior_attempt = next(
            item for item in inventory if item.attempt_id == prior_settled_attempt_id
        )
        assert prior_attempt.phase == "settled"
        assert not prior_attempt.unsettled
        assert prior_attempt.settlement_fingerprint is not None
    reopened = open_coding_windows_product_worker_provisioning_state_store(
        product,
        runtime=product_runtime,
        selected=selected,
        receipt=receipt,
        worker_request=request,
        plan=plan,
    )
    assert reopened.load() == document
    assert not reopened.compare_and_swap(expected_revision=0, document=document)
    executable_path.write_bytes(executable_bytes + b"changed")
    with pytest.raises(RuntimeError, match="Worker runtime bytes changed"):
        reopened.load()


def _windows_worker_dependency_wheel(name: str) -> bytes:
    """One bounded pure-Python dependency artifact for native Product proof."""

    files = {
        f"{name}/__init__.py": b"VALUE = 1\n",
        f"{name}-1.dist-info/METADATA": (
            f"Metadata-Version: 2.1\nName: {name}\nVersion: 1\n\n".encode()
        ),
        f"{name}-1.dist-info/WHEEL": (
            b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n"
        ),
    }
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for logical_path, body in sorted(files.items()):
        digest = urlsafe_b64encode(sha256(body).digest()).rstrip(b"=").decode()
        writer.writerow((logical_path, f"sha256={digest}", str(len(body))))
    writer.writerow((f"{name}-1.dist-info/RECORD", "", ""))
    files[f"{name}-1.dist-info/RECORD"] = record.getvalue().encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for logical_path, body in sorted(files.items()):
            member = zipfile.ZipInfo(logical_path, date_time=(1980, 1, 1, 0, 0, 0))
            member.create_system = 3
            member.external_attr = (stat.S_IFREG | 0o644) << 16
            member.compress_type = zipfile.ZIP_STORED
            archive.writestr(member, body)
    return output.getvalue()


@pytest.mark.parametrize("native_platform", ("windows-amd64", "linux-x86_64"))
def test_windows_worker_wheel_transaction_requires_exact_native_platform(
    windows_worker_test_root: Path, native_platform: str
) -> None:
    _exercise_windows_worker_wheel_transaction(
        windows_worker_test_root, native_platform
    )


@pytest.mark.requires_host_runtime
def test_windows_worker_public_coding_session_reaches_selected_product(
    windows_worker_test_root: Path,
) -> None:
    if os.environ.get("LOUSHANG_WINDOWS_BACKEND_REVIEW") != "1":
        pytest.skip("native Windows backend review is required")
    _exercise_windows_worker_wheel_transaction(
        windows_worker_test_root,
        "windows-amd64",
        owner_id="coding",
        ordinary_entry_kind="direct",
    )


@pytest.mark.requires_host_runtime
def test_windows_worker_hosted_first_session_reaches_selected_product(
    windows_worker_test_root: Path,
) -> None:
    if os.environ.get("LOUSHANG_WINDOWS_BACKEND_REVIEW") != "1":
        pytest.skip("native Windows backend review is required")
    _exercise_windows_worker_wheel_transaction(
        windows_worker_test_root,
        "windows-amd64",
        owner_id="coding",
        ordinary_entry_kind="hosted",
    )


@pytest.mark.requires_host_runtime
def test_windows_worker_public_session_disable_fences_pinned_product(
    windows_worker_test_root: Path,
) -> None:
    if os.name != "nt" or os.environ.get("LOUSHANG_WINDOWS_BACKEND_REVIEW") != "1":
        pytest.skip("native Windows backend review is required")
    _exercise_windows_worker_wheel_transaction(
        windows_worker_test_root,
        "windows-amd64",
        owner_id="coding",
        ordinary_entry_kind="direct",
        disable_while_ordinary_session_open=True,
    )


@pytest.mark.requires_host_runtime
@pytest.mark.parametrize("entry_kind", ("direct", "hosted"))
def test_windows_worker_public_session_crash_reopens_and_retires_product_attempt(
    windows_worker_test_root: Path,
    entry_kind: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if os.name != "nt" or os.environ.get("LOUSHANG_WINDOWS_BACKEND_REVIEW") != "1":
        pytest.skip("native Windows backend review is required")
    tmp_path = windows_worker_test_root
    script = """\
import runpy
import sys
from pathlib import Path

module = runpy.run_path(sys.argv[1])
module["_exercise_windows_worker_wheel_transaction"](
    Path(sys.argv[2]), "windows-amd64", owner_id="coding",
    ordinary_entry_kind=sys.argv[3], crash_after_ordinary_query=True,
)
"""
    child_stdout = tmp_path / f"public-{entry_kind}-crash.stdout"
    child_stderr = tmp_path / f"public-{entry_kind}-crash.stderr"
    with child_stdout.open("wb") as stdout, child_stderr.open("wb") as stderr:
        crashed = subprocess.run(
            (
                sys.executable,
                "-c",
                script,
                str(Path(__file__).resolve()),
                str(tmp_path),
                entry_kind,
            ),
            cwd=Path(__file__).resolve().parents[2],
            stdout=stdout,
            stderr=stderr,
            timeout=3600,
            check=False,
        )
    assert crashed.returncode == 7, child_stderr.read_text(
        encoding="utf-8", errors="replace"
    )
    assert f"windows-public-worker-healthy:{entry_kind}\n" in child_stdout.read_text(
        encoding="utf-8"
    )

    workspace = tmp_path / "workspace"
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        worker_candidates=True,
        windows_candidate=True,
    )
    try:
        product = owner.runtime_owner.product_owner
        attempts = inspect_coding_windows_product_worker_recovery_inventory(product)
        assert len(attempts) == 1
        attempt_id = attempts[0].attempt_id
        references = inspect_coding_windows_product_worker_attempt_references(product)
        assert len(references) == 1
        assert references[0].attempt_id == attempt_id
        assert references[0].plugin_id == "workerprobe"
        assert references[0].receipt_fingerprint == (
            attempts[0].launch_receipt_fingerprint
        )
        assert references[0].native_platform == "windows"
        gc_observations = inspect_coding_windows_product_worker_attempt_gc_observations(
            product
        )
        assert len(gc_observations) == 1
        assert gc_observations[0].attempt_reference == references[0]
        assert gc_observations[0].active_gc_reservation_count == 0
        assert gc_observations[0].gc_reservation_revision >= 0
        assert gc_observations[0].matching_revision_refs == ()
        assert gc_observations[0].worker_backup_references.attempt_id == attempt_id
        assert (
            gc_observations[0].worker_backup_references.worker_backup_supported is False
        )
        assert gc_observations[0].worker_backup_references.references == ()
        with patch.object(
            backup_types_module,
            "_SUPPORTED_BACKUP_KINDS",
            ("arch_private_data", "worker_attempt"),
        ):
            with pytest.raises(ValueError, match="backup topology changed"):
                inspect_coding_windows_product_worker_attempt_gc_observations(product)
        first = review_coding_windows_product_worker_crash_cleanup(
            product, attempt_id=attempt_id
        )
        [crashed_c5] = (
            item
            for item in CodingWindowsWorkerActivationStateJournal(
                product
            ).retained_attempts_read_only()
            if item.attempt_id == attempt_id
        )
        assert crashed_c5.phase == "published"
        with patch.object(
            CodingWindowsWorkerActivationStateJournal,
            "retained_attempts_read_only",
            return_value=(),
        ):
            with pytest.raises(ValueError, match="C5 owner is missing"):
                recover_coding_windows_product_worker_crash_attempt(
                    product, attempt_id=attempt_id
                )
        assert (
            review_coding_windows_product_worker_orphan_runtime(
                product, attempt_id=attempt_id
            ).attempt.supervisor_phase
            != "process_settled"
        )
        with pytest.raises(ValueError, match="incomplete"):
            settle_coding_windows_product_worker_crash_c5(
                product, attempt_id=attempt_id
            )
        assert first.orphan_review.native_job_absent is True
        assert len(first.orphan_review.orphan_leases) == 1
        assert (
            product.epoch_runtime.registry.review_orphans(
                store_id=product.epoch_runtime.registry.store_id
            )
            == first.orphan_review.orphan_leases
        )
        if entry_kind == "hosted":
            # Exercise the offline candidate operator entry over a fresh owner.
            with (
                patch(
                    "loushang.coding.cli.package_worker_windows_candidate.version",
                    return_value="2.0.0",
                ),
                patch(
                    "loushang.coding.cli.package_worker_windows_candidate.resolve_coding_plugin_lifecycle_state_layout",
                    return_value=lifecycle,
                ),
            ):
                args = (
                    "--workspace",
                    str(workspace),
                    "--windows-candidate",
                )
                assert (
                    windows_worker_candidate_main(
                        (*args, "inspect", "--attempt-id", attempt_id)
                    )
                    == 0
                )
                inspected = json.loads(capsys.readouterr().out.splitlines()[-1])
                assert inspected["c5Phase"] == "published"
                assert inspected["orphanLeaseCount"] == 1
                with patch(
                    "loushang.coding.package_product_worker_windows_crash_recovery.settle_coding_windows_product_worker_crash_native",
                    side_effect=OSError("injected native recovery pause"),
                ):
                    assert (
                        windows_worker_candidate_main(
                            (*args, "recover-crash", "--attempt-id", attempt_id)
                        )
                        == 1
                    )
                assert "windows_worker_candidate_recovery_unavailable" in (
                    capsys.readouterr().err
                )
                after_supervisor = review_coding_windows_product_worker_orphan_runtime(
                    product, attempt_id=attempt_id
                )
                assert after_supervisor.attempt is not None
                assert after_supervisor.attempt.supervisor_phase == "process_settled"
                assert after_supervisor.attempt.native_phase != "settled"
                with patch(
                    "loushang.coding.package_product_worker_windows_crash_recovery.settle_coding_windows_product_worker_crash_c5",
                    side_effect=OSError("injected C5 recovery pause"),
                ):
                    assert (
                        windows_worker_candidate_main(
                            (*args, "recover-crash", "--attempt-id", attempt_id)
                        )
                        == 1
                    )
                assert "windows_worker_candidate_recovery_unavailable" in (
                    capsys.readouterr().err
                )
                before_c5 = review_coding_windows_product_worker_orphan_runtime(
                    product, attempt_id=attempt_id
                )
                assert before_c5.attempt is not None
                assert before_c5.attempt.native_phase == "settled"
                assert before_c5.attempt.payload_directory_identity is None
                assert before_c5.orphan_leases == ()
                assert (
                    windows_worker_candidate_main(
                        (*args, "recover-crash", "--attempt-id", attempt_id)
                    )
                    == 0
                )
                recovered = json.loads(capsys.readouterr().out.splitlines()[-1])
                assert recovered["c5Phase"] == "settled"
            [c5_settled] = (
                item
                for item in CodingWindowsWorkerActivationStateJournal(
                    product
                ).retained_attempts_read_only()
                if item.attempt_id == attempt_id
            )
            assert (
                recover_coding_windows_product_worker_crash_attempt(
                    product, attempt_id=attempt_id
                )
                == c5_settled
            )
        else:
            supervisor = settle_coding_windows_product_worker_crash_supervisor(
                product, expected_review=first
            )
            assert supervisor is not None and supervisor.process_settled
            second = review_coding_windows_product_worker_crash_cleanup(
                product, attempt_id=attempt_id
            )
            native = settle_coding_windows_product_worker_crash_native(
                product, expected_review=second
            )
            assert native.attempt_id == attempt_id
            lease_review = review_coding_windows_product_worker_crash_lease_repair(
                product, attempt_id=attempt_id
            )
            repaired = repair_coding_windows_product_worker_crash_orphan_runtime(
                product, expected_review=lease_review
            )
            assert repaired == first.orphan_review.orphan_leases[0]
            stage_review = review_coding_windows_product_worker_crash_stage(
                product, attempt_id=attempt_id
            )
            retired = retire_coding_windows_product_worker_crash_stage(
                product, expected_review=stage_review
            )
            assert retired.attempt_id == attempt_id
            with patch(
                "loushang.coding.package_product_worker_windows_orphan_review.observe_windows_worker_job_absent",
                return_value=False,
            ):
                with pytest.raises(ValueError, match="incomplete"):
                    settle_coding_windows_product_worker_crash_c5(
                        product, attempt_id=attempt_id
                    )
            c5_settled = settle_coding_windows_product_worker_crash_c5(
                product, attempt_id=attempt_id
            )
            assert (
                settle_coding_windows_product_worker_crash_c5(
                    product, attempt_id=attempt_id
                )
                == c5_settled
            )
        assert not (product.state_root / f"worker-payload-{attempt_id}").exists()
        assert (
            product.epoch_runtime.registry.review_orphans(
                store_id=product.epoch_runtime.registry.store_id
            )
            == ()
        )
        assert c5_settled.phase == "settled"
        after = inspect_coding_windows_product_worker_offline_recovery(product)
        assert len(after.attempts) == 1
        assert after.attempts[0].payload_directory_identity is None
        assert after.attempts[0].supervisor_phase == "process_settled"
        assert after.opt_in_decisions
        assert len({item.operation_id for item in after.opt_in_decisions}) == len(
            after.opt_in_decisions
        )
        assert after.opt_in_history_revision == len(after.opt_in_decisions)
        assert after.retained_opt_in_operation_ids == tuple(
            item.operation_id for item in after.opt_in_decisions
        )
        assert after.receipt_records
        assert after.receipt_history_revision == len(after.receipt_records)
        assert after.receipt_records[-1].receipt.fingerprint == (
            after.attempts[0].launch_receipt_fingerprint
        )
        assert after.retained_receipt_fingerprints == (
            after.attempts[0].launch_receipt_fingerprint,
        )
        assert after.supervisor_records[-1].attempt_id == attempt_id
        assert after.supervisor_records[-1].phase == "process_settled"
        assert after.supervisor_history_revision == len(after.supervisor_records)
        assert after.retained_supervisor_attempt_ids == (attempt_id,)
        assert after.activation_state_owner_present
        assert after.activation_state_revision >= 6
        assert after.retained_activation_attempts == (c5_settled,)
        assert after.native_job_absence == ((attempt_id, True),)
        with patch(
            "loushang.coding.package_product_worker_windows_recovery_inventory.observe_windows_worker_job_absent",
            side_effect=OSError("native Job observation unavailable"),
        ):
            unknown_job = inspect_coding_windows_product_worker_offline_recovery(
                product
            )
        assert unknown_job.native_job_absence == ((attempt_id, None),)
        assert len(after.supervisor_epoch_high_water) == 1
        assert after.supervisor_epoch_high_water[0][1] >= 1
        assert after.gc_reservation_revision >= 0
        assert after.gc_revision_refs == frozenset()
        assert len(after.worker_backup_observations) == 1
        assert after.worker_backup_observations[0].attempt_id == attempt_id
        assert after.worker_backup_observations[0].references == ()
        opt_in_path = product.state_root / "worker-opt-in.jsonl"
        held_opt_in = product.state_root / "held-worker-opt-in.jsonl"
        opt_in_path.replace(held_opt_in)
        try:
            with pytest.raises(CodingWorkerOptInJournalError) as missing_opt_in:
                inspect_coding_windows_product_worker_offline_recovery(product)
            assert missing_opt_in.value.code == "coding_worker_opt_in_orphan_lock"
        finally:
            held_opt_in.replace(opt_in_path)
    finally:
        owner.close()
    _assert_windows_worker_public_session_restarts_after_recovery(
        tmp_path=tmp_path,
        workspace=workspace,
        entry_kind=entry_kind,
        retired_attempt_id=attempt_id,
    )


def _assert_windows_worker_public_session_restarts_after_recovery(
    *, tmp_path: Path, workspace: Path, entry_kind: str, retired_attempt_id: str
) -> None:
    settings = SettingsManager(
        global_settings_path=tmp_path / "global" / "settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    query_model = Model(
        id="windows-worker-query-after-recovery",
        name="Windows Worker Query After Recovery",
        provider="test",
        endpoint="test",
        capabilities=Capabilities(
            input=("text",), context_window=128_000, max_tokens=4_096
        ),
    )
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    with (
        patch("loushang.coding.package_product_runtime.version", return_value="2.0.0"),
        patch(
            "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
    ):
        if entry_kind == "direct":
            manager = asyncio.run(
                SessionManager.new_with_composition(
                    session_dir=tmp_path / "reopened-worker-transcripts",
                    cwd=str(workspace),
                    session_id="windows-worker-reopened",
                    defer_materialization=False,
                )
            )
            session = create_agent_session(
                session_manager=manager,
                model=query_model,
                services=create_services(settings_manager=settings),
                worker_candidate_plugin_id="workerprobe",
            )

            async def query_direct() -> None:
                try:
                    await session.prepare_model_call_runtime()
                    assert (
                        await session.query_worker_symbol("review") == "Review symbol"
                    )
                finally:
                    await session.dispose()

            asyncio.run(query_direct())
        else:
            assert entry_kind == "hosted"
            runtime = create_agent_session_runtime(
                session_dir=tmp_path / "reopened-hosted-worker-transcripts",
                model=query_model,
                services=create_services(settings_manager=settings),
                worker_candidate_plugin_id="workerprobe",
            )

            async def query_hosted() -> None:
                try:
                    session = await runtime.create_session(cwd=str(workspace))
                    await session.prepare_model_call_runtime()
                    assert (
                        await session.query_worker_symbol("review") == "Review symbol"
                    )
                finally:
                    await runtime.dispose_session_runtime()

            asyncio.run(query_hosted())

    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        worker_candidates=True,
        windows_candidate=True,
    )
    try:
        product = owner.runtime_owner.product_owner
        history = open_coding_windows_product_worker_supervisor_journal(
            product
        ).inspect_records()
        assert len({item.attempt_id for item in history}) == 2
        assert history[-1].attempt_id != retired_attempt_id
        assert history[-1].phase == "stopped"
        attempts = inspect_coding_windows_product_worker_offline_recovery(
            product
        ).attempts
        attempts_by_id = {item.attempt_id: item for item in attempts}
        assert set(attempts_by_id) == {retired_attempt_id, history[-1].attempt_id}
        assert attempts_by_id[retired_attempt_id].payload_directory_identity is None
        assert attempts_by_id[history[-1].attempt_id].native_phase == "settled"
    finally:
        owner.close()


@pytest.fixture
def windows_worker_test_root(tmp_path: Path) -> Iterator[Path]:
    if os.name != "nt" or os.environ.get("LOUSHANG_WINDOWS_BACKEND_REVIEW") != "1":
        yield tmp_path
        return
    # CreateProcessW cannot use a cwd longer than MAX_PATH. The managed pytest
    # tree is deep enough to hide the Product launch behind Win32 error 267.
    with tempfile.TemporaryDirectory(prefix="plc9-w-") as root:
        canonical_root = Path(root).resolve(strict=True)
        candidate = (
            canonical_root
            / "session-state"
            / "plugin-packages"
            / "coding-lifecycle.epochs"
            / ("e" * 64)
            / "product-state"
            / ("worker-payload-" + "7" * 32)
        )
        assert len(str(candidate)) < 260, "native Worker test cwd exceeds MAX_PATH"
        yield canonical_root


def test_windows_worker_clean_retirement_allows_fresh_product_launch(
    windows_worker_test_root: Path,
) -> None:
    if os.name != "nt" or os.environ.get("LOUSHANG_WINDOWS_BACKEND_REVIEW") != "1":
        pytest.skip("native Windows backend review is required")
    tmp_path = windows_worker_test_root
    _exercise_windows_worker_wheel_transaction(
        tmp_path, "windows-amd64", clean_rotation=True
    )
    _assert_windows_worker_retired_history_allows_gc(
        tmp_path, partial_attempt_id="b" * 32
    )


def _retain_windows_c5_test_attempt(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    host_identity: str,
    boot_identity: str,
    evidence_authority_id: str,
    evidence_authority_fingerprint: str,
    settled: bool,
) -> None:
    """Add ordered C5 test history for an already closed native attempt."""

    [attempt] = (
        item
        for item in inspect_coding_windows_product_worker_recovery_inventory(product)
        if item.attempt_id == attempt_id
    )
    assert attempt.launch_receipt_fingerprint is not None
    assert attempt.native_job_name is not None
    with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
        receipts = CodingWindowsWorkerReceiptJournal(
            product.state_root / "worker-activation-receipts.jsonl",
            scope_id=product.policy.project_scope_id,
        ).records(directory_fd=root)
    [record] = (
        item
        for item in receipts
        if item.receipt.fingerprint == attempt.launch_receipt_fingerprint
    )
    receipt = record.receipt
    generation = receipt.policy.owner_selection_generation
    settlement = WorkerCleanupSettlementV2(
        receipt_fingerprint=receipt.fingerprint,
        attempt_id=attempt_id,
        owner_generation=generation,
        host_identity=host_identity,
        boot_identity=boot_identity,
        protocol_terminal=True,
        domain_retired=True,
        tree_settled=True,
        native_containment_settled=True,
    )
    journal = CodingWindowsWorkerActivationStateJournal(product)
    prior = journal.load()
    prior_attempt_ids = {
        item.attempt_id for item in journal.retained_attempts_read_only()
    }
    state = _initial_state(restart_budget=3) if prior is None else dict(prior)
    revision = state["stateRevision"]
    assert type(revision) is int
    prior_attempts = state["attempts"]
    assert type(prior_attempts) is dict
    key = _AttemptKey(receipt.fingerprint, attempt_id, generation).encoded
    registered_attempt = {
        "attemptId": attempt_id,
        "bootIdentity": boot_identity,
        "cleanupContractVersion": 2,
        "cleanupDebt": None,
        "cleanupSettlement": None,
        "domainRetired": False,
        "evidenceAuthorityFingerprint": evidence_authority_fingerprint,
        "evidenceAuthorityId": evidence_authority_id,
        "hostIdentity": host_identity,
        "owner": "hosting",
        "ownerGeneration": generation,
        "phase": "registered",
        "policyFingerprint": receipt.policy.fingerprint,
        "protocolTerminal": False,
        "readiness": "pending",
        "receiptFingerprint": receipt.fingerprint,
        "required": receipt.policy.effective_required,
        "restartOrdinal": 0,
    }
    registered = {
        **state,
        "stateRevision": revision + 1,
        "attempts": {**prior_attempts, key: registered_attempt},
    }
    effect_started = {
        **registered,
        "stateRevision": revision + 2,
        "attempts": {
            **prior_attempts,
            key: {**registered_attempt, "phase": "effect_started"},
        },
    }
    retired_attempt = {
        **registered_attempt,
        "phase": "retired",
        "domainRetired": True,
        "protocolTerminal": True,
    }
    retired = {
        **effect_started,
        "stateRevision": revision + 3,
        "attempts": {**prior_attempts, key: retired_attempt},
    }
    settled_state = {
        **retired,
        "stateRevision": revision + 4,
        "attempts": {
            **prior_attempts,
            key: {
                **retired_attempt,
                "phase": "settled",
                "cleanupSettlement": settlement.to_dict(),
            },
        },
    }
    documents = (() if prior is not None else (state,)) + (
        registered,
        effect_started,
        retired,
    )
    if settled:
        documents += (settled_state,)
    for document in documents:
        document_revision = document["stateRevision"]
        assert type(document_revision) is int
        assert journal.compare_and_swap(
            expected_revision=document_revision - 1, document=document
        )
    assert {item.attempt_id for item in journal.retained_attempts_read_only()} == {
        *prior_attempt_ids,
        attempt_id,
    }


def _assert_windows_worker_retired_history_allows_gc(
    tmp_path: Path, *, partial_attempt_id: str | None
) -> None:
    workspace = tmp_path / "workspace"
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        worker_candidates=True,
        windows_candidate=True,
    )
    try:
        product = owner.runtime_owner.product_owner
        assert isinstance(product, WindowsLocalWheelProductSessionOwner)
        gc = open_windows_local_wheel_product_root_gc(
            product,
            worker_history_authority=CodingWindowsWorkerGcHistoryAuthority(product),
        )
        with pytest.raises(PackageProductGcExecutionError) as live_stage:
            gc.prepare()
        assert live_stage.value.code == "plugin_package_gc_worker_payload_unsettled"

        if partial_attempt_id is None:
            review = review_coding_windows_product_worker_complete_stage(
                product, attempt_id="9" * 32
            )
            retire_coding_windows_product_worker_complete_stage(
                product, expected_review=review
            )
        assert not (product.state_root / ("worker-payload-" + "9" * 32)).exists()
        assert (
            product.state_root / ("worker-stage-retired-" + "9" * 32 + ".json")
        ).is_file()
        if partial_attempt_id is not None:
            assert (
                product.state_root
                / ("worker-unlaunched-stage-retired-" + "a" * 32 + ".json")
            ).is_file()
            partial_review = review_coding_windows_product_worker_partial_stage(
                product, attempt_id=partial_attempt_id
            )
            retire_coding_windows_product_worker_partial_stage(
                product, expected_review=partial_review
            )
            assert not (
                product.state_root / ("worker-payload-" + partial_attempt_id)
            ).exists()

        without_worker_proof = open_windows_local_wheel_product_root_gc(product)
        with pytest.raises(PackageProductGcExecutionError) as unproved:
            without_worker_proof.prepare()
        assert unproved.value.code == "plugin_package_gc_worker_history_unsettled"
        unknown_history = product.state_root / (
            "worker-crash-stage-retired-" + "c" * 32 + ".json"
        )
        unknown_history.write_bytes(b"unproved")
        try:
            with pytest.raises(PackageProductGcExecutionError) as corrupt:
                gc.prepare()
            assert corrupt.value.code == "plugin_package_gc_worker_history_unsettled"
        finally:
            unknown_history.unlink()

        staged_history = product.state_root / (
            "worker-stage-retired-" + "9" * 32 + ".json.stage"
        )
        staged_history.write_bytes(b"unpublished")
        try:
            with pytest.raises(PackageProductGcExecutionError) as staged:
                gc.prepare()
            assert staged.value.code == "plugin_package_gc_worker_history_unsettled"
        finally:
            staged_history.unlink()

        unknown_state = product.state_root / "worker-future-reference.json"
        unknown_state.write_bytes(b"unknown owner")
        try:
            with pytest.raises(PackageProductGcExecutionError) as unknown:
                gc.prepare()
            assert unknown.value.code == "plugin_package_gc_worker_history_unsettled"
        finally:
            unknown_state.unlink()

        completed_receipt = product.state_root / (
            "worker-stage-retired-" + "9" * 32 + ".json"
        )
        held_receipt = product.state_root / "held-stage-retired-9.json"
        completed_receipt.replace(held_receipt)
        try:
            with pytest.raises(PackageProductGcExecutionError) as missing_receipt:
                gc.prepare()
            assert missing_receipt.value.code == (
                "plugin_package_gc_worker_history_unsettled"
            )
        finally:
            held_receipt.replace(completed_receipt)

        receipt_lock = product.state_root / "worker-activation-receipts.jsonl.lock"
        held_receipt_lock = product.state_root / "held-activation-receipts.lock"
        receipt_lock.replace(held_receipt_lock)
        try:
            with pytest.raises(PackageProductGcExecutionError) as missing_lock:
                gc.prepare()
            assert missing_lock.value.code == (
                "plugin_package_gc_worker_history_unsettled"
            )
        finally:
            held_receipt_lock.replace(receipt_lock)

        opt_in_owner = CodingWindowsWorkerProductOptInOwner(product)
        opt_in = opt_in_owner.current("workerprobe")
        assert opt_in is not None and opt_in.action == "allow"
        revoked = opt_in_owner.revoke(
            plugin_id="workerprobe",
            operation_id="operator:windows-worker-gc-revoke",
            expected_generation=opt_in.generation,
        )
        assert revoked.action == "revoke"
        snapshot = product.desired_state.snapshot()
        selected = next(
            item
            for item in snapshot.installations
            if item.installation_key.plugin_id == "workerprobe"
        )
        revision = selected.selection.package_revision
        assert revision is not None
        removed = product.management.submit(
            PluginManagementCommandV1(
                action="remove",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator:windows-worker-gc-remove",
                    idempotency_key="operator:windows-worker-gc-remove",
                    expected_inventory_revision=snapshot.inventory_revision,
                    installation_key=selected.installation_key,
                    desired_state="absent",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision="operator:1",
                ),
            )
        )
        assert removed.result is not None
        assert removed.result.disposition == "succeeded"
        opt_in_path = product.state_root / "worker-opt-in.jsonl"
        held_opt_in = product.state_root / "held-worker-opt-in-for-gc.jsonl"
        opt_in_path.replace(held_opt_in)
        try:
            with pytest.raises(PackageProductGcExecutionError) as missing_opt_in:
                gc.prepare()
            assert missing_opt_in.value.code == (
                "plugin_package_gc_worker_history_unsettled"
            )
        finally:
            held_opt_in.replace(opt_in_path)
        retained_ids = {
            item.attempt_id
            for item in CodingWindowsWorkerActivationStateJournal(
                product
            ).retained_attempts_read_only()
        }
        for earlier in inspect_coding_windows_product_worker_recovery_inventory(
            product
        ):
            if (
                earlier.attempt_id == "9" * 32
                or earlier.attempt_id in retained_ids
                or earlier.launch_request_fingerprint is None
            ):
                continue
            _retain_windows_c5_test_attempt(
                product,
                attempt_id=earlier.attempt_id,
                host_identity="native-gc-prior-test-host",
                boot_identity="native-gc-prior-test-boot",
                evidence_authority_id="native-gc-prior-test-evidence",
                evidence_authority_fingerprint="e" * 64,
                settled=True,
            )
        _retain_windows_c5_test_attempt(
            product,
            attempt_id="9" * 32,
            host_identity="native-gc-test-host",
            boot_identity="native-gc-test-boot",
            evidence_authority_id="native-gc-test-evidence",
            evidence_authority_fingerprint="d" * 64,
            settled=True,
        )
        for observed_absence in (False, None):
            with (
                patch(
                    "loushang.coding.package_product_worker_windows_gc_history._observe_native_job_absence",
                    return_value=observed_absence,
                ),
                pytest.raises(PackageProductGcExecutionError) as job_unverified,
            ):
                gc.prepare()
            assert job_unverified.value.code == (
                "plugin_package_gc_worker_history_unsettled"
            )
        gc.prepare()
        candidate = next(
            item for item in gc.candidates() if item.package_revision == revision
        )
        target = resolve_plugin_package_gc_root_target(
            revision,
            bindings=product.gc_bindings.records(),
            claims=product.gc_bindings.claims(),
            committed_sets=gc.application.executor.committed_sets.records(),
            settlements=gc.application.executor.root_settlements.records(),
        )
        deleted_root = product.plugin_store_root / target.settlement.final_name
        assert deleted_root.is_dir()
        result = gc.execute(
            PackageProductRootGcCommandV1(
                candidate=candidate,
                reservation_operation_id="operator:windows-worker-gc-reserve",
                reservation_idempotency_key="operator:windows-worker-gc-reserve",
                attempt_operation_id="operator:windows-worker-gc-delete",
                attempt_idempotency_key="operator:windows-worker-gc-delete",
            )
        )
        assert result.disposition == "succeeded"
        assert not deleted_root.exists()
        assert (
            product.state_root / ("worker-stage-retired-" + "9" * 32 + ".json")
        ).is_file()
        if partial_attempt_id is None:
            assert (
                product.state_root
                / ("worker-crash-stage-retired-" + "7" * 32 + ".json")
            ).is_file()
        else:
            assert (
                product.state_root
                / ("worker-unlaunched-stage-retired-" + "a" * 32 + ".json")
            ).is_file()
            assert (
                product.state_root
                / ("worker-partial-stage-retired-" + partial_attempt_id + ".json")
            ).is_file()
    finally:
        owner.close()


def test_windows_worker_host_crash_reopens_and_retires_product_attempt(
    windows_worker_test_root: Path,
) -> None:
    if os.name != "nt" or os.environ.get("LOUSHANG_WINDOWS_BACKEND_REVIEW") != "1":
        pytest.skip("native Windows backend review is required")
    tmp_path = windows_worker_test_root
    script = """\
import runpy
import sys
from pathlib import Path

module = runpy.run_path(sys.argv[1])
module["_exercise_windows_worker_wheel_transaction"](
    Path(sys.argv[2]), "windows-amd64", crash_after_healthy=True
)
"""
    child_stdout = tmp_path / "crash-child.stdout"
    child_stderr = tmp_path / "crash-child.stderr"
    try:
        with child_stdout.open("wb") as stdout, child_stderr.open("wb") as stderr:
            crashed = subprocess.run(
                (
                    sys.executable,
                    "-c",
                    script,
                    str(Path(__file__).resolve()),
                    str(tmp_path),
                ),
                cwd=Path(__file__).resolve().parents[2],
                stdout=stdout,
                stderr=stderr,
                # A native Worker may retain inherited file handles after its
                # host exits; wait on the host process, not captured pipes.
                timeout=3600,
                check=False,
            )
    except subprocess.TimeoutExpired as exc:

        def tail(path: Path) -> bytes:
            with path.open("rb") as output:
                output.seek(0, os.SEEK_END)
                output.seek(max(0, output.tell() - 4096))
                return output.read()

        raise AssertionError(
            "Windows Worker crash child did not reach its planned exit"
            f"\nstdout tail: {tail(child_stdout)!r}"
            f"\nstderr tail: {tail(child_stderr)!r}"
        ) from exc
    assert crashed.returncode == 7, child_stderr.read_text(
        encoding="utf-8", errors="replace"
    )
    assert "windows-product-worker-healthy\n" in child_stdout.read_text(
        encoding="utf-8"
    )

    workspace = tmp_path / "workspace"
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        worker_candidates=True,
        windows_candidate=True,
    )
    try:
        product = owner.runtime_owner.product_owner
        assert isinstance(product, WindowsLocalWheelProductSessionOwner)
        attempt_id = "7" * 32
        first = review_coding_windows_product_worker_crash_cleanup(
            product, attempt_id=attempt_id
        )
        assert first.orphan_review.native_job_absent is True
        assert len(first.orphan_review.orphan_leases) == 1
        supervisor = settle_coding_windows_product_worker_crash_supervisor(
            product, expected_review=first
        )
        assert supervisor is not None and supervisor.process_settled
        with pytest.raises(ValueError, match="stale"):
            settle_coding_windows_product_worker_crash_native(
                product, expected_review=first
            )
        second = review_coding_windows_product_worker_crash_cleanup(
            product, attempt_id=attempt_id
        )
        assert second.orphan_review.attempt is not None
        assert second.orphan_review.attempt.supervisor_process_settled is True
        native = settle_coding_windows_product_worker_crash_native(
            product, expected_review=second
        )
        assert native.attempt_id == attempt_id
        lease_review = review_coding_windows_product_worker_crash_lease_repair(
            product, attempt_id=attempt_id
        )
        repaired = repair_coding_windows_product_worker_crash_orphan_runtime(
            product, expected_review=lease_review
        )
        assert repaired == first.orphan_review.orphan_leases[0]
        stage_review = review_coding_windows_product_worker_crash_stage(
            product, attempt_id=attempt_id
        )
        retired = retire_coding_windows_product_worker_crash_stage(
            product, expected_review=stage_review
        )
        assert retired.attempt_id == attempt_id
        assert not (product.state_root / f"worker-payload-{attempt_id}").exists()
        assert (
            product.epoch_runtime.registry.review_orphans(
                store_id=product.epoch_runtime.registry.store_id
            )
            == ()
        )
        offline = inspect_coding_windows_product_worker_offline_recovery(product)
        assert len(offline.attempts) == 1
        assert offline.attempts[0].attempt_id == attempt_id
        assert offline.attempts[0].payload_directory_identity is None
        assert offline.attempts[0].supervisor_phase == "process_settled"
    finally:
        owner.close()
    _assert_windows_worker_clean_rotation(
        workspace=workspace,
        session_state=tmp_path / "session-state",
        expected_digest=sha256(
            (tmp_path / "compiled-worker.exe").read_bytes()
        ).hexdigest(),
        crash_retired=True,
    )
    _assert_windows_worker_retired_history_allows_gc(tmp_path, partial_attempt_id=None)


def test_windows_worker_selected_dependency_closure_remains_inert(
    windows_worker_test_root: Path,
) -> None:
    if os.name != "nt" or os.environ.get("LOUSHANG_WINDOWS_BACKEND_REVIEW") != "1":
        pytest.skip("native Windows backend review is required")
    _exercise_windows_worker_wheel_transaction(
        windows_worker_test_root, "windows-amd64", dependency_closure=True
    )


@pytest.mark.requires_host_runtime
def test_windows_worker_native_normal_exit_c5_cleanup_evidence(
    windows_worker_test_root: Path,
) -> None:
    if os.name != "nt" or os.environ.get("LOUSHANG_WINDOWS_BACKEND_REVIEW") != "1":
        pytest.skip("native Windows backend review is required")
    _exercise_windows_worker_wheel_transaction(
        windows_worker_test_root, "windows-amd64", c5_cleanup_review=True
    )


def _exercise_windows_worker_wheel_transaction(
    tmp_path: Path,
    native_platform: str,
    *,
    clean_rotation: bool = False,
    dependency_closure: bool = False,
    crash_after_healthy: bool = False,
    crash_after_ordinary_query: bool = False,
    c5_cleanup_review: bool = False,
    owner_id: str = "coding",
    ordinary_entry_kind: str | None = None,
    disable_while_ordinary_session_open: bool = False,
) -> None:
    """Only the explicit Product opener reads the inert Worker candidate."""

    assert not disable_while_ordinary_session_open or (
        ordinary_entry_kind == "direct" and not crash_after_ordinary_query
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global" / "settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="e" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    assert cutover.attempt.result.disposition == "fenced"
    assert bootstrap_coding_builtin_product_plugins(
        lifecycle,
        settings,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    try:
        product = owner.runtime_owner.product_owner
        assert isinstance(product, WindowsLocalWheelProductSessionOwner)
        assert isinstance(owner.epoch_runtime, PackageProductWindowsFencedRuntimeOwner)
        with owner.epoch_runtime.borrow_product_state_root_descriptor() as state_fd:
            assert os.path.samestat(os.fstat(state_fd), product.state_root.stat())
        switch = owner.epoch_runtime.cutover_result.switch_receipt
        assert switch is not None
        executable = bytearray(512)
        executable[:2] = b"MZ"
        pack_into("<I", executable, 0x3C, 0x80)
        executable[0x80:0x84] = b"PE\x00\x00"
        pack_into("<H", executable, 0x84, 0x8664)
        pack_into("<H", executable, 0x86, 1)
        pack_into("<H", executable, 0x94, 112)
        pack_into("<H", executable, 0x96, 0x0002)
        pack_into("<H", executable, 0x98, 0x20B)
        if (
            native_platform == "windows-amd64"
            and os.environ.get("LOUSHANG_WINDOWS_BACKEND_REVIEW") == "1"
        ):
            build_root = tmp_path / "worker-native-build"
            build_root.mkdir()
            compiled = tmp_path / "compiled-worker.exe"
            _compile_windows_query_worker(build_root, compiled)
            executable = bytearray(compiled.read_bytes())
        payload = build_coding_local_worker_candidate_wheel(
            plugin_id="workerprobe",
            version="1",
            contribution_id="query-provider",
            owner_id=owner_id,
            native_platform="windows-amd64",
            wheel_tag="py3-none-win_amd64",
            executable=bytes(executable),
            dependencies=(
                ("auxiliary==1", "dependency==1") if dependency_closure else ()
            ),
        )
        original_root = tmp_path / "worker-source"
        original_root.mkdir()
        source = original_root / "workerprobe-1-py3-none-win_amd64.whl"
        executable_source = tmp_path / "worker-query.exe"
        executable_source.write_bytes(bytes(executable))
        authored = subprocess.run(
            (
                sys.executable,
                "-m",
                "loushang.plugin",
                "build-coding-worker-candidate",
                str(executable_source),
                "--plugin-id",
                "workerprobe",
                "--version",
                "1",
                "--contribution-id",
                "query-provider",
                "--owner-id",
                owner_id,
                "--native-platform",
                "windows-amd64",
                *(
                    (
                        "--dependency",
                        "dependency==1",
                        "--dependency",
                        "auxiliary==1",
                    )
                    if dependency_closure
                    else ()
                ),
                "--output-dir",
                str(original_root),
            ),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert authored.returncode == 0, authored.stderr
        author_result = json.loads(authored.stdout)
        assert author_result["artifactPath"] == str(source)
        assert author_result["profile"] == "coding-local-worker-candidate-v1"
        assert author_result["productAdmission"] == "not_checked"
        assert author_result["productUse"] == "not_checked"
        assert source.read_bytes() == payload
        assert author_result["sha256"] == sha256(payload).hexdigest()
        windows_admission = PackageProductLocalWorkerAdmissionV1(
            contribution_id="query-provider",
            owner_id=owner_id,
            native_platform="windows-amd64",
        )
        if native_platform == "windows-amd64":
            with patch(
                "loushang.coding.package_legacy_windows_receipt.windows_rename_at",
                side_effect=RuntimeError("injected receipt publish interruption"),
            ):
                with pytest.raises(RuntimeError, match="publish interruption"):
                    admit_coding_external_worker_wheel(
                        lifecycle, source=source, admission=windows_admission
                    )
        record = admit_coding_external_worker_wheel(
            lifecycle, source=source, admission=windows_admission
        )
        assert record.artifact_digest == sha256(payload).hexdigest()
        assert (
            admit_coding_external_worker_wheel(
                lifecycle, source=source, admission=windows_admission
            )
            == record
        )
        with pytest.raises(CodingExternalWorkerWheelError):
            admit_coding_external_worker_wheel(
                lifecycle,
                source=source,
                admission=replace(windows_admission, owner_id="coding.other"),
            )
        catalog = CodingWindowsExternalWorkerWheelCatalog(
            epoch_runtime=owner.epoch_runtime,
            state_root=product.state_root,
            source_root=product.policy.source_root,
            store_id=owner.epoch_runtime.registry.store_id,
            namespace_id=switch.namespace_id,
            scope_id=lifecycle.scope_id,
        )
        source.write_bytes(b"changed original Source")
        assert catalog.records() == (record,)
        catalog.verify_record(record)
        plain_reopen = open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
            windows_candidate=True,
        )
        try:
            assert all(
                item.plugin_id != "workerprobe"
                for item in plain_reopen.runtime_owner.product_owner.policy.bindings
            )
        finally:
            plain_reopen.close()
        reopen_command: tuple[str, ...] | None = None
        if native_platform == "windows-amd64":
            epoch = resolve_coding_package_epoch_layout(lifecycle)
            script = """\
import json
import sys
from pathlib import Path
from loushang.coding.package_external_worker_wheel import CodingWindowsExternalWorkerWheelCatalog
from loushang.harness.resources.packages.product_windows_epoch_guard import PackageProductWindowsFencedRuntimeOwner

owner = PackageProductWindowsFencedRuntimeOwner.open(
    authority_root=Path(sys.argv[1]), control_root=Path(sys.argv[2]),
    store_id=sys.argv[3], epochs_root_name=sys.argv[4],
)
try:
    catalog = CodingWindowsExternalWorkerWheelCatalog(
        epoch_runtime=owner, state_root=Path(sys.argv[5]),
        source_root=Path(sys.argv[6]), store_id=sys.argv[3],
        namespace_id=sys.argv[7], scope_id=sys.argv[8],
    )
    records = catalog.records()
    for record in records:
        catalog.verify_record(record)
    print(json.dumps([record.to_dict() for record in records], sort_keys=True))
finally:
    owner.close()
"""
            reopen_command = (
                sys.executable,
                "-c",
                script,
                str(epoch.authority_root),
                str(epoch.control_root),
                epoch.store_id,
                epoch.epochs_root_name,
                str(product.state_root),
                str(product.policy.source_root),
                switch.namespace_id,
                lifecycle.scope_id,
            )
            reopened = subprocess.run(
                reopen_command,
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            assert reopened.returncode == 0, reopened.stderr
            assert json.loads(reopened.stdout) == [record.to_dict()]
        worker_owner = None
        receipt_fingerprint: str | None = None
        rotation_pending = False
        stage_retention_expected = False
        worker_state_root = product.state_root
        if native_platform == "windows-amd64":
            worker_owner = open_coding_fenced_product_application_owner(
                lifecycle,
                workspace=workspace,
                runtime_version="2.0.0",
                runtime_protocol_epoch=2,
                worker_candidates=True,
                windows_candidate=True,
            )
            worker_product = worker_owner.runtime_owner.product_owner
            assert isinstance(worker_product, WindowsLocalWheelProductSessionOwner)
            worker_state_root = worker_product.state_root
            assert any(
                item.plugin_id == "workerprobe"
                for item in worker_product.policy.bindings
            )
            assert (
                open_coding_windows_product_worker_activation_state_store(
                    worker_product
                ).load()
                is None
            )
            assert not any(
                name.startswith("worker-activation-state")
                for name in os.listdir(worker_state_root)
            )
            if dependency_closure:
                dependency_bindings = []
                for dependency_name in ("auxiliary", "dependency"):
                    dependency_payload = _windows_worker_dependency_wheel(
                        dependency_name
                    )
                    dependency_source = (
                        worker_product.policy.source_root
                        / f"{dependency_name}-1-py3-none-any.whl"
                    )
                    dependency_source.write_bytes(dependency_payload)
                    dependency_bindings.append(
                        PackageProductLocalWheelDependencyV1(
                            source_identity=str(dependency_source),
                            project_name=dependency_name,
                            version="1",
                            artifact_digest=sha256(dependency_payload).hexdigest(),
                        )
                    )
                worker_product = replace(
                    worker_product,
                    policy=replace(
                        worker_product.policy,
                        dependencies=tuple(dependency_bindings),
                    ),
                )
        else:
            binding = replace(
                record.policy_binding(product.policy.source_root),
                worker_admission=replace(
                    windows_admission, native_platform="linux-x86_64"
                ),
            )
            policy = replace(
                product.policy,
                bindings=tuple(
                    sorted(
                        (*product.policy.bindings, binding),
                        key=lambda item: item.source_identity,
                    )
                ),
            )
            worker_product = replace(product, policy=policy)
        controlled_source = record.policy_binding(
            product.policy.source_root
        ).source_identity
        factory = worker_product.factory_for_session(
            session_id="windows-worker-candidate",
            cwd=workspace,
            runtime_id="runtime:windows-worker-candidate",
        )
        runtime = None
        try:
            runtime = factory.create(
                PackageProductRuntimeRequestV1(
                    product_id="coding",
                    session_id="windows-worker-candidate",
                    cwd=str(workspace),
                )
            )
            runtime.activate()
            if native_platform == "windows-amd64":
                with pytest.raises(
                    CodingWindowsWorkerRecoveryAdmissionError,
                    match="coding_worker_offline_recovery_runtime_active",
                ):
                    inspect_coding_windows_product_worker_offline_recovery(
                        worker_product
                    )
            outcome = runtime.lifecycle.route(
                PackageProductLifecycleIntentV1(
                    operation_id="windows-worker-candidate-install",
                    action="install",
                    source=controlled_source,
                    scope="project",
                ),
                entrypoint="cli",
            )
            assert outcome.handled
            assert outcome.record is not None
            assert outcome.record.lifecycle == (
                "installed" if native_platform == "windows-amd64" else "failed"
            )
            installed = tuple(
                item
                for item in product.desired_state.snapshot().installations
                if item.installation_key.plugin_id == "workerprobe"
            )
            if native_platform == "windows-amd64":
                assert len(installed) == 1
                assert installed[0].selection.desired_state == "installed_disabled"
                with pytest.raises(PackageProductRuntimeReadError) as disabled:
                    runtime.capture_selected_plugin_manifest_for(
                        "workerprobe",
                        max_files=16,
                        max_total_bytes=16 * 1024 * 1024,
                    )
                assert disabled.value.code == "package_product_root_not_selected"
                snapshot = worker_product.desired_state.snapshot()
                enabled = worker_product.management.submit(
                    PluginManagementCommandV1(
                        action="enable",
                        mutation=PluginDesiredStateMutationV1(
                            operation_id="windows-worker-candidate-enable",
                            idempotency_key="windows-worker-candidate-enable",
                            expected_inventory_revision=snapshot.inventory_revision,
                            installation_key=installed[0].installation_key,
                            desired_state="installed_enabled",
                            package_revision=None,
                            actor_id=worker_product.actor_id,
                            policy_revision=worker_product.desired_policy_revision,
                        ),
                    )
                )
                assert enabled.status == "terminal"
                selected = runtime.capture_selected_plugin_manifest_for(
                    "workerprobe",
                    max_files=16,
                    max_total_bytes=16 * 1024 * 1024,
                )
                if dependency_closure:
                    assert (
                        selected.snapshot.committed_record.closure_lock.node_count == 3
                    )
                    closure = runtime.capture_selected_dependency_closure_for_plugin(
                        "workerprobe",
                        max_dependencies=3,
                        max_files_per_dependency=16,
                        max_total_bytes=3 * 1024 * 1024,
                    )
                    assert len(closure.members) == 2
                    assert {
                        member.dependency_ref.distribution for member in closure.members
                    } == {"auxiliary", "dependency"}
                    runtime.assert_selected_dependency_closure_current(closure)
                    with pytest.raises(PackageProductRuntimeReadError) as too_many:
                        runtime.capture_selected_dependency_closure_for_plugin(
                            "workerprobe",
                            max_dependencies=1,
                            max_files_per_dependency=16,
                            max_total_bytes=3 * 1024 * 1024,
                        )
                    assert too_many.value.code == (
                        "package_product_dependency_shape_unsupported"
                    )
                    with pytest.raises(CodingWorkerProductOptInError) as refused:
                        CodingWindowsWorkerProductOptInOwner(worker_product).allow(
                            plugin_id="workerprobe",
                            operation_id="windows-worker-dependency-refused",
                            expected_generation=0,
                            require_worker=False,
                        )
                    assert refused.value.code == (
                        "coding_worker_dependency_activation_unsupported"
                    )
                    current_inventory = worker_product.desired_state.snapshot()
                    disabled = worker_product.management.submit(
                        PluginManagementCommandV1(
                            action="disable",
                            mutation=PluginDesiredStateMutationV1(
                                operation_id="windows-worker-dependency-disable",
                                idempotency_key="windows-worker-dependency-disable",
                                expected_inventory_revision=(
                                    current_inventory.inventory_revision
                                ),
                                installation_key=installed[0].installation_key,
                                desired_state="installed_disabled",
                                package_revision=None,
                                actor_id=worker_product.actor_id,
                                policy_revision=worker_product.desired_policy_revision,
                            ),
                        )
                    )
                    assert disabled.status == "terminal"
                    with pytest.raises(PackageProductRuntimeReadError) as stale:
                        runtime.assert_selected_dependency_closure_current(closure)
                    assert stale.value.code == "package_product_root_not_selected"
                    return
                candidate = verify_product_selected_worker_candidate(
                    selected,
                    contribution_id="query-provider",
                    native_platform="windows-amd64",
                )
                assert candidate.plugin_id == "workerprobe"
                assert candidate.executable_digest == sha256(executable).hexdigest()
                runtime.assert_selected_plugin_manifest_current(selected)
                if os.environ.get("LOUSHANG_WINDOWS_BACKEND_REVIEW") == "1":
                    wheels = tuple(
                        Path(".artifacts/windows-backend-wheel").glob("loushang-*.whl")
                    )
                    assert len(wheels) == 1
                    wheel = wheels[0].read_bytes()
                    before_review = tuple(sorted(worker_product.state_root.iterdir()))
                    review = review_coding_windows_worker_backend_release(
                        worker_product, loushang_wheel=wheel
                    )
                    assert review.scope_id == worker_product.policy.project_scope_id
                    assert review.approval.wheel_sha256 == sha256(wheel).hexdigest()
                    assert (
                        tuple(sorted(worker_product.state_root.iterdir()))
                        == before_review
                    )
                    approval_owner = CodingWindowsWorkerNativeApprovalOwner(
                        worker_product
                    )
                    approved = approval_owner.approve(
                        loushang_wheel=wheel,
                        review_id=review.review_id,
                        operation_id="windows-native-reviewed-approval-1",
                        expected_generation=0,
                    )
                    assert approved.action == "approve"
                    assert approved.approval == review.approval
                    assert approval_owner.current() == approved
                    release_path = (
                        worker_product.state_root
                        / "worker-native-backend-release-v1.whl"
                    )
                    with patch.object(
                        windows_receipt_module,
                        "windows_rename_at",
                        side_effect=OSError("injected backend publish interruption"),
                    ):
                        with pytest.raises(OSError, match="publish interruption"):
                            install_coding_windows_worker_backend_release(
                                worker_product,
                                loushang_wheel=wheel,
                                review_id=review.review_id,
                            )
                    assert not release_path.exists()
                    assert release_path.with_name(release_path.name + ".stage").exists()
                    with pytest.raises(CodingWindowsWorkerInstalledBackendError):
                        read_coding_windows_worker_installed_backend_release(
                            worker_product
                        )
                    installed_backend = install_coding_windows_worker_backend_release(
                        worker_product,
                        loushang_wheel=wheel,
                        review_id=review.review_id,
                    )
                    assert installed_backend.review == review
                    assert installed_backend.approval_generation == 1
                    assert release_path.is_file()
                    assert not release_path.with_name(
                        release_path.name + ".stage"
                    ).exists()
                    closure = CodingWindowsWorkerInstalledBackendReader(
                        worker_product
                    ).current_closure()
                    assert closure.native_platform == "windows-amd64"
                    assert (
                        closure.containment_launcher_digest
                        == review.approval.launcher_sha256
                    )
                    assert closure.native_profile_catalog_revision.endswith(":g1")
                    assert (
                        read_coding_windows_worker_installed_backend_release(
                            worker_product
                        )
                        == installed_backend
                    )
                    opt_in_owner = CodingWindowsWorkerProductOptInOwner(worker_product)
                    allowed = opt_in_owner.allow(
                        plugin_id="workerprobe",
                        operation_id="windows-worker-product-allow-1",
                        expected_generation=0,
                        require_worker=False,
                    )
                    assert allowed.action == "allow"
                    assert allowed.opt_in is not None
                    assert allowed.opt_in.native_platform == "windows-amd64"
                    assert opt_in_owner.current("workerprobe") == allowed
                    if ordinary_entry_kind is not None:
                        assert owner_id == "coding"
                        assert ordinary_entry_kind in {"direct", "hosted"}
                        if crash_after_ordinary_query:
                            # The install runtime is fixture setup. The crash
                            # must leave only the public Session's lease orphaned.
                            runtime.dispose_runtime()
                        query_model = Model(
                            id="windows-worker-query",
                            name="Windows Worker Query",
                            provider="test",
                            endpoint="test",
                            capabilities=Capabilities(
                                input=("text",),
                                context_window=128_000,
                                max_tokens=4_096,
                            ),
                        )
                        with (
                            patch(
                                "loushang.coding.package_product_runtime.version",
                                return_value="2.0.0",
                            ),
                            patch(
                                "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
                                return_value=lifecycle,
                            ),
                        ):
                            if ordinary_entry_kind == "direct":
                                ordinary_manager = asyncio.run(
                                    SessionManager.new_with_composition(
                                        session_dir=(
                                            tmp_path / "ordinary-worker-transcripts"
                                        ),
                                        cwd=str(workspace),
                                        session_id="windows-worker-ordinary",
                                        defer_materialization=False,
                                    )
                                )
                                session_start = monotonic()
                                ordinary_session = create_agent_session(
                                    session_manager=ordinary_manager,
                                    model=query_model,
                                    services=create_services(settings_manager=settings),
                                    worker_candidate_plugin_id="workerprobe",
                                )
                                print(
                                    "windows-public-worker-session-created:"
                                    f"{monotonic() - session_start:.3f}s",
                                    flush=True,
                                )

                                async def exercise_direct_worker() -> None:
                                    prepare_start = monotonic()
                                    try:
                                        await ordinary_session.prepare_model_call_runtime()
                                        assert (
                                            await ordinary_session.query_worker_symbol(
                                                "review"
                                            )
                                            == "Review symbol"
                                        )
                                        worker_consumer = bind_coding_worker_query_consumer(
                                            ordinary_session
                                        )
                                        if disable_while_ordinary_session_open:
                                            snapshot = (
                                                worker_product.desired_state.snapshot()
                                            )
                                            disabled = worker_product.management.submit(
                                                PluginManagementCommandV1(
                                                    action="disable",
                                                    mutation=PluginDesiredStateMutationV1(
                                                        operation_id=(
                                                            "windows-worker-session-disable"
                                                        ),
                                                        idempotency_key=(
                                                            "windows-worker-session-disable"
                                                        ),
                                                        expected_inventory_revision=(
                                                            snapshot.inventory_revision
                                                        ),
                                                        installation_key=(
                                                            installed[
                                                                0
                                                            ].installation_key
                                                        ),
                                                        desired_state=(
                                                            "installed_disabled"
                                                        ),
                                                        package_revision=None,
                                                        actor_id=(
                                                            worker_product.actor_id
                                                        ),
                                                        policy_revision=(
                                                            worker_product.desired_policy_revision
                                                        ),
                                                    ),
                                                )
                                            )
                                            assert disabled.status == "terminal"
                                            with pytest.raises(
                                                ValueError,
                                                match="Coding Worker selection changed before Session preparation",
                                            ):
                                                await ordinary_session.query_worker_symbol(
                                                    "review"
                                                )
                                            with pytest.raises(
                                                CapabilityWorkerFacetProxyError,
                                                match="worker_capability_facet_proxy_owner_unavailable",
                                            ):
                                                await worker_consumer.query(symbol="review")
                                        if crash_after_ordinary_query:
                                            print(
                                                "windows-public-worker-healthy:direct",
                                                flush=True,
                                            )
                                            os._exit(7)
                                    finally:
                                        print(
                                            "windows-public-worker-graph-prepare:"
                                            f"{monotonic() - prepare_start:.3f}s",
                                            flush=True,
                                        )
                                        await ordinary_session.dispose()

                                asyncio.run(exercise_direct_worker())
                            else:
                                hosted_runtime = create_agent_session_runtime(
                                    session_dir=tmp_path / "hosted-worker-transcripts",
                                    model=query_model,
                                    services=create_services(settings_manager=settings),
                                    worker_candidate_plugin_id="workerprobe",
                                )

                                async def exercise_hosted_worker() -> None:
                                    try:
                                        hosted_session = (
                                            await hosted_runtime.create_session(
                                                cwd=str(workspace)
                                            )
                                        )
                                        assert hosted_session.session_manager.is_persisted()
                                        await (
                                            hosted_session.prepare_model_call_runtime()
                                        )
                                        assert (
                                            await hosted_session.query_worker_symbol(
                                                "review"
                                            )
                                            == "Review symbol"
                                        )
                                        if crash_after_ordinary_query:
                                            print(
                                                "windows-public-worker-healthy:hosted",
                                                flush=True,
                                            )
                                            os._exit(7)
                                    finally:
                                        await hosted_runtime.dispose_session_runtime()

                                asyncio.run(exercise_hosted_worker())
                        history = open_coding_windows_product_worker_supervisor_journal(
                            worker_product
                        ).inspect_records()
                        assert history
                        assert history[-1].phase == (
                            "process_settled"
                            if disable_while_ordinary_session_open
                            else "stopped"
                        )
                        attempt_id = history[-1].attempt_id
                        provisioning = (
                            inspect_coding_windows_product_worker_provisioning_attempts(
                                worker_product
                            )
                        )
                        assert tuple(
                            (item.attempt_id, item.phase) for item in provisioning
                        ) == ((attempt_id, "settled"),)
                        orphan_review = (
                            review_coding_windows_product_worker_orphan_runtime(
                                worker_product, attempt_id=attempt_id
                            )
                        )
                        assert orphan_review.native_job_absent is True
                        assert orphan_review.attempt is not None
                        if disable_while_ordinary_session_open:
                            assert orphan_review.attempt.fenced_exit_settled
                        else:
                            assert orphan_review.attempt.clean_exit_settled
                        [activation] = (
                            item
                            for item in CodingWindowsWorkerActivationStateJournal(
                                worker_product
                            ).retained_attempts_read_only()
                            if item.attempt_id == attempt_id
                        )
                        assert activation.phase == "settled"
                        assert activation.cleanup_contract_version == 2
                        if disable_while_ordinary_session_open:
                            assert (
                                next(
                                    item
                                    for item in worker_product.desired_state.snapshot().installations
                                    if item.installation_key.plugin_id == "workerprobe"
                                ).selection.desired_state
                                == "installed_disabled"
                            )
                        return
                    unmaterialized_session = asyncio.run(
                        SessionManager.new(
                            session_dir=tmp_path / "unmaterialized-worker-transcripts",
                            cwd=str(workspace),
                            session_id="windows-worker-candidate",
                            persist=False,
                        )
                    )
                    with pytest.raises(ValueError, match="Session owner changed"):
                        open_coding_windows_product_selected_worker_receipt_owner(
                            product_owner=worker_product,
                            runtime=runtime,
                            plugin_id="workerprobe",
                            transcript_directory=AgentTranscriptDirectoryRuntime(
                                session_dir=unmaterialized_session.get_session_dir()
                            ),
                            session_manager=unmaterialized_session,
                        )
                    worker_session = asyncio.run(
                        SessionManager.new_with_composition(
                            session_dir=tmp_path / "worker-transcripts",
                            cwd=str(workspace),
                            session_id="windows-worker-candidate",
                            defer_materialization=False,
                        )
                    )
                    assert worker_session.is_persisted()
                    receipt_owner = (
                        open_coding_windows_product_selected_worker_receipt_owner(
                            product_owner=worker_product,
                            runtime=runtime,
                            plugin_id="workerprobe",
                            transcript_directory=AgentTranscriptDirectoryRuntime(
                                session_dir=worker_session.get_session_dir()
                            ),
                            session_manager=worker_session,
                        )
                    )
                    assert (
                        inspect_coding_windows_product_worker_payload_attempts(
                            worker_product
                        )
                        == ()
                    )
                    assert (
                        inspect_coding_windows_product_worker_recovery_inventory(
                            worker_product
                        )
                        == ()
                    )
                    absent_orphan = review_coding_windows_product_worker_orphan_runtime(
                        worker_product, attempt_id="9" * 32
                    )
                    assert absent_orphan.attempt is None
                    assert absent_orphan.receipt_record is None
                    assert absent_orphan.orphan_leases == ()
                    assert absent_orphan.missing_proofs == (
                        "attempt_history_absent",
                        "activation_receipt_absent",
                        "orphan_lease_absent",
                        "native_job_absence_unverified",
                    )
                    receipt_path = (
                        worker_product.state_root / "worker-activation-receipts.jsonl"
                    )
                    assert (
                        read_coding_windows_product_worker_receipt_record(
                            worker_product, receipt_fingerprint="a" * 64
                        )
                        is None
                    )
                    assert not receipt_path.exists()
                    assert not receipt_path.with_name(
                        receipt_path.name + ".lock"
                    ).exists()
                    receipt = receipt_owner.issue()
                    assert receipt is not None
                    receipt_fingerprint = receipt.fingerprint
                    assert receipt.policy.native_profile_id == (
                        CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID
                    )
                    assert receipt_owner.issue() == receipt
                    assert receipt_owner.current_witness(receipt) == (
                        receipt.authority_witness
                    )
                    assert (
                        receipt_owner.current_backend_capture_expectation(receipt)
                        == installed_backend.expectation
                    )
                    assert receipt_owner.current_selected_manifest(receipt) == selected
                    selected_payload = receipt_owner.current_selected_payload(receipt)
                    assert selected_payload.body == executable
                    assert selected_payload.digest == sha256(executable).hexdigest()
                    assert (
                        selected_payload.configuration.entrypoint
                        == "worker/bin/query-worker"
                    )
                    assert receipt_owner.current_worker_owner_id(receipt) == (
                        allowed.opt_in.owner_id
                    )
                    query_provider = coding_worker_query_capability_provider(
                        "workerprobe"
                    )
                    with pytest.raises(
                        CodingWorkerProviderCandidateError,
                        match="coding_worker_provider_selection_mismatch",
                    ):
                        prepare_coding_selected_worker_provider_candidate(
                            receipt_owner=receipt_owner,
                            receipt=receipt,
                            definition=replace(
                                CODING_WORKER_QUERY_DEFINITION,
                                owner_id=(
                                    "coding.worker"
                                    if owner_id == "coding"
                                    else "coding"
                                ),
                            ),
                            provider=query_provider,
                        )
                    provider_candidate = (
                        prepare_coding_selected_worker_provider_candidate(
                            receipt_owner=receipt_owner,
                            receipt=receipt,
                            definition=replace(
                                CODING_WORKER_QUERY_DEFINITION,
                                owner_id=owner_id,
                            ),
                            provider=query_provider,
                        )
                    )
                    assert (
                        provider_candidate.binding_spec.native_platform
                        == "windows-amd64"
                    )
                    assert provider_candidate.plugin_candidate_fingerprint == (
                        receipt.fingerprint
                    )
                    with patch.object(
                        receipt_owner,
                        "current_witness",
                        side_effect=(
                            receipt.authority_witness,
                            ("0" * 64, "0" * 64, "stale", 0, 0),
                        ),
                    ):
                        with pytest.raises(CodingWorkerReceiptError, match="stale"):
                            receipt_owner.current_payload_and_worker_owner_id(receipt)
                    pending = plan_coding_windows_product_worker_pending_launch(
                        receipt_owner=receipt_owner,
                        receipt=receipt,
                        attempt_id="7" * 32,
                    )
                    assert pending.receipt_fingerprint == receipt.fingerprint
                    assert pending.identity.attempt_id == "7" * 32
                    assert (
                        inspect_coding_windows_product_worker_payload_attempts(
                            worker_product
                        )
                        == ()
                    )
                    lease = materialize_coding_windows_product_worker_payload(
                        receipt_owner=receipt_owner,
                        receipt=receipt,
                        attempt_id="7" * 32,
                    )
                    assert (
                        lease.runtime.executable_digest
                        == sha256(executable).hexdigest()
                    )
                    assert lease.owner_id == allowed.opt_in.owner_id
                    lease.runtime.verify()
                    marker = json.loads(
                        (
                            worker_product.state_root
                            / ("worker-payload-" + "7" * 32)
                            / "worker-payload.json"
                        ).read_text(encoding="utf-8")
                    )
                    assert marker["attemptId"] == "7" * 32
                    assert marker["payloadDigest"] == lease.payload_digest
                    assert marker["receiptFingerprint"] == receipt.fingerprint
                    with pytest.raises(
                        CodingWindowsWorkerPayloadMaterializationError,
                        match="coding_worker_payload_pending_launch_changed",
                    ):
                        bind_coding_windows_product_worker_launch_request(
                            receipt_owner=receipt_owner,
                            receipt=receipt,
                            payload_lease=lease,
                            supervisor_epoch=pending.identity.supervisor_epoch,
                            pending_launch=replace(
                                pending,
                                identity=replace(pending.identity, attempt_id="8" * 32),
                            ),
                        )
                    request = bind_coding_windows_product_worker_launch_request(
                        receipt_owner=receipt_owner,
                        receipt=receipt,
                        payload_lease=lease,
                        supervisor_epoch=pending.identity.supervisor_epoch,
                        pending_launch=pending,
                    )
                    request.validate_current()
                    assert request.identity == pending.identity
                    assert request.identity.attempt_id == lease.attempt_id
                    native_plan = receipt_owner.plan_current_native_attempt(
                        receipt, request
                    )
                    assert native_plan.backend_material_expectation == (
                        receipt_owner.current_backend_capture_expectation(receipt)
                    )
                    assert native_plan.expected_native_policy_closure_fingerprint == (
                        receipt.policy.expected_native_policy_closure_fingerprint
                    )
                    with pytest.raises(ValueError, match="launch intent is invalid"):
                        open_coding_windows_product_worker_provisioning_state_store(
                            worker_product,
                            runtime=runtime,
                            selected=selected,
                            receipt=receipt,
                            worker_request=request,
                            plan=native_plan,
                        )
                    forged_request = ManagedWorkerLaunchRequestV1(
                        identity=request.identity,
                        runtime=request.runtime,
                        validate_current=lambda: None,
                    )
                    with pytest.raises(
                        CodingWindowsWorkerPayloadMaterializationError,
                        match="coding_worker_payload_request_unbound",
                    ):
                        commit_coding_windows_product_worker_launch_intent(
                            worker_product,
                            receipt_owner=receipt_owner,
                            receipt=receipt,
                            request=forged_request,
                            payload_lease=lease,
                        )
                    precommit_marker = (
                        worker_product.state_root
                        / ("worker-payload-" + "7" * 32)
                        / "worker-payload.json"
                    )
                    marker_bytes = precommit_marker.read_bytes()
                    precommit_marker.write_bytes(marker_bytes + b" ")
                    try:
                        with pytest.raises(
                            CodingWindowsWorkerPayloadMaterializationError,
                            match="coding_worker_payload_marker_changed",
                        ):
                            commit_coding_windows_product_worker_launch_intent(
                                worker_product,
                                receipt_owner=receipt_owner,
                                receipt=receipt,
                                request=request,
                                payload_lease=lease,
                            )
                    finally:
                        precommit_marker.write_bytes(marker_bytes)
                    launch_intent = commit_coding_windows_product_worker_launch_intent(
                        worker_product,
                        receipt_owner=receipt_owner,
                        receipt=receipt,
                        request=request,
                        payload_lease=lease,
                    )
                    assert (
                        read_coding_windows_product_worker_launch_intent(
                            worker_product, attempt_id="7" * 32
                        )
                        == launch_intent
                    )
                    assert inspect_coding_windows_product_worker_launch_intents(
                        worker_product
                    ) == (launch_intent,)
                    with pytest.raises(
                        CodingWindowsWorkerLaunchIntentError,
                        match="coding_worker_launch_intent_attempt_reused",
                    ):
                        commit_coding_windows_product_worker_launch_intent(
                            worker_product,
                            receipt_owner=receipt_owner,
                            receipt=receipt,
                            request=request,
                            payload_lease=lease,
                        )
                    intent_path = (
                        worker_product.state_root
                        / f"worker-launch-intent-{'7' * 32}.json"
                    )
                    held_intent = tmp_path / "held-worker-launch-intent.json"
                    intent_path.replace(held_intent)
                    try:
                        with pytest.raises(
                            ValueError, match="launch intent is invalid"
                        ):
                            open_coding_windows_product_worker_provisioning_state_store(
                                worker_product,
                                runtime=runtime,
                                selected=selected,
                                receipt=receipt,
                                worker_request=request,
                                plan=native_plan,
                            )
                    finally:
                        held_intent.replace(intent_path)
                    request.validate_current()
                    assert (
                        native_plan.backend_material_expectation
                        == installed_backend.expectation
                    )
                    assert {
                        item.attempt_id
                        for item in inspect_coding_windows_product_worker_payload_attempts(
                            worker_product
                        )
                    } == {"7" * 32}
                    # The committed launch intent makes this ID permanently used.
                    with pytest.raises(
                        CodingWindowsWorkerPayloadMaterializationError,
                        match="coding_worker_payload_attempt_reused",
                    ):
                        materialize_coding_windows_product_worker_payload(
                            receipt_owner=receipt_owner,
                            receipt=receipt,
                            attempt_id="7" * 32,
                        )
                    native_store = (
                        open_coding_windows_product_worker_provisioning_state_store(
                            worker_product,
                            runtime=runtime,
                            selected=selected,
                            receipt=receipt,
                            worker_request=request,
                            plan=native_plan,
                        )
                    )
                    assert native_store.load() is None
                    native_profile = (
                        _bind_windows_lpac_contained_product_worker_profile(
                            receipt=receipt,
                            worker_request=request,
                            plan=native_plan,
                            platform_imports=WINDOWS_LPAC_PLATFORM_IMPORTS,
                            provisioning_state_store=native_store,
                        )
                    )
                    assert native_store.load() is None
                    marker_path = (
                        worker_product.state_root
                        / ("worker-payload-" + "7" * 32)
                        / "worker-payload.json"
                    )

                    async def exercise_native_hosting() -> None:
                        host = None
                        journal = open_coding_windows_product_worker_supervisor_journal(
                            worker_product
                        )
                        assert journal.inspect_records() == ()
                        assert not journal.path.exists()
                        supervisor = WorkerSupervisor(
                            identity=request.identity,
                            journal=journal,
                            protocol=request.runtime.protocol,
                            protocol_version=request.runtime.protocol_version,
                        )
                        try:
                            host = _create_windows_lpac_child_session_host(
                                max_sessions=1
                            )
                            adapter = HostingManagedWorkerSessionAdapter(
                                hosting=host,
                                preparation=native_profile,
                            )
                            await supervisor.start_session(
                                session_port=adapter,
                                launch_request=request,
                                correlation_id="windows-product-worker-hosting-probe",
                            )
                            assert supervisor.status.state == "healthy"
                            await native_profile.verify_current()
                            live_job = (
                                review_coding_windows_product_worker_orphan_runtime(
                                    worker_product, attempt_id="7" * 32
                                )
                            )
                            assert live_job.native_job_absent is False
                            assert "native_job_present" in live_job.missing_proofs
                            with patch(
                                "loushang.coding.package_product_worker_windows_backend_release.verify_windows_backend_material_expectation",
                                wraps=verify_windows_backend_material_expectation,
                            ) as full_backend_checks:
                                request.validate_current()
                            assert full_backend_checks.call_count == 2
                            described = await supervisor.query(
                                {"operation": "describe", "queryVersion": 1}
                            )
                            assert described["capabilities"] == [
                                {
                                    "capabilityId": "coding.worker.query",
                                    "descriptorVersion": 1,
                                    "facetIds": ["query"],
                                }
                            ]
                            original_marker = marker_path.read_bytes()
                            # Native launch pins every runtime member without
                            # FILE_SHARE_WRITE. A live marker mutation must fail
                            # before it can create stale Product state.
                            with pytest.raises(PermissionError):
                                marker_path.write_bytes(original_marker + b" ")
                            assert marker_path.read_bytes() == original_marker
                            request.validate_current()
                            invoked = await supervisor.query(
                                {
                                    "operation": "invokeReadOnlyFacet",
                                    "symbol": "review",
                                    "queryVersion": 1,
                                }
                            )
                            assert invoked["value"] == {"text": "Review symbol"}
                            if crash_after_healthy:
                                print("windows-product-worker-healthy", flush=True)
                                os._exit(7)
                            await supervisor.shutdown()
                            assert supervisor.status.state == "stopped"
                            assert journal.inspect_records()[-1].phase == "stopped"
                        finally:
                            try:
                                if supervisor.status.state == "healthy":
                                    await supervisor.fence(code="windows_test_cleanup")
                            finally:
                                try:
                                    await native_profile.close()
                                finally:
                                    if host is not None:
                                        await host.close()

                    asyncio.run(exercise_native_hosting())
                    native_witness = (
                        native_profile.native_containment_settlement_witness()
                    )
                    assert isinstance(
                        native_witness, _WindowsNativeContainmentSettlementWitness
                    )
                    settled_attempt = next(
                        item
                        for item in inspect_coding_windows_product_worker_provisioning_attempts(
                            worker_product
                        )
                        if item.attempt_id == "7" * 32
                    )
                    assert settled_attempt.phase == "settled"
                    assert settled_attempt.settlement_fingerprint == (
                        native_witness.journal_fingerprint
                    )
                    if c5_cleanup_review:
                        evidence = CodingWindowsWorkerCleanupEvidenceAuthority(
                            receipt_owner=receipt_owner,
                            receipt=receipt,
                            request=request,
                        )
                        _retain_windows_c5_test_attempt(
                            worker_product,
                            attempt_id=request.identity.attempt_id,
                            host_identity=evidence.host_identity,
                            boot_identity=evidence.boot_identity,
                            evidence_authority_id=evidence.authority_id,
                            evidence_authority_fingerprint=evidence.authority_fingerprint,
                            settled=False,
                        )
                        tree = evidence.current_tree_witness(
                            attempt_id=request.identity.attempt_id
                        )
                        facts = {
                            "receipt_fingerprint": receipt.fingerprint,
                            "attempt_id": request.identity.attempt_id,
                            "owner_generation": request.identity.owner_generation,
                            "host_identity": evidence.host_identity,
                            "boot_identity": evidence.boot_identity,
                            "evidence_authority_id": evidence.authority_id,
                            "evidence_authority_fingerprint": evidence.authority_fingerprint,
                        }
                        assert tree.runtime.native_job_absent is True
                        assert evidence.verify_tree_settlement(witness=tree, **facts)
                        assert evidence.verify_native_containment_settlement(
                            witness=native_witness, **facts
                        )
                        with patch(
                            "loushang.coding.package_product_worker_windows_orphan_review.observe_windows_worker_job_absent",
                            return_value=False,
                        ):
                            assert not evidence.verify_tree_settlement(
                                witness=tree, **facts
                            )
                        assert not evidence.verify_native_containment_settlement(
                            witness=replace(
                                native_witness, journal_fingerprint="0" * 64
                            ),
                            **facts,
                        )
                        return
                    with pytest.raises(WorkerBindingError, match="selection changed"):
                        request.validate_current()
                    supervisor_journal = (
                        open_coding_windows_product_worker_supervisor_journal(
                            worker_product
                        )
                    )
                    history_path = supervisor_journal.path
                    held_history = tmp_path / "held-worker-supervisor.jsonl"
                    history_path.replace(held_history)
                    try:
                        with pytest.raises(
                            WorkerSupervisorJournalError,
                            match="lock/history mismatch",
                        ):
                            supervisor_journal.inspect_records()
                    finally:
                        held_history.replace(history_path)
                    original_history = history_path.read_bytes()
                    history_path.write_bytes(original_history + b" ")
                    try:
                        with pytest.raises(
                            WorkerSupervisorJournalError,
                            match="torn",
                        ):
                            supervisor_journal.inspect_records()
                    finally:
                        history_path.write_bytes(original_history)
                    lock_path = history_path.with_name(history_path.name + ".lock")
                    held_lock = tmp_path / "held-worker-supervisor.lock"
                    lock_path.replace(held_lock)
                    try:
                        with pytest.raises(
                            WorkerSupervisorJournalError,
                            match="lock is missing",
                        ):
                            supervisor_journal.inspect_records()
                    finally:
                        held_lock.replace(lock_path)
                    assert supervisor_journal.inspect_records()[-1].phase == "stopped"
                    if clean_rotation:
                        rotation_pending = True
                        return
                    with pytest.raises(
                        CodingWindowsWorkerPayloadMaterializationError,
                        match="coding_worker_payload_recovery_required",
                    ):
                        bind_coding_windows_product_worker_launch_request(
                            receipt_owner=receipt_owner,
                            receipt=receipt,
                            payload_lease=lease,
                            supervisor_epoch=2,
                        )
                    with patch.object(
                        windows_payload_module,
                        "windows_flush_file",
                        side_effect=OSError("injected payload flush interruption"),
                    ):
                        with pytest.raises(OSError, match="flush interruption"):
                            materialize_coding_windows_product_worker_payload(
                                receipt_owner=receipt_owner,
                                receipt=receipt,
                                attempt_id="8" * 32,
                            )
                    assert {
                        item.attempt_id
                        for item in inspect_coding_windows_product_worker_payload_attempts(
                            worker_product
                        )
                    } == {"7" * 32, "8" * 32}
                    assert not (
                        worker_product.state_root
                        / ("worker-payload-" + "8" * 32)
                        / "worker-payload.json"
                    ).exists()
                    with pytest.raises(
                        CodingWindowsWorkerPayloadMaterializationError,
                        match="coding_worker_payload_attempt_debt",
                    ):
                        materialize_coding_windows_product_worker_payload(
                            receipt_owner=receipt_owner,
                            receipt=receipt,
                            attempt_id="8" * 32,
                        )
                    _assert_windows_product_worker_provisioning_state(
                        worker_product,
                        runtime,
                        selected,
                        tmp_path,
                        prior_settled_attempt_id="7" * 32,
                    )
                    recovery = {
                        item.attempt_id: item
                        for item in inspect_coding_windows_product_worker_recovery_inventory(
                            worker_product
                        )
                    }
                    assert set(recovery) == {"5" * 32, "7" * 32, "8" * 32}
                    stage_retention_expected = True
                    orphan_review = review_coding_windows_product_worker_orphan_runtime(
                        worker_product, attempt_id="7" * 32
                    )
                    assert orphan_review.attempt == recovery["7" * 32]
                    assert orphan_review.receipt_record is not None
                    assert orphan_review.receipt_record.receipt == receipt
                    assert orphan_review.orphan_leases == ()
                    assert orphan_review.attempt is not None
                    assert orphan_review.attempt.clean_exit_settled
                    assert orphan_review.native_job_absent is True
                    assert orphan_review.missing_proofs == ("orphan_lease_absent",)
                    assert not orphan_review.clean_exit_repair_candidate
                    with pytest.raises(ValueError, match="unproven"):
                        repair_coding_windows_product_worker_clean_exit_orphan_runtime(
                            worker_product, expected_review=orphan_review
                        )
                    assert recovery["5" * 32].native_phase == "reserved"
                    assert recovery["5" * 32].payload_directory_identity is None
                    assert recovery["7" * 32].native_phase == "settled"
                    assert (
                        recovery["7" * 32].native_worker_request_fingerprint
                        == request.fingerprint
                    )
                    assert (
                        recovery["7" * 32].native_receipt_fingerprint
                        == receipt.fingerprint
                    )
                    assert recovery["7" * 32].supervisor_phase == "stopped"
                    assert (
                        recovery["7" * 32].supervisor_identity_fingerprint
                        == request.identity.fingerprint
                    )
                    assert recovery["7" * 32].supervisor_process_settled
                    assert recovery["7" * 32].launch_request_fingerprint == (
                        request.fingerprint
                    )
                    assert recovery["7" * 32].launch_receipt_fingerprint == (
                        receipt.fingerprint
                    )
                    assert recovery["7" * 32].launch_identity_fingerprint == (
                        request.identity.fingerprint
                    )
                    assert recovery["7" * 32].launch_stage_identity == (
                        lease.stage_identity
                    )
                    assert recovery["7" * 32].observed_debts == (
                        "payload_retained",
                        "launch_intent_retained",
                    )
                    assert recovery["8" * 32].observed_debts == (
                        "payload_retained",
                        "launch_intent_missing",
                        "native_history_missing",
                        "supervisor_history_missing",
                    )
                    with pytest.raises(
                        CodingWindowsWorkerStageReviewError,
                        match="coding_worker_stage_review_runtime_active",
                    ):
                        review_coding_windows_product_worker_complete_stage(
                            worker_product, attempt_id="7" * 32
                        )
                    with pytest.raises(WorkerBindingError, match="selection changed"):
                        request.validate_current()
                    receipt_record = read_coding_windows_product_worker_receipt_record(
                        worker_product, receipt_fingerprint=receipt.fingerprint
                    )
                    assert receipt_record is not None
                    assert receipt_record.receipt == receipt
                    held_receipt = receipt_path.with_name(receipt_path.name + ".held")
                    receipt_path.replace(held_receipt)
                    try:
                        with pytest.raises(CodingWorkerReceiptError) as missing_history:
                            read_coding_windows_product_worker_receipt_record(
                                worker_product,
                                receipt_fingerprint=receipt.fingerprint,
                            )
                        assert missing_history.value.code == (
                            "coding_worker_receipt_orphan_lock"
                        )
                    finally:
                        held_receipt.replace(receipt_path)
                    with worker_product.gc_gate.guard():
                        with (
                            worker_product.epoch_runtime.borrow_product_state_root_descriptor() as root
                        ):
                            foreign_receipts = CodingWindowsWorkerReceiptJournal(
                                receipt_path, scope_id="workspace:foreign"
                            )
                            with pytest.raises(CodingWorkerReceiptError) as wrong_scope:
                                foreign_receipts.records(directory_fd=root)
                            assert wrong_scope.value.code == (
                                "coding_worker_receipt_corrupt"
                            )
                    revoked = approval_owner.revoke(
                        operation_id="windows-native-reviewed-revoke-2",
                        expected_generation=1,
                    )
                    assert revoked.action == "revoke"
                    assert revoked.generation == 2
                    assert approval_owner.current() == revoked
                    with pytest.raises(CodingWindowsWorkerInstalledBackendError):
                        read_coding_windows_worker_installed_backend_release(
                            worker_product
                        )
                    assert receipt_owner.latch_kill_switch(expected_generation=0) == 1
                    assert receipt_owner.latch_kill_switch(expected_generation=0) == 1
                    opt_revoked = opt_in_owner.current("workerprobe")
                    assert opt_revoked is not None
                    assert opt_revoked.action == "revoke"
                    assert opt_revoked.generation == 2
                    with pytest.raises(CodingWorkerReceiptError, match="stale"):
                        receipt_owner.latch_kill_switch(expected_generation=1)
                    assert opt_in_owner.current("workerprobe") == opt_revoked
                    assert receipt_owner.current_witness(receipt) != (
                        receipt.authority_witness
                    )
                    with pytest.raises(CodingWorkerReceiptError, match="stale"):
                        receipt_owner.current_selected_payload(receipt)
                    with pytest.raises(CodingWorkerReceiptError):
                        receipt_owner.current_backend_capture_expectation(receipt)
                else:
                    _assert_windows_product_worker_native_approval_journal(
                        worker_product
                    )
                    _assert_windows_product_worker_opt_in_journal(
                        worker_product, selected
                    )
                if os.environ.get("LOUSHANG_WINDOWS_BACKEND_REVIEW") != "1":
                    _assert_windows_product_worker_provisioning_state(
                        worker_product, runtime, selected, tmp_path
                    )
            else:
                assert installed == ()
        finally:
            if runtime is None:
                factory.dispose_unbound_runtime()
            else:
                runtime.dispose_runtime()
            retained_stage = worker_state_root / ("worker-payload-" + "7" * 32)
            after_runtime = (
                retained_stage.is_dir() if stage_retention_expected else None
            )
            if worker_owner is not None:
                worker_owner.close()
            if stage_retention_expected:
                assert after_runtime, "Worker stage disappeared during runtime disposal"
                assert retained_stage.is_dir(), (
                    "Worker stage disappeared during Product close"
                )
                assert (worker_state_root / ("worker-payload-" + "8" * 32)).is_dir()
                assert (
                    worker_state_root
                    / ("worker-native-provisioning-" + "7" * 32 + ".jsonl")
                ).is_file()
            elif (
                native_platform == "windows-amd64"
                and not rotation_pending
                and not c5_cleanup_review
                and sys.exc_info()[0] is None
            ):
                assert not retained_stage.exists()
            if rotation_pending:
                _assert_windows_worker_clean_rotation(
                    workspace=workspace,
                    session_state=tmp_path / "session-state",
                    expected_digest=sha256(executable).hexdigest(),
                )
        if (
            native_platform == "windows-amd64"
            and os.environ.get("LOUSHANG_WINDOWS_BACKEND_REVIEW") == "1"
        ):
            repair_script = """\
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from loushang.coding._plugin_lifecycle import resolve_ephemeral_coding_plugin_lifecycle_state_layout
from loushang.coding.package_product_runtime import open_coding_fenced_product_application_owner
from loushang.coding.package_product_worker_windows_orphan_review import (
    repair_coding_windows_product_worker_clean_exit_orphan_runtime,
    review_coding_windows_product_worker_orphan_runtime,
)

workspace = Path(sys.argv[1])
lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
    Path(sys.argv[2]), cwd=workspace
)
owner = open_coding_fenced_product_application_owner(
    lifecycle, workspace=workspace, runtime_version="2.0.0",
    runtime_protocol_epoch=2, worker_candidates=True, windows_candidate=True,
)
try:
    product = owner.runtime_owner.product_owner
    registry = product.epoch_runtime.registry
    child_script = "\\n".join((
        "import os, sys",
        "from pathlib import Path",
        "from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import PackageEpochFenceJournal",
        "from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import PackageWindowsEpochRuntimeLeaseRegistry",
        "registry = PackageWindowsEpochRuntimeLeaseRegistry(control_root=Path(sys.argv[1]), fences=PackageEpochFenceJournal(Path(sys.argv[2])), store_id=sys.argv[3])",
        "registry.register(runtime_id=sys.argv[4], runtime_protocol_epoch=2)",
        "os._exit(0)",
    ))
    crashed = subprocess.run(
        (sys.executable, "-c", child_script, str(registry.control_root),
         str(registry.fences.path), registry.store_id, sys.argv[3]),
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert crashed.returncode == 0, crashed.stderr
    review = review_coding_windows_product_worker_orphan_runtime(
        product, attempt_id="7" * 32
    )
    assert review.native_job_absent is True
    assert review.clean_exit_repair_candidate
    assert len(review.orphan_leases) == 1
    assert review.attempt is not None
    try:
        repair_coding_windows_product_worker_clean_exit_orphan_runtime(
            product, expected_review=replace(review, native_job_absent=False)
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Changed Job observation was accepted")
    stale = replace(
        review,
        attempt=replace(
            review.attempt,
            supervisor_revision=review.attempt.supervisor_revision + 1,
        ),
    )
    assert stale.clean_exit_repair_candidate
    try:
        repair_coding_windows_product_worker_clean_exit_orphan_runtime(
            product, expected_review=stale
        )
    except ValueError as error:
        assert "stale" in str(error)
    else:
        raise AssertionError("Stale Supervisor revision was accepted")
    assert registry.review_orphans(store_id=registry.store_id) == review.orphan_leases
    repaired = repair_coding_windows_product_worker_clean_exit_orphan_runtime(
        product, expected_review=review
    )
    assert repaired == review.orphan_leases[0]
    assert registry.review_orphans(store_id=registry.store_id) == ()
    retained_stage = product.state_root / ("worker-payload-" + "7" * 32)
    stage_before_close = retained_stage.is_dir()
finally:
    owner.close()
print(json.dumps({
    "cleanExitLeaseRepaired": True,
    "stageBeforeClose": stage_before_close,
    "stageAfterClose": retained_stage.is_dir(),
}))
"""
            repaired = subprocess.run(
                (
                    sys.executable,
                    "-c",
                    repair_script,
                    str(workspace),
                    str(tmp_path / "session-state"),
                    receipt.policy.product_runtime_id,
                ),
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            assert repaired.returncode == 0, repaired.stderr
            assert json.loads(repaired.stdout) == {
                "cleanExitLeaseRepaired": True,
                "stageBeforeClose": True,
                "stageAfterClose": True,
            }
            if stage_retention_expected:
                assert retained_stage.is_dir(), (
                    "Worker stage disappeared during clean-exit lease repair",
                    tuple(sorted(item.name for item in worker_state_root.iterdir())),
                )
        if (
            native_platform == "windows-amd64"
            and os.environ.get("LOUSHANG_WINDOWS_BACKEND_REVIEW") == "1"
        ):
            inventory_script = """\
import json
import sys
from pathlib import Path
preimport_worker_files = sorted(
    item.name for item in Path(sys.argv[4]).iterdir()
    if item.name.startswith("worker-")
)
from loushang.coding._plugin_lifecycle import resolve_ephemeral_coding_plugin_lifecycle_state_layout
from loushang.coding.package_product_runtime import open_coding_fenced_product_application_owner
from loushang.coding.package_product_worker_windows_native_approval_owner import CodingWindowsWorkerNativeApprovalOwner
from loushang.coding.package_product_worker_windows_opt_in_owner import CodingWindowsWorkerProductOptInOwner
from loushang.coding.package_product_worker_windows_crash_cleanup_review import CodingWindowsWorkerCrashCleanupReviewError, review_coding_windows_product_worker_crash_cleanup
from loushang.coding.package_product_worker_windows_provisioning import inspect_coding_windows_product_worker_provisioning_attempts
from loushang.coding.package_product_worker_windows_receipt import read_coding_windows_product_worker_receipt_record
from loushang.coding.package_product_worker_windows_recovery_inventory import inspect_coding_windows_product_worker_offline_recovery, inspect_coding_windows_product_worker_recovery_inventory
from loushang.coding.package_product_worker_windows_partial_stage_review import CodingWindowsWorkerPartialStageReviewError, review_coding_windows_product_worker_partial_stage
from loushang.coding.package_product_worker_windows_reserved_review import CodingWindowsWorkerReservedReviewError, review_coding_windows_product_worker_reserved_no_effect
from loushang.coding.package_product_worker_windows_stage_review import CodingWindowsWorkerStageReviewError, review_coding_windows_product_worker_complete_stage

workspace = Path(sys.argv[1])
lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(Path(sys.argv[2]), cwd=workspace)
preopen_worker_files = sorted(
    item.name for item in Path(sys.argv[4]).iterdir()
    if item.name.startswith("worker-")
)
retained_stage_name = "worker-payload-" + "7" * 32
if retained_stage_name not in preopen_worker_files:
    raise AssertionError(json.dumps({
        "stageBeforeImports": retained_stage_name in preimport_worker_files,
        "stageAfterImports": retained_stage_name in preopen_worker_files,
        "beforePayloads": [
            name for name in preimport_worker_files
            if name.startswith("worker-payload-")
        ],
        "afterPayloads": [
            name for name in preopen_worker_files
            if name.startswith("worker-payload-")
        ],
    }))
owner = open_coding_fenced_product_application_owner(
    lifecycle, workspace=workspace, runtime_version="2.0.0",
    runtime_protocol_epoch=2, worker_candidates=True, windows_candidate=True,
)
try:
    assert str(owner.runtime_owner.product_owner.state_root) == sys.argv[4], (
        "Worker Product state root changed across processes"
    )
    attempts = inspect_coding_windows_product_worker_provisioning_attempts(
        owner.runtime_owner.product_owner
    )
    recovery = inspect_coding_windows_product_worker_recovery_inventory(
        owner.runtime_owner.product_owner
    )
    offline = inspect_coding_windows_product_worker_offline_recovery(
        owner.runtime_owner.product_owner
    )
    assert any(item.attempt_id == "7" * 32 for item in recovery), {
        "beforeOpen": preopen_worker_files,
        "attempts": [item.attempt_id for item in attempts],
        "recovery": [item.attempt_id for item in recovery],
        "workerFiles": sorted(
            item.name for item in owner.runtime_owner.product_owner.state_root.iterdir()
            if item.name.startswith("worker-")
        ),
    }
    for incomplete in ("5" * 32, "7" * 32, "8" * 32):
        try:
            review_coding_windows_product_worker_crash_cleanup(
                owner.runtime_owner.product_owner, attempt_id=incomplete
            )
        except CodingWindowsWorkerCrashCleanupReviewError as error:
            assert error.code == "coding_worker_crash_cleanup_history_unverified"
        else:
            raise AssertionError("Incomplete Worker crash cleanup was accepted")
    reviewed = review_coding_windows_product_worker_complete_stage(
        owner.runtime_owner.product_owner, attempt_id="7" * 32
    )
    partial = review_coding_windows_product_worker_partial_stage(
        owner.runtime_owner.product_owner, attempt_id="8" * 32
    )
    for launched in ("5" * 32, "7" * 32):
        try:
            review_coding_windows_product_worker_partial_stage(
                owner.runtime_owner.product_owner, attempt_id=launched
            )
        except CodingWindowsWorkerPartialStageReviewError as error:
            assert error.code == "coding_worker_partial_stage_history_unverified"
        else:
            raise AssertionError("Launched Worker stage was accepted as partial")
    for unverified in ("5" * 32, "7" * 32, "8" * 32):
        try:
            review_coding_windows_product_worker_reserved_no_effect(
                owner.runtime_owner.product_owner, attempt_id=unverified
            )
        except CodingWindowsWorkerReservedReviewError as error:
            assert error.code == "coding_worker_reserved_history_unverified"
        else:
            raise AssertionError("Unverified reservation was accepted")
    for incomplete in ("5" * 32, "8" * 32):
        try:
            review_coding_windows_product_worker_complete_stage(
                owner.runtime_owner.product_owner, attempt_id=incomplete
            )
        except CodingWindowsWorkerStageReviewError as error:
            assert error.code == "coding_worker_stage_review_settlement_unverified"
        else:
            raise AssertionError("Incomplete Worker stage was accepted")
    decision = CodingWindowsWorkerProductOptInOwner(
        owner.runtime_owner.product_owner
    ).current("workerprobe")
    approval = CodingWindowsWorkerNativeApprovalOwner(
        owner.runtime_owner.product_owner
    ).current()
    receipt = (
        read_coding_windows_product_worker_receipt_record(
            owner.runtime_owner.product_owner, receipt_fingerprint=sys.argv[3]
        )
        if sys.argv[3] else None
    )
    print(json.dumps({
        "attempts": [[item.attempt_id, item.phase, item.unsettled] for item in attempts],
        "recovery": [[item.attempt_id, item.payload_directory_identity is not None, item.native_phase, item.supervisor_phase, list(item.observed_debts)] for item in recovery],
        "offline": offline.attempts == recovery and offline.lease_owner_revision >= 1,
        "review": [reviewed.attempt_id, reviewed.entrypoint, reviewed.executable_digest, len(reviewed.fingerprint)],
        "partialReview": [partial.attempt_id, partial.entrypoint, len(partial.fingerprint)],
        "decision": None if decision is None else [decision.action, decision.generation, decision.kill_switch_generation],
        "approval": None if approval is None else [approval.action, approval.generation],
        "receipt": None if receipt is None else receipt.receipt.fingerprint,
    }))
finally:
    owner.close()
"""
            stage_before_inventory_spawn = retained_stage.is_dir()
            inventoried = subprocess.run(
                (
                    sys.executable,
                    "-c",
                    inventory_script,
                    str(workspace),
                    str(tmp_path / "session-state"),
                    receipt_fingerprint or "",
                    str(worker_state_root),
                ),
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if inventoried.returncode != 0:
                pytest.fail(
                    json.dumps(
                        {
                            "childError": inventoried.stderr[-2000:],
                            "stageBeforeInventorySpawn": stage_before_inventory_spawn,
                            "parentStageRetained": retained_stage.is_dir(),
                            "parentPayloads": sorted(
                                item.name
                                for item in worker_state_root.iterdir()
                                if item.name.startswith("worker-payload-")
                            ),
                        }
                    ),
                    pytrace=False,
                )
            assert json.loads(inventoried.stdout) == {
                "attempts": [
                    ["5" * 32, "reserved", True],
                    ["7" * 32, "settled", False],
                ],
                "recovery": [
                    [
                        "5" * 32,
                        False,
                        "reserved",
                        None,
                        [
                            "payload_missing",
                            "launch_intent_retained",
                            "native_unsettled",
                            "supervisor_history_missing",
                        ],
                    ],
                    [
                        "7" * 32,
                        True,
                        "settled",
                        "stopped",
                        ["payload_retained", "launch_intent_retained"],
                    ],
                    [
                        "8" * 32,
                        True,
                        None,
                        None,
                        [
                            "payload_retained",
                            "launch_intent_missing",
                            "native_history_missing",
                            "supervisor_history_missing",
                        ],
                    ],
                ],
                "offline": True,
                "review": [
                    "7" * 32,
                    "worker/bin/query-worker",
                    sha256(executable).hexdigest(),
                    64,
                ],
                "partialReview": [
                    "8" * 32,
                    "worker/bin/query-worker",
                    64,
                ],
                "decision": ["revoke", 2, 1],
                "approval": ["revoke", 2],
                "receipt": receipt_fingerprint,
            }
            retirement_script = """\
import json
import sys
from pathlib import Path
from unittest.mock import patch
import loushang.coding.package_product_worker_windows_partial_stage_retirement as partial_retirement_module
from loushang.coding._plugin_lifecycle import resolve_ephemeral_coding_plugin_lifecycle_state_layout
from loushang.coding.package_product_runtime import open_coding_fenced_product_application_owner
from loushang.coding.package_product_worker_windows_recovery_inventory import CodingWindowsWorkerRecoveryAdmissionError, _current_after_verified_retirements_under_gc_guard, inspect_coding_windows_product_worker_offline_recovery
from loushang.coding.package_product_worker_windows_partial_stage_review import review_coding_windows_product_worker_partial_stage
from loushang.coding.package_product_worker_windows_partial_stage_retirement import retire_coding_windows_product_worker_partial_stage
from loushang.coding.package_product_worker_windows_stage_review import review_coding_windows_product_worker_complete_stage
from loushang.coding.package_product_worker_windows_stage_retirement import retire_coding_windows_product_worker_complete_stage

workspace = Path(sys.argv[1])
lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(Path(sys.argv[2]), cwd=workspace)
owner = open_coding_fenced_product_application_owner(
    lifecycle, workspace=workspace, runtime_version="2.0.0",
    runtime_protocol_epoch=2, worker_candidates=True, windows_candidate=True,
)
try:
    product = owner.runtime_owner.product_owner
    review = review_coding_windows_product_worker_complete_stage(product, attempt_id="7" * 32)
    first = retire_coding_windows_product_worker_complete_stage(product, expected_review=review)
    repeated = retire_coding_windows_product_worker_complete_stage(product, expected_review=review)
    partial_review = review_coding_windows_product_worker_partial_stage(product, attempt_id="8" * 32)
    with patch.object(
        partial_retirement_module, "_delete_directory_if_empty",
        side_effect=OSError("injected partial directory interruption"),
    ):
        try:
            retire_coding_windows_product_worker_partial_stage(
                product, expected_review=partial_review
            )
        except OSError as error:
            assert str(error) == "injected partial directory interruption"
        else:
            raise AssertionError("Partial retirement interruption was not observed")
    partial_first = retire_coding_windows_product_worker_partial_stage(
        product, expected_review=partial_review
    )
    partial_repeated = retire_coding_windows_product_worker_partial_stage(
        product, expected_review=partial_review
    )
    offline = inspect_coding_windows_product_worker_offline_recovery(product)
    attempt = next(item for item in offline.attempts if item.attempt_id == "7" * 32)
    partial_attempt = next(item for item in offline.attempts if item.attempt_id == "8" * 32)
    with product.gc_gate.read_guard():
        historical = _current_after_verified_retirements_under_gc_guard(
            product, (attempt, partial_attempt), attempt_id="9" * 32
        )
        try:
            _current_after_verified_retirements_under_gc_guard(
                product, offline.attempts, attempt_id="9" * 32
            )
        except CodingWindowsWorkerRecoveryAdmissionError:
            foreign_debt_blocked = True
        else:
            foreign_debt_blocked = False
    print(json.dumps({
        "sameReceipt": first == repeated,
        "reviewFingerprint": first.review_fingerprint == review.fingerprint,
        "stageRemoved": not (product.state_root / ("worker-payload-" + "7" * 32)).exists(),
        "debts": list(attempt.observed_debts),
        "partialSameReceipt": partial_first == partial_repeated,
        "partialResumed": True,
        "partialRemoved": not (product.state_root / ("worker-payload-" + "8" * 32)).exists(),
        "partialDebts": list(partial_attempt.observed_debts),
        "historicalAccepted": historical == (),
        "foreignDebtBlocked": foreign_debt_blocked,
    }))
finally:
    owner.close()
"""
            retired = subprocess.run(
                (
                    sys.executable,
                    "-c",
                    retirement_script,
                    str(workspace),
                    str(tmp_path / "session-state"),
                ),
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            assert retired.returncode == 0, retired.stderr
            assert json.loads(retired.stdout) == {
                "sameReceipt": True,
                "reviewFingerprint": True,
                "stageRemoved": True,
                "debts": ["payload_missing", "launch_intent_retained"],
                "partialSameReceipt": True,
                "partialResumed": True,
                "partialRemoved": True,
                "partialDebts": [
                    "payload_missing",
                    "launch_intent_missing",
                    "native_history_missing",
                    "supervisor_history_missing",
                ],
                "historicalAccepted": True,
                "foreignDebtBlocked": True,
            }
        Path(controlled_source).write_bytes(b"tampered controlled Worker Wheel")
        with pytest.raises(CodingExternalWorkerWheelError):
            catalog.verify_record(record)
        if native_platform == "windows-amd64":
            plain_after_tamper = open_coding_fenced_product_application_owner(
                lifecycle,
                workspace=workspace,
                runtime_version="2.0.0",
                runtime_protocol_epoch=2,
                windows_candidate=True,
            )
            try:
                assert all(
                    item.plugin_id != "workerprobe"
                    for item in plain_after_tamper.runtime_owner.product_owner.policy.bindings
                )
            finally:
                plain_after_tamper.close()
            with pytest.raises(CodingExternalWorkerWheelError):
                open_coding_fenced_product_application_owner(
                    lifecycle,
                    workspace=workspace,
                    runtime_version="2.0.0",
                    runtime_protocol_epoch=2,
                    worker_candidates=True,
                    windows_candidate=True,
                )
        if reopen_command is not None:
            tampered = subprocess.run(
                reopen_command,
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            assert tampered.returncode != 0
            assert "Windows Worker controlled bytes changed" in tampered.stderr
        receipt = product.state_root / "external-worker-binding-001.json"
        receipt.write_bytes(receipt.read_bytes() + b" ")
        with pytest.raises(CodingExternalWorkerWheelError):
            catalog.records()
    finally:
        owner.close()


def _assert_windows_worker_clean_rotation(
    *,
    workspace: Path,
    session_state: Path,
    expected_digest: str,
    crash_retired: bool = False,
) -> None:
    script = """\
import asyncio
import json
import sys
from pathlib import Path
from loushang.coding._plugin_lifecycle import resolve_ephemeral_coding_plugin_lifecycle_state_layout
from loushang.coding.package_product_runtime import open_coding_fenced_product_application_owner
from loushang.coding.package_product_worker_windows_launch_intent import commit_coding_windows_product_worker_launch_intent
from loushang.coding.package_product_worker_windows_payload import bind_coding_windows_product_worker_launch_request, materialize_coding_windows_product_worker_payload
from loushang.coding.package_product_worker_windows_provisioning import open_coding_windows_product_worker_provisioning_state_store
from loushang.coding.package_product_worker_windows_receipt import CodingWindowsWorkerProductReceiptOwner
from loushang.coding.package_product_worker_windows_recovery_inventory import inspect_coding_windows_product_worker_offline_recovery
from loushang.coding.package_product_worker_windows_stage_review import review_coding_windows_product_worker_complete_stage
from loushang.coding.package_product_worker_windows_stage_retirement import retire_coding_windows_product_worker_complete_stage
from loushang.coding.package_product_worker_windows_supervisor_journal import open_coding_windows_product_worker_supervisor_journal
from loushang.harness.package_product.product_runtime import PackageProductRuntimeRequestV1
from loushang.harness.worker import WorkerSupervisor
from loushang.harness.worker._native_profile_bridge import _bind_windows_lpac_contained_product_worker_profile
from loushang.harness.worker.hosting_adapter import HostingManagedWorkerSessionAdapter
from loushang.hosting._windows_lpac_runtime import _create_windows_lpac_child_session_host
from loushang.hosting.windows_backend_material import WINDOWS_LPAC_PLATFORM_IMPORTS

workspace = Path(sys.argv[1])
lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(Path(sys.argv[2]), cwd=workspace)
owner = open_coding_fenced_product_application_owner(
    lifecycle, workspace=workspace, runtime_version="2.0.0",
    runtime_protocol_epoch=2, worker_candidates=True, windows_candidate=True,
)
runtime = None
factory = None
try:
    product = owner.runtime_owner.product_owner
    before = inspect_coding_windows_product_worker_offline_recovery(product)
    assert len(before.attempts) == 1 and before.attempts[0].attempt_id == "7" * 32
    if sys.argv[4] == "crash-retired":
        assert before.attempts[0].payload_directory_identity is None
        assert before.attempts[0].supervisor_phase == "process_settled"
    else:
        review = review_coding_windows_product_worker_complete_stage(product, attempt_id="7" * 32)
        retired = retire_coding_windows_product_worker_complete_stage(product, expected_review=review)
        assert retired == retire_coding_windows_product_worker_complete_stage(product, expected_review=review)
    print("rotation:old-stage-retired", file=sys.stderr, flush=True)
    factory = product.factory_for_session(
        session_id="session:windows-worker-rotation", cwd=workspace,
        runtime_id="runtime:windows-worker-rotation",
    )
    runtime = factory.create(PackageProductRuntimeRequestV1(
        product_id="coding", session_id="session:windows-worker-rotation", cwd=str(workspace),
    ))
    runtime.activate()
    selected = runtime.capture_selected_plugin_manifest_for(
        "workerprobe", max_files=16, max_total_bytes=16 * 1024 * 1024,
    )
    receipt_owner = CodingWindowsWorkerProductReceiptOwner(
        product=product, runtime=runtime, selected=selected,
    )
    receipt = receipt_owner.issue()
    assert receipt is not None
    lease = materialize_coding_windows_product_worker_payload(
        receipt_owner=receipt_owner, receipt=receipt, attempt_id="9" * 32,
    )
    assert lease.payload_digest == sys.argv[3]
    request = bind_coding_windows_product_worker_launch_request(
        receipt_owner=receipt_owner, receipt=receipt, payload_lease=lease,
        supervisor_epoch=1,
    )
    commit_coding_windows_product_worker_launch_intent(
        product, receipt_owner=receipt_owner, receipt=receipt,
        request=request, payload_lease=lease,
    )
    plan = receipt_owner.plan_current_native_attempt(receipt, request)
    store = open_coding_windows_product_worker_provisioning_state_store(
        product, runtime=runtime, selected=selected, receipt=receipt,
        worker_request=request, plan=plan,
    )
    profile = _bind_windows_lpac_contained_product_worker_profile(
        receipt=receipt, worker_request=request, plan=plan,
        platform_imports=WINDOWS_LPAC_PLATFORM_IMPORTS,
        provisioning_state_store=store,
    )

    async def run_worker():
        host = None
        supervisor = WorkerSupervisor(
            identity=request.identity,
            journal=open_coding_windows_product_worker_supervisor_journal(product),
            protocol=request.runtime.protocol,
            protocol_version=request.runtime.protocol_version,
        )
        try:
            host = _create_windows_lpac_child_session_host(max_sessions=1)
            adapter = HostingManagedWorkerSessionAdapter(
                hosting=host, preparation=profile,
            )
            await supervisor.start_session(
                session_port=adapter, launch_request=request,
                correlation_id="windows-product-worker-rotation",
            )
            assert supervisor.status.state == "healthy"
            described = await supervisor.query({"operation": "describe", "queryVersion": 1})
            assert described["capabilities"][0]["capabilityId"] == "coding.worker.query"
            print("rotation:new-worker-healthy", file=sys.stderr, flush=True)
            await supervisor.shutdown()
            assert supervisor.status.state == "stopped"
        finally:
            try:
                if supervisor.status.state == "healthy":
                    await supervisor.fence(code="windows_rotation_cleanup")
            finally:
                try:
                    await profile.close()
                finally:
                    if host is not None:
                        await host.close()

    asyncio.run(run_worker())
    assert profile.native_containment_settlement_witness() is not None
    print("rotation:new-worker-settled", file=sys.stderr, flush=True)
    runtime.dispose_runtime()
    runtime = None
    factory = None
    after = inspect_coding_windows_product_worker_offline_recovery(product)
    attempts = {item.attempt_id: item for item in after.attempts}
    print(json.dumps({
        "oldRetired": attempts["7" * 32].payload_directory_identity is None,
        "newStopped": attempts["9" * 32].supervisor_phase == "stopped",
        "newNativeSettled": attempts["9" * 32].native_phase == "settled",
        "newPayloadRetained": attempts["9" * 32].payload_directory_identity is not None,
    }))
finally:
    if runtime is not None:
        runtime.dispose_runtime()
    elif factory is not None:
        factory.dispose_unbound_runtime()
    owner.close()
"""
    child_stdout = workspace.parent / "rotation-child.stdout"
    child_stderr = workspace.parent / "rotation-child.stderr"
    try:
        with child_stdout.open("wb") as stdout, child_stderr.open("wb") as stderr:
            completed = subprocess.run(
                (
                    sys.executable,
                    "-c",
                    script,
                    str(workspace),
                    str(session_state),
                    expected_digest,
                    "crash-retired" if crash_retired else "clean-retained",
                ),
                cwd=Path(__file__).resolve().parents[2],
                stdout=stdout,
                stderr=stderr,
                timeout=900,
                check=False,
            )
    except subprocess.TimeoutExpired as exc:
        with child_stderr.open("rb") as output:
            output.seek(0, os.SEEK_END)
            output.seek(max(0, output.tell() - 4096))
            tail = output.read()
        raise AssertionError(
            "Windows Worker rotation child did not settle within 900 seconds"
            f"\nstderr tail: {tail!r}"
        ) from exc
    assert completed.returncode == 0, child_stderr.read_text(
        encoding="utf-8", errors="replace"
    )
    assert json.loads(child_stdout.read_text(encoding="utf-8")) == {
        "oldRetired": True,
        "newStopped": True,
        "newNativeSettled": True,
        "newPayloadRetained": True,
    }
    if not crash_retired:
        _assert_windows_worker_reserved_settlement(
            workspace=workspace, session_state=session_state
        )


def _assert_windows_worker_reserved_settlement(
    *, workspace: Path, session_state: Path
) -> None:
    prepare_script = """\
import json
import sys
from pathlib import Path
from loushang.coding._plugin_lifecycle import resolve_ephemeral_coding_plugin_lifecycle_state_layout
from loushang.coding.package_product_runtime import open_coding_fenced_product_application_owner
from loushang.coding.package_product_worker_windows_launch_intent import commit_coding_windows_product_worker_launch_intent
from loushang.coding.package_product_worker_windows_payload import bind_coding_windows_product_worker_launch_request, materialize_coding_windows_product_worker_payload
from loushang.coding.package_product_worker_windows_provisioning import open_coding_windows_product_worker_provisioning_state_store
from loushang.coding.package_product_worker_windows_receipt import CodingWindowsWorkerProductReceiptOwner
from loushang.coding.package_product_worker_windows_stage_review import review_coding_windows_product_worker_complete_stage
from loushang.coding.package_product_worker_windows_stage_retirement import retire_coding_windows_product_worker_complete_stage
from loushang.harness.package_product.product_runtime import PackageProductRuntimeRequestV1
from loushang.harness.worker._native_profile_bridge import _windows_lpac_provisioning_identity

workspace = Path(sys.argv[1])
lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(Path(sys.argv[2]), cwd=workspace)
owner = open_coding_fenced_product_application_owner(
    lifecycle, workspace=workspace, runtime_version="2.0.0",
    runtime_protocol_epoch=2, worker_candidates=True, windows_candidate=True,
)
runtime = None
factory = None
try:
    product = owner.runtime_owner.product_owner
    review = review_coding_windows_product_worker_complete_stage(product, attempt_id="9" * 32)
    retire_coding_windows_product_worker_complete_stage(product, expected_review=review)
    factory = product.factory_for_session(
        session_id="session:windows-worker-reservation", cwd=workspace,
        runtime_id="runtime:windows-worker-reservation",
    )
    runtime = factory.create(PackageProductRuntimeRequestV1(
        product_id="coding", session_id="session:windows-worker-reservation", cwd=str(workspace),
    ))
    runtime.activate()
    selected = runtime.capture_selected_plugin_manifest_for(
        "workerprobe", max_files=16, max_total_bytes=16 * 1024 * 1024,
    )
    receipt_owner = CodingWindowsWorkerProductReceiptOwner(
        product=product, runtime=runtime, selected=selected,
    )
    receipt = receipt_owner.issue()
    assert receipt is not None
    lease = materialize_coding_windows_product_worker_payload(
        receipt_owner=receipt_owner, receipt=receipt, attempt_id="a" * 32,
    )
    request = bind_coding_windows_product_worker_launch_request(
        receipt_owner=receipt_owner, receipt=receipt, payload_lease=lease,
        supervisor_epoch=3,
    )
    commit_coding_windows_product_worker_launch_intent(
        product, receipt_owner=receipt_owner, receipt=receipt,
        request=request, payload_lease=lease,
    )
    plan = receipt_owner.plan_current_native_attempt(receipt, request)
    store = open_coding_windows_product_worker_provisioning_state_store(
        product, runtime=runtime, selected=selected, receipt=receipt,
        worker_request=request, plan=plan,
    )
    initial = {
        **_windows_lpac_provisioning_identity(
            receipt=receipt, worker_request=request, plan=plan,
        ),
        "phase": "reserved", "stateRevision": 1, "witness": None,
    }
    assert store.compare_and_swap(expected_revision=0, document=initial)
    assert store.load() == initial
    print(json.dumps({"reserved": True, "attemptId": request.identity.attempt_id}))
finally:
    if runtime is not None:
        runtime.dispose_runtime()
    elif factory is not None:
        factory.dispose_unbound_runtime()
    owner.close()
"""
    prepared = subprocess.run(
        (sys.executable, "-c", prepare_script, str(workspace), str(session_state)),
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert prepared.returncode == 0, prepared.stderr
    assert json.loads(prepared.stdout) == {"reserved": True, "attemptId": "a" * 32}
    settle_script = """\
import json
import sys
from pathlib import Path
from unittest.mock import patch
from loushang.coding._plugin_lifecycle import resolve_ephemeral_coding_plugin_lifecycle_state_layout
from loushang.coding.package_product_runtime import open_coding_fenced_product_application_owner
import loushang.coding.package_product_worker_windows_payload as payload_module
import loushang.coding.package_product_worker_windows_unlaunched_stage_retirement as unlaunched_retirement_module
from loushang.coding.package_product_worker_windows_payload import CodingWindowsWorkerPayloadMaterializationError, materialize_coding_windows_product_worker_payload
from loushang.coding.package_product_worker_windows_recovery_inventory import CodingWindowsWorkerRecoveryAdmissionError, _current_after_verified_retirements_under_gc_guard, _inspect_windows_worker_recovery_inventory_under_gc_guard, inspect_coding_windows_product_worker_offline_recovery
from loushang.coding.package_product_worker_windows_receipt import CodingWindowsWorkerProductReceiptOwner
from loushang.coding.package_product_worker_windows_reserved_review import review_coding_windows_product_worker_reserved_no_effect, review_coding_windows_product_worker_settled_unlaunched
from loushang.coding.package_product_worker_windows_reserved_settlement import settle_coding_windows_product_worker_reserved_no_effect
from loushang.coding.package_product_worker_windows_unlaunched_stage_retirement import retire_coding_windows_product_worker_settled_unlaunched_stage
from loushang.harness.package_product.product_runtime import PackageProductRuntimeRequestV1

workspace = Path(sys.argv[1])
lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(Path(sys.argv[2]), cwd=workspace)
owner = open_coding_fenced_product_application_owner(
    lifecycle, workspace=workspace, runtime_version="2.0.0",
    runtime_protocol_epoch=2, worker_candidates=True, windows_candidate=True,
)
runtime = None
factory = None
try:
    product = owner.runtime_owner.product_owner
    review = review_coding_windows_product_worker_reserved_no_effect(product, attempt_id="a" * 32)
    settle_coding_windows_product_worker_reserved_no_effect(product, expected_review=review)
    after = {item.attempt_id: item for item in inspect_coding_windows_product_worker_offline_recovery(product).attempts}
    settled = after["a" * 32].native_phase == "settled" and after["a" * 32].native_revision == 2
    unlaunched = after["a" * 32].supervisor_phase is None
    retained = after["a" * 32].payload_directory_identity is not None
    with product.gc_gate.guard():
        try:
            _current_after_verified_retirements_under_gc_guard(
                product,
                _inspect_windows_worker_recovery_inventory_under_gc_guard(product),
                attempt_id="b" * 32,
            )
        except CodingWindowsWorkerRecoveryAdmissionError as error:
            assert error.code == "coding_worker_payload_recovery_required"
        else:
            raise AssertionError("Unretired reservation was admitted")
    unlaunched_review = review_coding_windows_product_worker_settled_unlaunched(product, attempt_id="a" * 32)
    with patch.object(unlaunched_retirement_module, "_delete_directory_if_empty", side_effect=OSError("injected unlaunched retirement interruption")):
        try:
            retire_coding_windows_product_worker_settled_unlaunched_stage(product, expected_review=unlaunched_review)
        except OSError as error:
            assert "injected unlaunched retirement interruption" in str(error)
        else:
            raise AssertionError("Unlaunched retirement interruption was not observed")
    retired = retire_coding_windows_product_worker_settled_unlaunched_stage(product, expected_review=unlaunched_review)
    assert retired == retire_coding_windows_product_worker_settled_unlaunched_stage(product, expected_review=unlaunched_review)
    after_retirement = {item.attempt_id: item for item in inspect_coding_windows_product_worker_offline_recovery(product).attempts}
    assert after_retirement["a" * 32].payload_directory_identity is None
    factory = product.factory_for_session(
        session_id="session:windows-worker-after-reservation", cwd=workspace,
        runtime_id="runtime:windows-worker-after-reservation",
    )
    runtime = factory.create(PackageProductRuntimeRequestV1(
        product_id="coding", session_id="session:windows-worker-after-reservation", cwd=str(workspace),
    ))
    runtime.activate()
    selected = runtime.capture_selected_plugin_manifest_for(
        "workerprobe", max_files=16, max_total_bytes=16 * 1024 * 1024,
    )
    receipt_owner = CodingWindowsWorkerProductReceiptOwner(
        product=product, runtime=runtime, selected=selected,
    )
    receipt = receipt_owner.issue()
    assert receipt is not None
    try:
        materialize_coding_windows_product_worker_payload(
            receipt_owner=receipt_owner, receipt=receipt, attempt_id="a" * 32,
        )
    except CodingWindowsWorkerPayloadMaterializationError as error:
        assert error.code == "coding_worker_payload_attempt_reused"
    else:
        raise AssertionError("Retired attempt ID was reused")
    assert not (product.state_root / ("worker-payload-" + "a" * 32)).exists()
    with patch.object(payload_module, "_MAX_RETAINED_ATTEMPTS", len(after_retirement)):
        try:
            materialize_coding_windows_product_worker_payload(
                receipt_owner=receipt_owner, receipt=receipt, attempt_id="b" * 32,
            )
        except CodingWindowsWorkerPayloadMaterializationError as error:
            assert error.code == "coding_worker_payload_capacity"
        else:
            raise AssertionError("Bounded inventory allowed another attempt")
    assert not (product.state_root / ("worker-payload-" + "b" * 32)).exists()
    with patch.object(
        payload_module,
        "windows_flush_file",
        side_effect=OSError("injected partial payload write interruption"),
    ):
        try:
            materialize_coding_windows_product_worker_payload(
                receipt_owner=receipt_owner, receipt=receipt, attempt_id="b" * 32,
            )
        except OSError as error:
            assert "partial payload write interruption" in str(error)
        else:
            raise AssertionError("Partial payload write interruption was not observed")
    partial_stage = product.state_root / ("worker-payload-" + "b" * 32)
    assert partial_stage.is_dir()
    assert not (partial_stage / "worker-payload.json").exists()
    print(json.dumps({
        "settled": settled,
        "unlaunched": unlaunched,
        "retainedBeforeRetirement": retained,
        "retiredIdRejected": True,
        "capacityRejectedBeforeStage": True,
        "partialRetained": True,
    }))
finally:
    if runtime is not None:
        runtime.dispose_runtime()
    elif factory is not None:
        factory.dispose_unbound_runtime()
    owner.close()
"""
    settled = subprocess.run(
        (sys.executable, "-c", settle_script, str(workspace), str(session_state)),
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert settled.returncode == 0, settled.stderr
    assert json.loads(settled.stdout) == {
        "settled": True,
        "unlaunched": True,
        "retainedBeforeRetirement": True,
        "retiredIdRejected": True,
        "capacityRejectedBeforeStage": True,
        "partialRetained": True,
    }


def test_windows_coding_first_b_captures_real_fresh_workspace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global" / "settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )

    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="a" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )

    assert cutover.attempt.result.disposition == "fenced"
    assert reopen_coding_package_cutover(lifecycle) == cutover.attempt.result
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    switch = cutover.attempt.result.switch_receipt
    assert switch is not None
    evidence = read_windows_product_pre_b_snapshot(
        snapshot_root=epoch.snapshot_root,
        store_id=epoch.store_id,
        snapshot_receipt_id=switch.snapshot_receipt_id,
    )
    assert evidence is not None
    assert evidence.snapshot.receipt_id == switch.snapshot_receipt_id
    product = PackageProductWindowsFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    try:
        state = open_coding_package_product_state(lifecycle, product)
        assert state.state_root == epoch.control_root / "product-state"
        fence = product.cutover_result.fence
        assert fence is not None
        observation = CodingFirstBLegacyStateObserver(lifecycle, product).observe(
            store_id=epoch.store_id,
            legacy_root_identity=fence.request.legacy_root_identity,
        )
        assert observation.state_digest == evidence.snapshot_tree_digest
        inventory = read_coding_legacy_installation_inventory(lifecycle, product)
        assert inventory.first_fence_id == fence.fence_id
        assert inventory.inventory.active_local == ()
        assert inventory.inventory.builtin_intent == ()
        assert inventory.inventory.unselected_source_identities == ()
        with pytest.raises(CodingLegacySnapshotError):
            CodingFirstBLegacyStateObserver(lifecycle, product).observe(
                store_id="foreign-store",
                legacy_root_identity=fence.request.legacy_root_identity,
            )
        assert list_coding_first_b_snapshot_domain_members(
            lifecycle, product, domain="source_configuration"
        ) == ("coding-source-configuration.json",)
        source_projection = read_coding_first_b_snapshot_member(
            lifecycle,
            product,
            domain="source_configuration",
            member_name="coding-source-configuration.json",
            maximum_bytes=2 * 1024 * 1024,
        )
        assert source_projection is not None
        assert "scopes" in json.loads(source_projection)
        with product.issue_runtime_lease(
            runtime_id="coding-first-b-native-smoke",
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        ) as lease:
            assert lease.admission_request.store_id == epoch.store_id
            product.assert_current()
        current_b_root = epoch.epoch_root(fence.request.namespace_id)
        b_marker = current_b_root / "current-b.txt"
        b_marker.write_bytes(b"current B remains isolated")
        fence_bytes = (epoch.control_root / "epoch.jsonl").read_bytes()
        restore_root = tmp_path / "coding-restore-authority"
        activation_root = tmp_path / "coding-activation-authority"
        restore_root.mkdir()
        activation_root.mkdir()
        restore_request = PackageOfflineRestoreRequestV1.create(
            current_fence=fence,
            genesis_fence=fence,
            snapshot_evidence=evidence,
            restore_namespace_id=sha256(b"windows-coding-first-b-restore").hexdigest(),
            legacy_runtime_version="1.9.0",
        )
        materializer = PackageWindowsOfflineRestoreMaterializer(
            epoch.snapshot_root,
            restore_root,
            current_b_authority_root=current_b_root,
            store_id=epoch.store_id,
        )
        activation = PackageWindowsLegacyRuntimeActivationOwner(
            restore_root,
            activation_root,
            current_b_authority_root=current_b_root,
            store_id=epoch.store_id,
            legacy_runtime_version=restore_request.legacy_runtime_version,
            command=(
                os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"),
                "/d",
                "/q",
                "/c",
                (
                    "> %LOUSHANG_LEGACY_RUNTIME_READY_PATH% "
                    "echo %LOUSHANG_LEGACY_RUNTIME_READY_TOKEN% && "
                    "for /L %i in (1,1,2147483647) do ver >nul 2>&1"
                ),
            ),
        )
        restore_owner = PackageOfflineRestoreOwner(
            store_id=epoch.store_id,
            epoch_journal=product.registry.fences,
            coordination=PackageWindowsCurrentEpochCutoverCoordinationOwner(
                product.registry
            ),
            snapshots=cutover.snapshots,
            materialization=materializer,
            activation=activation,
        )
        restored = None
        try:
            restored = restore_owner.restore(restore_request)
            assert restored.disposition == "restored"
            assert restored.materialization is not None
            assert restored.activation is not None
            assert restored.materialization.legacy_snapshot_exact
            assert restored.materialization.b_namespace_unreachable
            restored_projection = (
                restore_root
                / restore_request.restore_namespace_id
                / "payload"
                / "source_configuration"
                / "coding-source-configuration.json"
            )
            assert restored_projection.read_bytes() == source_projection
            assert b_marker.read_bytes() == b"current B remains isolated"
        finally:
            if restored is not None and restored.activation is not None:
                activation.deactivate_required(restored.activation)
            if restored is not None and restored.materialization is not None:
                materializer.discard(restored.materialization)
        assert not (restore_root / restore_request.restore_namespace_id).exists()
        assert not (activation_root / "active-runtime.json").exists()
        assert (epoch.control_root / "epoch.jsonl").read_bytes() == fence_bytes
        assert product.registry.fences.current(epoch.store_id) == fence
    finally:
        product.close()
    assert inspect_coding_package_cutover_backup(lifecycle).status == "retained"
    with patch(
        "loushang.coding.cli.package_cutover.resolve_coding_plugin_lifecycle_state_layout",
        return_value=lifecycle,
    ):
        assert cutover_cli_main(("--workspace", str(workspace), "--backup-status")) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "retained"
    (
        epoch.snapshot_root
        / evidence.snapshot.snapshot_id
        / "payload"
        / "source_configuration"
        / "coding-source-configuration.json"
    ).write_bytes(b"tampered")
    with pytest.raises(PackageOfflineRestoreError):
        inspect_coding_package_cutover_backup(lifecycle)


def test_windows_coding_first_b_reviews_frozen_builtin_desired_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global" / "settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    prepare_coding_package_cutover_roots(lifecycle)
    old_path = tmp_path / "old-builtin.jsonl"
    PluginDesiredStateLedger(old_path).commit(
        PluginDesiredStateMutationV1(
            operation_id="old-arch-intent",
            idempotency_key="old-arch-intent",
            expected_inventory_revision=0,
            installation_key=PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=lifecycle.scope_id,
                plugin_id="coding.arch.default",
            ),
            desired_state="installed_disabled",
            package_revision=PluginPackageRevisionRefV1(
                plugin_id="coding.arch.default",
                plugin_version="1",
                package_content_digest="1" * 64,
                dependency_lock_digest="2" * 64,
                package_source_identity="embedded:coding.arch.default",
            ),
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    lifecycle.desired_state.write_bytes(old_path.read_bytes())
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="b" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
        snapshot_admission=lambda prepared, snapshot: (
            admit_coding_builtin_only_snapshot(lifecycle, prepared, snapshot)
        ),
    )
    assert cutover.attempt.result.disposition == "fenced"
    product = PackageProductWindowsFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    try:
        fence = product.cutover_result.fence
        assert fence is not None
        inventory = read_coding_legacy_installation_inventory(lifecycle, product)
        assert inventory.first_fence_id == fence.fence_id
        assert [
            (item.plugin_id, item.desired_state)
            for item in inventory.inventory.builtin_intent
        ] == [("coding.arch.default", "installed_disabled")]
        review = review_coding_first_b_builtin_only(
            lifecycle, product, settings_manager=settings
        )
        assert review.first_fence_id == fence.fence_id
        assert [
            (item.plugin_id, item.desired_state) for item in review.builtin_intent
        ] == [("coding.arch.default", "installed_disabled")]
        assert review.removed_builtin_ids == ()
        lifecycle.desired_state.write_bytes(b"changed after the first fence\n")
        assert (
            review_coding_first_b_builtin_only(
                lifecycle, product, settings_manager=settings
            )
            == review
        )
        with pytest.raises(CodingLegacyBuiltinOnlyAcceptanceError):
            accept_coding_first_b_builtin_only(
                lifecycle,
                product,
                settings_manager=settings,
                accepted_review_id="0" * 64,
            )
        desired_path = product.prepare_product_state_root() / "desired-state.jsonl"
        desired_path.write_bytes(old_path.read_bytes())
        with pytest.raises(CodingLegacyBuiltinOnlyAcceptanceError):
            accept_coding_first_b_builtin_only(
                lifecycle,
                product,
                settings_manager=settings,
                accepted_review_id=review.review_id,
            )
        desired_path.write_bytes(b"")
        with patch(
            "loushang.coding.package_legacy_windows_receipt.windows_rename_at",
            side_effect=OSError("injected publish interruption"),
        ):
            with pytest.raises(OSError, match="injected publish interruption"):
                accept_coding_first_b_builtin_only(
                    lifecycle,
                    product,
                    settings_manager=settings,
                    accepted_review_id=review.review_id,
                )
        stage_path = desired_path.parent / "legacy-builtin-acceptance.jsonl.stage"
        assert stage_path.is_file()
        with pytest.raises(CodingWindowsPrivateReceiptError, match="unpublished stage"):
            read_coding_first_b_builtin_only_acceptance(
                lifecycle, product, settings_manager=settings
            )
        acceptance = accept_coding_first_b_builtin_only(
            lifecycle,
            product,
            settings_manager=settings,
            accepted_review_id=review.review_id,
        )
        assert acceptance.review == review
        assert not stage_path.exists()
        assert (
            read_coding_first_b_builtin_only_acceptance(
                lifecycle, product, settings_manager=settings
            )
            == acceptance
        )
        assert (
            accept_coding_first_b_builtin_only(
                lifecycle,
                product,
                settings_manager=settings,
                accepted_review_id=review.review_id,
            )
            == acceptance
        )
    finally:
        product.close()

    with pytest.raises(RuntimeError, match="not admitted"):
        adopt_coding_first_b_builtin_only(
            lifecycle,
            settings,
            workspace=workspace,
            accepted_review_id=review.review_id,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )
    desired_before = desired_path.read_bytes()
    with (
        patch(
            "loushang.coding.cli.package_cutover.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
        patch(
            "loushang.coding.cli.package_cutover.default_global_settings_path",
            return_value=tmp_path / "global" / "settings.json",
        ),
        patch(
            "loushang.coding.cli.package_cutover.default_project_settings_path",
            return_value=workspace / ".loushang" / "settings.json",
        ),
        patch("loushang.coding.cli.package_cutover.version", return_value="2.0.0"),
        patch(
            "loushang.coding.cli.package_cutover._WINDOWS_CANDIDATE_ROUTE_ADMITTED",
            True,
        ),
    ):
        arguments = (
            "--workspace",
            str(workspace),
            "--windows-candidate",
            "--adopt-legacy-builtin-review",
            review.review_id,
        )
        assert cutover_cli_main(arguments) == 0
        adopted = json.loads(capsys.readouterr().out)
        assert adopted == {
            "disposition": "adopted",
            "acceptanceId": acceptance.acceptance_id,
            "reviewId": review.review_id,
        }
        assert cutover_cli_main(arguments) == 0
        assert json.loads(capsys.readouterr().out) == adopted
    assert desired_path.read_bytes() != desired_before
    assert (
        adopt_coding_first_b_builtin_only(
            lifecycle,
            settings,
            workspace=workspace,
            accepted_review_id=review.review_id,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
            windows_candidate=True,
        )
        == acceptance
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    try:
        product_owner = owner.runtime_owner.product_owner
        selected = product_owner.desired_state.snapshot()
        assert {
            item.installation_key.plugin_id: item.selection.desired_state
            for item in selected.installations
        } == {
            "coding.base": "installed_enabled",
            "coding.lsp.default": "installed_enabled",
            "coding.arch.default": "installed_disabled",
        }
        factory = product_owner.factory_for_session(
            session_id="session:windows-migrated-builtin",
            cwd=workspace,
            runtime_id="runtime:windows-migrated-builtin",
        )
        binding = None
        try:
            binding = factory.create(
                PackageProductRuntimeRequestV1(
                    product_id="coding",
                    session_id="session:windows-migrated-builtin",
                    cwd=str(workspace),
                )
            )
            runtime = binding.activate()
            assert (
                runtime.capture_selected_plugin_manifest_for(
                    "coding.base", max_files=64, max_total_bytes=1024 * 1024
                )
                .verified_manifest()
                .name
                == "coding.base"
            )
            with pytest.raises(PackageProductRuntimeReadError, match="not selected"):
                runtime.capture_selected_plugin_manifest_for(
                    "coding.arch.default",
                    max_files=64,
                    max_total_bytes=1024 * 1024,
                )
        finally:
            if binding is None:
                factory.dispose_unbound_runtime()
            else:
                binding.dispose_runtime()
        base = next(
            item
            for item in selected.installations
            if item.installation_key.plugin_id == "coding.base"
        )
        disabled = product_owner.management.submit(
            PluginManagementCommandV1(
                action="disable",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator:windows-disable-migrated-base",
                    idempotency_key="operator:windows-disable-migrated-base",
                    expected_inventory_revision=(
                        product_owner.desired_state.snapshot().inventory_revision
                    ),
                    installation_key=base.installation_key,
                    desired_state="installed_disabled",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision=product_owner.desired_policy_revision,
                ),
            )
        )
        assert disabled.result is not None
        assert disabled.result.disposition == "succeeded"
    finally:
        owner.close()
    assert (
        adopt_coding_first_b_builtin_only(
            lifecycle,
            settings,
            workspace=workspace,
            accepted_review_id=review.review_id,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
            windows_candidate=True,
        )
        == acceptance
    )
    reopened = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    try:
        assert {
            item.installation_key.plugin_id: item.selection.desired_state
            for item in reopened.runtime_owner.product_owner.desired_state.snapshot().installations
        } == {
            "coding.base": "installed_disabled",
            "coding.lsp.default": "installed_enabled",
            "coding.arch.default": "installed_disabled",
        }
    finally:
        reopened.close()


def test_windows_builtin_candidate_cli_prepares_reviews_and_adopts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    prepare_coding_package_cutover_roots(lifecycle)
    old_path = tmp_path / "old-builtin.jsonl"
    PluginDesiredStateLedger(old_path).commit(
        PluginDesiredStateMutationV1(
            operation_id="old-arch-intent",
            idempotency_key="old-arch-intent",
            expected_inventory_revision=0,
            installation_key=PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=lifecycle.scope_id,
                plugin_id="coding.arch.default",
            ),
            desired_state="installed_disabled",
            package_revision=PluginPackageRevisionRefV1(
                plugin_id="coding.arch.default",
                plugin_version="1",
                package_content_digest="1" * 64,
                dependency_lock_digest="2" * 64,
                package_source_identity="embedded:coding.arch.default",
            ),
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    lifecycle.desired_state.write_bytes(old_path.read_bytes())
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    prepare_args = (
        "--workspace",
        str(workspace),
        "--windows-candidate",
        "--prepare-legacy-builtin-review",
    )
    with (
        patch(
            "loushang.coding.cli.package_cutover.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
        patch(
            "loushang.coding.cli.package_cutover.default_global_settings_path",
            return_value=tmp_path / "global" / "settings.json",
        ),
        patch(
            "loushang.coding.cli.package_cutover.default_project_settings_path",
            return_value=workspace / ".loushang" / "settings.json",
        ),
        patch("loushang.coding.cli.package_cutover.version", return_value="2.0.0"),
    ):
        with patch(
            "loushang.coding.cli.package_cutover._WINDOWS_CANDIDATE_ROUTE_ADMITTED",
            False,
        ):
            assert cutover_cli_main(prepare_args) == 1
        assert not (epoch.control_root / "epoch.jsonl").exists()
        capsys.readouterr()
        with patch(
            "loushang.coding.cli.package_cutover._WINDOWS_CANDIDATE_ROUTE_ADMITTED",
            True,
        ):
            assert cutover_cli_main(prepare_args) == 0
            review = json.loads(capsys.readouterr().out)
            assert review["builtinIntent"][0]["pluginId"] == "coding.arch.default"
            desired_path = epoch.control_root / "product-state" / "desired-state.jsonl"
            desired_before_review = (
                desired_path.read_bytes() if desired_path.exists() else None
            )
            assert (
                cutover_cli_main(
                    (
                        "--workspace",
                        str(workspace),
                        "--windows-candidate",
                        "--review-legacy-builtin-only",
                    )
                )
                == 0
            )
            assert json.loads(capsys.readouterr().out) == review
            assert (
                desired_path.read_bytes() if desired_path.exists() else None
            ) == desired_before_review
            adopt_args = (
                "--workspace",
                str(workspace),
                "--windows-candidate",
                "--adopt-legacy-builtin-review",
                review["reviewId"],
            )
            assert cutover_cli_main(adopt_args[:-1] + ("",)) == 1
            capsys.readouterr()
            assert cutover_cli_main(adopt_args[:-1] + ("0" * 64,)) == 1
            capsys.readouterr()
            assert cutover_cli_main(adopt_args) == 0
            adopted = json.loads(capsys.readouterr().out)
            assert adopted["reviewId"] == review["reviewId"]
            assert cutover_cli_main(adopt_args) == 0
            assert json.loads(capsys.readouterr().out) == adopted
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    try:
        selected = owner.runtime_owner.product_owner.desired_state.snapshot()
        assert {
            item.installation_key.plugin_id: item.selection.desired_state
            for item in selected.installations
        } == {
            "coding.base": "installed_enabled",
            "coding.lsp.default": "installed_enabled",
            "coding.arch.default": "installed_disabled",
        }
    finally:
        owner.close()


def test_windows_coding_first_b_refuses_live_old_process_then_retries(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global" / "settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    fences = PackageEpochFenceJournal(epoch.control_root / "epoch.jsonl")
    registration = PackageWindowsPreFenceRegistrationOwner(
        epoch.control_root, store_id=epoch.store_id, fences=fences
    ).register(startup_id="old-coding-session")
    try:
        refused = prepare_and_cutover_coding_package_store_from_legacy(
            lifecycle,
            settings,
            namespace_id="b" * 64,
            minimum_runtime_version="2.0.0",
            minimum_runtime_protocol_epoch=2,
        )
        assert refused.attempt.result.disposition == "rejected"
        assert fences.current(epoch.store_id) is None
        assert not list(epoch.snapshot_root.glob("*.evidence.json"))
    finally:
        registration.release()

    accepted = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="b" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    assert accepted.attempt.result.disposition == "fenced"


def test_windows_coding_first_b_installs_and_selects_builtin_product_wheel(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global" / "settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="e" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    assert cutover.attempt.result.disposition == "fenced"
    with pytest.raises(RuntimeError, match="not yet admitted"):
        open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )
    assert not (
        resolve_coding_package_epoch_layout(lifecycle).control_root / "product-state"
    ).exists()
    assert bootstrap_coding_builtin_product_plugins(
        lifecycle,
        settings,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    try:
        product = owner.runtime_owner.product_owner
        state = open_coding_package_product_state(lifecycle, owner.epoch_runtime)
        worker_owner = open_coding_builtin_product_runtime_owner(
            lifecycle,
            owner.epoch_runtime,
            state,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
            worker_candidates=True,
        )
        assert worker_owner.product_owner.policy.product_id == "coding"
        factory = product.factory_for_session(
            session_id="session:windows-selected-base",
            cwd=workspace,
            runtime_id="runtime:windows-selected-base",
        )
        binding = None
        try:
            binding = factory.create(
                PackageProductRuntimeRequestV1(
                    product_id="coding",
                    session_id="session:windows-selected-base",
                    cwd=str(workspace),
                )
            )
            binding.activate()
            selected = binding.capture_selected_plugin_manifest_for(
                "coding.base", max_files=64, max_total_bytes=2 * 1024 * 1024
            )
            assert selected.verified_manifest().name == "coding.base"
        finally:
            if binding is None:
                factory.dispose_unbound_runtime()
            else:
                binding.dispose_runtime()
    finally:
        owner.close()


def test_windows_coding_product_gc_reclaims_only_removed_builtin_root(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global" / "settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="f" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    assert cutover.attempt.result.disposition == "fenced"
    assert bootstrap_coding_builtin_product_plugins(
        lifecycle,
        settings,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    try:
        product = owner.runtime_owner.product_owner
        assert isinstance(product, WindowsLocalWheelProductSessionOwner)
        selected = product.desired_state.snapshot()
        arch = next(
            item
            for item in selected.installations
            if item.installation_key.plugin_id == "coding.arch.default"
        )
        revision = arch.selection.package_revision
        assert revision is not None
        removed = product.management.submit(
            PluginManagementCommandV1(
                action="remove",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator:windows-remove-arch",
                    idempotency_key="operator:windows-remove-arch",
                    expected_inventory_revision=selected.inventory_revision,
                    installation_key=arch.installation_key,
                    desired_state="absent",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision="operator:1",
                ),
            )
        )
        assert removed.result is not None
        assert removed.result.disposition == "succeeded"
        gc = open_windows_local_wheel_product_root_gc(product)
        payload_debt = product.state_root / ("worker-payload-" + "a" * 32)
        payload_debt.mkdir()
        with pytest.raises(PackageProductGcExecutionError) as unsettled:
            gc.prepare()
        assert unsettled.value.code == "plugin_package_gc_worker_payload_unsettled"
        payload_debt.rmdir()
        differently_cased_payload = product.state_root / ("Worker-Payload-" + "a" * 32)
        differently_cased_payload.mkdir()
        with pytest.raises(PackageProductGcExecutionError) as unsettled_case:
            gc.prepare()
        assert unsettled_case.value.code == "plugin_package_gc_worker_payload_unsettled"
        differently_cased_payload.rmdir()
        launch_history = product.state_root / (
            "worker-launch-intent-" + "a" * 32 + ".json"
        )
        launch_history.write_bytes(b"unsettled")
        with pytest.raises(PackageProductGcExecutionError) as retained_history:
            gc.prepare()
        assert (
            retained_history.value.code == "plugin_package_gc_worker_history_unsettled"
        )
        launch_history.unlink()
        orphan_supervisor_lock = product.state_root / "worker-supervisor.jsonl.lock"
        orphan_supervisor_lock.write_bytes(b"")
        with pytest.raises(PackageProductGcExecutionError) as orphaned_history:
            gc.prepare()
        assert (
            orphaned_history.value.code == "plugin_package_gc_worker_history_unsettled"
        )
        orphan_supervisor_lock.unlink()
        gc.prepare()
        (candidate,) = gc.candidates()
        assert candidate.package_revision == revision
        executor = gc.application.executor
        target = resolve_plugin_package_gc_root_target(
            revision,
            bindings=product.gc_bindings.records(),
            claims=product.gc_bindings.claims(),
            committed_sets=executor.committed_sets.records(),
            settlements=executor.root_settlements.records(),
        )
        deleted_root = product.plugin_store_root / target.settlement.final_name
        assert deleted_root.is_dir()
        command = PackageProductRootGcCommandV1(
            candidate=candidate,
            reservation_operation_id="operator:windows-gc-reserve-arch",
            reservation_idempotency_key="operator:windows-gc-reserve-arch",
            attempt_operation_id="operator:windows-gc-delete-arch",
            attempt_idempotency_key="operator:windows-gc-delete-arch",
        )
        live = product.factory_for_session(
            session_id="session:windows-gc-live",
            cwd=workspace,
            runtime_id="runtime:windows-gc-live",
        )
        try:
            with pytest.raises(PackageProductGcExecutionError) as busy:
                gc.execute(command)
            assert busy.value.code == "plugin_package_gc_runtime_active"
            assert deleted_root.is_dir()
        finally:
            live.dispose_unbound_runtime()
        result = gc.execute(command)
        assert result.disposition == "succeeded"
        assert not deleted_root.exists()
        assert gc.execute(command) == result
        (status,) = gc.statuses()
        assert status.state == "succeeded"
    finally:
        owner.close()


@pytest.mark.parametrize("legacy_input", ("settings", "desired", "package"))
def test_windows_fresh_candidate_refuses_pre_b_without_writing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    legacy_input: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    project_path = workspace / ".loushang" / "settings.json"
    if legacy_input == "settings":
        project_path.parent.mkdir()
        project_path.write_text(
            json.dumps({"disabled_plugins": ["coding.base"]}), encoding="utf-8"
        )
    else:
        root = lifecycle.root if legacy_input == "desired" else lifecycle.package_root
        member = (
            "desired-state.jsonl" if legacy_input == "desired" else "package-lock.json"
        )
        root.mkdir(parents=True)
        (root / member).write_bytes(b"")
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}

    with (
        patch(
            "loushang.coding.cli.package_cutover.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
        patch(
            "loushang.coding.cli.package_cutover.default_global_settings_path",
            return_value=tmp_path / "global" / "settings.json",
        ),
        patch(
            "loushang.coding.cli.package_cutover.default_project_settings_path",
            return_value=project_path,
        ),
        patch(
            "loushang.coding.cli.package_cutover._WINDOWS_CANDIDATE_ROUTE_ADMITTED",
            True,
        ),
    ):
        assert (
            cutover_cli_main(("--workspace", str(workspace), "--windows-candidate"))
            == 1
        )

    assert "pre-B workspace is unsupported" in capsys.readouterr().err
    assert {path.relative_to(tmp_path) for path in tmp_path.rglob("*")} == before


def test_windows_coding_fresh_candidate_cli_fences_bootstraps_and_replays(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    with (
        patch(
            "loushang.coding.cli.package_cutover.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
        patch(
            "loushang.coding.cli.package_cutover.default_global_settings_path",
            return_value=tmp_path / "global" / "settings.json",
        ),
        patch(
            "loushang.coding.cli.package_cutover.default_project_settings_path",
            return_value=workspace / ".loushang" / "settings.json",
        ),
        patch("loushang.coding.cli.package_cutover.version", return_value="2.0.0"),
    ):
        arguments = (
            "--workspace",
            str(workspace),
            "--windows-candidate",
        )
        with patch(
            "loushang.coding.cli.package_cutover._WINDOWS_CANDIDATE_ROUTE_ADMITTED",
            False,
        ):
            assert cutover_cli_main(arguments) == 1
        assert not (
            resolve_coding_package_epoch_layout(lifecycle).control_root / "epoch.jsonl"
        ).exists()
        capsys.readouterr()
        assert cutover_cli_main(arguments + ("--review-legacy-local-plugin", "")) == 1
        assert not (
            resolve_coding_package_epoch_layout(lifecycle).control_root / "epoch.jsonl"
        ).exists()
        capsys.readouterr()
        assert cutover_cli_main(arguments) == 0
        first = json.loads(capsys.readouterr().out)
        assert first["disposition"] == "fenced"
        assert cutover_cli_main(arguments) == 0
        assert json.loads(capsys.readouterr().out) == first


def test_windows_fresh_candidate_replay_refuses_old_desired_snapshot(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings_path = tmp_path / "global" / "settings.json"
    settings = SettingsManager(
        global_settings_path=settings_path,
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    prepare_coding_package_cutover_roots(lifecycle)
    old_path = tmp_path / "old-desired.jsonl"
    PluginDesiredStateLedger(old_path).commit(
        PluginDesiredStateMutationV1(
            operation_id="old-arch-disable",
            idempotency_key="old-arch-disable",
            expected_inventory_revision=0,
            installation_key=PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=lifecycle.scope_id,
                plugin_id="coding.arch.default",
            ),
            desired_state="installed_disabled",
            package_revision=PluginPackageRevisionRefV1(
                plugin_id="coding.arch.default",
                plugin_version="1",
                package_content_digest="1" * 64,
                dependency_lock_digest="2" * 64,
                package_source_identity="embedded:coding.arch.default",
            ),
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    old_bytes = old_path.read_bytes()
    lifecycle.desired_state.write_bytes(old_bytes)
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    namespace_id = sha256(
        b"loushang.coding-fresh-product-epoch/v1\0" + epoch.store_id.encode()
    ).hexdigest()
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id=namespace_id,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
        snapshot_admission=lambda prepared, snapshot: (
            admit_coding_builtin_only_snapshot(lifecycle, prepared, snapshot)
        ),
    )
    assert cutover.attempt.result.disposition == "fenced"
    with (
        patch(
            "loushang.coding.cli.package_cutover.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
        patch(
            "loushang.coding.cli.package_cutover.default_global_settings_path",
            return_value=settings_path,
        ),
        patch(
            "loushang.coding.cli.package_cutover.default_project_settings_path",
            return_value=workspace / ".loushang" / "settings.json",
        ),
        patch("loushang.coding.cli.package_cutover.version", return_value="2.0.0"),
        patch(
            "loushang.coding.cli.package_cutover._WINDOWS_CANDIDATE_ROUTE_ADMITTED",
            True,
        ),
    ):
        assert (
            cutover_cli_main(("--workspace", str(workspace), "--windows-candidate"))
            == 1
        )
    assert "not a fresh cutover" in capsys.readouterr().err
    assert lifecycle.desired_state.read_bytes() == old_bytes
    assert not (epoch.control_root / "product-state").exists()


def test_windows_coding_gc_cli_requires_candidate_and_reads_product(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global" / "settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="9" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    assert cutover.attempt.result.disposition == "fenced"
    assert bootstrap_coding_builtin_product_plugins(
        lifecycle,
        settings,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    with (
        patch(
            "loushang.coding.cli.package_gc.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
        patch("loushang.coding.cli.package_gc.version", return_value="2.0.0"),
    ):
        base = ("--workspace", str(workspace))
        assert gc_cli_main((*base, "list")) == 1
        assert "package_gc_platform_unsupported" in capsys.readouterr().err
        candidate = (*base, "--windows-candidate")
        with patch(
            "loushang.coding.cli.package_gc._WINDOWS_CANDIDATE_ROUTE_ADMITTED",
            False,
        ):
            assert gc_cli_main((*candidate, "prepare")) == 1
        assert "package_gc_platform_unsupported" in capsys.readouterr().err
        assert gc_cli_main((*candidate, "prepare")) == 0
        assert json.loads(capsys.readouterr().out)["disposition"] == "prepared"
        assert gc_cli_main((*candidate, "list")) == 0
        listed = json.loads(capsys.readouterr().out)
        assert listed["candidates"] == []


def test_windows_coding_gc_cli_deletes_exact_removed_builtin_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global" / "settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="a" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    assert cutover.attempt.result.disposition == "fenced"
    assert bootstrap_coding_builtin_product_plugins(
        lifecycle,
        settings,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    try:
        product = owner.runtime_owner.product_owner
        assert isinstance(product, WindowsLocalWheelProductSessionOwner)
        selected = product.desired_state.snapshot()
        arch = next(
            item
            for item in selected.installations
            if item.installation_key.plugin_id == "coding.arch.default"
        )
        revision = arch.selection.package_revision
        assert revision is not None
        removed = product.management.submit(
            PluginManagementCommandV1(
                action="remove",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator:windows-cli-remove-arch",
                    idempotency_key="operator:windows-cli-remove-arch",
                    expected_inventory_revision=selected.inventory_revision,
                    installation_key=arch.installation_key,
                    desired_state="absent",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision="operator:1",
                ),
            )
        )
        assert removed.result is not None
        assert removed.result.disposition == "succeeded"
        gc = open_windows_local_wheel_product_root_gc(product)
        executor = gc.application.executor
        target = resolve_plugin_package_gc_root_target(
            revision,
            bindings=product.gc_bindings.records(),
            claims=product.gc_bindings.claims(),
            committed_sets=executor.committed_sets.records(),
            settlements=executor.root_settlements.records(),
        )
        deleted_root = product.plugin_store_root / target.settlement.final_name
        assert deleted_root.is_dir()
    finally:
        owner.close()

    with (
        patch(
            "loushang.coding.cli.package_gc.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
        patch("loushang.coding.cli.package_gc.version", return_value="2.0.0"),
    ):
        args = ("--workspace", str(workspace), "--windows-candidate")
        assert gc_cli_main((*args, "prepare")) == 0
        capsys.readouterr()
        assert gc_cli_main((*args, "list")) == 0
        (candidate,) = json.loads(capsys.readouterr().out)["candidates"]
        assert candidate["pluginId"] == "coding.arch.default"
        assert deleted_root.is_dir()
        assert (
            gc_cli_main(
                (*args, "delete", "--candidate-id", "0" * 64, "--attempt-key", "wrong")
            )
            == 1
        )
        assert "Exact Package GC candidate is unavailable" in capsys.readouterr().err
        assert deleted_root.is_dir()
        assert (
            gc_cli_main(
                (
                    *args,
                    "delete",
                    "--candidate-id",
                    candidate["candidateId"],
                    "--attempt-key",
                    "operator:windows-cli-delete-arch",
                )
            )
            == 0
        )
        deleted = json.loads(capsys.readouterr().out)
        assert deleted["disposition"] == "succeeded"
        assert not deleted_root.exists()
        assert (
            gc_cli_main(
                (
                    *args,
                    "retry",
                    "--reservation-id",
                    deleted["reservationId"],
                    "--attempt-key",
                    "operator:windows-cli-retry-arch",
                )
            )
            == 0
        )
        assert json.loads(capsys.readouterr().out) == deleted
        assert gc_cli_main((*args, "list")) == 0
        listed = json.loads(capsys.readouterr().out)
        assert any(
            item["candidateId"] == candidate["candidateId"]
            and item["state"] == "succeeded"
            for item in listed["statuses"]
        )


def test_windows_coding_default_cutover_refuses_old_plugin_state_before_fence(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    (lifecycle.package_root / "package-lock.json").write_bytes(b"{}")
    settings = SettingsManager(
        global_settings_path=tmp_path / "global" / "settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )

    with pytest.raises(RuntimeError, match="pre-B workspace is unsupported"):
        prepare_and_cutover_coding_package_store_from_legacy(
            lifecycle,
            settings,
            namespace_id="d" * 64,
            minimum_runtime_version="2.0.0",
            minimum_runtime_protocol_epoch=2,
        )

    assert not (epoch.control_root / "epoch.jsonl").exists()


def test_windows_coding_write_cli_refuses_before_first_fence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    epoch = resolve_coding_package_epoch_layout(lifecycle)

    with patch(
        "loushang.coding.cli.package_cutover.resolve_coding_plugin_lifecycle_state_layout",
        return_value=lifecycle,
    ):
        assert cutover_cli_main(("--workspace", str(workspace))) == 1

    assert "requires an admitted candidate" in capsys.readouterr().err
    settings = SettingsManager(
        global_settings_path=tmp_path / "global" / "settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    with pytest.raises(RuntimeError, match="not yet admitted"):
        cutover_and_bootstrap_coding_package_product(
            lifecycle,
            settings,
            workspace=workspace,
            namespace_id="c" * 64,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )
    assert not (epoch.control_root / "epoch.jsonl").exists()


def test_windows_fresh_cutover_bootstraps_builtins_through_candidate_product(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global" / "settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover = cutover_and_bootstrap_coding_package_product(
        lifecycle,
        settings,
        workspace=workspace,
        namespace_id="c" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    assert cutover.attempt.result.disposition == "fenced"
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    try:
        selections = {
            item.installation_key.plugin_id: item.selection.desired_state
            for item in owner.runtime_owner.product_owner.desired_state.snapshot().installations
        }
        assert selections == {
            "coding.base": "installed_enabled",
            "coding.lsp.default": "installed_enabled",
            "coding.arch.default": "installed_enabled",
        }
    finally:
        owner.close()
