"""Internal Product transaction evidence for a default-dark Worker Wheel."""

from __future__ import annotations

import asyncio
import csv
import ctypes
import io
import json
import os
import select
import shutil
import signal
import stat
import subprocess
import sys
import time
import zipfile
from argparse import Namespace
from base64 import urlsafe_b64encode
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import replace
from hashlib import sha256, shake_256
from pathlib import Path
from struct import pack_into
from threading import Event
from types import SimpleNamespace

import pytest

import loushang.coding.package_product_backup_types as backup_types_module
import loushang.coding.package_product_worker_activation_state_journal as activation_state_journal_module
import loushang.coding.package_product_worker_history_retention as history_retention_module
import loushang.coding.package_product_worker_native_install as native_install_module
import loushang.coding.package_product_worker_opt_in as opt_in_journal_module
import loushang.coding.package_product_worker_payload as worker_payload_module
import loushang.coding.package_product_worker_receipt as receipt_journal_module
import loushang.coding.package_product_worker_start_gate_journal as gate_journal_module
import loushang.coding.package_product_worker_start_gate_recovery as gated_recovery_module
import loushang.harness.package_product.product_local_wheel_runtime as local_wheel_runtime_module
import loushang.harness.package_product.product_root_gc_runtime as root_gc_module
import loushang.hosting.service_group as service_group_module
from loushang.agent import Agent
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import UserMessage
from loushang.coding._base_product_composition import (
    compile_coding_base_product_selection,
    extend_coding_base_product_data_resources,
)
from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding._resource_catalog_shadow import (
    build_coding_initial_resource_catalog_adapter,
)
from loushang.coding.bootstrap import (
    create_agent_session,
    create_agent_session_runtime,
    create_services,
)
from loushang.coding.cli.package_worker_native import _execute as execute_native_cli
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.package_external_worker_wheel import (
    CodingExternalWorkerWheelError,
)
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.package_product_preview import (
    CodingFencedProductReadOnlyPreviewOwner,
)
from loushang.coding.package_product_runtime import (
    admit_coding_external_data_wheel,
    admit_coding_external_worker_wheel,
    open_coding_fenced_product_application_owner,
)
from loushang.coding.package_product_worker_activation_state import (
    open_coding_product_worker_activation_state_store,
)
from loushang.coding.package_product_worker_capability import (
    CodingProductWorkerCapabilityAuthority,
    CodingWorkerCapabilityBindingError,
)
from loushang.coding.package_product_worker_discovery import (
    CodingWorkerTranscriptDiscoveryReader,
)
from loushang.coding.package_product_worker_history_retention import (
    review_coding_product_worker_history_retention,
)
from loushang.coding.package_product_worker_installed_native import (
    open_coding_product_installed_worker_release_reader,
)
from loushang.coding.package_product_worker_native_approval import (
    CodingWorkerNativeApprovalError,
    CodingWorkerNativeApprovalJournal,
)
from loushang.coding.package_product_worker_native_install import (
    _verified_wheel_members,
    _write_stage,
    install_coding_product_worker_native_release,
    repair_coding_product_worker_native_release,
    review_coding_product_worker_native_release,
)
from loushang.coding.package_product_worker_native_release import (
    CodingLinuxWorkerReleaseCatalogReader,
    CodingWorkerNativeReleaseError,
)
from loushang.coding.package_product_worker_opt_in import CodingWorkerOptInJournal
from loushang.coding.package_product_worker_opt_in_owner import (
    CodingWorkerProductOptInError,
    CodingWorkerProductOptInOwner,
)
from loushang.coding.package_product_worker_ordinary_bootstrap import (
    prepare_coding_product_worker_ordinary_binding,
)
from loushang.coding.package_product_worker_payload import (
    CodingWorkerPayloadDebtPlanV1,
    CodingWorkerPayloadMaterializationError,
    bind_coding_product_worker_launch_request,
    list_coding_product_worker_payload_debts,
    materialize_coding_product_worker_payload,
    open_coding_product_worker_supervisor_journal,
    plan_coding_product_worker_pending_launch,
    preview_coding_product_worker_empty_payload_debt,
    preview_coding_product_worker_payload_debt,
    reopen_coding_product_worker_empty_payload_repair,
    reopen_coding_product_worker_payload_repair,
    reopen_coding_product_worker_unmarked_payload_repair,
    repair_coding_product_worker_empty_payload_debt,
    repair_coding_product_worker_payload_debt,
    repair_coding_product_worker_unmarked_payload_debt,
    review_coding_product_worker_payload_recovery,
    review_coding_product_worker_unmarked_payload_debt,
)
from loushang.coding.package_product_worker_pending_host import (
    CodingWorkerPendingHostError,
    prepare_coding_product_worker_pending_session_inputs,
)
from loushang.coding.package_product_worker_policy import (
    CodingWorkerNativeClosureReadError,
    CodingWorkerNativeClosureV1,
    CodingWorkerOptInV1,
    CodingWorkerPolicySelectionError,
    coding_worker_session_scope_id,
    derive_coding_selected_worker_policy,
)
from loushang.coding.package_product_worker_posix_gc_history import (
    CodingPosixWorkerGcHistoryAuthority,
)
from loushang.coding.package_product_worker_provider import (
    CodingWorkerBaseCompositionPolicyBinding,
    CodingWorkerProviderCandidateError,
    coding_worker_query_capability_provider,
    prepare_coding_selected_worker_provider_candidate,
)
from loushang.coding.package_product_worker_provider_host import (
    CodingWorkerProviderHostError,
    prepare_coding_worker_provider_binding,
)
from loushang.coding.package_product_worker_query_consumer import (
    CODING_WORKER_QUERY_CAPABILITY_ID,
    CODING_WORKER_QUERY_DEFINITION,
    CODING_WORKER_QUERY_FACET_ID,
    CODING_WORKER_QUERY_OWNER_POLICY_REVISION,
    CODING_WORKER_QUERY_REQUIREMENT,
    bind_coding_worker_query_consumer,
    bind_coding_worker_query_facet_owner,
    coding_worker_query_owner_authority,
)
from loushang.coding.package_product_worker_receipt import (
    CodingWorkerProductReceiptOwner,
    CodingWorkerReceiptError,
    open_coding_product_selected_worker_receipt_owner,
    open_coding_selected_worker_receipt_owner,
    read_coding_product_worker_receipt_record,
)
from loushang.coding.package_product_worker_session_composition import (
    CodingProductWorkerOrdinarySessionBinding,
    CodingWorkerSessionCompositionError,
    compose_coding_product_worker_with_ordinary_session,
    prepare_coding_product_worker_session_inputs,
    validate_coding_product_worker_ordinary_session_inputs,
)
from loushang.coding.package_product_worker_start_gate import (
    CodingProductWorkerStartGate,
)
from loushang.coding.package_product_worker_start_gate_journal import (
    CodingWorkerStartGateJournal,
    CodingWorkerStartGateJournalError,
)
from loushang.coding.package_product_worker_start_gate_recovery import (
    CodingWorkerGatedRecoveryError,
    repair_coding_product_worker_orphan_runtime,
    review_coding_product_worker_gated_recovery,
    review_coding_product_worker_orphan_runtime,
    settle_coding_product_worker_gated_attempt,
)
from loushang.coding.session.agent_session import AgentSession
from loushang.coding.session_manager import SessionManager
from loushang.harness.capabilities import (
    MODEL_INPUT_CAPABILITY_DEFINITION,
    WORKSPACE_CAPABILITY_DEFINITION,
    stage_resource_composition_candidate,
    standard_capability_composition_plan,
)
from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionAuthorityContext,
    ProductCompositionCompiler,
)
from loushang.harness.capabilities.contracts import (
    CapabilityContractRange,
    CapabilityRequirement,
)
from loushang.harness.capabilities.graph_binding import (
    CapabilityGraphBindingError,
    RuntimeCapabilityGraphBinder,
)
from loushang.harness.capabilities.graph_planning import (
    CapabilityGraphPlanRequest,
    RuntimeCapabilityGraphPlanner,
)
from loushang.harness.capabilities.graph_runtime import (
    RuntimeCapabilityGraphRuntime,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderOwnerAuthority,
    CapabilityWorkerProviderBindingSpec,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
    CapabilityBundleValue,
    CapabilityFacetBinding,
)
from loushang.harness.capabilities.provider_selection import (
    ProductCapabilityProviderChoice,
    ProductCapabilityProviderResolver,
    ProductCapabilityProviderSelectionPlanV1,
)
from loushang.harness.capabilities.providers import CapabilityBundleProvider
from loushang.harness.capabilities.workspace_provider import (
    workspace_capability_provider_binding,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.conversation import ConversationHeader
from loushang.harness.environment import LocalHostEnvironmentProbe
from loushang.harness.extensions.agent import ExtensionRunner
from loushang.harness.extensions.context import ExtensionRuntimeBindings
from loushang.harness.journal import JournalFileError
from loushang.harness.package_product.product_gc_executor import (
    PackageProductGcExecutionError,
    PackageProductRootGcCommandV1,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_root_gc_runtime import (
    open_posix_local_wheel_product_root_gc,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1,
)
from loushang.harness.package_product.product_worker_candidate import (
    verify_product_selected_worker_candidate,
)
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationError,
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.package_gc_target import (
    resolve_plugin_package_gc_root_target,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources._catalog_input_receipt import (
    ResourceCatalogInputReceipt,
)
from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
    PackageEpochRuntimeLeaseRegistryError,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_materialization import (
    PackagePhysicalStagingError,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreSettlementJournal,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleIntentV1,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
    PackageProductLocalWheelDependencyV1,
    PackageProductLocalWorkerAdmissionV1,
)
from loushang.harness.resources.plugins.declarations import (
    PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION,
    PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION,
    PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION,
    PluginContributionIndex,
    PluginContributionReservation,
    PluginDeclaration,
    PluginDeclarationDocument,
    PluginDeclarationDocumentCodec,
    PluginDeclarationSource,
    PluginLocalWorkerConfiguration,
)
from loushang.harness.resources.plugins.engine import required_plugin_engine_features
from loushang.harness.runtime import RuntimeProfileResolver
from loushang.harness.session import AgentProductSession
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
)
from loushang.harness.tools.workspace import LOCAL_TOOL_OPERATIONS
from loushang.harness.transcript import (
    AgentTranscriptDirectoryRuntime,
    write_agent_transcript_export,
)
from loushang.harness.transcript.discovery import (
    SessionDiscoveryMetadata,
    SessionLocator,
)
from loushang.harness.worker._native_profile_bridge import (
    _bind_posix_static_contained_product_worker_profile,
)
from loushang.harness.worker.activation_state_journal import (
    WorkerActivationStateJournalError,
)
from loushang.harness.worker.capability_query import (
    CapabilityQueryWorkerAdapter,
    CapabilityWorkerAuthorityV1,
    CapabilityWorkerBindingV1,
    bind_capability_query_worker_adapter,
)
from loushang.harness.worker.contracts import (
    WorkerBindingError,
    WorkerLaunchIdentityV1,
)
from loushang.harness.worker.facet_proxy import (
    CapabilityWorkerFacetProxyError,
    CapabilityWorkerReadOnlyFacetProxy,
)
from loushang.harness.worker.gated_start import (
    bind_worker_gated_start_release,
    worker_native_group_absent_after_restart,
    worker_native_group_status_after_restart,
)
from loushang.harness.worker.hosting_adapter import (
    HostingManagedWorkerSessionAdapter,
    _map_worker_request,
    _worker_launch_preparation_port,
)
from loushang.harness.worker.journal import (
    WorkerSupervisorJournal,
    WorkerSupervisorJournalError,
)
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationCoordinator,
    WorkerCleanupSettlementV1,
    _AttemptKey,
    _initial_state,
)
from loushang.harness.worker.supervisor import WorkerSupervisor, WorkerSupervisorError
from loushang.hosting import ChildSessionRequest
from loushang.hosting._posix_launch_preparation import (
    _PosixStaticContainedLaunchCaptureSpec,
    _PosixStaticLaunchCaptureBackend,
)
from loushang.plugin._coding_local_worker_wheel import (
    build_coding_local_worker_candidate_wheel,
    write_coding_local_worker_candidate_wheel,
)
from tests.coding.test_package_external_data_wheel import _data_wheel
from tests.coding.test_package_product_worker_activation_segments import (
    _next_state,
    _registered_attempt,
)
from tests.harness.worker.test_product_activation import _CleanupEvidenceOwner
from tests.hosting.test_posix_launch_preparation import _native_host

_PLUGIN = "reviewworker"
_VERSION = "1"
_CONTRIBUTION = "query-provider"
_OWNER = "coding"
_TAG = "py3-none-manylinux_2_17_x86_64"
_H6_BUILDER = (
    Path(__file__).resolve().parents[2]
    / "scripts/dev/build_posix_containment_launcher.py"
)
_H6_WHEEL_BUILDER = (
    Path(__file__).resolve().parents[2]
    / "scripts/dev/build_posix_native_release_wheel.py"
)
_QUERY_WORKER_SOURCE = (
    Path(__file__).resolve().parents[1] / "fixtures/worker/contained_query_worker.c"
)


def _run_independent_product_worker_crash(
    workspace_path: str,
    transcript_path: str,
    attempt_id: str,
) -> None:
    """Open a fresh Product process and exit after its gated Worker starts."""

    workspace = Path(workspace_path)
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    application = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        worker_candidates=True,
    )
    product = application.runtime_owner.product_owner
    runtime = product.factory_for_session(
        session_id="worker-catalog",
        cwd=workspace,
        runtime_id="worker-independent-crash",
    ).create(
        PackageProductRuntimeRequestV1(
            product_id="coding", session_id="worker-catalog", cwd=str(workspace)
        )
    )
    runtime.activate()
    transcript_file = Path(transcript_path)
    session_manager = asyncio.run(SessionManager.load(transcript_file))
    receipt_owner = open_coding_product_selected_worker_receipt_owner(
        product_owner=product,
        runtime=runtime,
        plugin_id=_PLUGIN,
        transcript_directory=AgentTranscriptDirectoryRuntime(
            session_dir=transcript_file.parent
        ),
        session_manager=session_manager,
    )
    receipt = receipt_owner.issue()
    assert receipt is not None
    with materialize_coding_product_worker_payload(
        receipt_owner=receipt_owner,
        receipt=receipt,
        attempt_id=attempt_id,
    ) as payload:
        request = bind_coding_product_worker_launch_request(
            receipt_owner=receipt_owner,
            receipt=receipt,
            payload_lease=payload,
            supervisor_epoch=1,
        )
        journal = open_coding_product_worker_supervisor_journal(product)
        claimed = journal.claim(request.identity, max_attempts=3)
        journal.transition(
            attempt_id,
            expected_phase="claimed",
            next_phase="launching",
            expected_record_revision=claimed.record_revision,
            expected_supervisor_epoch=1,
        )
        gate = CodingProductWorkerStartGate(
            receipt_owner=receipt_owner,
            receipt=receipt,
            worker_request=request,
            attempt_id=attempt_id,
        )
        material = receipt_owner.current_native_launch_material(receipt)
        profile = _bind_posix_static_contained_product_worker_profile(
            receipt=receipt,
            worker_request=request,
            native_profile_catalog_revision=(
                material.closure.native_profile_catalog_revision
            ),
            launcher_path=material.launcher_path,
            launcher_sha256=material.closure.containment_launcher_digest,
            containment_profile_sha256=material.closure.containment_profile_digest,
            start_gate_read_fd=gate.start_gate_read_fd,
        )

        async def start_and_crash() -> None:
            host = _native_host(max_capture_slots=4)
            adapter = HostingManagedWorkerSessionAdapter(
                hosting=host,
                preparation=profile,
                start_gate=bind_worker_gated_start_release(gate),
            )
            await adapter.start(request, correlation_id="independent-product-crash")
            os._exit(0)

        asyncio.run(start_and_crash())
    raise AssertionError("Independent Product Worker crash did not exit")


@pytest.mark.parametrize(
    "native_mode",
    (
        "test-facts",
        pytest.param(
            "built-release",
            marks=(
                pytest.mark.requires_host_runtime,
                pytest.mark.skipif(sys.platform != "linux", reason="Linux H6 release"),
            ),
        ),
        pytest.param(
            "installed-release",
            marks=(
                pytest.mark.requires_host_runtime,
                pytest.mark.skipif(sys.platform != "linux", reason="Linux H6 release"),
            ),
        ),
        pytest.param(
            "repaired-release",
            marks=(
                pytest.mark.requires_host_runtime,
                pytest.mark.skipif(sys.platform != "linux", reason="Linux H6 release"),
            ),
        ),
        pytest.param(
            "installed-protocol",
            marks=(
                pytest.mark.requires_host_runtime,
                pytest.mark.skipif(sys.platform != "linux", reason="Linux H6 release"),
            ),
        ),
        pytest.param(
            "installed-graph-failure",
            marks=(
                pytest.mark.requires_host_runtime,
                pytest.mark.skipif(sys.platform != "linux", reason="Linux H6 release"),
            ),
        ),
        pytest.param(
            "installed-revocation",
            marks=(
                pytest.mark.requires_host_runtime,
                pytest.mark.skipif(sys.platform != "linux", reason="Linux H6 release"),
            ),
        ),
        pytest.param(
            "installed-expiry",
            marks=(
                pytest.mark.requires_host_runtime,
                pytest.mark.skipif(sys.platform != "linux", reason="Linux H6 release"),
            ),
        ),
    ),
)
def test_worker_source_catalog_pins_explicit_product_candidate(
    tmp_path: Path,
    native_mode: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    protocol_queries: int = 1,
    direct_entry_only: bool = False,
    hosted_entry_only: bool = False,
    disable_while_direct_session_open: bool = False,
    update_while_direct_session_open: bool = False,
) -> None:
    assert not disable_while_direct_session_open or direct_entry_only
    assert not update_while_direct_session_open or direct_entry_only
    assert not (disable_while_direct_session_open and update_while_direct_session_open)
    installed_native = native_mode in {
        "installed-release",
        "repaired-release",
        "installed-protocol",
        "installed-graph-failure",
        "installed-revocation",
        "installed-expiry",
    }
    has_native_release = native_mode == "built-release" or installed_native
    protocol_worker = native_mode in {
        "installed-protocol",
        "installed-graph-failure",
        "installed-revocation",
        "installed-expiry",
    }
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    if native_mode == "repaired-release" or direct_entry_only or hosted_entry_only:
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
        if direct_entry_only or hosted_entry_only:
            monkeypatch.setattr(
                "loushang.coding.package_product_runtime.version",
                lambda _distribution: "2.0.0",
            )
        lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    else:
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
        namespace_id="a" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    source = tmp_path / f"{_PLUGIN}-{_VERSION}-{_TAG}.whl"
    if protocol_worker:
        compiler = shutil.which("cc")
        assert compiler is not None, "Linux H6 native gate requires a C compiler"
        executable = tmp_path / "contained-query-worker"
        built_worker = subprocess.run(
            (
                compiler,
                "-static",
                "-O2",
                "-s",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-o",
                str(executable),
                str(_QUERY_WORKER_SOURCE),
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        assert built_worker.returncode == 0, built_worker.stderr
        payload = build_coding_local_worker_candidate_wheel(
            plugin_id=_PLUGIN,
            version=_VERSION,
            contribution_id=_CONTRIBUTION,
            owner_id=_OWNER,
            native_platform="linux-x86_64",
            wheel_tag=_TAG,
            executable=executable.read_bytes(),
        )
    else:
        payload = _worker_wheel(linger=has_native_release)
    source.write_bytes(payload)
    admission = PackageProductLocalWorkerAdmissionV1(
        contribution_id=_CONTRIBUTION,
        owner_id=_OWNER,
        native_platform="linux-x86_64",
    )
    record = admit_coding_external_worker_wheel(
        lifecycle, source=source, admission=admission
    )
    assert record.artifact_digest == sha256(payload).hexdigest()
    assert (
        admit_coding_external_worker_wheel(
            lifecycle, source=source, admission=admission
        )
        == record
    )
    with pytest.raises(CodingExternalWorkerWheelError):
        admit_coding_external_worker_wheel(
            lifecycle,
            source=source,
            admission=replace(admission, owner_id="coding.other"),
        )
    ordinary = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        ordinary_product = ordinary.runtime_owner.product_owner
        with pytest.raises(ValueError, match="candidate owner is required"):
            open_coding_product_installed_worker_release_reader(ordinary_product)
        assert not any(
            item.source_trust_class == "local-worker-candidate"
            for item in ordinary_product.policy.bindings
        )
        ordinary_runtime = ordinary_product.factory_for_session(
            session_id="worker-ordinary", cwd=workspace, runtime_id="worker-ordinary"
        ).create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id="worker-ordinary", cwd=str(workspace)
            )
        )
        try:
            ordinary_runtime.activate()
            refused = ordinary_runtime.lifecycle.route(
                PackageProductLifecycleIntentV1(
                    operation_id="worker-ordinary-install",
                    action="install",
                    source=record.policy_binding(
                        ordinary_product.policy.source_root
                    ).source_identity,
                    scope="project",
                ),
                entrypoint="cli",
            )
            assert refused.handled
            assert refused.record is not None
            assert refused.record.lifecycle == "failed"
            assert (
                refused.record.failure_code
                == "package_target_classification_indeterminate"
            )
            assert not any(
                item.installation_key.plugin_id == _PLUGIN
                for item in ordinary_product.desired_state.snapshot().installations
            )
        finally:
            ordinary_runtime.dispose_runtime()
    finally:
        ordinary.close()
    if native_mode == "installed-protocol":
        data_source = tmp_path / "reviewpack-1-py3-none-any.whl"
        data_source.write_bytes(_data_wheel(skill_name="worker-extra"))
        admit_coding_external_data_wheel(lifecycle, source=data_source)
    explicit = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        worker_candidates=True,
    )
    try:
        product = explicit.runtime_owner.product_owner
        approval_reader = CodingWorkerNativeApprovalJournal(product)
        approval_lock = product.state_root / "worker-native-release-approvals.jsonl.lock"
        with product.gc_gate.read_snapshot_guard():
            assert approval_reader.current() is None
            assert not approval_reader.path.exists() and not approval_lock.exists()
        if native_mode == "test-facts":
            activation_state = open_coding_product_worker_activation_state_store(
                product
            )
            assert activation_state.path == (
                product.state_root / "worker-activation-state.jsonl"
            )
            with product.gc_gate.guard():
                assert activation_state.load() is None
        (binding,) = tuple(
            item
            for item in product.policy.bindings
            if item.source_trust_class == "local-worker-candidate"
        )
        assert binding == record.policy_binding(product.policy.source_root)
        controlled = Path(binding.source_identity)
        assert controlled.read_bytes() == payload
        source.write_bytes(b"changed original source")
        runtime = product.factory_for_session(
            session_id="worker-catalog", cwd=workspace, runtime_id="worker-catalog"
        ).create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id="worker-catalog", cwd=str(workspace)
            )
        )
        try:
            runtime.activate()
            installed = runtime.lifecycle.route(
                PackageProductLifecycleIntentV1(
                    operation_id="worker-catalog-install",
                    action="install",
                    source=binding.source_identity,
                    scope="project",
                ),
                entrypoint="cli",
            )
            assert installed.handled
            assert installed.record is not None
            assert installed.record.lifecycle == "installed"
            if native_mode == "installed-protocol":
                (data_binding,) = tuple(
                    item
                    for item in product.policy.bindings
                    if item.plugin_id == "reviewpack"
                )
                data_installed = runtime.lifecycle.route(
                    PackageProductLifecycleIntentV1(
                        operation_id="worker-catalog-install-data",
                        action="install",
                        source=data_binding.source_identity,
                        scope="project",
                    ),
                    entrypoint="cli",
                )
                assert data_installed.handled
                assert data_installed.record is not None
                assert data_installed.record.lifecycle == "installed"
                (data_installation,) = tuple(
                    item
                    for item in product.desired_state.snapshot().installations
                    if item.installation_key.plugin_id == "reviewpack"
                )
                data_enabled = product.management.submit(
                    PluginManagementCommandV1(
                        action="enable",
                        mutation=PluginDesiredStateMutationV1(
                            operation_id="worker-catalog-enable-data",
                            idempotency_key="worker-catalog-enable-data",
                            expected_inventory_revision=(
                                product.desired_state.snapshot().inventory_revision
                            ),
                            installation_key=data_installation.installation_key,
                            desired_state="installed_enabled",
                            package_revision=None,
                            actor_id=product.actor_id,
                            policy_revision=product.desired_policy_revision,
                        ),
                    )
                )
                assert data_enabled.status == "terminal"
            installations = tuple(
                item
                for item in product.desired_state.snapshot().installations
                if item.installation_key.plugin_id == _PLUGIN
            )
            assert len(installations) == 1
            assert installations[0].selection.desired_state == "installed_disabled"
            test_closure = CodingWorkerNativeClosureV1(
                native_platform="linux-x86_64",
                native_profile_catalog_revision="native-catalog:1",
                containment_launcher_digest=sha256(b"launcher").hexdigest(),
                containment_profile_digest=sha256(b"containment").hexdigest(),
            )
            release = tmp_path / "h6-release"
            if has_native_release:
                built = subprocess.run(
                    (sys.executable, str(_H6_BUILDER), "--output-dir", str(release)),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                    check=False,
                )
                assert built.returncode == 0, built.stderr
            if native_mode == "built-release":
                native_reader = CodingLinuxWorkerReleaseCatalogReader(
                    release_root=release, gc_gate=product.gc_gate
                )
            elif installed_native:
                packaged = subprocess.run(
                    (
                        sys.executable,
                        str(_H6_WHEEL_BUILDER),
                        "--release-dir",
                        str(release),
                        "--wheel-dir",
                        str(tmp_path / "h6-wheels"),
                    ),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                    check=False,
                )
                assert packaged.returncode == 0, packaged.stderr
                native_wheel_path = Path(packaged.stdout.decode().strip())
                native_wheel = native_wheel_path.read_bytes()
                review = review_coding_product_worker_native_release(
                    product, wheel=native_wheel
                )
                native_approval = review.approval
                assert review.scope_id == product.policy.project_scope_id
                assert native_approval.wheel_sha256 == sha256(native_wheel).hexdigest()
                assert review.review_id == (
                    review_coding_product_worker_native_release(
                        product, wheel=native_wheel
                    ).review_id
                )
                assert execute_native_cli(
                    product,
                    Namespace(action="review", wheel=str(native_wheel_path)),
                ) == {"nativeReleaseReview": review.to_dict()}
                approval_owner = CodingWorkerNativeApprovalJournal(product)
                with pytest.raises(
                    CodingWorkerNativeReleaseError,
                    match="approval is not current",
                ):
                    install_coding_product_worker_native_release(
                        product,
                        approval_owner=approval_owner,
                        approved=native_approval,
                        wheel=native_wheel,
                    )
                with pytest.raises(ValueError, match="review changed"):
                    execute_native_cli(
                        product,
                        Namespace(
                            action="approve",
                            wheel=str(native_wheel_path),
                            review_id="0" * 64,
                            operation_id="approve-native-release-one",
                            expected_generation=0,
                        ),
                    )
                assert approval_owner.current() is None
                assert (
                    execute_native_cli(
                        product,
                        Namespace(
                            action="approve",
                            wheel=str(native_wheel_path),
                            review_id=review.review_id,
                            operation_id="approve-native-release-one",
                            expected_generation=0,
                        ),
                    )["approvalDecision"]
                    == approval_owner.current().to_dict()
                )
                approved_release = approval_owner.current()
                assert approved_release is not None
                assert approval_owner.current() == approved_release
                if native_mode == "installed-release":
                    assert (
                        approval_owner.change(
                            operation_id="approve-native-release-one",
                            expected_generation=0,
                            action="approve",
                            approval=native_approval,
                        )
                        == approved_release
                    )
                    with pytest.raises(CodingWorkerNativeApprovalError) as conflict:
                        approval_owner.change(
                            operation_id="approve-native-release-one",
                            expected_generation=0,
                            action="approve",
                            approval=replace(native_approval, wheel_sha256="0" * 64),
                        )
                    assert conflict.value.code == (
                        "coding_worker_native_approval_operation_conflict"
                    )
                    with pytest.raises(CodingWorkerNativeApprovalError) as stale:
                        approval_owner.change(
                            operation_id="approve-native-release-stale",
                            expected_generation=0,
                            action="approve",
                            approval=native_approval,
                        )
                    assert stale.value.code == "coding_worker_native_approval_stale"
                    approval_bytes = approval_owner.path.read_bytes()
                    retained_approval = (
                        product.state_root / "retained-native-approval.jsonl"
                    )
                    approval_owner.path.rename(retained_approval)
                    approval_owner.path.symlink_to(retained_approval)
                    try:
                        with pytest.raises(OSError):
                            approval_owner.current()
                        assert retained_approval.read_bytes() == approval_bytes
                    finally:
                        approval_owner.path.unlink()
                        retained_approval.rename(approval_owner.path)
                    with approval_owner.path.open("ab") as handle:
                        handle.write(b"{")
                    with pytest.raises(JournalFileError):
                        approval_owner.current()
                    approval_owner.path.write_bytes(approval_bytes)
                interrupted_stage = (
                    product.state_root / ".worker-native-release-stage-interrupted"
                )
                interrupted_stage.mkdir(mode=0o700)
                with pytest.raises(
                    CodingWorkerNativeReleaseError,
                    match="unsettled staging debt",
                ):
                    install_coding_product_worker_native_release(
                        product,
                        approval_owner=approval_owner,
                        approved=native_approval,
                        wheel=native_wheel,
                    )
                with pytest.raises(CodingWorkerNativeReleaseError):
                    repair_coding_product_worker_native_release(
                        product, approval_owner=approval_owner, approved=native_approval
                    )
                assert not (product.state_root / "worker-native-release-v1").exists()
                interrupted_stage.rmdir()
                if native_mode == "repaired-release":
                    complete_stage = (
                        product.state_root / ".worker-native-release-stage-complete"
                    )
                    complete_stage.mkdir(mode=0o700)
                    _write_stage(
                        complete_stage,
                        _verified_wheel_members(native_wheel),
                        native_wheel,
                        native_approval,
                        product,
                    )
                    moved_stage = product.state_root / "held-stage"
                    original_verify = native_install_module.verify_coding_product_native_release_descriptor

                    def replace_stage_after_verify(
                        root: int, owner: PosixLocalWheelProductSessionOwner
                    ) -> tuple[CodingWorkerNativeClosureV1, dict[str, object]]:
                        result = original_verify(root, owner)
                        complete_stage.rename(moved_stage)
                        complete_stage.symlink_to(moved_stage, target_is_directory=True)
                        return result

                    with monkeypatch.context() as patch:
                        patch.setattr(
                            native_install_module,
                            "verify_coding_product_native_release_descriptor",
                            replace_stage_after_verify,
                        )
                        with pytest.raises(
                            CodingWorkerNativeReleaseError,
                            match="staged root changed",
                        ):
                            repair_coding_product_worker_native_release(
                                product,
                                approval_owner=approval_owner,
                                approved=native_approval,
                            )
                    assert not (
                        product.state_root / "worker-native-release-v1"
                    ).exists()
                    complete_stage.unlink()
                    moved_stage.rename(complete_stage)
                    native_reader = repair_coding_product_worker_native_release(
                        product, approval_owner=approval_owner, approved=native_approval
                    )
                    assert not complete_stage.exists()
                else:
                    native_reader = install_coding_product_worker_native_release(
                        product,
                        approval_owner=approval_owner,
                        approved=native_approval,
                        wheel=native_wheel,
                    )
                installation_root = product.state_root / "worker-native-release-v1"
                assert (
                    install_coding_product_worker_native_release(
                        product,
                        approval_owner=approval_owner,
                        approved=native_approval,
                        wheel=native_wheel,
                    ).current_closure()
                    == native_reader.current_closure()
                )
                if native_mode == "installed-release":
                    assert execute_native_cli(
                        product,
                        Namespace(action="install", wheel=str(native_wheel_path)),
                    ) == {"nativeClosure": native_reader.current_closure().to_dict()}
                with pytest.raises(ValueError, match="does not match Wheel"):
                    install_coding_product_worker_native_release(
                        product,
                        approval_owner=approval_owner,
                        approved=native_approval,
                        wheel=native_wheel + b"changed",
                    )
            else:
                native_reader = _ProductNativeClosureReader(
                    product.gc_gate, test_closure
                )
            expected_native_closure = native_reader.current_closure()
            if installed_native:
                launch_material = native_reader.current_launch_material()
                assert launch_material.closure == expected_native_closure
                assert launch_material.launcher_path == (
                    installation_root
                    / "loushang_h6_native/release/containment-launcher"
                )
                assert launch_material.launcher_path.is_file()
            transcript_root = tmp_path / "catalog-transcripts"
            transcript_root.mkdir()
            session_manager = asyncio.run(
                SessionManager.new(
                    session_dir=transcript_root,
                    cwd=str(workspace),
                    session_id="worker-catalog",
                )
            )
            transcript_directory = AgentTranscriptDirectoryRuntime(
                session_dir=transcript_root
            )
            with pytest.raises(ValueError, match="selected Session owner changed"):
                open_coding_selected_worker_receipt_owner(
                    product_owner=product,
                    runtime=runtime,
                    plugin_id=_PLUGIN,
                    native_closure_reader=native_reader,
                    transcript_directory=transcript_directory,
                    session_manager=session_manager,
                )
            asyncio.run(
                session_manager.append_message(
                    UserMessage(role="user", content="Worker candidate", timestamp=1.0)
                )
            )
            selected_transcript = session_manager.get_session_file()
            assert selected_transcript is not None
            assert session_manager.is_persisted()
            with pytest.raises(ValueError, match="runtime owners changed"):
                open_coding_selected_worker_receipt_owner(
                    product_owner=ordinary_product,
                    runtime=runtime,
                    plugin_id=_PLUGIN,
                    native_closure_reader=native_reader,
                    transcript_directory=transcript_directory,
                    session_manager=session_manager,
                )
            with pytest.raises(PackageProductRuntimeReadError):
                open_coding_selected_worker_receipt_owner(
                    product_owner=product,
                    runtime=runtime,
                    plugin_id=_PLUGIN,
                    native_closure_reader=native_reader,
                    transcript_directory=transcript_directory,
                    session_manager=session_manager,
                )
            with pytest.raises(CodingWorkerProductOptInError) as disabled_opt_in:
                CodingWorkerProductOptInOwner(product).allow(
                    plugin_id=_PLUGIN,
                    operation_id="worker-disabled-allow",
                    expected_generation=0,
                    require_worker=False,
                )
            assert disabled_opt_in.value.code == (
                "coding_worker_opt_in_selection_unavailable"
            )
            enabled = product.management.submit(
                PluginManagementCommandV1(
                    action="enable",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id="worker-catalog-enable",
                        idempotency_key="worker-catalog-enable",
                        expected_inventory_revision=product.desired_state.snapshot().inventory_revision,
                        installation_key=installations[0].installation_key,
                        desired_state="installed_enabled",
                        package_revision=None,
                        actor_id=product.actor_id,
                        policy_revision=product.desired_policy_revision,
                    ),
                )
            )
            assert enabled.status == "terminal"
            selected = runtime.capture_selected_plugin_manifest_for(
                _PLUGIN, max_files=16, max_total_bytes=16 * 1024 * 1024
            )
            opt_in_journal = CodingWorkerOptInJournal(
                product.state_root / "worker-opt-in.jsonl",
                scope_id=product.policy.project_scope_id,
                gc_gate=product.gc_gate,
            )
            if not installed_native:
                with pytest.raises(CodingWorkerNativeReleaseError):
                    open_coding_product_selected_worker_receipt_owner(
                        product_owner=product,
                        runtime=runtime,
                        plugin_id=_PLUGIN,
                        transcript_directory=transcript_directory,
                        session_manager=session_manager,
                    )
                with pytest.raises(CodingWorkerNativeReleaseError):
                    CodingWorkerProductOptInOwner(product).allow(
                        plugin_id=_PLUGIN,
                        operation_id="worker-no-native-allow",
                        expected_generation=0,
                        require_worker=False,
                    )
                assert opt_in_journal.current(_PLUGIN) is None
            if installed_native:
                receipt_owner = open_coding_product_selected_worker_receipt_owner(
                    product_owner=product,
                    runtime=runtime,
                    plugin_id=_PLUGIN,
                    transcript_directory=transcript_directory,
                    session_manager=session_manager,
                )
            else:
                receipt_owner = open_coding_selected_worker_receipt_owner(
                    product_owner=product,
                    runtime=runtime,
                    plugin_id=_PLUGIN,
                    native_closure_reader=native_reader,
                    transcript_directory=transcript_directory,
                    session_manager=session_manager,
                )
            assert receipt_owner.issue() is None
            if installed_native:
                product_opt_in = CodingWorkerProductOptInOwner(product)
                assert execute_native_cli(
                    product,
                    Namespace(action="candidate-status", plugin_id=_PLUGIN),
                ) == {
                    "candidateOptInDecision": None,
                    "ordinarySessionRouting": "python_sdk_explicit_linux",
                    "defaultSessionRouting": "closed",
                }
                with pytest.raises(CodingWorkerProductOptInError) as missing:
                    product_opt_in.allow(
                        plugin_id="coding.missing",
                        operation_id="worker-missing-allow",
                        expected_generation=0,
                        require_worker=False,
                    )
                assert missing.value.code == (
                    "coding_worker_opt_in_candidate_unavailable"
                )
                allowed_output = execute_native_cli(
                    product,
                    Namespace(
                        action="candidate-allow",
                        plugin_id=_PLUGIN,
                        operation_id="worker-catalog-allow",
                        expected_generation=0,
                        require_worker=False,
                    ),
                )
                decision = product_opt_in.current(_PLUGIN)
                assert decision is not None
                assert allowed_output == {
                    "candidateOptInDecision": decision.to_dict(),
                    "ordinarySessionRouting": "python_sdk_explicit_linux",
                    "defaultSessionRouting": "closed",
                }
                assert decision.opt_in is not None
                assert decision.opt_in.artifact_digest == (
                    selected.snapshot.root_ref.artifact_digest
                )
                assert decision.opt_in.owner_id == _OWNER
                assert product_opt_in.current(_PLUGIN) == decision
                if direct_entry_only:
                    with CodingFencedProductReadOnlyPreviewOwner.open(
                        lifecycle
                    ) as read_owner:
                        assert read_owner.worker_opt_in_decision(_PLUGIN) == decision
                        with pytest.raises(PermissionError):
                            read_owner.selected_worker_candidate(_PLUGIN)
                    with CodingFencedProductReadOnlyPreviewOwner.open(
                        lifecycle, worker_candidates=True
                    ) as read_worker_owner:
                        observed = read_worker_owner.selected_worker_candidate(
                            _PLUGIN
                        )
                        assert observed.plugin_version == _VERSION
                        assert observed.executable_digest == sha256(
                            executable.read_bytes()
                        ).hexdigest()
                assert execute_native_cli(
                    product,
                    Namespace(action="candidate-status", plugin_id=_PLUGIN),
                ) == {
                    "candidateOptInDecision": decision.to_dict(),
                    "ordinarySessionRouting": "python_sdk_explicit_linux",
                    "defaultSessionRouting": "closed",
                }
                assert (
                    product_opt_in.allow(
                        plugin_id=_PLUGIN,
                        operation_id="worker-catalog-allow",
                        expected_generation=0,
                        require_worker=False,
                    )
                    == decision
                )
                with pytest.raises(CodingWorkerProductOptInError) as conflict:
                    product_opt_in.allow(
                        plugin_id=_PLUGIN,
                        operation_id="worker-catalog-allow",
                        expected_generation=0,
                        require_worker=True,
                    )
                assert conflict.value.code == (
                    "coding_worker_opt_in_operation_conflict"
                )
            else:
                opt_in_journal.change(
                    plugin_id=_PLUGIN,
                    operation_id="worker-catalog-allow",
                    expected_generation=0,
                    action="allow",
                    opt_in=CodingWorkerOptInV1(
                        plugin_id=_PLUGIN,
                        contribution_id=_CONTRIBUTION,
                        owner_id=_OWNER,
                        artifact_digest=selected.snapshot.root_ref.artifact_digest,
                        native_platform="linux-x86_64",
                        owner_selection_generation=1,
                        kill_switch_generation=0,
                        require_worker=False,
                    ),
                )
            different_transcript = transcript_root / "different.jsonl"
            different_transcript.write_bytes(selected_transcript.read_bytes())
            different_manager = asyncio.run(SessionManager.load(different_transcript))
            wrong_file_owner = open_coding_selected_worker_receipt_owner(
                product_owner=product,
                runtime=runtime,
                plugin_id=_PLUGIN,
                native_closure_reader=native_reader,
                transcript_directory=transcript_directory,
                session_manager=different_manager,
            )
            with pytest.raises(CodingWorkerPolicySelectionError) as wrong_file:
                wrong_file_owner.issue()
            assert wrong_file.value.code == "coding_worker_session_discovery_conflict"
            receipt = receipt_owner.issue()
            assert receipt is not None
            assert receipt.policy.session_route == "selected"
            assert runtime.session_id is not None
            assert receipt.policy.product_scope_id == coding_worker_session_scope_id(
                runtime.session_id
            )
            assert receipt_owner.current_witness(receipt) == receipt.authority_witness
            if native_mode == "test-facts":
                evidence_owner = _CleanupEvidenceOwner(receipt)
                coordinator = ProductWorkerActivationCoordinator(
                    authority=receipt_owner,
                    evidence_authority=evidence_owner,
                    trusted_evidence_authority_id=evidence_owner.authority_id,
                    trusted_evidence_authority_fingerprint=(
                        evidence_owner.authority_fingerprint
                    ),
                    state_store=activation_state,
                )
                initial_state = _initial_state(restart_budget=3)
                assert coordinator.snapshot() == initial_state
                reopened_coordinator = ProductWorkerActivationCoordinator(
                    authority=receipt_owner,
                    evidence_authority=evidence_owner,
                    trusted_evidence_authority_id=evidence_owner.authority_id,
                    trusted_evidence_authority_fingerprint=(
                        evidence_owner.authority_fingerprint
                    ),
                    state_store=open_coding_product_worker_activation_state_store(
                        product
                    ),
                )
                assert reopened_coordinator.snapshot() == initial_state
                monkeypatch.setattr(
                    activation_state_journal_module, "_MAX_REVISIONS", 1
                )
                second_state = dict(initial_state)
                second_state["stateRevision"] = 2
                assert activation_state.compare_and_swap(
                    expected_revision=1, document=second_state
                )
                assert (
                    open_coding_product_worker_activation_state_store(product).load()
                    == second_state
                )
                assert (
                    product.state_root / "worker-activation-state.segments.json"
                ).is_file()
            if installed_native:
                assert (
                    receipt_owner.current_native_launch_material(receipt)
                    == launch_material
                )
                selected_payload = receipt_owner.current_selected_payload(receipt)
                assert (
                    selected_payload.digest == sha256(selected_payload.body).hexdigest()
                )
                assert selected_payload.configuration.fingerprint == (
                    receipt.policy.worker_configuration_fingerprint
                )
                selected_root = (
                    product.plugin_store_root
                    / f"revision-{selected.snapshot.root_ref.ref_id}"
                )
                manifest_root = selected.manifest.root_relative_path.as_posix()
                stored_payload = selected_root / (
                    selected_payload.configuration.entrypoint
                    if manifest_root == "."
                    else f"{manifest_root}/{selected_payload.configuration.entrypoint}"
                )
                assert stat.S_IMODE(stored_payload.stat().st_mode) == 0o600
                stored_payload.write_bytes(b"changed Store payload")
                with pytest.raises(CodingWorkerReceiptError) as changed_payload:
                    receipt_owner.current_selected_payload(receipt)
                assert (
                    changed_payload.value.code == "coding_worker_selected_payload_stale"
                )
                stored_payload.write_bytes(selected_payload.body)
                assert (
                    receipt_owner.current_selected_payload(receipt) == selected_payload
                )
                attempt_id = "ab" * 16
                pending_launch = plan_coding_product_worker_pending_launch(
                    receipt_owner=receipt_owner,
                    receipt=receipt,
                    attempt_id=attempt_id,
                )
                assert pending_launch.receipt_fingerprint == receipt.fingerprint
                assert pending_launch.identity.attempt_id == attempt_id
                assert not (
                    product.state_root / f"worker-payload-{attempt_id}"
                ).exists()
                with materialize_coding_product_worker_payload(
                    receipt_owner=receipt_owner,
                    receipt=receipt,
                    attempt_id=attempt_id,
                ) as payload_lease:
                    assert payload_lease.attempt_id == attempt_id
                    assert payload_lease.receipt_fingerprint == receipt.fingerprint
                    assert payload_lease.native_material == launch_material
                    assert payload_lease.runtime.executable_digest == (
                        selected_payload.digest
                    )
                    assert payload_lease.runtime.executable.read_bytes() == (
                        selected_payload.body
                    )
                    assert (
                        stat.S_IMODE(payload_lease.runtime.executable.stat().st_mode)
                        == 0o500
                    )
                    payload_lease.runtime.verify()
                    with pytest.raises(
                        CodingWorkerPayloadMaterializationError,
                        match="coding_worker_payload_pending_launch_changed",
                    ):
                        bind_coding_product_worker_launch_request(
                            receipt_owner=receipt_owner,
                            receipt=receipt,
                            payload_lease=payload_lease,
                            supervisor_epoch=pending_launch.identity.supervisor_epoch,
                            pending_launch=replace(
                                pending_launch,
                                identity=replace(
                                    pending_launch.identity,
                                    attempt_id="cd" * 16,
                                ),
                            ),
                        )
                    worker_request = bind_coding_product_worker_launch_request(
                        receipt_owner=receipt_owner,
                        receipt=receipt,
                        payload_lease=payload_lease,
                        supervisor_epoch=pending_launch.identity.supervisor_epoch,
                        pending_launch=pending_launch,
                    )
                    assert worker_request.identity == pending_launch.identity
                    assert worker_request.identity.owner_id == _OWNER
                    assert worker_request.identity.attempt_id == attempt_id
                    worker_request.validate_current()
                    profile = _bind_posix_static_contained_product_worker_profile(
                        receipt=receipt,
                        worker_request=worker_request,
                        native_profile_catalog_revision=(
                            launch_material.closure.native_profile_catalog_revision
                        ),
                        launcher_path=launch_material.launcher_path,
                        launcher_sha256=(
                            launch_material.closure.containment_launcher_digest
                        ),
                        containment_profile_sha256=(
                            launch_material.closure.containment_profile_digest
                        ),
                    )
                    process_request = _map_worker_request(worker_request)
                    backend = _PosixStaticLaunchCaptureBackend()

                    async def capture_native(spec: object) -> object:
                        assert isinstance(spec, _PosixStaticContainedLaunchCaptureSpec)
                        return await backend.capture(
                            spec,
                            attempt_id=attempt_id,
                            attempt_token=object(),
                            on_capture=lambda _value: None,
                        )

                    async def exercise_native_capture() -> None:
                        prepared = await profile.capture_native(
                            process_request, capture=capture_native
                        )
                        await profile.verify_current()
                        await prepared.verify_current(process_request)
                        await prepared.close()
                        await profile.close()

                    asyncio.run(exercise_native_capture())
                    if native_mode in {"installed-release", "repaired-release"}:
                        if native_mode == "installed-release":
                            monkeypatch.setattr(gate_journal_module, "_MAX_EVENTS", 1)
                        gate = CodingProductWorkerStartGate(
                            receipt_owner=receipt_owner,
                            receipt=receipt,
                            worker_request=worker_request,
                            attempt_id=attempt_id,
                        )
                        gate_journal = CodingWorkerStartGateJournal(product)
                        intent = gate_journal.current(attempt_id)
                        assert intent is not None and intent.phase == "intent"
                        gated_profile = _bind_posix_static_contained_product_worker_profile(
                            receipt=receipt,
                            worker_request=worker_request,
                            native_profile_catalog_revision=(
                                launch_material.closure.native_profile_catalog_revision
                            ),
                            launcher_path=launch_material.launcher_path,
                            launcher_sha256=(
                                launch_material.closure.containment_launcher_digest
                            ),
                            containment_profile_sha256=(
                                launch_material.closure.containment_profile_digest
                            ),
                            start_gate_read_fd=gate.start_gate_read_fd,
                        )

                        async def exercise_product_gate() -> None:
                            host = _native_host(max_capture_slots=4)
                            try:
                                adapter = HostingManagedWorkerSessionAdapter(
                                    hosting=host,
                                    preparation=gated_profile,
                                    start_gate=bind_worker_gated_start_release(gate),
                                )
                                session = await adapter.start(
                                    worker_request,
                                    correlation_id="product-worker-gated-start",
                                )
                                try:
                                    bound = gate_journal.current(attempt_id)
                                    assert bound is not None
                                    assert bound.phase == "bound"
                                    assert bound.identity is not None
                                    assert bound.worker_identity_fingerprint == (
                                        worker_request.identity.fingerprint
                                    )
                                    await session.terminate()
                                finally:
                                    await session.close()
                            finally:
                                gate.close()
                                await gated_profile.close()
                                await host.close()

                        asyncio.run(exercise_product_gate())
                        with pytest.raises(
                            CodingWorkerStartGateJournalError
                        ) as gate_replay:
                            CodingProductWorkerStartGate(
                                receipt_owner=receipt_owner,
                                receipt=receipt,
                                worker_request=worker_request,
                                attempt_id=attempt_id,
                            )
                        assert gate_replay.value.code == (
                            "coding_worker_start_gate_attempt_conflict"
                        )
                        gate_history = gate_journal.path.read_bytes()
                        gate_journal.path.write_bytes(gate_history + b"{}\n")
                        try:
                            with pytest.raises(
                                CodingWorkerStartGateJournalError
                            ) as gate_corruption:
                                gate_journal.current(attempt_id)
                            assert gate_corruption.value.code == (
                                "coding_worker_sealed_segment_changed"
                                if native_mode == "installed-release"
                                else "coding_worker_segment_head_changed"
                            )
                        finally:
                            gate_journal.path.write_bytes(gate_history)
                    launch_profile = (
                        _bind_posix_static_contained_product_worker_profile(
                            receipt=receipt,
                            worker_request=worker_request,
                            native_profile_catalog_revision=(
                                launch_material.closure.native_profile_catalog_revision
                            ),
                            launcher_path=launch_material.launcher_path,
                            launcher_sha256=(
                                launch_material.closure.containment_launcher_digest
                            ),
                            containment_profile_sha256=(
                                launch_material.closure.containment_profile_digest
                            ),
                        )
                    )

                    async def exercise_native_spawn() -> None:
                        host = _native_host()
                        try:
                            preparation = _worker_launch_preparation_port(
                                expected=process_request,
                                worker_request=worker_request,
                                delegate=launch_profile,
                                signal=None,
                            )
                            session = await host.start(
                                ChildSessionRequest(process_request), preparation
                            )
                            try:
                                assert (
                                    await session.process.terminate()
                                ).return_code != 0
                            finally:
                                await session.close()
                        finally:
                            await launch_profile.close()
                            await host.close()

                    if not protocol_worker:
                        asyncio.run(exercise_native_spawn())
                    protocol_gate = (
                        CodingProductWorkerStartGate(
                            receipt_owner=receipt_owner,
                            receipt=receipt,
                            worker_request=worker_request,
                            attempt_id=attempt_id,
                        )
                        if protocol_worker
                        else None
                    )
                    protocol_profile = (
                        _bind_posix_static_contained_product_worker_profile(
                            receipt=receipt,
                            worker_request=worker_request,
                            native_profile_catalog_revision=(
                                launch_material.closure.native_profile_catalog_revision
                            ),
                            launcher_path=launch_material.launcher_path,
                            launcher_sha256=(
                                launch_material.closure.containment_launcher_digest
                            ),
                            containment_profile_sha256=(
                                launch_material.closure.containment_profile_digest
                            ),
                            start_gate_read_fd=(
                                None
                                if protocol_gate is None
                                else protocol_gate.start_gate_read_fd
                            ),
                        )
                    )

                    async def exercise_native_protocol_refusal() -> None:
                        host = _native_host(
                            max_capture_slots=4 if protocol_worker else 3
                        )
                        journal = open_coding_product_worker_supervisor_journal(product)
                        supervisor = WorkerSupervisor(
                            identity=worker_request.identity,
                            journal=journal,
                            protocol=worker_request.runtime.protocol,
                            protocol_version=worker_request.runtime.protocol_version,
                        )
                        try:
                            adapter = HostingManagedWorkerSessionAdapter(
                                hosting=host,
                                preparation=protocol_profile,
                                start_gate=(
                                    None
                                    if protocol_gate is None
                                    else bind_worker_gated_start_release(protocol_gate)
                                ),
                            )
                            if protocol_worker:
                                await supervisor.start_session(
                                    session_port=adapter,
                                    launch_request=worker_request,
                                    correlation_id="product-worker-protocol",
                                )
                                assert supervisor.status.state == "healthy"
                                identity = worker_request.identity
                                authority = CapabilityWorkerAuthorityV1(
                                    plugin_revision_digest=identity.plugin_revision_digest,
                                    declaration_fingerprint=(
                                        identity.declaration_fingerprint
                                    ),
                                    owner_generation=identity.owner_generation,
                                    product_policy_revision=(
                                        receipt.policy.product_policy_revision
                                    ),
                                    owner_policy_revision=CODING_WORKER_QUERY_OWNER_POLICY_REVISION,
                                    revocation_epoch=0,
                                )
                                binding = CapabilityWorkerBindingV1(
                                    plugin_id=identity.plugin_id,
                                    contribution_id=identity.contribution_id,
                                    product_id=identity.product_id,
                                    scope_id=identity.scope_id,
                                    owner_id=identity.owner_id,
                                    allowed_capability_ids=(
                                        CODING_WORKER_QUERY_CAPABILITY_ID,
                                    ),
                                    authority=authority,
                                )

                                hover_definition = CODING_WORKER_QUERY_DEFINITION
                                hover_owner = coding_worker_query_owner_authority()
                                facet_owner = bind_coding_worker_query_facet_owner(
                                    binding=binding,
                                    provider_owner=hover_owner,
                                    current_owner_snapshot=lambda: (
                                        hover_owner.snapshot()
                                    ),
                                )
                                accepted_hover_owner = hover_owner
                                with pytest.raises(
                                    CodingWorkerCapabilityBindingError
                                ) as wrong_owner:
                                    CodingProductWorkerCapabilityAuthority(
                                        receipt_owner=receipt_owner,
                                        receipt=receipt,
                                        request=worker_request,
                                        binding=replace(
                                            binding, owner_id="coding.other"
                                        ),
                                        owner_policy=facet_owner,
                                    )
                                assert wrong_owner.value.code == (
                                    "coding_worker_capability_identity_mismatch"
                                )
                                current_authority = (
                                    CodingProductWorkerCapabilityAuthority(
                                        receipt_owner=receipt_owner,
                                        receipt=receipt,
                                        request=worker_request,
                                        binding=binding,
                                        owner_policy=facet_owner,
                                    )
                                )

                                capability = bind_capability_query_worker_adapter(
                                    supervisor=supervisor,
                                    binding=current_authority.binding,
                                    authority_reader=(
                                        current_authority.current_authority
                                    ),
                                    enabled=True,
                                )
                                admitted = capability.admit()
                                descriptors = await capability.describe()
                                assert tuple(
                                    item.capability_id for item in descriptors
                                ) == (CODING_WORKER_QUERY_CAPABILITY_ID,)
                                assert descriptors[0].facet_ids == (
                                    CODING_WORKER_QUERY_FACET_ID,
                                )
                                hover_provider = CapabilityBundleProvider(
                                    capability_id=CODING_WORKER_QUERY_CAPABILITY_ID,
                                    provider_id="worker.query",
                                    implementation_version=1,
                                    compatible_contract=CapabilityContractRange.exact(
                                        1
                                    ),
                                    facets=(CODING_WORKER_QUERY_FACET_ID,),
                                    source_id=f"plugin:{_PLUGIN}",
                                    selection_rule="product-selected-canary",
                                )
                                if installed_native:
                                    admission_clock = [150]
                                    with pytest.raises(
                                        CodingWorkerProviderCandidateError
                                    ) as foreign_source:
                                        prepare_coding_selected_worker_provider_candidate(
                                            receipt_owner=receipt_owner,
                                            receipt=receipt,
                                            definition=hover_definition,
                                            provider=replace(
                                                hover_provider,
                                                source_id="plugin:foreign",
                                            ),
                                        )
                                    assert foreign_source.value.code == (
                                        "coding_worker_provider_selection_mismatch"
                                    )
                                    provider_candidate = prepare_coding_selected_worker_provider_candidate(
                                        receipt_owner=receipt_owner,
                                        receipt=receipt,
                                        definition=hover_definition,
                                        provider=hover_provider,
                                    )
                                    assert isinstance(
                                        provider_candidate.binding_spec,
                                        CapabilityWorkerProviderBindingSpec,
                                    )
                                    assert provider_candidate.scope_id == (
                                        f"session:{receipt.policy.session_id}"
                                    )
                                    assert (
                                        provider_candidate.binding_spec.executable_digest
                                        == selected_payload.digest
                                    )
                                    provider_eligibility = (
                                        hover_owner.grant_eligibility(
                                            provider_candidate,
                                            issued_at=100,
                                            expires_at=220,
                                        )
                                    )
                                    provider_admission = hover_owner.admit(
                                        provider_candidate,
                                        eligibility=provider_eligibility,
                                        issued_at=120,
                                        expires_at=200,
                                    )
                                    resolved_providers = ProductCapabilityProviderResolver().resolve(
                                        ProductCapabilityProviderSelectionPlanV1(
                                            product_id="coding",
                                            roots=(CODING_WORKER_QUERY_CAPABILITY_ID,),
                                            choices=(
                                                ProductCapabilityProviderChoice(
                                                    capability_id=(
                                                        CODING_WORKER_QUERY_CAPABILITY_ID
                                                    ),
                                                    provider_id=(
                                                        hover_provider.provider_id
                                                    ),
                                                    candidate_fingerprint=(
                                                        provider_admission.candidate_fingerprint
                                                    ),
                                                ),
                                            ),
                                            policy_revision=(
                                                receipt.policy.product_policy_revision
                                            ),
                                        ),
                                        definitions=(hover_definition,),
                                        admissions=(provider_admission,),
                                        owner_snapshots=(hover_owner.snapshot(),),
                                        evaluated_at=150,
                                    )
                                    assert resolved_providers.binding_specs == (
                                        provider_candidate.binding_spec,
                                    )
                                    planned_providers = resolved_providers.providers
                                else:
                                    planned_providers = (hover_provider,)
                                graph_plan = RuntimeCapabilityGraphPlanner().plan(
                                    CapabilityGraphPlanRequest(
                                        product_id="coding",
                                        roots=(CODING_WORKER_QUERY_CAPABILITY_ID,),
                                        definitions=(hover_definition,),
                                        providers=planned_providers,
                                    )
                                )

                                async def release_worker_attempt() -> None:
                                    if supervisor.status.state == "healthy":
                                        await supervisor.shutdown()

                                if installed_native:
                                    with pytest.raises(
                                        CodingWorkerProviderHostError
                                    ) as foreign_attempt:
                                        prepare_coding_worker_provider_binding(
                                            resolved=resolved_providers.entries[0],
                                            receipt_owner=receipt_owner,
                                            receipt=receipt,
                                            capability_authority=current_authority,
                                            adapter=capability,
                                            worker_admission=replace(
                                                admitted,
                                                worker_attempt_id="ff" * 16,
                                            ),
                                            graph_generation=1,
                                            clock=lambda: 150,
                                            release_attempt=release_worker_attempt,
                                        )
                                    assert foreign_attempt.value.code == (
                                        "coding_worker_provider_host_mismatch"
                                    )
                                    with pytest.raises(
                                        CodingWorkerProviderHostError
                                    ) as expired_admission:
                                        prepare_coding_worker_provider_binding(
                                            resolved=resolved_providers.entries[0],
                                            receipt_owner=receipt_owner,
                                            receipt=receipt,
                                            capability_authority=current_authority,
                                            adapter=capability,
                                            worker_admission=admitted,
                                            graph_generation=1,
                                            clock=lambda: 200,
                                            release_attempt=release_worker_attempt,
                                        )
                                    assert expired_admission.value.code == (
                                        "coding_worker_provider_admission_expired"
                                    )
                                    trust = selected.source_trust_snapshot
                                    assert trust is not None
                                    session_inputs = (
                                        prepare_coding_product_worker_session_inputs(
                                            resolved_providers=resolved_providers,
                                            provider_owner=hover_owner,
                                            receipt_owner=receipt_owner,
                                            receipt=receipt,
                                            capability_authority=current_authority,
                                            adapter=capability,
                                            worker_admission=admitted,
                                            evaluated_at=150,
                                            clock=lambda: admission_clock[0],
                                            release_attempt=release_worker_attempt,
                                        )
                                    )
                                    assert (
                                        session_inputs.host_consumer_requirements
                                        == (CODING_WORKER_QUERY_REQUIREMENT,)
                                    )
                                    assert (
                                        session_inputs.product_composition.authority_context.scope_id
                                        == (f"session:{receipt.policy.session_id}")
                                    )
                                    with pytest.raises(
                                        CodingWorkerSessionCompositionError,
                                        match="coding_worker_session_selection_stale",
                                    ):
                                        prepare_coding_product_worker_session_inputs(
                                            resolved_providers=resolved_providers,
                                            provider_owner=CapabilityProviderOwnerAuthority(
                                                replace(
                                                    hover_owner.policy,
                                                    revocation_epoch=1,
                                                )
                                            ),
                                            receipt_owner=receipt_owner,
                                            receipt=receipt,
                                            capability_authority=current_authority,
                                            adapter=capability,
                                            worker_admission=admitted,
                                            evaluated_at=150,
                                            clock=lambda: admission_clock[0],
                                            release_attempt=release_worker_attempt,
                                        )
                                    with pytest.raises(
                                        CodingWorkerSessionCompositionError,
                                        match="coding_worker_session_selection_stale",
                                    ):
                                        prepare_coding_product_worker_session_inputs(
                                            resolved_providers=resolved_providers,
                                            provider_owner=hover_owner,
                                            receipt_owner=receipt_owner,
                                            receipt=receipt,
                                            capability_authority=current_authority,
                                            adapter=capability,
                                            worker_admission=replace(
                                                admitted,
                                                worker_attempt_id="ff" * 16,
                                            ),
                                            evaluated_at=150,
                                            clock=lambda: admission_clock[0],
                                            release_attempt=release_worker_attempt,
                                        )
                                    [session_request] = (
                                        session_inputs.component_requests
                                    )
                                    if native_mode in {
                                        "installed-protocol",
                                        "installed-graph-failure",
                                    }:
                                        session_preparations = []
                                        original_prepare = session_request.prepare

                                        async def check_staged_prepare(generation: int):
                                            item = await original_prepare(generation)
                                            with pytest.raises(
                                                CapabilityWorkerFacetProxyError
                                            ) as staged:
                                                await item.facet.invoke(
                                                    {"symbol": "review"}
                                                )
                                            assert staged.value.code == (
                                                "worker_capability_facet_proxy_not_visible"
                                            )
                                            with pytest.raises(
                                                CapabilityWorkerFacetProxyError
                                            ) as stale:
                                                item.facet.publish(
                                                    admission=admitted,
                                                    owner_generation=(
                                                        identity.owner_generation + 1
                                                    ),
                                                )
                                            assert stale.value.code == (
                                                "worker_capability_facet_proxy_publish_stale"
                                            )
                                            if native_mode == "installed-graph-failure":

                                                def fail_graph_create(_context):
                                                    raise RuntimeError(
                                                        "injected Worker graph failure"
                                                    )

                                                item = replace(
                                                    item,
                                                    binding=replace(
                                                        item.binding,
                                                        create=fail_graph_create,
                                                    ),
                                                )
                                            session_preparations.append(item)
                                            return item

                                        session_inputs = replace(
                                            session_inputs,
                                            component_requests=(
                                                replace(
                                                    session_request,
                                                    prepare=check_staged_prepare,
                                                ),
                                            ),
                                        )
                                    else:
                                        prepared = (
                                            await session_request.prepare_component(1)
                                        )
                                        graph_binding = prepared.binding
                                        facet = prepared.facet
                                else:
                                    facet = CapabilityWorkerReadOnlyFacetProxy(
                                        adapter=capability,
                                        admission=admitted,
                                        capability_id=CODING_WORKER_QUERY_CAPABILITY_ID,
                                        facet_id=CODING_WORKER_QUERY_FACET_ID,
                                        owner_generation=identity.owner_generation,
                                        graph_generation=1,
                                        issue_grant=lambda: (
                                            current_authority.issue_read_only_facet(
                                                capability_id=CODING_WORKER_QUERY_CAPABILITY_ID,
                                                facet_id=CODING_WORKER_QUERY_FACET_ID,
                                            )
                                        ),
                                    )

                                    async def release_worker_facet(
                                        _value: CapabilityBundleValue,
                                    ) -> None:
                                        assert facet.state == "retired"
                                        await release_worker_attempt()

                                    graph_binding = CapabilityBundleProviderBinding(
                                        provider=hover_provider,
                                        scope_instance_id=(
                                            f"{identity.scope_id}:{identity.attempt_id}"
                                        ),
                                        binding_input_fingerprint=admitted.fingerprint,
                                        create=lambda _context: CapabilityBundleValue(
                                            (
                                                CapabilityFacetBinding(
                                                    CODING_WORKER_QUERY_FACET_ID, facet
                                                ),
                                            )
                                        ),
                                        dispose=release_worker_facet,
                                        visibility_gates=(facet.visibility_gate,),
                                    )
                                if native_mode in {
                                    "installed-protocol",
                                    "installed-graph-failure",
                                }:
                                    profile = RuntimeProfileResolver().resolve(
                                        standard_capability_composition_plan(
                                            product_id="coding"
                                        )
                                    )
                                    workspace_binding = None
                                    if native_mode in {
                                        "installed-protocol",
                                        "installed-graph-failure",
                                    }:
                                        workspace_binding = (
                                            workspace_capability_provider_binding(
                                                operations=LOCAL_TOOL_OPERATIONS,
                                                process_launcher=SimpleNamespace(),
                                                scope_instance_id="workspace:worker-canary",
                                                binding_input_fingerprint=sha256(
                                                    b"worker-canary-workspace"
                                                ).hexdigest(),
                                            )
                                        )
                                        context = (
                                            session_inputs.product_composition.authority_context
                                        )
                                        definitions = (
                                            MODEL_INPUT_CAPABILITY_DEFINITION,
                                            WORKSPACE_CAPABILITY_DEFINITION,
                                            hover_definition,
                                        )
                                        worker_only_inputs = session_inputs
                                        ordinary_compilation = (
                                            ProductCompositionCompiler().compile(
                                                authority_context=ProductCompositionAuthorityContext(
                                                    product_id="coding",
                                                    scope_id=context.scope_id,
                                                    product_policy_revision=(
                                                        context.product_policy_revision
                                                    ),
                                                    evaluated_at=150,
                                                    owner_snapshots=(),
                                                    trust_snapshots=(),
                                                ),
                                                mandatory_roots=(
                                                    MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,
                                                    WORKSPACE_CAPABILITY_DEFINITION.capability_id,
                                                ),
                                                admissions=(),
                                                definitions=definitions,
                                                optional_choices=(),
                                            )
                                        )
                                        ordinary_resolved = (
                                            ProductCapabilityProviderResolver().resolve(
                                                ProductCapabilityProviderSelectionPlanV1(
                                                    product_id="coding",
                                                    roots=(),
                                                    choices=(),
                                                    policy_revision=(
                                                        context.product_policy_revision
                                                    ),
                                                ),
                                                definitions=definitions,
                                                admissions=(),
                                                owner_snapshots=(),
                                                evaluated_at=150,
                                                prebound_providers=(
                                                    workspace_binding.provider,
                                                ),
                                            )
                                        )
                                        ordinary_inputs = (
                                            SessionCapabilityCompositionInputs(
                                                product_composition=(
                                                    ordinary_compilation
                                                ),
                                                resolved_providers=ordinary_resolved,
                                                component_requests=(),
                                            )
                                        )
                                        foreign_inputs = replace(
                                            ordinary_inputs,
                                            product_composition=replace(
                                                ordinary_compilation,
                                                authority_context=replace(
                                                    ordinary_compilation.authority_context,
                                                    scope_id="session:foreign-worker",
                                                ),
                                            ),
                                        )
                                        with pytest.raises(
                                            CodingWorkerSessionCompositionError,
                                            match="coding_worker_ordinary_composition_authority_mismatch",
                                        ):
                                            compose_coding_product_worker_with_ordinary_session(
                                                ordinary=foreign_inputs,
                                                worker=session_inputs,
                                                definitions=definitions,
                                                workspace_binding=workspace_binding,
                                            )
                                        session_inputs = (
                                            compose_coding_product_worker_with_ordinary_session(
                                                ordinary=ordinary_inputs,
                                                worker=session_inputs,
                                                definitions=definitions,
                                                workspace_binding=workspace_binding,
                                            )
                                        )
                                        assert (
                                            session_inputs.product_composition.consumer_requirements.roots
                                            == tuple(
                                                sorted(
                                                    (
                                                        MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,
                                                        WORKSPACE_CAPABILITY_DEFINITION.capability_id,
                                                        CODING_WORKER_QUERY_CAPABILITY_ID,
                                                    )
                                                )
                                            )
                                        )
                                        if native_mode in {
                                            "installed-protocol",
                                            "installed-graph-failure",
                                        }:
                                            selected_base = (
                                                runtime.capture_selected_plugin_manifest_for(
                                                    "coding.base",
                                                    max_files=64,
                                                    max_total_bytes=16 * 1024 * 1024,
                                                )
                                            )
                                            compiled_base = (
                                                compile_coding_base_product_selection(
                                                    selected_base,
                                                    resolve_coding_composition_set(
                                                        "coding-standard"
                                                    ),
                                                    installation_key=(
                                                        selected_base.snapshot.installation_key
                                                    ),
                                                    session_id="worker-catalog",
                                                    host_environment=(
                                                        LocalHostEnvironmentProbe().detect()
                                                    ),
                                                    evaluated_at=150,
                                                )
                                            )
                                            if native_mode == "installed-protocol":
                                                selected_data = (
                                                    runtime.capture_selected_plugin_manifest_for(
                                                        "reviewpack",
                                                        max_files=64,
                                                        max_total_bytes=1024 * 1024,
                                                    )
                                                )
                                                compiled_base = (
                                                    extend_coding_base_product_data_resources(
                                                        compiled_base,
                                                        (selected_data,),
                                                        evaluated_at=150,
                                                    )
                                                )
                                            full_base_session = (
                                                compiled_base.bind_workspace(
                                                    workspace_binding
                                                )
                                            )
                                            full_base_inputs = (
                                                full_base_session.session_inputs
                                            )
                                            base_context = (
                                                full_base_inputs.product_composition.authority_context
                                            )
                                            worker_context = (
                                                worker_only_inputs.product_composition.authority_context
                                            )
                                            assert base_context.scope_id == worker_context.scope_id
                                            assert (
                                                base_context.evaluated_at
                                                == worker_context.evaluated_at
                                            )
                                            assert (
                                                base_context.product_policy_revision
                                                != worker_context.product_policy_revision
                                            )
                                            assert (
                                                full_base_inputs.product_composition.resource_admissions
                                            )
                                            assert (
                                                full_base_inputs.product_composition.catalog_admissions
                                            )
                                            with pytest.raises(
                                                CodingWorkerSessionCompositionError,
                                                match="coding_worker_ordinary_composition_authority_mismatch",
                                            ):
                                                compose_coding_product_worker_with_ordinary_session(
                                                    ordinary=full_base_inputs,
                                                    worker=worker_only_inputs,
                                                    definitions=definitions,
                                                    workspace_binding=workspace_binding,
                                                )
                                            base_policy_binding = (
                                                CodingWorkerBaseCompositionPolicyBinding(
                                                    base=compiled_base,
                                                    receipt_owner=receipt_owner,
                                                    receipt=receipt,
                                                )
                                            )
                                            base_candidate = (
                                                prepare_coding_selected_worker_provider_candidate(
                                                    receipt_owner=receipt_owner,
                                                    receipt=receipt,
                                                    definition=hover_definition,
                                                    provider=hover_provider,
                                                    base_policy_binding=base_policy_binding,
                                                )
                                            )
                                            assert (
                                                base_candidate.product_policy_revision
                                                == base_context.product_policy_revision
                                            )
                                            assert (
                                                base_candidate.plugin_candidate_fingerprint
                                                == receipt.fingerprint
                                            )
                                            base_eligibility = hover_owner.grant_eligibility(
                                                base_candidate,
                                                issued_at=150,
                                                expires_at=450,
                                            )
                                            base_admission = hover_owner.admit(
                                                base_candidate,
                                                eligibility=base_eligibility,
                                                issued_at=150,
                                                expires_at=330,
                                            )
                                            base_resolved = (
                                                ProductCapabilityProviderResolver().resolve(
                                                    ProductCapabilityProviderSelectionPlanV1(
                                                        product_id="coding",
                                                        roots=(
                                                            CODING_WORKER_QUERY_CAPABILITY_ID,
                                                        ),
                                                        choices=(
                                                            ProductCapabilityProviderChoice(
                                                                capability_id=(
                                                                    CODING_WORKER_QUERY_CAPABILITY_ID
                                                                ),
                                                                provider_id=(
                                                                    hover_provider.provider_id
                                                                ),
                                                                candidate_fingerprint=(
                                                                    base_admission.candidate_fingerprint
                                                                ),
                                                            ),
                                                        ),
                                                        policy_revision=(
                                                            base_policy_binding.policy_revision
                                                        ),
                                                    ),
                                                    definitions=(hover_definition,),
                                                    admissions=(base_admission,),
                                                    owner_snapshots=(
                                                        hover_owner.snapshot(),
                                                    ),
                                                    evaluated_at=150,
                                                )
                                            )
                                            base_worker_inputs = (
                                                prepare_coding_product_worker_session_inputs(
                                                    resolved_providers=base_resolved,
                                                    provider_owner=hover_owner,
                                                    receipt_owner=receipt_owner,
                                                    receipt=receipt,
                                                    capability_authority=current_authority,
                                                    adapter=capability,
                                                    worker_admission=admitted,
                                                    evaluated_at=150,
                                                    clock=lambda: admission_clock[0],
                                                    release_attempt=release_worker_attempt,
                                                    base_policy_binding=base_policy_binding,
                                                )
                                            )
                                            full_inputs = (
                                                compose_coding_product_worker_with_ordinary_session(
                                                    ordinary=full_base_inputs,
                                                    worker=base_worker_inputs,
                                                    definitions=definitions,
                                                    workspace_binding=workspace_binding,
                                                )
                                            )
                                            validate_coding_product_worker_ordinary_session_inputs(
                                                ordinary=full_base_inputs,
                                                combined=full_inputs,
                                                workspace_binding=workspace_binding,
                                            )
                                            with pytest.raises(
                                                CodingWorkerSessionCompositionError,
                                                match="coding_worker_ordinary_session_facts_changed",
                                            ):
                                                validate_coding_product_worker_ordinary_session_inputs(
                                                    ordinary=full_base_inputs,
                                                    combined=replace(
                                                        full_inputs,
                                                        product_composition=replace(
                                                            full_inputs.product_composition,
                                                            resource_admissions=(),
                                                        ),
                                                    ),
                                                    workspace_binding=workspace_binding,
                                                )
                                            assert (
                                                full_inputs.product_composition.resource_admissions
                                                == full_base_inputs.product_composition.resource_admissions
                                            )
                                            assert (
                                                full_inputs.product_composition.catalog_admissions
                                                == full_base_inputs.product_composition.catalog_admissions
                                            )
                                            root_settlements = PackageStoreSettlementJournal(
                                                product.state_root
                                                / "root-settlements.jsonl"
                                            )
                                            (base_settlement,) = tuple(
                                                item
                                                for item in root_settlements.records()
                                                if item.receipt.stable_ref
                                                == selected_base.snapshot.root_ref
                                            )
                                            base_member, base_bytes = (
                                                selected_base.snapshot.files[0]
                                            )
                                            published_base = (
                                                product.plugin_store_root
                                                / base_settlement.final_name
                                                / base_member
                                            )
                                            assert published_base.read_bytes() == base_bytes
                                            try:
                                                published_base.write_bytes(b"changed")
                                                with pytest.raises(
                                                    CodingWorkerProviderCandidateError
                                                ) as stale_base_policy:
                                                    base_policy_binding.assert_current()
                                                assert stale_base_policy.value.code == (
                                                    "coding_worker_provider_base_selection_stale"
                                                )
                                                with pytest.raises(
                                                    CodingWorkerProviderCandidateError
                                                ) as stale_base_host:
                                                    await base_worker_inputs.component_requests[
                                                        0
                                                    ].prepare_component(1)
                                                assert stale_base_host.value.code == (
                                                    "coding_worker_provider_base_selection_stale"
                                                )
                                            finally:
                                                published_base.write_bytes(base_bytes)
                                            base_policy_binding.assert_current()
                                            if native_mode == "installed-protocol":
                                                (data_settlement,) = tuple(
                                                    item
                                                    for item in root_settlements.records()
                                                    if item.receipt.stable_ref
                                                    == selected_data.snapshot.root_ref
                                                )
                                                data_member, data_bytes = (
                                                    selected_data.snapshot.files[0]
                                                )
                                                published_data = (
                                                    product.plugin_store_root
                                                    / data_settlement.final_name
                                                    / data_member
                                                )
                                                assert published_data.read_bytes() == data_bytes
                                                try:
                                                    published_data.write_bytes(b"changed")
                                                    with pytest.raises(
                                                        CodingWorkerProviderCandidateError
                                                    ) as stale_data_policy:
                                                        base_policy_binding.assert_current()
                                                    assert stale_data_policy.value.code == (
                                                        "coding_worker_provider_base_selection_stale"
                                                    )
                                                    with pytest.raises(
                                                        CodingWorkerProviderCandidateError
                                                    ) as stale_data_host:
                                                        await base_worker_inputs.component_requests[
                                                            0
                                                        ].prepare_component(1)
                                                    assert stale_data_host.value.code == (
                                                        "coding_worker_provider_base_selection_stale"
                                                    )
                                                finally:
                                                    published_data.write_bytes(
                                                        data_bytes
                                                    )
                                                base_policy_binding.assert_current()
                                            (base_request,) = (
                                                base_worker_inputs.component_requests
                                            )
                                            original_prepare = base_request.prepare
                                            base_worker_inputs = replace(
                                                base_worker_inputs,
                                                component_requests=(
                                                    replace(
                                                        base_request,
                                                        prepare=check_staged_prepare,
                                                    ),
                                                ),
                                            )
                                            session_inputs = (
                                                compose_coding_product_worker_with_ordinary_session(
                                                    ordinary=full_base_inputs,
                                                    worker=base_worker_inputs,
                                                    definitions=definitions,
                                                    workspace_binding=workspace_binding,
                                                )
                                            )
                                            validate_coding_product_worker_ordinary_session_inputs(
                                                ordinary=full_base_inputs,
                                                combined=session_inputs,
                                                workspace_binding=workspace_binding,
                                            )
                                            ordinary_worker_binding = (
                                                CodingProductWorkerOrdinarySessionBinding(
                                                    ordinary=full_base_inputs,
                                                    combined=session_inputs,
                                                    workspace_binding=(
                                                        workspace_binding
                                                    ),
                                                )
                                            )
                                            catalog_receipt = (
                                                ResourceCatalogInputReceipt(
                                                    cwd=workspace,
                                                    project_resource_root=workspace,
                                                    project_context_roots=(),
                                                    package_mounts=(),
                                                    package_resource_candidates=(),
                                                    package_diagnostic_codes=(),
                                                    user_resource_roots=(),
                                                    explicit_user_resource_roots=frozenset(),
                                                    additional_extension_paths=(),
                                                    additional_skill_paths=(),
                                                    additional_prompt_template_paths=(),
                                                    additional_theme_paths=(),
                                                    no_extensions=False,
                                                    no_skills=False,
                                                    no_prompt_templates=False,
                                                    no_themes=False,
                                                    no_context_files=False,
                                                    built_in_resource_packages=(),
                                                    context_file_names=(
                                                        "AGENTS.md",
                                                        "CLAUDE.md",
                                                    ),
                                                )
                                            )
                                            catalog_adapter = (
                                                build_coding_initial_resource_catalog_adapter(
                                                    catalog_receipt,
                                                    product_scope_id="worker-catalog",
                                                    product_composition=(
                                                        compiled_base.product_composition
                                                    ),
                                                    product_snapshot_resources=(
                                                        compiled_base.product_resource_inputs()
                                                    ),
                                                    package_admission_now=150,
                                                    clock=lambda: 150,
                                                )
                                            )
                                            catalog_bundle = (
                                                catalog_adapter.prepare_bootstrap_projection(
                                                    product_id="coding",
                                                    session_id="worker-catalog",
                                                    cwd=workspace,
                                                )
                                            )
                                            if native_mode == "installed-protocol":
                                                assert any(
                                                    item.name == "worker-extra"
                                                    for item in catalog_bundle.skills
                                                )
                                            catalog_bootstrap = (
                                                catalog_adapter.construct_session(
                                                    product_id="coding",
                                                    session_id="worker-catalog",
                                                    base_resource_bundle=(
                                                        catalog_bundle
                                                    ),
                                                    construct=lambda value: value,
                                                )
                                            )

                                    async def unsupported_runtime(*_args, **_kwargs):
                                        raise AssertionError(
                                            "Worker canary does not invoke model callbacks"
                                        )

                                    session_kwargs = {
                                        "agent": Agent(
                                            initial_state={
                                                "system_prompt": "Worker canary",
                                                "model": Model(
                                                    id="worker-canary",
                                                    name="Worker Canary",
                                                    provider="test",
                                                    endpoint="test",
                                                    capabilities=Capabilities(
                                                        input=("text",),
                                                        context_window=128_000,
                                                        max_tokens=4_096,
                                                    ),
                                                ),
                                                "thinking_level": "off",
                                            }
                                        ),
                                        "session_manager": await SessionManager.load(
                                            selected_transcript
                                        ),
                                        "capability_runtime": (
                                            stage_resource_composition_candidate(
                                                profile
                                            )
                                        ),
                                        "footer_data_provider": SimpleNamespace(
                                            set_extension_status=lambda *_: None,
                                            set_available_provider_count=lambda *_: (
                                                None
                                            ),
                                            dispose=lambda: None,
                                        ),
                                        "workspace_capability_binding": workspace_binding,
                                    }
                                    if native_mode in {
                                        "installed-protocol",
                                        "installed-graph-failure",
                                    }:
                                        async def ignore_extension_update(
                                            _value: object,
                                        ) -> None:
                                            return None

                                        extension_runner = ExtensionRunner([])
                                        await extension_runner.activate_runtime_generation(
                                            ExtensionRuntimeBindings(
                                                cwd=str(workspace),
                                                get_active_tool_names=lambda: [],
                                                get_model_selection=lambda: None,
                                                set_active_tools=ignore_extension_update,
                                                set_model=ignore_extension_update,
                                                request_resource_refresh=lambda: None,
                                                shutdown=lambda: None,
                                                record_diagnostic=lambda _diagnostic: None,
                                            )
                                        )
                                        full_session_kwargs = {
                                            **session_kwargs,
                                            "extension_runner": extension_runner,
                                            "resource_bundle": catalog_bundle,
                                            "coding_base_product_session_assembly": (
                                                full_base_session
                                            ),
                                            "coding_base_product_runtime_binding": runtime,
                                            "coding_plugin_clock": lambda: 150,
                                            "initial_resource_catalog_bootstrap": (
                                                catalog_bootstrap
                                            ),
                                            "coding_product_worker_ordinary_binding": (
                                                ordinary_worker_binding
                                            ),
                                        }
                                        with pytest.raises(
                                            ValueError,
                                            match="Coding Product Worker ordinary Session changed",
                                        ):
                                            AgentSession(
                                                **{
                                                    **full_session_kwargs,
                                                    "workspace_capability_binding": None,
                                                },
                                            )
                                        foreign_manager = await SessionManager.new(
                                            session_dir=(
                                                tmp_path / "foreign-worker-session"
                                            ),
                                            cwd=str(workspace),
                                            persist=False,
                                        )
                                        with pytest.raises(
                                            ValueError,
                                            match="Coding base Product Session identity changed",
                                        ):
                                            AgentSession(
                                                **{
                                                    **full_session_kwargs,
                                                    "session_manager": foreign_manager,
                                                },
                                            )
                                        product_session = AgentSession(
                                            **full_session_kwargs,
                                        )
                                    else:
                                        product_session = AgentProductSession(
                                            **session_kwargs,
                                            execute_compaction=unsupported_runtime,
                                            execute_branch_summary=unsupported_runtime,
                                            get_changelog=lambda cwd, args: (cwd, args),
                                            copy_to_clipboard=lambda text: text,
                                            retry_sleep=unsupported_runtime,
                                            capability_composition_inputs=session_inputs,
                                        )
                                    if native_mode == "installed-graph-failure":
                                        with pytest.raises(
                                            CapabilityGraphBindingError,
                                        ):
                                            await product_session.prepare_model_call_runtime()
                                        assert len(session_preparations) == 1
                                        assert (
                                            session_preparations[0].facet.state
                                            == "retired"
                                        )
                                        assert catalog_bootstrap.state == "disposed"
                                        assert (
                                            product_session._capability_graph_runtime.snapshot
                                            is None
                                        )
                                        await product_session.dispose()
                                        assert supervisor.status.state == "stopped"
                                        settled = journal.status(
                                            worker_request.identity.attempt_id
                                        )
                                        assert settled is not None
                                        assert settled.phase == "stopped"
                                        return
                                    await product_session.prepare_model_call_runtime()
                                    assert len(session_preparations) == 1
                                    if native_mode == "installed-protocol":
                                        assert catalog_bootstrap.state == "published"
                                        assert product_session.resource_bundle is not None
                                        assert any(
                                            item.name == "worker-extra"
                                            for item in product_session.resource_bundle.skills
                                        )
                                    facet = session_preparations[0].facet
                                    graph = product_session._capability_graph_runtime
                                else:
                                    with pytest.raises(
                                        CapabilityWorkerFacetProxyError
                                    ) as staged_facet:
                                        await facet.invoke({"symbol": "review"})
                                    assert staged_facet.value.code == (
                                        "worker_capability_facet_proxy_not_visible"
                                    )
                                    with pytest.raises(
                                        CapabilityWorkerFacetProxyError
                                    ) as stale_publication:
                                        facet.publish(
                                            admission=admitted,
                                            owner_generation=(
                                                identity.owner_generation + 1
                                            ),
                                        )
                                    assert stale_publication.value.code == (
                                        "worker_capability_facet_proxy_publish_stale"
                                    )
                                    graph = RuntimeCapabilityGraphRuntime(
                                        product_id="coding",
                                        runtime_id=f"worker:{identity.attempt_id}",
                                        profile_fingerprint=admitted.fingerprint,
                                    )
                                    graph_binder = RuntimeCapabilityGraphBinder()
                                    await graph_binder.bind(
                                        graph, graph_plan, (graph_binding,)
                                    )
                                    if installed_native:
                                        prepared.commit_after_graph_publication()
                                assert facet.state == "visible"
                                consumed_facet = graph.capture(
                                    CapabilityRequirement(
                                        capability=CODING_WORKER_QUERY_CAPABILITY_ID,
                                        facets=(CODING_WORKER_QUERY_FACET_ID,),
                                        compatible_contract=(
                                            CapabilityContractRange.exact(1)
                                        ),
                                    )
                                ).require(CODING_WORKER_QUERY_FACET_ID)
                                assert consumed_facet is facet
                                with pytest.raises(
                                    CodingWorkerCapabilityBindingError
                                ) as unapproved_facet:
                                    current_authority.issue_read_only_facet(
                                        capability_id=CODING_WORKER_QUERY_CAPABILITY_ID,
                                        facet_id="documentation",
                                    )
                                assert unapproved_facet.value.code == (
                                    "coding_worker_capability_facet_not_approved"
                                )
                                if native_mode == "installed-revocation":
                                    stored_payload.write_bytes(b"stale selected Worker")
                                    try:
                                        with pytest.raises(
                                            CapabilityWorkerFacetProxyError
                                        ) as stale_capability:
                                            await consumed_facet.invoke(
                                                {"symbol": "review"}
                                            )
                                        assert stale_capability.value.code == (
                                            "worker_capability_facet_proxy_owner_unavailable"
                                        )
                                        assert supervisor.status.state == "fenced"
                                    finally:
                                        stored_payload.write_bytes(
                                            selected_payload.body
                                        )
                                elif native_mode == "installed-expiry":
                                    admission_clock[0] = 200
                                    with pytest.raises(
                                        CapabilityWorkerFacetProxyError
                                    ) as expired_facet:
                                        await consumed_facet.invoke(
                                            {"symbol": "review"}
                                        )
                                    assert expired_facet.value.code == (
                                        "worker_capability_facet_proxy_owner_unavailable"
                                    )
                                    assert supervisor.status.state == "fenced"
                                else:
                                    if native_mode == "installed-protocol":
                                        product_consumer = (
                                            bind_coding_worker_query_consumer(
                                                product_session
                                            )
                                        )
                                        for _ in range(protocol_queries):
                                            assert (
                                                await product_consumer.query(
                                                    symbol="review"
                                                )
                                                == "Review symbol"
                                            )
                                    else:
                                        assert (
                                            await consumed_facet.invoke(
                                                {"symbol": "review"}
                                            )
                                            == "Review symbol"
                                        )
                                    hover_owner = CapabilityProviderOwnerAuthority(
                                        replace(
                                            hover_owner.policy,
                                            policy_revision="owner-policy-2",
                                        )
                                    )
                                    with pytest.raises(
                                        CodingWorkerCapabilityBindingError
                                    ) as stale_owner_policy:
                                        current_authority.issue_read_only_facet(
                                            capability_id=CODING_WORKER_QUERY_CAPABILITY_ID,
                                            facet_id=CODING_WORKER_QUERY_FACET_ID,
                                        )
                                    assert stale_owner_policy.value.code == (
                                        "coding_worker_capability_owner_authority_stale"
                                    )
                                    hover_owner = None
                                    with pytest.raises(
                                        CodingWorkerCapabilityBindingError
                                    ) as unavailable_owner:
                                        current_authority.issue_read_only_facet(
                                            capability_id=CODING_WORKER_QUERY_CAPABILITY_ID,
                                            facet_id=CODING_WORKER_QUERY_FACET_ID,
                                        )
                                    assert unavailable_owner.value.code == (
                                        "coding_worker_capability_owner_authority_unavailable"
                                    )
                                    hover_owner = accepted_hover_owner
                                if native_mode == "installed-protocol":
                                    await product_session.dispose()
                                    assert graph.is_closed
                                else:
                                    assert await graph_binder.dispose(graph) == ()
                                assert facet.state == "retired"
                                with pytest.raises(
                                    CapabilityWorkerFacetProxyError
                                ) as retired_facet:
                                    await facet.invoke({"symbol": "review"})
                                assert retired_facet.value.code == (
                                    "worker_capability_facet_proxy_not_visible"
                                )
                                if native_mode not in {
                                    "installed-revocation",
                                    "installed-expiry",
                                }:
                                    assert supervisor.status.state == "stopped"
                            else:
                                with pytest.raises(WorkerSupervisorError) as failure:
                                    await supervisor.start_session(
                                        session_port=adapter,
                                        launch_request=worker_request,
                                        correlation_id="product-worker-protocol",
                                    )
                                assert failure.value.code in {
                                    "worker_protocol_peer_closed",
                                    "worker_protocol_write_failed",
                                    "worker_handshake_timeout",
                                }, repr(failure.value.__cause__)
                                assert supervisor.status.state == "fenced"
                            settled = journal.status(worker_request.identity.attempt_id)
                            assert settled is not None
                            assert settled.phase == (
                                "process_settled"
                                if supervisor.status.state in {"failed", "fenced"}
                                else supervisor.status.state
                            )
                            assert (
                                settled.failure_code == supervisor.status.failure_code
                            )
                        finally:
                            if protocol_gate is not None:
                                protocol_gate.close()
                            await protocol_profile.close()
                            await host.close()

                    asyncio.run(exercise_native_protocol_refusal())
                    with pytest.raises(
                        CodingWorkerPayloadMaterializationError
                    ) as duplicate_attempt:
                        with materialize_coding_product_worker_payload(
                            receipt_owner=receipt_owner,
                            receipt=receipt,
                            attempt_id=attempt_id,
                        ):
                            pass
                    assert (
                        duplicate_attempt.value.code
                        == "coding_worker_payload_attempt_debt"
                    )
                terminal_attempt = open_coding_product_worker_supervisor_journal(
                    product
                ).status(attempt_id)
                assert terminal_attempt is not None
                assert terminal_attempt.terminal
                assert payload_lease.runtime.package_root.exists() == (
                    not terminal_attempt.process_settled
                )
                if terminal_attempt.process_settled:
                    with pytest.raises(
                        CodingWorkerPayloadMaterializationError
                    ) as reused_attempt:
                        with materialize_coding_product_worker_payload(
                            receipt_owner=receipt_owner,
                            receipt=receipt,
                            attempt_id=attempt_id,
                        ):
                            pass
                    assert reused_attempt.value.code == (
                        "coding_worker_payload_attempt_reused"
                    )
                with pytest.raises(WorkerBindingError) as closed_payload:
                    worker_request.validate_current()
                assert closed_payload.value.code == "worker_product_selection_stale"
                if native_mode == "installed-protocol":
                    selected_base = runtime.capture_selected_plugin_manifest_for(
                        "coding.base",
                        max_files=64,
                        max_total_bytes=16 * 1024 * 1024,
                    )
                    compiled_base = compile_coding_base_product_selection(
                        selected_base,
                        resolve_coding_composition_set("coding-standard"),
                        installation_key=selected_base.snapshot.installation_key,
                        session_id="worker-catalog",
                        host_environment=LocalHostEnvironmentProbe().detect(),
                        evaluated_at=150,
                    )
                    selected_data = runtime.capture_selected_plugin_manifest_for(
                        "reviewpack", max_files=64, max_total_bytes=1024 * 1024
                    )
                    compiled_base = extend_coding_base_product_data_resources(
                        compiled_base, (selected_data,), evaluated_at=150
                    )
                    base_policy = CodingWorkerBaseCompositionPolicyBinding(
                        base=compiled_base,
                        receipt_owner=receipt_owner,
                        receipt=receipt,
                    )
                    deferred_owner = coding_worker_query_owner_authority()
                    deferred_provider = coding_worker_query_capability_provider(_PLUGIN)
                    deferred_candidate = prepare_coding_selected_worker_provider_candidate(
                        receipt_owner=receipt_owner,
                        receipt=receipt,
                        definition=CODING_WORKER_QUERY_DEFINITION,
                        provider=deferred_provider,
                        base_policy_binding=base_policy,
                    )
                    deferred_eligibility = deferred_owner.grant_eligibility(
                        deferred_candidate, issued_at=150, expires_at=450
                    )
                    deferred_admission = deferred_owner.admit(
                        deferred_candidate,
                        eligibility=deferred_eligibility,
                        issued_at=150,
                        expires_at=330,
                    )
                    deferred_resolved = ProductCapabilityProviderResolver().resolve(
                        ProductCapabilityProviderSelectionPlanV1(
                            product_id="coding",
                            roots=(CODING_WORKER_QUERY_CAPABILITY_ID,),
                            choices=(
                                ProductCapabilityProviderChoice(
                                    capability_id=CODING_WORKER_QUERY_CAPABILITY_ID,
                                    provider_id=deferred_provider.provider_id,
                                    candidate_fingerprint=(
                                        deferred_admission.candidate_fingerprint
                                    ),
                                ),
                            ),
                            policy_revision=base_policy.policy_revision,
                        ),
                        definitions=(CODING_WORKER_QUERY_DEFINITION,),
                        admissions=(deferred_admission,),
                        owner_snapshots=(deferred_owner.snapshot(),),
                        evaluated_at=150,
                    )
                    deferred_attempt = "e1" * 16
                    deferred_pending = plan_coding_product_worker_pending_launch(
                        receipt_owner=receipt_owner,
                        receipt=receipt,
                        attempt_id=deferred_attempt,
                    )
                    deferred_worker_inputs = prepare_coding_product_worker_pending_session_inputs(
                        resolved_providers=deferred_resolved,
                        provider_owner=deferred_owner,
                        receipt_owner=receipt_owner,
                        receipt=receipt,
                        pending_launch=deferred_pending,
                        evaluated_at=150,
                        clock=lambda: 150,
                        base_policy_binding=base_policy,
                    )
                    deferred_workspace = workspace_capability_provider_binding(
                        operations=LOCAL_TOOL_OPERATIONS,
                        process_launcher=SimpleNamespace(),
                        scope_instance_id="workspace:worker-deferred-ordinary",
                        binding_input_fingerprint=sha256(
                            b"worker-deferred-ordinary-workspace"
                        ).hexdigest(),
                    )
                    deferred_ordinary = compiled_base.bind_workspace(
                        deferred_workspace
                    ).session_inputs
                    assert deferred_ordinary.product_composition.resource_admissions
                    assert deferred_ordinary.product_composition.catalog_admissions
                    deferred_ordinary_inputs = compose_coding_product_worker_with_ordinary_session(
                        ordinary=deferred_ordinary,
                        worker=deferred_worker_inputs,
                        definitions=(
                            MODEL_INPUT_CAPABILITY_DEFINITION,
                            WORKSPACE_CAPABILITY_DEFINITION,
                            CODING_WORKER_QUERY_DEFINITION,
                        ),
                        workspace_binding=deferred_workspace,
                    )
                    deferred_ordinary_binding = CodingProductWorkerOrdinarySessionBinding(
                        ordinary=deferred_ordinary,
                        combined=deferred_ordinary_inputs,
                        workspace_binding=deferred_workspace,
                    )
                    assert (
                        deferred_ordinary_binding.combined.product_composition.resource_admissions
                        == deferred_ordinary.product_composition.resource_admissions
                    )
                    assert (
                        deferred_ordinary_binding.combined.product_composition.catalog_admissions
                        == deferred_ordinary.product_composition.catalog_admissions
                    )
                    assert not (
                        product.state_root / f"worker-payload-{deferred_attempt}"
                    ).exists()
                    assert (
                        open_coding_product_worker_supervisor_journal(product).status(
                            deferred_attempt
                        )
                        is None
                    )

                    async def exercise_deferred_host() -> None:
                        async def unsupported_runtime(*_args, **_kwargs):
                            raise AssertionError("Worker query does not use the model")

                        session = AgentProductSession(
                            agent=Agent(
                                initial_state={
                                    "system_prompt": "Deferred Worker query",
                                    "model": Model(
                                        id="deferred-worker",
                                        name="Deferred Worker",
                                        provider="test",
                                        endpoint="test",
                                        capabilities=Capabilities(
                                            input=("text",),
                                            context_window=128_000,
                                            max_tokens=4_096,
                                        ),
                                    ),
                                    "thinking_level": "off",
                                }
                            ),
                            session_manager=session_manager,
                            capability_runtime=stage_resource_composition_candidate(
                                RuntimeProfileResolver().resolve(
                                    standard_capability_composition_plan(
                                        product_id="coding"
                                    )
                                )
                            ),
                            execute_compaction=unsupported_runtime,
                            execute_branch_summary=unsupported_runtime,
                            get_changelog=lambda cwd, args: (cwd, args),
                            copy_to_clipboard=lambda text: text,
                            retry_sleep=unsupported_runtime,
                            footer_data_provider=SimpleNamespace(
                                set_extension_status=lambda *_: None,
                                set_available_provider_count=lambda *_: None,
                                dispose=lambda: None,
                            ),
                            capability_composition_inputs=deferred_worker_inputs,
                        )
                        try:
                            assert (
                                open_coding_product_worker_supervisor_journal(
                                    product
                                ).status(deferred_attempt)
                                is None
                            )
                            await session.prepare_model_call_runtime()
                            assert await bind_coding_worker_query_consumer(
                                session
                            ).query(symbol="review") == "Review symbol"
                        finally:
                            await session.dispose()

                    asyncio.run(exercise_deferred_host())
                    deferred_settled = open_coding_product_worker_supervisor_journal(
                        product
                    ).status(deferred_attempt)
                    assert deferred_settled is not None
                    assert deferred_settled.phase == "stopped"
                    assert not (
                        product.state_root / f"worker-payload-{deferred_attempt}"
                    ).exists()
                    failed_attempt = "e2" * 16
                    failed_pending = plan_coding_product_worker_pending_launch(
                        receipt_owner=receipt_owner,
                        receipt=receipt,
                        attempt_id=failed_attempt,
                    )
                    failed_inputs = prepare_coding_product_worker_pending_session_inputs(
                        resolved_providers=deferred_resolved,
                        provider_owner=deferred_owner,
                        receipt_owner=receipt_owner,
                        receipt=receipt,
                        pending_launch=failed_pending,
                        evaluated_at=150,
                        clock=lambda: 150,
                        base_policy_binding=base_policy,
                    )
                    failed_request = failed_inputs.component_requests[0]
                    original_admit = CapabilityQueryWorkerAdapter.admit

                    def changed_worker_admission(
                        adapter: CapabilityQueryWorkerAdapter,
                    ):
                        return replace(
                            original_admit(adapter),
                            worker_identity_fingerprint="f" * 64,
                        )

                    async def exercise_deferred_refusal() -> None:
                        with pytest.raises(
                            CodingWorkerPendingHostError,
                            match="coding_worker_pending_admission_changed",
                        ):
                            await failed_request.prepare_component(1)

                    with monkeypatch.context() as refusal_patch:
                        refusal_patch.setattr(
                            CapabilityQueryWorkerAdapter,
                            "admit",
                            changed_worker_admission,
                        )
                        asyncio.run(exercise_deferred_refusal())
                    failed_settled = open_coding_product_worker_supervisor_journal(
                        product
                    ).status(failed_attempt)
                    assert failed_settled is not None
                    assert failed_settled.phase in {"stopped", "process_settled"}
                    assert failed_settled.process_settled
                    assert not (
                        product.state_root / f"worker-payload-{failed_attempt}"
                    ).exists()
                    payloads_before_ordinary_bootstrap = tuple(
                        product.state_root.glob("worker-payload-*")
                    )
                    selected_ordinary_assembly = compiled_base.bind_workspace(
                        deferred_workspace
                    )
                    ordinary_worker_now = [150]
                    selected_ordinary_binding = (
                        prepare_coding_product_worker_ordinary_binding(
                            product_owner=product,
                            runtime=runtime,
                            session_manager=session_manager,
                            plugin_id=_PLUGIN,
                            ordinary=selected_ordinary_assembly,
                            clock=lambda: ordinary_worker_now[0],
                        )
                    )
                    assert (
                        selected_ordinary_binding.combined.product_composition.resource_admissions
                        == deferred_ordinary.product_composition.resource_admissions
                    )
                    assert (
                        selected_ordinary_binding.combined.product_composition.catalog_admissions
                        == deferred_ordinary.product_composition.catalog_admissions
                    )
                    assert tuple(product.state_root.glob("worker-payload-*")) == (
                        payloads_before_ordinary_bootstrap
                    )

                    async def exercise_selected_ordinary_worker() -> None:
                        async def ignore_extension_update(_value: object) -> None:
                            return None

                        extension_runner = ExtensionRunner([])
                        await extension_runner.activate_runtime_generation(
                            ExtensionRuntimeBindings(
                                cwd=str(workspace),
                                get_active_tool_names=lambda: [],
                                get_model_selection=lambda: None,
                                set_active_tools=ignore_extension_update,
                                set_model=ignore_extension_update,
                                request_resource_refresh=lambda: None,
                                shutdown=lambda: None,
                                record_diagnostic=lambda _diagnostic: None,
                            )
                        )
                        catalog_receipt = ResourceCatalogInputReceipt(
                            cwd=workspace,
                            project_resource_root=workspace,
                            project_context_roots=(),
                            package_mounts=(),
                            package_resource_candidates=(),
                            package_diagnostic_codes=(),
                            user_resource_roots=(),
                            explicit_user_resource_roots=frozenset(),
                            additional_extension_paths=(),
                            additional_skill_paths=(),
                            additional_prompt_template_paths=(),
                            additional_theme_paths=(),
                            no_extensions=False,
                            no_skills=False,
                            no_prompt_templates=False,
                            no_themes=False,
                            no_context_files=False,
                            built_in_resource_packages=(),
                            context_file_names=("AGENTS.md", "CLAUDE.md"),
                        )
                        catalog_adapter = build_coding_initial_resource_catalog_adapter(
                            catalog_receipt,
                            product_scope_id="worker-catalog",
                            product_composition=compiled_base.product_composition,
                            product_snapshot_resources=(
                                compiled_base.product_resource_inputs()
                            ),
                            package_admission_now=150,
                            clock=lambda: 150,
                        )
                        catalog_bundle = catalog_adapter.prepare_bootstrap_projection(
                            product_id="coding",
                            session_id="worker-catalog",
                            cwd=workspace,
                        )
                        catalog_bootstrap = catalog_adapter.construct_session(
                            product_id="coding",
                            session_id="worker-catalog",
                            base_resource_bundle=catalog_bundle,
                            construct=lambda value: value,
                        )
                        session = AgentSession(
                            agent=Agent(
                                initial_state={
                                    "system_prompt": "Ordinary deferred Worker query",
                                    "model": Model(
                                        id="ordinary-worker",
                                        name="Ordinary Worker",
                                        provider="test",
                                        endpoint="test",
                                        capabilities=Capabilities(
                                            input=("text",),
                                            context_window=128_000,
                                            max_tokens=4_096,
                                        ),
                                    ),
                                    "thinking_level": "off",
                                }
                            ),
                            session_manager=await SessionManager.load(selected_transcript),
                            capability_runtime=stage_resource_composition_candidate(
                                RuntimeProfileResolver().resolve(
                                    standard_capability_composition_plan(
                                        product_id="coding"
                                    )
                                )
                            ),
                            footer_data_provider=SimpleNamespace(
                                set_extension_status=lambda *_: None,
                                set_available_provider_count=lambda *_: None,
                                dispose=lambda: None,
                            ),
                            workspace_capability_binding=deferred_workspace,
                            extension_runner=extension_runner,
                            resource_bundle=catalog_bundle,
                            coding_base_product_session_assembly=(
                                selected_ordinary_assembly
                            ),
                            coding_base_product_runtime_binding=runtime,
                            coding_plugin_clock=lambda: 150,
                            initial_resource_catalog_bootstrap=catalog_bootstrap,
                            coding_product_worker_ordinary_binding=(
                                selected_ordinary_binding
                            ),
                        )
                        try:
                            ordinary_worker_now[0] = 180_151
                            await session.prepare_model_call_runtime()
                            assert (
                                await bind_coding_worker_query_consumer(session).query(
                                    symbol="review"
                                )
                                == "Review symbol"
                            )
                            ordinary_worker_now[0] = 360_152
                            assert (
                                await bind_coding_worker_query_consumer(session).query(
                                    symbol="review"
                                )
                                == "Review symbol"
                            )
                            ordinary_worker_now[0] = 540_153
                            stored_payload.write_bytes(b"changed selected Worker")
                            try:
                                with pytest.raises(
                                    CapabilityWorkerFacetProxyError
                                ) as changed_after_renewal:
                                    await bind_coding_worker_query_consumer(
                                        session
                                    ).query(symbol="review")
                                assert changed_after_renewal.value.code == (
                                    "worker_capability_facet_proxy_owner_unavailable"
                                )
                            finally:
                                stored_payload.write_bytes(selected_payload.body)
                            assert any(
                                item.name == "worker-extra"
                                for item in session.resource_bundle.skills
                            )
                        finally:
                            await session.dispose()

                    asyncio.run(exercise_selected_ordinary_worker())
                    if direct_entry_only:
                        payloads_before_direct = frozenset(
                            product.state_root.glob("worker-payload-*")
                        )
                        gate_attempts_before_direct = {
                            item.attempt_id
                            for item in CodingWorkerStartGateJournal(product).attempts()
                        }
                        supervisor_journal = (
                            open_coding_product_worker_supervisor_journal(product)
                        )
                        incomplete_before_direct = supervisor_journal.incomplete()
                        direct_model = Model(
                            id="direct-worker",
                            name="Direct Worker",
                            provider="test",
                            endpoint="test",
                            capabilities=Capabilities(
                                input=("text",),
                                context_window=128_000,
                                max_tokens=4_096,
                            ),
                        )
                        direct_session = create_agent_session(
                            session_manager=asyncio.run(
                                SessionManager.load(selected_transcript)
                            ),
                            model=direct_model,
                            services=create_services(settings_manager=settings),
                            worker_candidate_plugin_id=_PLUGIN,
                        )

                        async def exercise_direct_worker() -> None:
                            try:
                                await direct_session.prepare_model_call_runtime()
                                assert await direct_session.query_worker_symbol(
                                    "review"
                                ) == "Review symbol"
                                assert any(
                                    item.name == "worker-extra"
                                    for item in direct_session.resource_bundle.skills
                                )
                                if disable_while_direct_session_open:
                                    disabled = product.management.submit(
                                        PluginManagementCommandV1(
                                            action="disable",
                                            mutation=PluginDesiredStateMutationV1(
                                                operation_id=(
                                                    "worker-public-session-disable"
                                                ),
                                                idempotency_key=(
                                                    "worker-public-session-disable"
                                                ),
                                                expected_inventory_revision=(
                                                    product.desired_state.snapshot().inventory_revision
                                                ),
                                                installation_key=(
                                                    installations[0].installation_key
                                                ),
                                                desired_state="installed_disabled",
                                                package_revision=None,
                                                actor_id=product.actor_id,
                                                policy_revision=(
                                                    product.desired_policy_revision
                                                ),
                                            ),
                                        )
                                    )
                                    assert disabled.status == "terminal"
                                elif update_while_direct_session_open:
                                    updated_payload = (
                                        build_coding_local_worker_candidate_wheel(
                                            plugin_id=_PLUGIN,
                                            version="2",
                                            contribution_id=_CONTRIBUTION,
                                            owner_id=_OWNER,
                                            native_platform="linux-x86_64",
                                            wheel_tag=_TAG,
                                            executable=executable.read_bytes(),
                                        )
                                    )
                                    updated_source = (
                                        product.policy.source_root
                                        / f"{_PLUGIN}-2-{_TAG}.whl"
                                    )
                                    updated_source.write_bytes(updated_payload)
                                    updated_binding = replace(
                                        binding,
                                        source_identity=str(updated_source),
                                        requested_package=f"{_PLUGIN}==2",
                                        artifact_digest=sha256(updated_payload).hexdigest(),
                                    )
                                    updated_policy = replace(
                                        product.policy,
                                        bindings=tuple(
                                            sorted(
                                                (
                                                    *product.policy.bindings,
                                                    updated_binding,
                                                ),
                                                key=lambda item: item.source_identity,
                                            )
                                        ),
                                    )
                                    updated_product = replace(
                                        product, policy=updated_policy
                                    )
                                    updated_runtime = updated_product.factory_for_session(
                                        session_id="worker-public-session-update",
                                        cwd=workspace,
                                        runtime_id="worker-public-session-update",
                                    ).create(
                                        PackageProductRuntimeRequestV1(
                                            product_id="coding",
                                            session_id="worker-public-session-update",
                                            cwd=str(workspace),
                                        )
                                    )
                                    try:
                                        updated_runtime.activate()
                                        updated = updated_runtime.lifecycle.route(
                                            PackageProductLifecycleIntentV1(
                                                operation_id=(
                                                    "worker-public-session-update"
                                                ),
                                                action="update",
                                                source=str(updated_source),
                                                scope="project",
                                            ),
                                            entrypoint="cli",
                                        )
                                        assert updated.handled
                                        assert updated.record is not None
                                        assert updated.record.lifecycle == "installed"
                                        selected_updated = (
                                            updated_runtime.capture_selected_plugin_manifest_for(
                                                _PLUGIN,
                                                max_files=16,
                                                max_total_bytes=16 * 1024 * 1024,
                                            )
                                        )
                                        assert selected_updated.manifest.version == "2"
                                    finally:
                                        updated_runtime.dispose_runtime()
                                else:
                                    revoked = product_opt_in.revoke(
                                        plugin_id=_PLUGIN,
                                        operation_id="worker-public-session-revoke",
                                        expected_generation=decision.generation,
                                    )
                                    assert revoked.action == "revoke"
                                    assert revoked.kill_switch_generation == (
                                        decision.kill_switch_generation + 1
                                    )
                                with pytest.raises(
                                    CapabilityWorkerFacetProxyError,
                                    match="worker_capability_facet_proxy_owner_unavailable",
                                ):
                                    await direct_session.query_worker_symbol("review")
                            finally:
                                await direct_session.dispose()

                        asyncio.run(exercise_direct_worker())
                        assert frozenset(product.state_root.glob("worker-payload-*")) == (
                            payloads_before_direct
                        )
                        assert supervisor_journal.incomplete() == incomplete_before_direct
                        direct_gate_attempts = tuple(
                            item
                            for item in CodingWorkerStartGateJournal(product).attempts()
                            if item.attempt_id not in gate_attempts_before_direct
                        )
                        assert len(direct_gate_attempts) == 1
                        direct_retention = review_coding_product_worker_history_retention(
                            product, attempt_id=direct_gate_attempts[0].attempt_id
                        )
                        reference = direct_retention.attempt_reference
                        assert reference is not None
                        assert direct_retention.receipt_record is not None
                        assert reference.attempt_id == direct_gate_attempts[0].attempt_id
                        assert reference.plugin_id == _PLUGIN
                        assert reference.receipt_fingerprint == (
                            direct_gate_attempts[0].receipt_fingerprint
                        )
                        assert reference.selected_package_revision_digest == (
                            direct_retention.receipt_record.receipt.policy.plugin_revision_digest
                        )
                        assert reference.native_platform == "linux"
                        assert direct_retention.gc_reservation_revision >= 0
                        assert direct_retention.start_gate_history_revision >= (
                            direct_gate_attempts[0].journal_revision
                        )
                        assert direct_retention.attempt_record is not None
                        assert direct_retention.supervisor_history_revision >= (
                            direct_retention.attempt_record.record_revision
                        )
                        assert direct_retention.receipt_record is not None
                        assert direct_retention.receipt_history_revision >= (
                            direct_retention.receipt_record.journal_revision
                        )
                        assert direct_retention.unbound_supervisor_attempt_ids == ()
                        assert direct_retention.retained_start_gate_attempt_ids
                        assert direct_retention.retained_supervisor_attempt_ids
                        assert direct_retention.retained_receipt_fingerprints
                        assert direct_retention.supervisor_epoch_high_water
                        assert direct_retention.opt_in_history_revision >= 1
                        assert direct_retention.current_opt_in is not None
                        assert (
                            direct_retention.current_opt_in.operation_id
                            in direct_retention.retained_opt_in_operation_ids
                        )
                        assert direct_retention.unrecognized_worker_state_names == ()
                        assert direct_retention.gc_matching_revision_refs == ()
                        assert direct_retention.worker_backup_references is not None
                        assert (
                            direct_retention.worker_backup_references.references == ()
                        )
                        assert (
                            "worker_backup_references_unverified"
                            not in direct_retention.missing_proofs
                        )
                        with monkeypatch.context() as altered_backup_topology:
                            altered_backup_topology.setattr(
                                backup_types_module,
                                "_SUPPORTED_BACKUP_KINDS",
                                ("arch_private_data", "worker_attempt"),
                            )
                            with pytest.raises(
                                ValueError,
                                match="backup topology changed",
                            ):
                                review_coding_product_worker_history_retention(
                                    product,
                                    attempt_id=direct_gate_attempts[0].attempt_id,
                                )
                        backup_topology_path = (
                            product.state_root / "coding-backup-types.json"
                        )
                        hidden_topology_path = (
                            product.state_root / "coding-backup-types.hidden"
                        )
                        backup_topology_path.rename(hidden_topology_path)
                        try:
                            with pytest.raises(
                                ValueError,
                                match="absent after Worker history",
                            ):
                                review_coding_product_worker_history_retention(
                                    product,
                                    attempt_id=direct_gate_attempts[0].attempt_id,
                                )
                        finally:
                            hidden_topology_path.rename(backup_topology_path)
                        assert direct_retention.unverified_receipt_gate_references == ()
                        assert direct_retention.attempt_record is not None
                        assert history_retention_module._receipt_gate_reference_issue(
                            direct_gate_attempts[0],
                            direct_retention.receipt_record,
                            direct_retention.attempt_record,
                            "present",
                        ) == "receipt_reference_native_absence_unverified"
                        mismatched_gate = gate_journal_module.CodingWorkerStartGateRecordV1.create(
                            journal_revision=direct_gate_attempts[0].journal_revision,
                            phase=direct_gate_attempts[0].phase,
                            attempt_id=direct_gate_attempts[0].attempt_id,
                            worker_identity_fingerprint=(
                                direct_gate_attempts[0].worker_identity_fingerprint
                            ),
                            receipt_fingerprint="0" * 64,
                            policy_fingerprint=direct_gate_attempts[0].policy_fingerprint,
                            scope_id=direct_gate_attempts[0].scope_id,
                            native_closure_digest=(
                                direct_gate_attempts[0].native_closure_digest
                            ),
                            identity=direct_gate_attempts[0].identity,
                        )
                        assert history_retention_module._receipt_gate_reference_issue(
                            mismatched_gate,
                            direct_retention.receipt_record,
                            direct_retention.attempt_record,
                            "absent",
                        ) == "receipt_reference_binding_changed"
                        assert (
                            replace(
                                direct_retention, gate_record=mismatched_gate
                            ).attempt_reference
                            is None
                        )
                        assert direct_retention.activation_state_revision == 0
                        assert (
                            "activation_state_absent"
                            not in direct_retention.missing_proofs
                        )
                        activation_path = (
                            product.state_root / "worker-activation-state.jsonl"
                        )
                        hidden_activation_path = (
                            product.state_root / "worker-activation-state.hidden"
                        )
                        activation_path.rename(hidden_activation_path)
                        try:
                            with pytest.raises(
                                WorkerActivationStateJournalError,
                                match="worker_activation_state_orphan_lock",
                            ):
                                review_coding_product_worker_history_retention(
                                    product,
                                    attempt_id=direct_gate_attempts[0].attempt_id,
                                )
                        finally:
                            hidden_activation_path.rename(activation_path)
                        assert (
                            "receipt_references_unverified"
                            in direct_retention.missing_proofs
                        )
                        if disable_while_direct_session_open:
                            with pytest.raises(
                                PackageProductRuntimeReadError
                            ) as disabled_new_session:
                                create_agent_session(
                                    session_manager=asyncio.run(
                                        SessionManager.load(selected_transcript)
                                    ),
                                    model=direct_model,
                                    services=create_services(settings_manager=settings),
                                    worker_candidate_plugin_id=_PLUGIN,
                                )
                            assert disabled_new_session.value.code == (
                                "package_product_root_not_selected"
                            )
                        return
                    if hosted_entry_only:
                        payloads_before_hosted = frozenset(
                            product.state_root.glob("worker-payload-*")
                        )
                        supervisor_journal = (
                            open_coding_product_worker_supervisor_journal(product)
                        )
                        incomplete_before_hosted = supervisor_journal.incomplete()
                        hosted_sessions_parent = tmp_path / "hosted-session-files"
                        hosted_sessions_parent.mkdir(mode=0o700)
                        hosted_runtime = create_agent_session_runtime(
                            session_dir=hosted_sessions_parent / "sessions",
                            model=Model(
                                id="hosted-worker",
                                name="Hosted Worker",
                                provider="test",
                                endpoint="test",
                                capabilities=Capabilities(
                                    input=("text",),
                                    context_window=128_000,
                                    max_tokens=4_096,
                                ),
                            ),
                            services=create_services(settings_manager=settings),
                            worker_candidate_plugin_id=_PLUGIN,
                        )

                        async def exercise_hosted_worker() -> None:
                            try:
                                session = await hosted_runtime.create_session(
                                    cwd=str(workspace)
                                )
                                assert session.session_manager.is_persisted()
                                await session.prepare_model_call_runtime()
                                assert await session.query_worker_symbol(
                                    "review"
                                ) == "Review symbol"
                                assert any(
                                    item.name == "worker-extra"
                                    for item in session.resource_bundle.skills
                                )
                                revoked = product_opt_in.revoke(
                                    plugin_id=_PLUGIN,
                                    operation_id="worker-hosted-session-revoke",
                                    expected_generation=decision.generation,
                                )
                                assert revoked.action == "revoke"
                                assert revoked.kill_switch_generation == (
                                    decision.kill_switch_generation + 1
                                )
                                with pytest.raises(
                                    CapabilityWorkerFacetProxyError,
                                    match="worker_capability_facet_proxy_owner_unavailable",
                                ):
                                    await session.query_worker_symbol("review")
                            finally:
                                await hosted_runtime.dispose_session_runtime()

                        asyncio.run(exercise_hosted_worker())
                        assert frozenset(product.state_root.glob("worker-payload-*")) == (
                            payloads_before_hosted
                        )
                        assert supervisor_journal.incomplete() == incomplete_before_hosted
                        return
                if native_mode == "installed-release":
                    settled_start_attempt = "ad" * 16
                    with materialize_coding_product_worker_payload(
                        receipt_owner=receipt_owner,
                        receipt=receipt,
                        attempt_id=settled_start_attempt,
                    ) as settled_start_lease:
                        settled_start_request = (
                            bind_coding_product_worker_launch_request(
                                receipt_owner=receipt_owner,
                                receipt=receipt,
                                payload_lease=settled_start_lease,
                                supervisor_epoch=2,
                            )
                        )
                        validate_selected = settled_start_request.validate_current
                        changed_after_preflight = False

                        def change_selected_after_preflight() -> None:
                            nonlocal changed_after_preflight
                            validate_selected()
                            if not changed_after_preflight:
                                stored_payload.write_bytes(b"changed after preflight")
                                changed_after_preflight = True

                        settled_start_request = replace(
                            settled_start_request,
                            validate_current=change_selected_after_preflight,
                        )
                        settled_start_profile = _bind_posix_static_contained_product_worker_profile(
                            receipt=receipt,
                            worker_request=settled_start_request,
                            native_profile_catalog_revision=(
                                launch_material.closure.native_profile_catalog_revision
                            ),
                            launcher_path=launch_material.launcher_path,
                            launcher_sha256=(
                                launch_material.closure.containment_launcher_digest
                            ),
                            containment_profile_sha256=(
                                launch_material.closure.containment_profile_digest
                            ),
                        )

                        async def exercise_settled_product_start_refusal() -> None:
                            host = _native_host()
                            journal = open_coding_product_worker_supervisor_journal(
                                product
                            )
                            supervisor = WorkerSupervisor(
                                identity=settled_start_request.identity,
                                journal=journal,
                                protocol=settled_start_request.runtime.protocol,
                                protocol_version=(
                                    settled_start_request.runtime.protocol_version
                                ),
                            )
                            try:
                                adapter = HostingManagedWorkerSessionAdapter(
                                    hosting=host,
                                    preparation=settled_start_profile,
                                )
                                with pytest.raises(WorkerSupervisorError) as failed:
                                    await supervisor.start_session(
                                        session_port=adapter,
                                        launch_request=settled_start_request,
                                        correlation_id="product-worker-preparation-refusal",
                                    )
                                assert failed.value.code == "worker_launch_failed"
                                assert changed_after_preflight
                                settled = journal.status(settled_start_attempt)
                                assert settled is not None
                                assert settled.phase == "process_settled"
                            finally:
                                stored_payload.write_bytes(selected_payload.body)
                                await settled_start_profile.close()
                                await host.close()

                        asyncio.run(exercise_settled_product_start_refusal())
                    assert not settled_start_lease.runtime.package_root.exists()
                if native_mode == "installed-protocol":
                    journaled_root = product.state_root / f"worker-payload-{attempt_id}"
                    # Reopen a complete stage left by an older Product version.
                    # Current materialization must never recreate this settled ID.
                    journaled_root.mkdir(mode=0o700)
                    stage_fd = os.open(
                        journaled_root,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    )
                    try:
                        worker_payload_module._write_payload(
                            stage_fd,
                            selected_payload.configuration.entrypoint,
                            selected_payload.body,
                        )
                        stage_stat = os.fstat(stage_fd)
                        worker_payload_module._write_marker(
                            stage_fd,
                            worker_payload_module.CodingWorkerPayloadDebtPlanV1(
                                attempt_id=attempt_id,
                                entrypoint=selected_payload.configuration.entrypoint,
                                payload_digest=selected_payload.digest,
                                payload_size=len(selected_payload.body),
                                receipt_fingerprint=receipt.fingerprint,
                                stage_device=stage_stat.st_dev,
                                stage_inode=stage_stat.st_ino,
                            ),
                        )
                    finally:
                        os.close(stage_fd)
                    with pytest.raises(
                        CodingWorkerPayloadMaterializationError
                    ) as retained_journaled_stage:
                        with materialize_coding_product_worker_payload(
                            receipt_owner=receipt_owner,
                            receipt=receipt,
                            attempt_id=attempt_id,
                        ):
                            pass
                    assert retained_journaled_stage.value.code == (
                        "coding_worker_payload_attempt_debt"
                    )
                if native_mode == "installed-release":
                    partial_attempt = "ba" * 16

                    def fail_marker_write(_stage_fd: int, _plan: object) -> None:
                        raise OSError("injected marker write failure")

                    with monkeypatch.context() as patch:
                        patch.setattr(
                            worker_payload_module,
                            "_write_marker",
                            fail_marker_write,
                        )
                        with pytest.raises(
                            OSError, match="injected marker write failure"
                        ):
                            with materialize_coding_product_worker_payload(
                                receipt_owner=receipt_owner,
                                receipt=receipt,
                                attempt_id=partial_attempt,
                            ):
                                pass
                    assert not (
                        product.state_root / f"worker-payload-{partial_attempt}"
                    ).exists()
                    race_attempt = "bc" * 16
                    race_root = product.state_root / f"worker-payload-{race_attempt}"
                    retained_race_root = product.state_root / "retained-worker-race"
                    foreign_member = race_root / "foreign-member"
                    original_unlink = os.unlink
                    swapped_on_unlink = False

                    def replace_stage_before_leaf_unlink(
                        name: str, *, dir_fd: int | None = None
                    ) -> None:
                        nonlocal swapped_on_unlink
                        if name == "query-worker" and not swapped_on_unlink:
                            swapped_on_unlink = True
                            race_root.rename(retained_race_root)
                            race_root.mkdir(mode=0o700)
                            foreign_member.write_bytes(b"keep foreign contents")
                        original_unlink(name, dir_fd=dir_fd)

                    with monkeypatch.context() as patch:
                        patch.setattr(
                            worker_payload_module.os,
                            "unlink",
                            replace_stage_before_leaf_unlink,
                        )
                        with pytest.raises(
                            CodingWorkerPayloadMaterializationError
                        ) as replaced_during_cleanup:
                            with materialize_coding_product_worker_payload(
                                receipt_owner=receipt_owner,
                                receipt=receipt,
                                attempt_id=race_attempt,
                            ):
                                pass
                    assert swapped_on_unlink
                    assert replaced_during_cleanup.value.code == (
                        "coding_worker_payload_stage_changed"
                    )
                    assert foreign_member.read_bytes() == b"keep foreign contents"
                    foreign_member.unlink()
                    race_root.rmdir()
                    retained_race_root.rmdir()
                debt_attempt = "cd" * 16
                debt_root = product.state_root / f"worker-payload-{debt_attempt}"
                debt_root.mkdir(mode=0o700)
                debt_marker = debt_root / "debt-marker"
                debt_marker.write_bytes(b"unresolved")
                with pytest.raises(
                    CodingWorkerPayloadMaterializationError
                ) as unresolved_attempt:
                    with materialize_coding_product_worker_payload(
                        receipt_owner=receipt_owner,
                        receipt=receipt,
                        attempt_id=debt_attempt,
                    ):
                        pass
                assert (
                    unresolved_attempt.value.code
                    == "coding_worker_payload_attempt_debt"
                )
                assert debt_marker.read_bytes() == b"unresolved"
                debt_marker.unlink()
                debt_root.rmdir()
                if native_mode == "repaired-release":
                    crash_attempt = "af" * 16
                    crash_journal = open_coding_product_worker_supervisor_journal(
                        product
                    )
                    prior = crash_journal.status(attempt_id)
                    assert prior is not None and prior.process_settled
                    moved_crash_root = product.state_root / "retained-crash-payload"
                    with pytest.raises(
                        CodingWorkerPayloadMaterializationError
                    ) as crash_stage:
                        with materialize_coding_product_worker_payload(
                            receipt_owner=receipt_owner,
                            receipt=receipt,
                            attempt_id=crash_attempt,
                        ) as crash_payload:
                            crash_request = bind_coding_product_worker_launch_request(
                                receipt_owner=receipt_owner,
                                receipt=receipt,
                                payload_lease=crash_payload,
                                supervisor_epoch=2,
                            )
                            claimed = crash_journal.claim(
                                crash_request.identity, max_attempts=3
                            )
                            launching = crash_journal.transition(
                                crash_attempt,
                                expected_phase="claimed",
                                next_phase="launching",
                                expected_record_revision=claimed.record_revision,
                                expected_supervisor_epoch=2,
                            )
                            crash_gate = CodingProductWorkerStartGate(
                                receipt_owner=receipt_owner,
                                receipt=receipt,
                                worker_request=crash_request,
                                attempt_id=crash_attempt,
                            )
                            crash_profile = _bind_posix_static_contained_product_worker_profile(
                                receipt=receipt,
                                worker_request=crash_request,
                                native_profile_catalog_revision=(
                                    launch_material.closure.native_profile_catalog_revision
                                ),
                                launcher_path=launch_material.launcher_path,
                                launcher_sha256=(
                                    launch_material.closure.containment_launcher_digest
                                ),
                                containment_profile_sha256=(
                                    launch_material.closure.containment_profile_digest
                                ),
                                start_gate_read_fd=crash_gate.start_gate_read_fd,
                            )

                            libc = ctypes.CDLL(None, use_errno=True)
                            prior_subreaper = ctypes.c_int()
                            assert (
                                libc.prctl(37, ctypes.byref(prior_subreaper), 0, 0, 0)
                                == 0
                            )
                            assert libc.prctl(36, 1, 0, 0, 0) == 0
                            report_read, report_write = os.pipe2(os.O_CLOEXEC)
                            crash_host_pid = -1
                            crash_native_identity = None
                            try:
                                crash_host_pid = os.fork()
                                if crash_host_pid == 0:
                                    os.close(report_read)

                                    async def start_then_crash() -> None:
                                        host = _native_host(max_capture_slots=4)
                                        adapter = HostingManagedWorkerSessionAdapter(
                                            hosting=host,
                                            preparation=crash_profile,
                                            start_gate=bind_worker_gated_start_release(
                                                crash_gate
                                            ),
                                        )
                                        await adapter.start(
                                            crash_request,
                                            correlation_id="product-worker-crash-debt",
                                        )
                                        os.write(report_write, b"S")
                                        os._exit(0)

                                    try:
                                        asyncio.run(start_then_crash())
                                    except BaseException:
                                        os._exit(2)
                                    os._exit(3)
                                os.close(report_write)
                                report_write = -1
                                assert select.select([report_read], [], [], 30)[0]
                                assert os.read(report_read, 1) == b"S"
                                assert os.waitpid(crash_host_pid, 0)[1] == 0
                                crash_host_pid = -1
                                crash_bound = CodingWorkerStartGateJournal(
                                    product
                                ).current(crash_attempt)
                                assert crash_bound is not None
                                assert crash_bound.phase == "bound"
                                assert crash_bound.identity is not None
                                crash_native_identity = crash_bound.identity
                            finally:
                                os.close(report_read)
                                if report_write >= 0:
                                    os.close(report_write)
                                if crash_host_pid > 0:
                                    with suppress(ProcessLookupError):
                                        os.kill(crash_host_pid, signal.SIGKILL)
                                    with suppress(ChildProcessError):
                                        os.waitpid(crash_host_pid, 0)
                                assert (
                                    libc.prctl(36, prior_subreaper.value, 0, 0, 0) == 0
                                )
                                crash_gate.close()
                                asyncio.run(crash_profile.close())
                                if crash_native_identity is not None:
                                    group_status = (
                                        worker_native_group_status_after_restart(
                                            crash_native_identity
                                        )
                                    )
                                    if group_status == "present":
                                        with suppress(ProcessLookupError):
                                            os.killpg(
                                                crash_native_identity.pid,
                                                signal.SIGKILL,
                                            )
                                    deadline = time.monotonic() + 5
                                    while time.monotonic() < deadline:
                                        try:
                                            reaped_pid, _ = os.waitpid(
                                                crash_native_identity.pid,
                                                os.WNOHANG,
                                            )
                                        except ChildProcessError:
                                            break
                                        if reaped_pid == crash_native_identity.pid:
                                            break
                                        time.sleep(0.01)
                                    else:
                                        pytest.fail(
                                            "crashed Product Worker was not reaped"
                                        )
                                    assert worker_native_group_absent_after_restart(
                                        crash_native_identity
                                    )
                            assert not launching.process_settled
                            crash_root = crash_payload.runtime.package_root
                            crash_root.rename(moved_crash_root)
                            crash_root.symlink_to(
                                moved_crash_root, target_is_directory=True
                            )
                    assert crash_stage.value.code == (
                        "coding_worker_payload_stage_changed"
                    )
                    crash_root.unlink()
                    moved_crash_root.rename(crash_root)
                swapped_attempt = "ef" * 16
                moved_root = product.state_root / "retained-worker-payload"
                with pytest.raises(
                    CodingWorkerPayloadMaterializationError
                ) as swapped_stage:
                    with materialize_coding_product_worker_payload(
                        receipt_owner=receipt_owner,
                        receipt=receipt,
                        attempt_id=swapped_attempt,
                    ) as swapped_lease:
                        swapped_root = swapped_lease.runtime.package_root
                        swapped_root.rename(moved_root)
                        swapped_root.symlink_to(moved_root, target_is_directory=True)
                assert swapped_stage.value.code == "coding_worker_payload_stage_changed"
                assert moved_root.is_dir()
                swapped_root.unlink()
                moved_root.rename(swapped_root)
                with pytest.raises(
                    CodingWorkerPayloadMaterializationError
                ) as active_repair:
                    preview_coding_product_worker_payload_debt(
                        product, attempt_id=swapped_attempt
                    )
                assert (
                    active_repair.value.code == "coding_worker_payload_runtime_active"
                )
                with pytest.raises(CodingWorkerReceiptError) as forged_launch:
                    receipt_owner.current_native_launch_material(
                        replace(receipt, issue_nonce="forged")
                    )
                assert forged_launch.value.code == "coding_worker_receipt_stale"
                retained_wheel = installation_root / "source.whl"
                retained_wheel_bytes = retained_wheel.read_bytes()
                retained_wheel.write_bytes(b"changed source Wheel")
                with pytest.raises(CodingWorkerNativeReleaseError):
                    native_reader.current_launch_material()
                with pytest.raises(CodingWorkerReceiptError) as stale_launch:
                    receipt_owner.current_native_launch_material(receipt)
                assert stale_launch.value.code == "coding_worker_receipt_stale"
                assert (
                    receipt_owner.current_witness(receipt) != receipt.authority_witness
                )
                retained_wheel.write_bytes(retained_wheel_bytes)
                assert (
                    receipt_owner.current_witness(receipt) == receipt.authority_witness
                )
                native_receipt = installation_root / "product-native-release.json"
                retained_receipt = installation_root / "retained-receipt.json"
                native_receipt.rename(retained_receipt)
                native_receipt.symlink_to(retained_receipt)
                with pytest.raises(CodingWorkerNativeReleaseError):
                    native_reader.current_launch_material()
                with pytest.raises(CodingWorkerReceiptError):
                    receipt_owner.current_native_launch_material(receipt)
                assert (
                    receipt_owner.current_witness(receipt) != receipt.authority_witness
                )
                native_receipt.unlink()
                retained_receipt.rename(native_receipt)
                assert (
                    receipt_owner.current_witness(receipt) == receipt.authority_witness
                )
            else:
                with pytest.raises(CodingWorkerReceiptError) as unbound_launch:
                    receipt_owner.current_native_launch_material(receipt)
                assert (
                    unbound_launch.value.code == "coding_worker_native_launch_unbound"
                )
            if has_native_release:
                launcher = (
                    release / "containment-launcher"
                    if native_mode == "built-release"
                    else installation_root
                    / "loushang_h6_native/release/containment-launcher"
                )
                launcher_bytes = launcher.read_bytes()
                launcher.unlink()
                launcher.write_bytes(b"changed launcher")
                launcher.chmod(0o500)
                if installed_native:
                    with pytest.raises(CodingWorkerNativeReleaseError):
                        native_reader.current_launch_material()
                    with pytest.raises(CodingWorkerReceiptError):
                        receipt_owner.current_native_launch_material(receipt)
            else:
                assert isinstance(native_reader, _ProductNativeClosureReader)
                native_reader.fail()
            assert receipt_owner.current_witness(receipt) != receipt.authority_witness
            if has_native_release:
                launcher.unlink()
                launcher.write_bytes(launcher_bytes)
                launcher.chmod(0o500)
            else:
                native_reader.change(test_closure)
            assert receipt_owner.current_witness(receipt) == receipt.authority_witness
            if native_mode == "installed-release":
                assert (
                    execute_native_cli(
                        product,
                        Namespace(
                            action="revoke",
                            operation_id="revoke-native-release-one",
                            expected_generation=1,
                        ),
                    )["approvalDecision"]
                    == approval_owner.current().to_dict()
                )
                with pytest.raises(CodingWorkerNativeReleaseError):
                    native_reader.current_closure()
                assert (
                    receipt_owner.current_witness(receipt) != receipt.authority_witness
                )
                assert (
                    execute_native_cli(
                        product,
                        Namespace(
                            action="approve",
                            wheel=str(native_wheel_path),
                            review_id=review.review_id,
                            operation_id="reapprove-native-release-one",
                            expected_generation=2,
                        ),
                    )["approvalDecision"]
                    == approval_owner.current().to_dict()
                )
                assert (
                    receipt_owner.current_witness(receipt) != receipt.authority_witness
                )
                expected_native_closure = native_reader.current_closure()
                assert expected_native_closure.native_profile_catalog_revision.endswith(
                    ":g3"
                )
                fresh_receipt = receipt_owner.issue()
                assert fresh_receipt is not None
                assert fresh_receipt != receipt
                assert (
                    receipt_owner.current_witness(fresh_receipt)
                    == fresh_receipt.authority_witness
                )
                fresh_attempt = "ae" * 16
                with materialize_coding_product_worker_payload(
                    receipt_owner=receipt_owner,
                    receipt=fresh_receipt,
                    attempt_id=fresh_attempt,
                ) as fresh_payload:
                    fresh_request = bind_coding_product_worker_launch_request(
                        receipt_owner=receipt_owner,
                        receipt=fresh_receipt,
                        payload_lease=fresh_payload,
                        supervisor_epoch=1,
                    )
                    fresh_material = receipt_owner.current_native_launch_material(
                        fresh_receipt
                    )
                    fresh_gate = CodingProductWorkerStartGate(
                        receipt_owner=receipt_owner,
                        receipt=fresh_receipt,
                        worker_request=fresh_request,
                        attempt_id=fresh_attempt,
                    )
                    fresh_profile = _bind_posix_static_contained_product_worker_profile(
                        receipt=fresh_receipt,
                        worker_request=fresh_request,
                        native_profile_catalog_revision=(
                            fresh_material.closure.native_profile_catalog_revision
                        ),
                        launcher_path=fresh_material.launcher_path,
                        launcher_sha256=(
                            fresh_material.closure.containment_launcher_digest
                        ),
                        containment_profile_sha256=(
                            fresh_material.closure.containment_profile_digest
                        ),
                        start_gate_read_fd=fresh_gate.start_gate_read_fd,
                    )

                    async def exercise_fresh_native_gate() -> None:
                        host = _native_host(max_capture_slots=4)
                        try:
                            adapter = HostingManagedWorkerSessionAdapter(
                                hosting=host,
                                preparation=fresh_profile,
                                start_gate=bind_worker_gated_start_release(fresh_gate),
                            )
                            session = await adapter.start(
                                fresh_request,
                                correlation_id="product-worker-fresh-gated-start",
                            )
                            try:
                                await session.terminate()
                            finally:
                                await session.close()
                        finally:
                            fresh_gate.close()
                            await fresh_profile.close()
                            await host.close()

                    asyncio.run(exercise_fresh_native_gate())
            disabled = product.management.submit(
                PluginManagementCommandV1(
                    action="disable",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id="worker-catalog-disable",
                        idempotency_key="worker-catalog-disable",
                        expected_inventory_revision=product.desired_state.snapshot().inventory_revision,
                        installation_key=installations[0].installation_key,
                        desired_state="installed_disabled",
                        package_revision=None,
                        actor_id=product.actor_id,
                        policy_revision=product.desired_policy_revision,
                    ),
                )
            )
            assert disabled.status == "terminal"
            assert receipt_owner.current_witness(receipt) != receipt.authority_witness
            if installed_native:
                with pytest.raises(CodingWorkerProductOptInError) as stale_selection:
                    product_opt_in.allow(
                        plugin_id=_PLUGIN,
                        operation_id="worker-after-disable-allow",
                        expected_generation=1,
                        require_worker=False,
                    )
                assert stale_selection.value.code == (
                    "coding_worker_opt_in_selection_unavailable"
                )
                revoke_output = execute_native_cli(
                    product,
                    Namespace(
                        action="candidate-revoke",
                        plugin_id=_PLUGIN,
                        operation_id="worker-after-disable-revoke",
                        expected_generation=1,
                    ),
                )
                revoked_opt_in = product_opt_in.current(_PLUGIN)
                assert revoked_opt_in is not None
                assert revoke_output == {
                    "candidateOptInDecision": revoked_opt_in.to_dict(),
                    "ordinarySessionRouting": "python_sdk_explicit_linux",
                    "defaultSessionRouting": "closed",
                }
                assert revoked_opt_in.action == "revoke"
                assert revoked_opt_in.kill_switch_generation == 1
                assert product_opt_in.current(_PLUGIN) == revoked_opt_in
                with pytest.raises(CodingWorkerReceiptError) as disabled_launch:
                    receipt_owner.current_native_launch_material(receipt)
                assert disabled_launch.value.code == "coding_worker_receipt_stale"
            with pytest.raises(PackageProductRuntimeReadError):
                open_coding_selected_worker_receipt_owner(
                    product_owner=product,
                    runtime=runtime,
                    plugin_id=_PLUGIN,
                    native_closure_reader=native_reader,
                    transcript_directory=transcript_directory,
                    session_manager=session_manager,
                )
        finally:
            runtime.dispose_runtime()
    finally:
        explicit.close()
    if installed_native:
        reopened = open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
            worker_candidates=True,
        )
        try:
            reopened_reader = open_coding_product_installed_worker_release_reader(
                reopened.runtime_owner.product_owner
            )
            assert reopened_reader.current_closure() == expected_native_closure
            reopened_product = reopened.runtime_owner.product_owner
            reopened_attempt = open_coding_product_worker_supervisor_journal(
                reopened_product
            ).status(attempt_id)
            assert reopened_attempt is not None
            assert reopened_attempt.terminal
            assert reopened_attempt.identity_fingerprint == (
                worker_request.identity.fingerprint
            )
            if native_mode in {"installed-release", "repaired-release"}:
                reopened_gate = CodingWorkerStartGateJournal(reopened_product).current(
                    attempt_id
                )
                assert reopened_gate is not None
                assert reopened_gate.phase == "bound"
                assert reopened_gate.worker_identity_fingerprint == (
                    reopened_attempt.identity_fingerprint
                )
                assert reopened_gate.identity is not None
                assert worker_native_group_absent_after_restart(reopened_gate.identity)
                gated_recovery = review_coding_product_worker_gated_recovery(
                    reopened_product, attempt_id=attempt_id
                )
                assert gated_recovery.gate_record == reopened_gate
                assert gated_recovery.attempt_record == reopened_attempt
                # Installed-release was reapproved at g3 above; repaired-release
                # keeps the exact native generation used by this attempt.
                assert gated_recovery.native_closure_current == (
                    native_mode == "repaired-release"
                )
                assert gated_recovery.group_status == "absent"
                assert gated_recovery.same_boot_settlement_candidate == (
                    native_mode == "repaired-release"
                    and reopened_attempt.phase in {"failed", "fenced"}
                )
                with pytest.raises(CodingWorkerGatedRecoveryError) as no_settlement:
                    settle_coding_product_worker_gated_attempt(
                        reopened_product,
                        expected_review=gated_recovery,
                        expected_plan=preview_coding_product_worker_payload_debt(
                            reopened_product, attempt_id=swapped_attempt
                        ),
                    )
                assert no_settlement.value.code == (
                    "coding_worker_gated_recovery_unproven"
                )
                if native_mode == "installed-release":
                    fresh_recovery = review_coding_product_worker_gated_recovery(
                        reopened_product, attempt_id=fresh_attempt
                    )
                    assert fresh_recovery.gate_record is not None
                    assert fresh_recovery.gate_record.phase == "bound"
                    assert fresh_recovery.attempt_record is None
                    assert fresh_recovery.native_closure_current
                    assert fresh_recovery.group_status == "absent"
                    assert not fresh_recovery.same_boot_settlement_candidate
                else:
                    crash_plan = preview_coding_product_worker_payload_debt(
                        reopened_product, attempt_id=crash_attempt
                    )
                    crash_review = review_coding_product_worker_gated_recovery(
                        reopened_product, attempt_id=crash_attempt
                    )
                    assert crash_review.same_boot_settlement_candidate
                    with monkeypatch.context() as patch:
                        patch.setattr(
                            gated_recovery_module,
                            "worker_native_group_status_after_restart",
                            lambda _: "present",
                        )
                        live_review = review_coding_product_worker_gated_recovery(
                            reopened_product, attempt_id=crash_attempt
                        )
                        assert live_review.group_status == "present"
                        assert not live_review.settlement_candidate
                        with pytest.raises(CodingWorkerGatedRecoveryError) as live:
                            settle_coding_product_worker_gated_attempt(
                                reopened_product,
                                expected_review=live_review,
                                expected_plan=crash_plan,
                            )
                        assert live.value.code == (
                            "coding_worker_gated_recovery_unproven"
                        )
                    assert (
                        open_coding_product_worker_supervisor_journal(
                            reopened_product
                        ).status(crash_attempt)
                        == crash_review.attempt_record
                    )
                    with pytest.raises(CodingWorkerGatedRecoveryError) as wrong_debt:
                        settle_coding_product_worker_gated_attempt(
                            reopened_product,
                            expected_review=crash_review,
                            expected_plan=preview_coding_product_worker_payload_debt(
                                reopened_product, attempt_id=swapped_attempt
                            ),
                        )
                    assert wrong_debt.value.code == (
                        "coding_worker_gated_recovery_attempt_mismatch"
                    )
                    with pytest.raises(CodingWorkerGatedRecoveryError) as stale_review:
                        settle_coding_product_worker_gated_attempt(
                            reopened_product,
                            expected_review=replace(
                                crash_review, native_closure_current=False
                            ),
                            expected_plan=crash_plan,
                        )
                    assert stale_review.value.code == (
                        "coding_worker_gated_recovery_review_stale"
                    )
                    with pytest.raises(CodingWorkerGatedRecoveryError) as wrong_receipt:
                        settle_coding_product_worker_gated_attempt(
                            reopened_product,
                            expected_review=crash_review,
                            expected_plan=replace(
                                crash_plan, receipt_fingerprint="0" * 64
                            ),
                        )
                    assert wrong_receipt.value.code == (
                        "coding_worker_gated_recovery_payload_mismatch"
                    )
                    before_settlement = open_coding_product_worker_supervisor_journal(
                        reopened_product
                    ).status(crash_attempt)
                    assert before_settlement is not None
                    assert before_settlement.phase == "launching"
                    original_read = service_group_module._read_file

                    def changed_boot_read(
                        path: str, *, parent: int | None = None, limit: int = 4096
                    ) -> bytes:
                        if path == "/proc/sys/kernel/random/boot_id":
                            return b"00000000-0000-0000-0000-000000000000\n"
                        return original_read(path, parent=parent, limit=limit)

                    with monkeypatch.context() as patch:
                        patch.setattr(
                            service_group_module, "_read_file", changed_boot_read
                        )
                        changed_boot_review = (
                            review_coding_product_worker_gated_recovery(
                                reopened_product, attempt_id=crash_attempt
                            )
                        )
                        assert changed_boot_review.group_status == ("prior_boot_absent")
                        assert changed_boot_review.prior_boot_settlement_candidate
                        original_transition = WorkerSupervisorJournal.transition

                        def fail_after_failure_record(
                            journal: WorkerSupervisorJournal,
                            attempt: str,
                            **kwargs: object,
                        ):
                            if kwargs["next_phase"] == "process_settled":
                                raise OSError("injected settlement interruption")
                            return original_transition(journal, attempt, **kwargs)

                        with monkeypatch.context() as interrupt:
                            interrupt.setattr(
                                WorkerSupervisorJournal,
                                "transition",
                                fail_after_failure_record,
                            )
                            with pytest.raises(
                                OSError, match="settlement interruption"
                            ):
                                settle_coding_product_worker_gated_attempt(
                                    reopened_product,
                                    expected_review=changed_boot_review,
                                    expected_plan=crash_plan,
                                )
                        interrupted = open_coding_product_worker_supervisor_journal(
                            reopened_product
                        ).status(crash_attempt)
                        assert interrupted is not None
                        assert interrupted.phase == "failed"
                        assert interrupted.failure_code == "coding_worker_host_lost"
                        retry_review = review_coding_product_worker_gated_recovery(
                            reopened_product, attempt_id=crash_attempt
                        )
                        assert retry_review.prior_boot_settlement_candidate
                        settled_crash = settle_coding_product_worker_gated_attempt(
                            reopened_product,
                            expected_review=retry_review,
                            expected_plan=crash_plan,
                        )
                    assert settled_crash.process_settled
                    assert settled_crash.failure_code == "coding_worker_host_lost"
                    assert (
                        repair_coding_product_worker_payload_debt(
                            reopened_product, expected_plan=crash_plan
                        )
                        == crash_plan
                    )
                    assert not (
                        reopened_product.state_root / f"worker-payload-{crash_attempt}"
                    ).exists()
            journaled_root = (
                reopened_product.state_root / f"worker-payload-{attempt_id}"
            )
            has_journaled_debt = (
                not reopened_attempt.process_settled
                or native_mode == "installed-protocol"
            )
            debt_plan = preview_coding_product_worker_payload_debt(
                reopened_product, attempt_id=swapped_attempt
            )
            recovery_review = review_coding_product_worker_payload_recovery(
                reopened_product, attempt_id=swapped_attempt
            )
            assert recovery_review.plan == debt_plan
            assert recovery_review.attempt_record is None
            assert not recovery_review.process_wait_recorded
            if has_journaled_debt:
                journaled_plan = preview_coding_product_worker_payload_debt(
                    reopened_product, attempt_id=attempt_id
                )
                journaled_review = review_coding_product_worker_payload_recovery(
                    reopened_product, attempt_id=attempt_id
                )
                assert journaled_review.plan == journaled_plan
                assert journaled_review.attempt_record == reopened_attempt
                assert journaled_review.process_wait_recorded == (
                    reopened_attempt.process_settled
                )
            supervisor_journal_path = (
                reopened_product.state_root / "worker-supervisor.jsonl"
            )
            supervisor_journal_bytes = supervisor_journal_path.read_bytes()
            supervisor_journal_path.write_bytes(b"invalid supervisor history\n")
            try:
                with pytest.raises(WorkerSupervisorJournalError) as corrupt_review:
                    review_coding_product_worker_payload_recovery(
                        reopened_product, attempt_id=swapped_attempt
                    )
                assert corrupt_review.value.code == (
                    "worker_supervisor_journal_corrupt"
                )
                with pytest.raises(WorkerSupervisorJournalError) as corrupt_repair:
                    repair_coding_product_worker_payload_debt(
                        reopened_product, expected_plan=debt_plan
                    )
                assert corrupt_repair.value.code == (
                    "worker_supervisor_journal_corrupt"
                )
            finally:
                supervisor_journal_path.write_bytes(supervisor_journal_bytes)
            product_gc = open_posix_local_wheel_product_root_gc(reopened_product)
            with pytest.raises(
                PackageProductGcExecutionError,
                match="Worker payload attempt must settle",
            ) as gc_with_payload_debt:
                product_gc.prepare()
            assert gc_with_payload_debt.value.code == (
                "plugin_package_gc_worker_payload_unsettled"
            )
            expected_debts = (
                tuple(
                    sorted(
                        (journaled_plan, debt_plan), key=lambda plan: plan.attempt_id
                    )
                )
                if has_journaled_debt
                else (debt_plan,)
            )
            assert (
                list_coding_product_worker_payload_debts(reopened_product)
                == expected_debts
            )
            assert debt_plan.receipt_fingerprint == receipt.fingerprint
            assert debt_plan.payload_digest == selected_payload.digest
            partial_attempt = "12" * 16
            partial_root = reopened_product.state_root / (
                f"worker-payload-{partial_attempt}"
            )
            partial_root.mkdir(mode=0o700)
            with pytest.raises(CodingWorkerPayloadMaterializationError) as partial_list:
                list_coding_product_worker_payload_debts(reopened_product)
            assert partial_list.value.code == "coding_worker_payload_debt_unverified"
            with pytest.raises(CodingWorkerPayloadMaterializationError):
                preview_coding_product_worker_payload_debt(
                    reopened_product, attempt_id=partial_attempt
                )
            partial_root.rmdir()
            invalid_attempt_root = reopened_product.state_root / (
                "worker-payload-not-an-attempt"
            )
            invalid_attempt_root.mkdir(mode=0o700)
            with pytest.raises(CodingWorkerPayloadMaterializationError) as invalid_name:
                list_coding_product_worker_payload_debts(reopened_product)
            assert invalid_name.value.code == "coding_worker_payload_debt_unverified"
            invalid_attempt_root.rmdir()
            debt_marker = swapped_root / "product-payload.json"
            marker_bytes = debt_marker.read_bytes()
            debt_marker.write_bytes(b"changed")
            with pytest.raises(CodingWorkerPayloadMaterializationError):
                list_coding_product_worker_payload_debts(reopened_product)
            with pytest.raises(CodingWorkerPayloadMaterializationError):
                preview_coding_product_worker_payload_debt(
                    reopened_product, attempt_id=swapped_attempt
                )
            debt_marker.write_bytes(marker_bytes)
            foreign_member = swapped_root / "foreign"
            foreign_member.write_bytes(b"foreign")
            with pytest.raises(CodingWorkerPayloadMaterializationError):
                preview_coding_product_worker_payload_debt(
                    reopened_product, attempt_id=swapped_attempt
                )
            foreign_member.unlink()
            with pytest.raises(CodingWorkerPayloadMaterializationError) as stale_plan:
                repair_coding_product_worker_payload_debt(
                    reopened_product,
                    expected_plan=replace(debt_plan, payload_digest="0" * 64),
                )
            assert stale_plan.value.code == "coding_worker_payload_debt_plan_stale"
            with pytest.raises(
                CodingWorkerPayloadMaterializationError
            ) as unclaimed_repair:
                repair_coding_product_worker_payload_debt(
                    reopened_product, expected_plan=debt_plan
                )
            assert unclaimed_repair.value.code == (
                "coding_worker_payload_process_unsettled"
            )
            assert swapped_root.exists()
            if native_mode == "installed-protocol":
                assert (
                    repair_coding_product_worker_payload_debt(
                        reopened_product, expected_plan=journaled_plan
                    )
                    == journaled_plan
                )
                assert not journaled_root.exists()
                history_paths = (
                    reopened_product.gc_gate.path,
                    reopened_product.state_root / "worker-opt-in.jsonl",
                    reopened_product.state_root / "worker-activation-state.jsonl",
                    reopened_product.state_root / "worker-start-gates.jsonl",
                    reopened_product.state_root / "worker-activation-receipts.jsonl",
                    reopened_product.state_root / "worker-supervisor.jsonl",
                )
                history_before = tuple(
                    path.read_bytes() if path.exists() else None
                    for path in history_paths
                )
                entries_before = set(os.listdir(reopened_product.state_root))
                retention = review_coding_product_worker_history_retention(
                    reopened_product, attempt_id=journaled_plan.attempt_id
                )
                assert set(os.listdir(reopened_product.state_root)) == entries_before
                assert (
                    tuple(
                        path.read_bytes() if path.exists() else None
                        for path in history_paths
                    )
                    == history_before
                )
                assert retention.gate_record is not None
                assert retention.gate_record.phase == "bound"
                assert retention.attempt_record is not None
                assert retention.attempt_record.process_settled
                assert retention.receipt_record is not None
                assert retention.activation_state_revision == 0
                assert retention.active_activation_references == ()
                assert "activation_state_absent" not in retention.missing_proofs
                assert journaled_plan.attempt_id in retention.receipt_gate_references
                assert (
                    journaled_plan.attempt_id
                    not in retention.unsettled_receipt_gate_references
                )
                assert retention.group_status in {"absent", "prior_boot_absent"}
                assert "payload_stage_retained" in retention.missing_proofs
                assert retention.worker_backup_references is not None
                assert retention.worker_backup_references.references == ()
                assert "worker_backup_references_unverified" not in (
                    retention.missing_proofs
                )
            elif has_journaled_debt:
                with pytest.raises(
                    CodingWorkerPayloadMaterializationError
                ) as fenced_repair:
                    repair_coding_product_worker_payload_debt(
                        reopened_product, expected_plan=journaled_plan
                    )
                assert fenced_repair.value.code == (
                    "coding_worker_payload_process_unsettled"
                )
                assert journaled_root.exists()
            if native_mode == "test-facts":
                retention = review_coding_product_worker_history_retention(
                    reopened_product, attempt_id=swapped_attempt
                )
                assert retention.gate_record is None
                assert retention.attempt_reference is None
                assert retention.activation_state_revision == 2
                assert retention.active_activation_references == ()
                assert "start_gate_absent" in retention.missing_proofs
            expected_remaining_debts = (
                (debt_plan, journaled_plan)
                if has_journaled_debt and native_mode != "installed-protocol"
                else (debt_plan,)
            )
            assert list_coding_product_worker_payload_debts(reopened_product) == tuple(
                sorted(expected_remaining_debts, key=lambda plan: plan.attempt_id)
            )
            with pytest.raises(PackageProductGcExecutionError) as retained_gc:
                product_gc.prepare()
            assert retained_gc.value.code == (
                "plugin_package_gc_worker_payload_unsettled"
            )
        finally:
            reopened.close()
    if native_mode == "repaired-release":
        rearmed = open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
            worker_candidates=True,
        )
        try:
            rearmed_product = rearmed.runtime_owner.product_owner
            resumed = rearmed_product.management.submit(
                PluginManagementCommandV1(
                    action="enable",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id="worker-independent-crash-enable",
                        idempotency_key="worker-independent-crash-enable",
                        expected_inventory_revision=(
                            rearmed_product.desired_state.snapshot().inventory_revision
                        ),
                        installation_key=installations[0].installation_key,
                        desired_state="installed_enabled",
                        package_revision=None,
                        actor_id=rearmed_product.actor_id,
                        policy_revision=rearmed_product.desired_policy_revision,
                    ),
                )
            )
            assert resumed.status == "terminal"
            rearmed_opt_in = CodingWorkerProductOptInOwner(rearmed_product).allow(
                plugin_id=_PLUGIN,
                operation_id="worker-independent-crash-allow",
                expected_generation=2,
                require_worker=False,
            )
            assert rearmed_opt_in.opt_in is not None
            assert rearmed_opt_in.opt_in.owner_selection_generation == 3
        finally:
            rearmed.close()

        independent_attempt = "bd" * 16
        libc = ctypes.CDLL(None, use_errno=True)
        prior_subreaper = ctypes.c_int()
        assert libc.prctl(37, ctypes.byref(prior_subreaper), 0, 0, 0) == 0
        assert libc.prctl(36, 1, 0, 0, 0) == 0
        independent = None
        try:
            independent = subprocess.run(
                (
                    sys.executable,
                    "-c",
                    (
                        "from tests.coding.test_package_worker_candidate_wheel "
                        "import _run_independent_product_worker_crash; "
                        "import sys; _run_independent_product_worker_crash(*sys.argv[1:])"
                    ),
                    str(workspace),
                    str(selected_transcript),
                    independent_attempt,
                ),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=90,
                check=False,
            )
            recovered = open_coding_fenced_product_application_owner(
                lifecycle,
                workspace=workspace,
                runtime_version="2.0.0",
                runtime_protocol_epoch=2,
                worker_candidates=True,
            )
            try:
                recovered_product = recovered.runtime_owner.product_owner
                independent_gate = CodingWorkerStartGateJournal(
                    recovered_product
                ).current(independent_attempt)
                assert independent is not None
                assert independent.returncode == 0, independent.stderr
                assert independent_gate is not None
                assert independent_gate.phase == "bound"
                assert independent_gate.identity is not None
                historical_receipt = read_coding_product_worker_receipt_record(
                    recovered_product,
                    receipt_fingerprint=independent_gate.receipt_fingerprint,
                )
                assert historical_receipt is not None
                assert historical_receipt.receipt.policy.fingerprint == (
                    independent_gate.policy_fingerprint
                )
                assert (
                    historical_receipt.receipt.policy.product_runtime_id
                    == "worker-independent-crash"
                )
                assert (
                    read_coding_product_worker_receipt_record(
                        recovered_product, receipt_fingerprint="0" * 64
                    )
                    is None
                )
                native_identity = independent_gate.identity
                group_status = worker_native_group_status_after_restart(native_identity)
                if group_status == "present":
                    with suppress(ProcessLookupError):
                        os.killpg(native_identity.pid, signal.SIGKILL)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    try:
                        reaped_pid, _ = os.waitpid(native_identity.pid, os.WNOHANG)
                    except ChildProcessError:
                        break
                    if reaped_pid == native_identity.pid:
                        break
                    time.sleep(0.01)
                else:
                    pytest.fail("independent Product Worker was not reaped")
                assert worker_native_group_absent_after_restart(native_identity)
                # A separate operator opener owns no Session lease. It must be
                # able to leave the orphan untouched and still close.
                observer = open_coding_fenced_product_application_owner(
                    lifecycle,
                    workspace=workspace,
                    runtime_version="2.0.0",
                    runtime_protocol_epoch=2,
                    worker_candidates=True,
                )
                try:
                    observed_orphans = observer.epoch_runtime.registry.review_orphans(
                        store_id=observer.epoch_runtime.registry.store_id
                    )
                    assert any(
                        lease.runtime_id == "worker-independent-crash"
                        for lease in observed_orphans
                    )
                finally:
                    observer.close()
                registry = recovered_product.epoch_runtime.registry
                with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as orphan:
                    review_coding_product_worker_gated_recovery(
                        recovered_product, attempt_id=independent_attempt
                    )
                assert orphan.value.code == "package_epoch_lease_orphaned"
                orphan_review = review_coding_product_worker_orphan_runtime(
                    recovered_product, attempt_id=independent_attempt
                )
                assert orphan_review.repair_candidate
                assert orphan_review.receipt_record == historical_receipt
                assert orphan_review.orphan_lease is not None
                orphan_lease = orphan_review.orphan_lease
                assert orphan_lease.runtime_id == (
                    historical_receipt.receipt.policy.product_runtime_id
                )
                with monkeypatch.context() as patch:
                    patch.setattr(
                        gated_recovery_module,
                        "read_coding_product_worker_receipt_record",
                        lambda *_args, **_kwargs: None,
                    )
                    missing_receipt = review_coding_product_worker_orphan_runtime(
                        recovered_product, attempt_id=independent_attempt
                    )
                    assert not missing_receipt.repair_candidate
                    with pytest.raises(CodingWorkerGatedRecoveryError) as missing:
                        repair_coding_product_worker_orphan_runtime(
                            recovered_product, expected_review=missing_receipt
                        )
                    assert missing.value.code == (
                        "coding_worker_orphan_runtime_unproven"
                    )
                with monkeypatch.context() as patch:
                    patch.setattr(
                        gated_recovery_module,
                        "worker_native_group_status_after_restart",
                        lambda _: "present",
                    )
                    live_review = review_coding_product_worker_orphan_runtime(
                        recovered_product, attempt_id=independent_attempt
                    )
                    assert not live_review.repair_candidate
                    with pytest.raises(CodingWorkerGatedRecoveryError) as live:
                        repair_coding_product_worker_orphan_runtime(
                            recovered_product, expected_review=live_review
                        )
                    assert live.value.code == ("coding_worker_orphan_runtime_unproven")
                with pytest.raises(CodingWorkerGatedRecoveryError) as stale:
                    repair_coding_product_worker_orphan_runtime(
                        recovered_product,
                        expected_review=replace(orphan_review, orphan_lease=None),
                    )
                assert stale.value.code == "coding_worker_orphan_runtime_review_stale"
                cli_review = execute_native_cli(
                    recovered_product,
                    Namespace(
                        action="review-orphan-runtime",
                        attempt_id=independent_attempt,
                    ),
                )
                assert cli_review["orphanRuntimeReview"] == {
                    "attemptId": independent_attempt,
                    "reviewId": orphan_review.review_id,
                    "repairCandidate": True,
                    "groupStatus": "absent",
                    "supervisorPhase": "launching",
                    "leaseId": orphan_lease.lease_id,
                }
                with pytest.raises(CodingWorkerGatedRecoveryError) as stale_cli:
                    execute_native_cli(
                        recovered_product,
                        Namespace(
                            action="repair-orphan-runtime",
                            attempt_id=independent_attempt,
                            review_id="0" * 64,
                        ),
                    )
                assert stale_cli.value.code == (
                    "coding_worker_orphan_runtime_review_stale"
                )

                def run_recovery_cli(
                    *arguments: str,
                ) -> subprocess.CompletedProcess[bytes]:
                    return subprocess.run(
                        (
                            sys.executable,
                            "-m",
                            "loushang.coding.cli.package_worker_native",
                            "--workspace",
                            str(workspace),
                            *arguments,
                        ),
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=30,
                        check=False,
                    )

                fresh_review = run_recovery_cli(
                    "review-orphan-runtime", "--attempt-id", independent_attempt
                )
                assert fresh_review.returncode == 0, fresh_review.stderr
                assert json.loads(fresh_review.stdout) == cli_review
                fresh_wrong = run_recovery_cli(
                    "repair-orphan-runtime",
                    "--attempt-id",
                    independent_attempt,
                    "--review-id",
                    "0" * 64,
                )
                assert fresh_wrong.returncode == 1
                assert (
                    b"coding_worker_orphan_runtime_review_stale" in fresh_wrong.stderr
                )
                fresh_repair = run_recovery_cli(
                    "repair-orphan-runtime",
                    "--attempt-id",
                    independent_attempt,
                    "--review-id",
                    orphan_review.review_id,
                )
                assert fresh_repair.returncode == 0, fresh_repair.stderr
                assert json.loads(fresh_repair.stdout) == {
                    "orphanRuntimeRepair": {
                        "attemptId": independent_attempt,
                        "leaseId": orphan_lease.lease_id,
                        "reviewId": orphan_review.review_id,
                    }
                }
                assert registry.review_orphans(store_id=registry.store_id) == ()
                independent_review = review_coding_product_worker_gated_recovery(
                    recovered_product, attempt_id=independent_attempt
                )
                assert independent_review.same_boot_settlement_candidate
                assert independent_review.attempt_record is not None
                assert independent_review.attempt_record.phase == "launching"
                independent_plan = preview_coding_product_worker_payload_debt(
                    recovered_product, attempt_id=independent_attempt
                )
                fresh_gated = run_recovery_cli(
                    "review-gated-attempt", "--attempt-id", independent_attempt
                )
                assert fresh_gated.returncode == 0, fresh_gated.stderr
                gated_projection = json.loads(fresh_gated.stdout)["gatedRecoveryReview"]
                assert gated_projection["settlementCandidate"] is True
                assert gated_projection["groupStatus"] == "absent"
                assert gated_projection["supervisorPhase"] == "launching"
                assert gated_projection["planId"] == independent_plan.fingerprint
                premature_cleanup = run_recovery_cli(
                    "repair-payload-debt",
                    "--attempt-id",
                    independent_attempt,
                    "--plan-id",
                    independent_plan.fingerprint,
                )
                assert premature_cleanup.returncode == 1
                assert b"coding_worker_payload_process_unsettled" in (
                    premature_cleanup.stderr
                )
                stale_settlement = run_recovery_cli(
                    "settle-gated-attempt",
                    "--attempt-id",
                    independent_attempt,
                    "--review-id",
                    "0" * 64,
                    "--plan-id",
                    independent_plan.fingerprint,
                )
                assert stale_settlement.returncode == 1
                assert b"coding_worker_gated_recovery_review_stale" in (
                    stale_settlement.stderr
                )
                fresh_settlement = run_recovery_cli(
                    "settle-gated-attempt",
                    "--attempt-id",
                    independent_attempt,
                    "--review-id",
                    gated_projection["reviewId"],
                    "--plan-id",
                    independent_plan.fingerprint,
                )
                assert fresh_settlement.returncode == 0, fresh_settlement.stderr
                assert (
                    json.loads(fresh_settlement.stdout)["gatedAttemptSettlement"][
                        "phase"
                    ]
                    == "process_settled"
                )
                stale_cleanup = run_recovery_cli(
                    "repair-payload-debt",
                    "--attempt-id",
                    independent_attempt,
                    "--plan-id",
                    "0" * 64,
                )
                assert stale_cleanup.returncode == 1
                assert b"coding_worker_payload_debt_plan_stale" in stale_cleanup.stderr
                fresh_cleanup = run_recovery_cli(
                    "repair-payload-debt",
                    "--attempt-id",
                    independent_attempt,
                    "--plan-id",
                    independent_plan.fingerprint,
                )
                assert fresh_cleanup.returncode == 0, fresh_cleanup.stderr
                assert json.loads(fresh_cleanup.stdout) == {
                    "payloadDebtRepair": {
                        "attemptId": independent_attempt,
                        "planId": independent_plan.fingerprint,
                    }
                }
            finally:
                recovered.close()
        finally:
            assert libc.prctl(36, prior_subreaper.value, 0, 0, 0) == 0
    with pytest.raises(CodingExternalWorkerWheelError):
        admit_coding_external_worker_wheel(
            lifecycle, source=source, admission=admission
        )
    dependent_source = tmp_path / f"{_PLUGIN}-2-{_TAG}.whl"
    dependent_source.write_bytes(_worker_wheel(shape="dependency", version="2"))
    dependent_record = admit_coding_external_worker_wheel(
        lifecycle, source=dependent_source, admission=admission
    )
    dependent_owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        worker_candidates=True,
    )
    try:
        dependent_product = dependent_owner.runtime_owner.product_owner
        dependency_payload = _dependency_library_wheel()
        dependency_source = (
            dependent_product.policy.source_root / "dependency-1-py3-none-any.whl"
        )
        dependency_source.write_bytes(dependency_payload)
        dependency = PackageProductLocalWheelDependencyV1(
            source_identity=str(dependency_source),
            project_name="dependency",
            version="1",
            artifact_digest=sha256(dependency_payload).hexdigest(),
        )
        dependent_product = replace(
            dependent_product,
            policy=replace(dependent_product.policy, dependencies=(dependency,)),
        )
        dependent_runtime = dependent_product.factory_for_session(
            session_id="worker-dependency",
            cwd=workspace,
            runtime_id="worker-dependency",
        ).create(
            PackageProductRuntimeRequestV1(
                product_id="coding",
                session_id="worker-dependency",
                cwd=str(workspace),
            )
        )
        try:
            dependent_runtime.activate()
            admitted = dependent_runtime.lifecycle.route(
                PackageProductLifecycleIntentV1(
                    operation_id="worker-dependency-update",
                    action="update",
                    source=dependent_record.policy_binding(
                        dependent_product.policy.source_root
                    ).source_identity,
                    scope="project",
                ),
                entrypoint="cli",
            )
            assert admitted.handled
            assert admitted.record is not None
            assert admitted.record.lifecycle == "installed"
            prior = tuple(
                item
                for item in dependent_product.desired_state.snapshot().installations
                if item.installation_key.plugin_id == _PLUGIN
            )
            assert len(prior) == 1
            assert prior[0].selection.package_revision is not None
            assert prior[0].selection.package_revision.plugin_version == "2"
        finally:
            dependent_runtime.dispose_runtime()
    finally:
        dependent_owner.close()
    controlled.write_bytes(b"tampered controlled Worker Wheel")
    with pytest.raises(CodingExternalWorkerWheelError):
        open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
            worker_candidates=True,
        )
    controlled.write_bytes(payload)
    journal = product.state_root / "external-worker-wheel-bindings.jsonl"
    retained = tmp_path / "retained-worker-bindings.jsonl"
    journal.rename(retained)
    victim = tmp_path / "journal-victim"
    victim.write_bytes(b"private-data")
    journal.symlink_to(victim)
    with pytest.raises(CodingExternalWorkerWheelError):
        open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
            worker_candidates=True,
        )
    assert victim.read_bytes() == b"private-data"
    journal.unlink()
    retained.rename(journal)


@pytest.mark.requires_host_runtime
@pytest.mark.skipif(sys.platform != "linux", reason="Linux H6 release")
def test_explicit_worker_public_coding_session_reaches_installed_product(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_worker_source_catalog_pins_explicit_product_candidate(
        tmp_path,
        "installed-protocol",
        monkeypatch,
        direct_entry_only=True,
    )
    workspace = tmp_path / "workspace"
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    reopened = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        worker_candidates=True,
    )
    try:
        product = reopened.runtime_owner.product_owner
        gates = CodingWorkerStartGateJournal(product).attempts()
        assert gates
        gc = open_posix_local_wheel_product_root_gc(
            product,
            worker_history_authority=CodingPosixWorkerGcHistoryAuthority(product),
        )
        gc.prepare()
        gate = gates[0]
        receipt = gate.receipt_fingerprint
        attempt_id = gate.attempt_id
        key = _AttemptKey(receipt, attempt_id, 1).encoded
        c5_attempt = _registered_attempt(receipt=receipt, attempt_id=attempt_id)
        c5_attempt["policyFingerprint"] = gate.policy_fingerprint
        initial = _initial_state(restart_budget=3)
        registered = _next_state(initial)
        registered["attempts"] = {key: c5_attempt}
        settled = _next_state(registered)
        settled_attempt = dict(c5_attempt)
        settled_attempt.update(
            phase="settled",
            domainRetired=True,
            protocolTerminal=True,
            cleanupSettlement=WorkerCleanupSettlementV1(
                receipt_fingerprint=receipt,
                attempt_id=attempt_id,
                owner_generation=1,
                host_identity="host-a",
                boot_identity="boot-a",
                protocol_terminal=True,
                domain_retired=True,
                tree_settled=True,
            ).to_dict(),
        )
        settled["attempts"] = {key: settled_attempt}
        compacted = _next_state(settled)
        compacted["attempts"] = {}
        activation_journal = (
            activation_state_journal_module.CodingProductWorkerActivationStateJournal(
                product.state_root / "worker-activation-state.jsonl"
            )
        )
        for revision, state in enumerate(
            (initial, registered, settled, compacted)
        ):
            assert activation_journal.compare_and_swap(
                expected_revision=revision, document=state
            )
        assert not activation_journal.retained_attempts_read_only()[0].current
        retention = review_coding_product_worker_history_retention(
            product, attempt_id=attempt_id
        )
        assert retention.unverified_activation_references == ()
        assert retention.global_unverified_activation_references == ()
        with monkeypatch.context() as changed_native_observation:
            changed_native_observation.setattr(
                history_retention_module,
                "worker_native_group_status_after_restart",
                lambda _identity: "present",
            )
            observed_present = review_coding_product_worker_history_retention(
                product, attempt_id=attempt_id
            )
            assert observed_present.global_unverified_activation_references == (
                (attempt_id, "activation_reference_native_absence_unverified"),
            )
        gc.prepare()
        gate_path = CodingWorkerStartGateJournal(product).path
        retained_gate = gate_path.read_bytes()
        gate_path.write_bytes(retained_gate + b"{}\n")
        try:
            with pytest.raises(PackageProductGcExecutionError) as changed:
                gc.prepare()
            assert changed.value.code == "plugin_package_gc_worker_history_unsettled"
        finally:
            gate_path.write_bytes(retained_gate)
        gc.prepare()
    finally:
        reopened.close()


@pytest.mark.requires_host_runtime
@pytest.mark.skipif(sys.platform != "linux", reason="Linux H6 release")
def test_explicit_worker_public_coding_session_disable_fences_pinned_product(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_worker_source_catalog_pins_explicit_product_candidate(
        tmp_path,
        "installed-protocol",
        monkeypatch,
        direct_entry_only=True,
        disable_while_direct_session_open=True,
    )


@pytest.mark.requires_host_runtime
@pytest.mark.skipif(sys.platform != "linux", reason="Linux H6 release")
def test_explicit_worker_public_coding_session_update_fences_pinned_product(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_worker_source_catalog_pins_explicit_product_candidate(
        tmp_path,
        "installed-protocol",
        monkeypatch,
        direct_entry_only=True,
        update_while_direct_session_open=True,
    )


@pytest.mark.requires_host_runtime
@pytest.mark.skipif(sys.platform != "linux", reason="Linux H6 release")
def test_explicit_worker_hosted_first_session_reaches_installed_product(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_worker_source_catalog_pins_explicit_product_candidate(
        tmp_path,
        "installed-protocol",
        monkeypatch,
        hosted_entry_only=True,
    )


@pytest.mark.requires_host_runtime
@pytest.mark.skipif(sys.platform != "linux", reason="Linux H6 release")
def test_worker_source_catalog_sustained_product_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.environ.get("LOUSHANG_WORKER_SUSTAINED") != "1":
        pytest.skip("Dedicated H6 sustained Worker gate")
    test_worker_source_catalog_pins_explicit_product_candidate(
        tmp_path,
        "installed-protocol",
        monkeypatch,
        protocol_queries=2_049,
    )


class _ProductNativeClosureReader:
    def __init__(
        self,
        gc_gate: PluginPackageGcReservationJournal,
        closure: CodingWorkerNativeClosureV1,
    ) -> None:
        self.gc_gate = gc_gate
        self._closure: CodingWorkerNativeClosureV1 | None = closure

    def current_closure(self) -> CodingWorkerNativeClosureV1:
        if self._closure is None:
            raise CodingWorkerNativeClosureReadError("native closure changed")
        return self._closure

    def change(self, closure: CodingWorkerNativeClosureV1) -> None:
        with self.gc_gate.guard():
            self._closure = closure

    def fail(self) -> None:
        with self.gc_gate.guard():
            self._closure = None


class _ProductSessionDiscoveryReader:
    def __init__(
        self,
        gc_gate: PluginPackageGcReservationJournal,
        discovery: SessionDiscoveryMetadata,
    ) -> None:
        self.gc_gate = gc_gate
        self.session_id = discovery.locator.conversation_id
        self._discovery = discovery

    def current_discovery(self) -> SessionDiscoveryMetadata:
        return self._discovery

    def change(self, discovery: SessionDiscoveryMetadata) -> None:
        with self.gc_gate.guard():
            self._discovery = discovery


def _static_worker_executable(
    *, extra_program_type: int | None = None, linger: bool = False
) -> bytes:
    """A tiny loader-free Linux x86-64 ELF; optionally await host termination."""

    code = (
        b"\xb8\x22\x00\x00\x00\x0f\x05\xeb\xf7"
        if linger  # pause(); loop after any unrelated signal
        else b"\xb8\x3c\x00\x00\x00\x31\xff\x0f\x05"
    )
    count = 1 if extra_program_type is None else 2
    header_end = 64 + 56 * count
    body = bytearray(header_end + len(code))
    body[:7] = b"\x7fELF\x02\x01\x01"
    pack_into("<H", body, 16, 2)
    pack_into("<H", body, 18, 62)
    pack_into("<I", body, 20, 1)
    pack_into("<Q", body, 24, 0x400000 + header_end)
    pack_into("<Q", body, 32, 64)
    pack_into("<H", body, 52, 64)
    pack_into("<H", body, 54, 56)
    pack_into("<H", body, 56, count)
    pack_into("<I", body, 64, 1)
    pack_into("<I", body, 68, 5)
    pack_into("<Q", body, 80, 0x400000)
    pack_into("<Q", body, 88, 0x400000)
    pack_into("<Q", body, 96, len(body))
    pack_into("<Q", body, 104, len(body))
    pack_into("<Q", body, 112, 0x1000)
    if extra_program_type is not None:
        pack_into("<I", body, 120, extra_program_type)
    body[header_end:] = code
    return bytes(body)


def _worker_wheel(
    *,
    shape: str = "valid",
    tag: str = _TAG,
    version: str = _VERSION,
    linger: bool = False,
) -> bytes:
    if shape in {"valid", "dependency", "dependency_two"}:
        return build_coding_local_worker_candidate_wheel(
            plugin_id=_PLUGIN,
            version=version,
            contribution_id=_CONTRIBUTION,
            owner_id=_OWNER,
            native_platform="linux-x86_64",
            wheel_tag=tag,
            executable=_static_worker_executable(linger=linger),
            dependency="dependency==1" if shape == "dependency" else None,
            dependencies=(
                ("auxiliary==1", "dependency==1")
                if shape == "dependency_two"
                else ()
            ),
        )
    configuration = PluginLocalWorkerConfiguration(
        entrypoint="worker/bin/query-worker",
        protocol="capability.query",
        protocol_version=1,
    )
    reservation = PluginContributionReservation(
        contribution_id=_CONTRIBUTION,
        kind="capability_provider",
        owner=_OWNER,
        declaration_source=PluginDeclarationSource.document(
            "declarations/providers.json",
            schema_version=PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION,
        ),
        contribution_execution_model="local_worker",
        requested_authorities=(),
        worker_configuration=configuration,
        index_version=PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION,
    )
    index = PluginContributionIndex(
        items=(reservation,), version=PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION
    )
    declaration = PluginDeclaration(
        plugin_id=_PLUGIN,
        contribution_id=_CONTRIBUTION,
        kind="capability_provider",
        owner=_OWNER,
        reservation_fingerprint=reservation.fingerprint,
        source_descriptor_fingerprint=reservation.source_descriptor_fingerprint,
        source_kind="document",
        payload={"querySchema": "loushang.capability-query/read-only/v1"},
        ir_version=PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION,
        contribution_execution_model="local_worker",
        worker_configuration=configuration,
    )

    declaration_document = PluginDeclarationDocumentCodec.encode_bytes(
        PluginDeclarationDocument(
            declarations=(declaration,),
            document_version=PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION,
        )
    )
    if shape == "declaration_drift":
        changed = json.loads(declaration_document)
        changed["declarations"][0]["workerConfiguration"]["protocolVersion"] = 2
        declaration_document = json.dumps(
            changed, separators=(",", ":"), sort_keys=True
        ).encode()
    spoofed_header = "X-Root-Is-Purelib: false\n" if shape == "spoofed_purelib" else ""

    files = {
        f"{_PLUGIN}/plugin.json": json.dumps(
            {
                "contributionIndex": index.to_dict(),
                "engine": {
                    "apiVersion": 1,
                    "declarationIrVersion": 3,
                    "requiredFeatures": sorted(required_plugin_engine_features(index)),
                },
                "manifestVersion": 1,
                "name": _PLUGIN,
                "packageRoot": ".",
                "version": version,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode(),
        f"{_PLUGIN}/declarations/providers.json": declaration_document,
        f"{_PLUGIN}/worker/bin/query-worker": (
            b"#!/bin/sh\nexit 0\n"
            if shape == "script"
            else _static_worker_executable(
                extra_program_type=3 if shape == "dynamic" else None
            )
        ),
        f"{_PLUGIN}-{version}.dist-info/WHEEL": (
            "Wheel-Version: 1.0\nGenerator: worker-product-test\n"
            f"Root-Is-Purelib: {'true' if shape in {'purelib', 'spoofed_purelib'} else 'false'}\n"
            f"{spoofed_header}"
            f"Tag: {tag}\n\n"
        ).encode(),
        f"{_PLUGIN}-{version}.dist-info/METADATA": (
            f"Metadata-Version: 2.1\nName: {_PLUGIN}\nVersion: {version}\n"
            + (
                "Requires-Dist: auxiliary==1\nRequires-Dist: dependency==1\n"
                if shape == "dependency_two_nonpure"
                else (
                    "Requires-Dist: dependency==1\n"
                    if shape in {
                        "dependency_nonpure",
                        "dependency_extra_executable",
                    }
                    else ""
                )
            )
            + "\n"
        ).encode(),
    }
    if shape == "extra_file":
        files[f"{_PLUGIN}/worker/bin/other"] = b"unreviewed executable"
    record = io.StringIO(newline="")
    rows = [
        (
            name,
            "sha256=" + urlsafe_b64encode(sha256(body).digest()).rstrip(b"=").decode(),
            str(len(body)),
        )
        for name, body in sorted(files.items())
    ]
    rows.append((f"{_PLUGIN}-{version}.dist-info/RECORD", "", ""))
    csv.writer(record, lineterminator="\n").writerows(rows)
    files[f"{_PLUGIN}-{version}.dist-info/RECORD"] = record.getvalue().encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in sorted(files.items()):
            item = zipfile.ZipInfo(name)
            item.create_system = 3
            item.external_attr = (stat.S_IFREG | 0o644) << 16
            item.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(item, body)
    return output.getvalue()


def _dependency_library_wheel(
    *, name: str = "dependency", purelib: bool = True, extra_executable: bool = False
) -> bytes:
    files = {
        f"{name}/__init__.py": b"VALUE = 1\n",
        f"{name}-1.dist-info/METADATA": (
            f"Metadata-Version: 2.1\nName: {name}\nVersion: 1\n\n".encode()
        ),
        f"{name}-1.dist-info/WHEEL": (
            "Wheel-Version: 1.0\n"
            f"Root-Is-Purelib: {'true' if purelib else 'false'}\n"
            "Tag: py3-none-any\n\n"
        ).encode(),
    }
    if extra_executable:
        files[f"{name}/bin/rogue"] = b"unreviewed executable"
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for logical_path, body in sorted(files.items()):
        digest = urlsafe_b64encode(sha256(body).digest()).rstrip(b"=").decode()
        writer.writerow((logical_path, f"sha256={digest}", str(len(body))))
    writer.writerow((f"{name}-1.dist-info/RECORD", "", ""))
    files[f"{name}-1.dist-info/RECORD"] = record.getvalue().encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, body in sorted(files.items()):
            item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            item.create_system = 3
            item.external_attr = (stat.S_IFREG | 0o644) << 16
            item.compress_type = zipfile.ZIP_STORED
            archive.writestr(item, body)
    return output.getvalue()


@pytest.mark.skipif(
    not sys.platform.startswith("linux") or os.uname().machine != "x86_64",
    reason="Linux x86-64 Worker author artifact",
)
def test_worker_candidate_author_recipe_is_reproducible_and_no_replace(
    tmp_path: Path,
) -> None:
    executable = _static_worker_executable()

    def build() -> bytes:
        return build_coding_local_worker_candidate_wheel(
            plugin_id=_PLUGIN,
            version=_VERSION,
            contribution_id=_CONTRIBUTION,
            owner_id=_OWNER,
            native_platform="linux-x86_64",
            wheel_tag=_TAG,
            executable=executable,
        )

    first = build()
    assert first == build()

    def build_pinned(pins: tuple[str, ...]) -> bytes:
        return build_coding_local_worker_candidate_wheel(
            plugin_id=_PLUGIN,
            version=_VERSION,
            contribution_id=_CONTRIBUTION,
            owner_id=_OWNER,
            native_platform="linux-x86_64",
            wheel_tag=_TAG,
            executable=executable,
            dependencies=pins,
        )

    assert build_pinned(("dependency==1", "auxiliary==1")) == build_pinned(
        ("auxiliary==1", "dependency==1")
    )
    with pytest.raises(ValueError, match="distinct exact pins"):
        build_pinned(("dependency==1", "dependency==2"))
    with pytest.raises(ValueError, match="Product limit"):
        build_pinned(("alpha==1", "beta==1", "gamma==1", "delta==1"))
    written = write_coding_local_worker_candidate_wheel(
        tmp_path,
        plugin_id=_PLUGIN,
        version=_VERSION,
        contribution_id=_CONTRIBUTION,
        owner_id=_OWNER,
        native_platform="linux-x86_64",
        wheel_tag=_TAG,
        executable=executable,
    )
    assert written.read_bytes() == first
    for invalid_dependency in (
        "dependency>=1",
        "Dependency==1",
        "dependency==1;python_version>='3.11'",
        f"{_PLUGIN}==1",
    ):
        with pytest.raises(ValueError, match="distinct exact pin"):
            build_coding_local_worker_candidate_wheel(
                plugin_id=_PLUGIN,
                version=_VERSION,
                contribution_id=_CONTRIBUTION,
                owner_id=_OWNER,
                native_platform="linux-x86_64",
                wheel_tag=_TAG,
                executable=executable,
                dependency=invalid_dependency,
            )
    with pytest.raises(FileExistsError):
        write_coding_local_worker_candidate_wheel(
            tmp_path,
            plugin_id=_PLUGIN,
            version=_VERSION,
            contribution_id=_CONTRIBUTION,
            owner_id=_OWNER,
            native_platform="linux-x86_64",
            wheel_tag=_TAG,
            executable=executable,
        )
    with pytest.raises(ValueError, match="Product Source limit"):
        build_coding_local_worker_candidate_wheel(
            plugin_id=_PLUGIN,
            version=_VERSION,
            contribution_id=_CONTRIBUTION,
            owner_id=_OWNER,
            native_platform="linux-x86_64",
            wheel_tag=_TAG,
            executable=executable + shake_256(b"worker-budget").digest(3 * 1024 * 1024),
        )
    source = tmp_path / "author-worker"
    source.write_bytes(executable)
    linked_source = tmp_path / "linked-author-worker"
    linked_source.symlink_to(source)
    authored = subprocess.run(
        (
            sys.executable,
            "-m",
            "loushang.plugin",
            "build-coding-worker-candidate",
            str(linked_source),
            "--plugin-id",
            _PLUGIN,
            "--version",
            _VERSION,
            "--contribution-id",
            _CONTRIBUTION,
            "--owner-id",
            _OWNER,
            "--native-platform",
            "linux-x86_64",
            "--output-dir",
            str(tmp_path / "refused"),
        ),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert authored.returncode != 0
    assert b"regular file" in authored.stderr
    assert not (tmp_path / "refused").exists()


def test_windows_worker_candidate_author_recipe_is_inert_offline(
    tmp_path: Path,
) -> None:
    executable = bytearray(512)
    executable[:2] = b"MZ"
    pack_into("<I", executable, 0x3C, 0x80)
    executable[0x80:0x84] = b"PE\x00\x00"
    pack_into("<H", executable, 0x84, 0x8664)
    pack_into("<H", executable, 0x86, 1)
    pack_into("<H", executable, 0x94, 112)
    pack_into("<H", executable, 0x96, 0x0002)
    pack_into("<H", executable, 0x98, 0x20B)
    source = tmp_path / "query-worker.exe"
    source.write_bytes(executable)
    authored = subprocess.run(
        (
            sys.executable,
            "-m",
            "loushang.plugin",
            "build-coding-worker-candidate",
            str(source),
            "--plugin-id",
            _PLUGIN,
            "--version",
            _VERSION,
            "--contribution-id",
            _CONTRIBUTION,
            "--owner-id",
            _OWNER,
            "--native-platform",
            "windows-amd64",
            "--output-dir",
            str(tmp_path / "dist"),
        ),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert authored.returncode == 0, authored.stderr
    result = json.loads(authored.stdout)
    assert result["productAdmission"] == "not_checked"
    assert result["productUse"] == "not_checked"
    wheel = Path(result["artifactPath"])
    assert wheel.name == f"{_PLUGIN}-{_VERSION}-py3-none-win_amd64.whl"
    assert wheel.read_bytes() == build_coding_local_worker_candidate_wheel(
        plugin_id=_PLUGIN,
        version=_VERSION,
        contribution_id=_CONTRIBUTION,
        owner_id=_OWNER,
        native_platform="windows-amd64",
        wheel_tag="py3-none-win_amd64",
        executable=bytes(executable),
    )


@pytest.mark.skipif(
    not sys.platform.startswith("linux") or os.uname().machine != "x86_64",
    reason="Linux x86-64 Product and Worker candidate",
)
@pytest.mark.parametrize(
    "shape",
    (
        "valid",
        "extra_file",
        "script",
        "dynamic",
        "dependency",
        "dependency_two",
        "dependency_two_nonpure",
        "dependency_nonpure",
        "dependency_extra_executable",
        "declaration_drift",
        "purelib",
        "spoofed_purelib",
        "any_tag",
        "wrong_policy_owner",
        "wrong_policy_contribution",
        "wrong_policy_platform",
    ),
)
def test_explicit_worker_wheel_reaches_real_product_transaction(
    tmp_path: Path, shape: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
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
        namespace_id="a" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        product = owner.runtime_owner.product_owner
        tag = "py3-none-any" if shape == "any_tag" else _TAG
        source = product.policy.source_root / f"{_PLUGIN}-{_VERSION}-{tag}.whl"
        if shape in {"valid", "dependency", "dependency_two"}:
            executable_source = tmp_path / "worker-author-source"
            executable_source.write_bytes(_static_worker_executable())
            authored = subprocess.run(
                (
                    sys.executable,
                    "-m",
                    "loushang.plugin",
                    "build-coding-worker-candidate",
                    str(executable_source),
                    "--plugin-id",
                    _PLUGIN,
                    "--version",
                    _VERSION,
                    "--contribution-id",
                    _CONTRIBUTION,
                    "--owner-id",
                    _OWNER,
                    "--native-platform",
                    "linux-x86_64",
                    *(
                        ("--dependency", "dependency==1")
                        if shape == "dependency"
                        else (
                            (
                                "--dependency",
                                "dependency==1",
                                "--dependency",
                                "auxiliary==1",
                            )
                            if shape == "dependency_two"
                            else ()
                        )
                    ),
                    "--output-dir",
                    str(tmp_path / "authored"),
                ),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=30,
                check=False,
            )
            assert authored.returncode == 0, authored.stderr
            author_result = json.loads(authored.stdout)
            assert author_result["profile"] == "coding-local-worker-candidate-v1"
            assert author_result["productAdmission"] == "not_checked"
            assert author_result["productUse"] == "not_checked"
            payload = Path(author_result["artifactPath"]).read_bytes()
            assert payload == _worker_wheel(shape=shape, tag=tag)
            assert author_result["sha256"] == sha256(payload).hexdigest()
        else:
            payload = _worker_wheel(shape=shape, tag=tag)
        source.write_bytes(payload)
        binding = PackageProductLocalWheelBindingV1(
            source_identity=str(source),
            requested_package=f"{_PLUGIN}=={_VERSION}",
            plugin_id=_PLUGIN,
            artifact_digest=sha256(payload).hexdigest(),
            plugin_manifest_path=f"{_PLUGIN}/plugin.json",
            source_trust_class="local-worker-candidate",
            worker_admission=PackageProductLocalWorkerAdmissionV1(
                contribution_id=(
                    "other-provider"
                    if shape == "wrong_policy_contribution"
                    else _CONTRIBUTION
                ),
                owner_id="coding.other" if shape == "wrong_policy_owner" else _OWNER,
                native_platform=(
                    "windows-amd64"
                    if shape == "wrong_policy_platform"
                    else "linux-x86_64"
                ),
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
        if shape in {
            "dependency",
            "dependency_two",
            "dependency_two_nonpure",
            "dependency_nonpure",
            "dependency_extra_executable",
        }:
            dependency_payload = _dependency_library_wheel(
                purelib=shape != "dependency_nonpure",
                extra_executable=shape == "dependency_extra_executable",
            )
            dependency_source = policy.source_root / "dependency-1-py3-none-any.whl"
            dependency_source.write_bytes(dependency_payload)
            dependency_bindings = [
                PackageProductLocalWheelDependencyV1(
                    source_identity=str(dependency_source),
                    project_name="dependency",
                    version="1",
                    artifact_digest=sha256(dependency_payload).hexdigest(),
                )
            ]
            if shape in {"dependency_two", "dependency_two_nonpure"}:
                auxiliary_payload = _dependency_library_wheel(
                    name="auxiliary", purelib=shape != "dependency_two_nonpure"
                )
                auxiliary_source = policy.source_root / "auxiliary-1-py3-none-any.whl"
                auxiliary_source.write_bytes(auxiliary_payload)
                dependency_bindings.append(
                    PackageProductLocalWheelDependencyV1(
                        source_identity=str(auxiliary_source),
                        project_name="auxiliary",
                        version="1",
                        artifact_digest=sha256(auxiliary_payload).hexdigest(),
                    )
                )
            policy = replace(
                policy,
                dependencies=tuple(
                    sorted(dependency_bindings, key=lambda item: item.project_name)
                ),
            )
        worker_product = replace(product, policy=policy)
        runtime = worker_product.factory_for_session(
            session_id="worker-candidate",
            cwd=workspace,
            runtime_id="worker-candidate",
        ).create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id="worker-candidate", cwd=str(workspace)
            )
        )
        try:
            runtime.activate()
            outcome = runtime.lifecycle.route(
                PackageProductLifecycleIntentV1(
                    operation_id="worker-candidate-install",
                    action="install",
                    source=str(source),
                    scope="project",
                ),
                entrypoint="cli",
            )
            assert outcome.handled
            assert outcome.record is not None
            assert outcome.record.lifecycle == (
                "installed"
                if shape in {"valid", "dependency", "dependency_two"}
                else "failed"
            ), outcome.record
            snapshot = product.desired_state.snapshot()
            installed = tuple(
                item
                for item in snapshot.installations
                if item.installation_key.plugin_id == _PLUGIN
            )
            if shape == "dependency":
                assert len(installed) == 1
                assert installed[0].selection.desired_state == "installed_disabled"
                enabled = product.management.submit(
                    PluginManagementCommandV1(
                        action="enable",
                        mutation=PluginDesiredStateMutationV1(
                            operation_id="worker-dependency-enable",
                            idempotency_key="worker-dependency-enable",
                            expected_inventory_revision=snapshot.inventory_revision,
                            installation_key=installed[0].installation_key,
                            desired_state="installed_enabled",
                            package_revision=None,
                            actor_id=product.actor_id,
                            policy_revision=product.desired_policy_revision,
                        ),
                    )
                )
                assert enabled.status == "terminal"
                selected = runtime.capture_selected_plugin_manifest_for(
                    _PLUGIN, max_files=16, max_total_bytes=16 * 1024 * 1024
                )
                assert selected.snapshot.committed_record.closure_lock.node_count == 2
                dependency_settlements = PackageStoreSettlementJournal(
                    worker_product.state_root / "dependency-settlements.jsonl"
                )
                dependency_snapshot = runtime.capture_selected_dependency_for_plugin(
                    _PLUGIN,
                    max_files=16,
                    max_total_bytes=1024 * 1024,
                )
                assert dependency_snapshot.package_revision == (
                    selected.snapshot.package_revision
                )
                assert dependency_snapshot.committed_record == (
                    selected.snapshot.committed_record
                )
                assert (
                    dependency_snapshot.dependency_ref
                    == (
                        selected.snapshot.committed_record.committed_set.dependency_refs[
                            0
                        ]
                    )
                )
                assert dependency_snapshot.files
                runtime.assert_selected_dependency_current(dependency_snapshot)
                (dependency_settlement,) = tuple(
                    item
                    for item in dependency_settlements.records()
                    if item.settlement_id == dependency_snapshot.settlement_id
                )
                dependency_path, original_bytes = dependency_snapshot.files[0]
                published = (
                    worker_product.dependency_store_root
                    / dependency_settlement.final_name
                    / dependency_path
                )
                published.write_bytes(b"changed")
                with pytest.raises(PackagePhysicalStagingError):
                    runtime.capture_selected_dependency_for_plugin(
                        _PLUGIN,
                        max_files=16,
                        max_total_bytes=1024 * 1024,
                    )
                with pytest.raises(PackagePhysicalStagingError):
                    runtime.assert_selected_dependency_current(dependency_snapshot)
                published.write_bytes(original_bytes)
                runtime.assert_selected_dependency_current(dependency_snapshot)
                candidate = verify_product_selected_worker_candidate(
                    selected,
                    contribution_id=_CONTRIBUTION,
                    native_platform="linux-x86_64",
                )
                assert candidate.plugin_id == _PLUGIN
                with pytest.raises(CodingWorkerProductOptInError) as unavailable:
                    CodingWorkerProductOptInOwner(worker_product).allow(
                        plugin_id=_PLUGIN,
                        operation_id="worker-dependency-opt-in",
                        expected_generation=0,
                        require_worker=False,
                    )
                assert unavailable.value.code == (
                    "coding_worker_dependency_activation_unsupported"
                )
                with pytest.raises(CodingWorkerPolicySelectionError) as unsupported:
                    derive_coding_selected_worker_policy(
                        runtime=runtime,
                        product_policy=policy,
                        selected=selected,
                        session_id="worker-candidate",
                        product_runtime_id="worker-candidate",
                        opt_in=CodingWorkerOptInV1(
                            plugin_id=_PLUGIN,
                            contribution_id=_CONTRIBUTION,
                            owner_id=_OWNER,
                            artifact_digest=selected.snapshot.root_ref.artifact_digest,
                            native_platform="linux-x86_64",
                            owner_selection_generation=1,
                            kill_switch_generation=0,
                            require_worker=False,
                        ),
                        native_closure=CodingWorkerNativeClosureV1(
                            native_platform="linux-x86_64",
                            native_profile_catalog_revision="native-catalog:1",
                            containment_launcher_digest=sha256(b"launcher").hexdigest(),
                            containment_profile_digest=sha256(
                                b"containment"
                            ).hexdigest(),
                        ),
                    )
                assert unsupported.value.code == (
                    "coding_worker_dependency_activation_unsupported"
                )
                current_inventory = product.desired_state.snapshot()
                disabled = product.management.submit(
                    PluginManagementCommandV1(
                        action="disable",
                        mutation=PluginDesiredStateMutationV1(
                            operation_id="worker-dependency-disable",
                            idempotency_key="worker-dependency-disable",
                            expected_inventory_revision=(
                                current_inventory.inventory_revision
                            ),
                            installation_key=installed[0].installation_key,
                            desired_state="installed_disabled",
                            package_revision=None,
                            actor_id=product.actor_id,
                            policy_revision=product.desired_policy_revision,
                        ),
                    )
                )
                assert disabled.status == "terminal"
                with pytest.raises(
                    PackageProductRuntimeReadError
                ) as no_longer_selected:
                    runtime.capture_selected_dependency_for_plugin(
                        _PLUGIN,
                        max_files=16,
                        max_total_bytes=1024 * 1024,
                    )
                assert no_longer_selected.value.code == (
                    "package_product_root_not_selected"
                )
                with pytest.raises(PackageProductRuntimeReadError) as stale_snapshot:
                    runtime.assert_selected_dependency_current(dependency_snapshot)
                assert stale_snapshot.value.code == (
                    "package_product_root_not_selected"
                )
                disabled_inventory = product.desired_state.snapshot()
                reenabled = product.management.submit(
                    PluginManagementCommandV1(
                        action="enable",
                        mutation=PluginDesiredStateMutationV1(
                            operation_id="worker-dependency-reenable",
                            idempotency_key="worker-dependency-reenable",
                            expected_inventory_revision=(
                                disabled_inventory.inventory_revision
                            ),
                            installation_key=installed[0].installation_key,
                            desired_state="installed_enabled",
                            package_revision=None,
                            actor_id=product.actor_id,
                            policy_revision=product.desired_policy_revision,
                        ),
                    )
                )
                assert reenabled.status == "terminal"
                with pytest.raises(PackageProductRuntimeReadError) as replaced:
                    runtime.assert_selected_dependency_current(dependency_snapshot)
                assert replaced.value.code == (
                    "package_product_dependency_selection_changed"
                )
            elif shape == "dependency_two":
                assert len(installed) == 1
                assert installed[0].selection.desired_state == "installed_disabled"
                enabled = product.management.submit(
                    PluginManagementCommandV1(
                        action="enable",
                        mutation=PluginDesiredStateMutationV1(
                            operation_id="worker-two-dependencies-enable",
                            idempotency_key="worker-two-dependencies-enable",
                            expected_inventory_revision=snapshot.inventory_revision,
                            installation_key=installed[0].installation_key,
                            desired_state="installed_enabled",
                            package_revision=None,
                            actor_id=product.actor_id,
                            policy_revision=product.desired_policy_revision,
                        ),
                    )
                )
                assert enabled.status == "terminal"
                selected = runtime.capture_selected_plugin_manifest_for(
                    _PLUGIN, max_files=16, max_total_bytes=16 * 1024 * 1024
                )
                assert selected.snapshot.committed_record.closure_lock.node_count == 3
                assert len(
                    selected.snapshot.committed_record.committed_set.dependency_refs
                ) == 2
                closure_snapshot = (
                    runtime.capture_selected_dependency_closure_for_plugin(
                        _PLUGIN,
                        max_dependencies=3,
                        max_files_per_dependency=16,
                        max_total_bytes=3 * 1024 * 1024,
                    )
                )
                assert len(closure_snapshot.members) == 2
                assert {member.dependency_ref for member in closure_snapshot.members} == set(
                    selected.snapshot.committed_record.committed_set.dependency_refs
                )
                runtime.assert_selected_dependency_closure_current(closure_snapshot)
                with pytest.raises(PackageProductRuntimeReadError) as too_many:
                    runtime.capture_selected_dependency_closure_for_plugin(
                        _PLUGIN,
                        max_dependencies=1,
                        max_files_per_dependency=16,
                        max_total_bytes=3 * 1024 * 1024,
                    )
                assert too_many.value.code == (
                    "package_product_dependency_shape_unsupported"
                )
                settlements = PackageStoreSettlementJournal(
                    worker_product.state_root / "dependency-settlements.jsonl"
                )
                auxiliary_member = next(
                    member
                    for member in closure_snapshot.members
                    if member.dependency_ref.distribution == "auxiliary"
                )
                (auxiliary_settlement,) = tuple(
                    item
                    for item in settlements.records()
                    if item.settlement_id == auxiliary_member.settlement_id
                )
                auxiliary_path, auxiliary_bytes = auxiliary_member.files[0]
                published_auxiliary = (
                    worker_product.dependency_store_root
                    / auxiliary_settlement.final_name
                    / auxiliary_path
                )
                published_auxiliary.write_bytes(b"changed")
                with pytest.raises(PackagePhysicalStagingError):
                    runtime.assert_selected_dependency_closure_current(
                        closure_snapshot
                    )
                published_auxiliary.write_bytes(auxiliary_bytes)
                runtime.assert_selected_dependency_closure_current(closure_snapshot)
                with pytest.raises(PackageProductRuntimeReadError) as unsupported:
                    runtime.capture_selected_dependency_for_plugin(
                        _PLUGIN, max_files=16, max_total_bytes=1024 * 1024
                    )
                assert unsupported.value.code == (
                    "package_product_dependency_shape_unsupported"
                )
                with pytest.raises(CodingWorkerProductOptInError) as refused:
                    CodingWorkerProductOptInOwner(worker_product).allow(
                        plugin_id=_PLUGIN,
                        operation_id="worker-two-dependencies-opt-in",
                        expected_generation=0,
                        require_worker=False,
                    )
                assert refused.value.code == (
                    "coding_worker_dependency_activation_unsupported"
                )
                current_inventory = product.desired_state.snapshot()
                disabled = product.management.submit(
                    PluginManagementCommandV1(
                        action="disable",
                        mutation=PluginDesiredStateMutationV1(
                            operation_id="worker-two-dependencies-disable",
                            idempotency_key="worker-two-dependencies-disable",
                            expected_inventory_revision=(
                                current_inventory.inventory_revision
                            ),
                            installation_key=installed[0].installation_key,
                            desired_state="installed_disabled",
                            package_revision=None,
                            actor_id=product.actor_id,
                            policy_revision=product.desired_policy_revision,
                        ),
                    )
                )
                assert disabled.status == "terminal"
                with pytest.raises(PackageProductRuntimeReadError) as stale_closure:
                    runtime.assert_selected_dependency_closure_current(
                        closure_snapshot
                    )
                assert stale_closure.value.code == "package_product_root_not_selected"
            elif shape != "valid":
                assert installed == ()
            else:
                assert len(installed) == 1
                assert installed[0].selection.desired_state == "installed_disabled"
                with pytest.raises(PackageProductRuntimeReadError) as disabled:
                    runtime.capture_selected_plugin_manifest_for(
                        _PLUGIN, max_files=16, max_total_bytes=16 * 1024 * 1024
                    )
                assert disabled.value.code == "package_product_root_not_selected"
                enabled = product.management.submit(
                    PluginManagementCommandV1(
                        action="enable",
                        mutation=PluginDesiredStateMutationV1(
                            operation_id="worker-candidate-enable",
                            idempotency_key="worker-candidate-enable",
                            expected_inventory_revision=snapshot.inventory_revision,
                            installation_key=installed[0].installation_key,
                            desired_state="installed_enabled",
                            package_revision=None,
                            actor_id=product.actor_id,
                            policy_revision=product.desired_policy_revision,
                        ),
                    )
                )
                assert enabled.status == "terminal"
                selected = runtime.capture_selected_plugin_manifest_for(
                    _PLUGIN, max_files=16, max_total_bytes=16 * 1024 * 1024
                )
                candidate = verify_product_selected_worker_candidate(
                    selected,
                    contribution_id=_CONTRIBUTION,
                    native_platform="linux-x86_64",
                )
                assert candidate.plugin_id == _PLUGIN
                assert (
                    candidate.executable_digest
                    == sha256(_static_worker_executable()).hexdigest()
                )
                runtime.assert_selected_plugin_manifest_current(selected)
                opt_in = CodingWorkerOptInV1(
                    plugin_id=_PLUGIN,
                    contribution_id=_CONTRIBUTION,
                    owner_id=_OWNER,
                    artifact_digest=selected.snapshot.root_ref.artifact_digest,
                    native_platform="linux-x86_64",
                    owner_selection_generation=1,
                    kill_switch_generation=0,
                    require_worker=False,
                )
                native_closure = CodingWorkerNativeClosureV1(
                    native_platform="linux-x86_64",
                    native_profile_catalog_revision="native-catalog:1",
                    containment_launcher_digest=sha256(b"launcher").hexdigest(),
                    containment_profile_digest=sha256(b"containment").hexdigest(),
                )
                native_reader = _ProductNativeClosureReader(
                    product.gc_gate, native_closure
                )
                opt_in_journal = CodingWorkerOptInJournal(
                    product.state_root / "worker-opt-in.jsonl",
                    scope_id=policy.project_scope_id,
                    gc_gate=product.gc_gate,
                )
                assert opt_in_journal.current(_PLUGIN) is None
                with pytest.raises(ValueError):
                    CodingWorkerProductReceiptOwner(
                        product_owner=worker_product,
                        runtime=runtime,
                        selected=selected,
                        opt_in_journal=opt_in_journal,
                        native_closure_reader=_ProductNativeClosureReader(
                            PluginPackageGcReservationJournal(product.gc_gate.path),
                            native_closure,
                        ),
                    )
                receipt_owner = CodingWorkerProductReceiptOwner(
                    product_owner=worker_product,
                    runtime=runtime,
                    selected=selected,
                    opt_in_journal=opt_in_journal,
                    native_closure_reader=native_reader,
                )
                assert receipt_owner.issue() is None
                assert not receipt_owner.path.exists()
                if shape == "valid":
                    monkeypatch.setattr(opt_in_journal_module, "_MAX_EVENTS", 1)
                allowed = opt_in_journal.change(
                    plugin_id=_PLUGIN,
                    operation_id="worker-candidate-opt-in",
                    expected_generation=0,
                    action="allow",
                    opt_in=opt_in,
                )
                assert allowed.opt_in == opt_in

                def derive(candidate_opt_in: CodingWorkerOptInV1 | None):
                    return derive_coding_selected_worker_policy(
                        runtime=runtime,
                        product_policy=policy,
                        selected=selected,
                        session_id="worker-candidate",
                        product_runtime_id="worker-candidate",
                        opt_in=candidate_opt_in,
                        native_closure=native_closure,
                    )

                assert derive(None) is None
                with pytest.raises(CodingWorkerPolicySelectionError) as foreign_session:
                    derive_coding_selected_worker_policy(
                        runtime=runtime,
                        product_policy=policy,
                        selected=selected,
                        session_id="other-session",
                        product_runtime_id="worker-candidate",
                        opt_in=opt_in,
                        native_closure=native_closure,
                    )
                assert (
                    foreign_session.value.code
                    == "coding_worker_product_selection_invalid"
                )
                with pytest.raises(CodingWorkerPolicySelectionError) as wrong_native:
                    derive_coding_selected_worker_policy(
                        runtime=runtime,
                        product_policy=policy,
                        selected=selected,
                        session_id="worker-candidate",
                        product_runtime_id="worker-candidate",
                        opt_in=opt_in,
                        native_closure=replace(
                            native_closure, native_platform="windows-amd64"
                        ),
                    )
                assert (
                    wrong_native.value.code == "coding_worker_product_selection_invalid"
                )
                with pytest.raises(CodingWorkerPolicySelectionError) as wrong_revision:
                    derive(replace(opt_in, artifact_digest="0" * 64))
                assert (
                    wrong_revision.value.code
                    == "coding_worker_product_selection_invalid"
                )
                worker_policy = derive(opt_in_journal.current(_PLUGIN).opt_in)
                assert worker_policy is not None
                assert worker_policy.plugin_revision_digest == opt_in.artifact_digest
                assert worker_policy.worker_configuration_fingerprint == (
                    candidate.worker_configuration_fingerprint
                )
                assert worker_policy.effective_required
                assert worker_policy.native_profile_id == (
                    "posix-static-contained-elf-v1"
                )
                receipt = receipt_owner.issue()
                if shape == "valid":
                    monkeypatch.setattr(receipt_journal_module, "_MAX_RECEIPTS", 1)
                assert receipt is not None
                assert receipt.policy == worker_policy
                assert receipt_owner.issue() == receipt
                if shape == "valid":
                    exact_receipt_history = receipt_owner.path.read_bytes()
                    receipt_owner.path.write_bytes(
                        exact_receipt_history.replace(b"{", b"{ ", 1)
                    )
                    try:
                        with pytest.raises(CodingWorkerReceiptError) as changed:
                            receipt_owner.current_witness(receipt)
                        assert changed.value.code == "coding_worker_segment_head_changed"
                    finally:
                        receipt_owner.path.write_bytes(exact_receipt_history)
                assert receipt_owner.current_witness(receipt) == (
                    receipt.authority_witness
                )
                with receipt_owner.serialized_admission():
                    assert receipt_owner.current_witness(receipt) == (
                        receipt.authority_witness
                    )
                reopened_receipt_owner = CodingWorkerProductReceiptOwner(
                    product_owner=worker_product,
                    runtime=runtime,
                    selected=selected,
                    opt_in_journal=CodingWorkerOptInJournal(
                        opt_in_journal.path,
                        scope_id=policy.project_scope_id,
                        gc_gate=product.gc_gate,
                    ),
                    native_closure_reader=native_reader,
                )
                assert reopened_receipt_owner.issue() == receipt
                assert reopened_receipt_owner.current_witness(receipt) == (
                    receipt.authority_witness
                )
                transcript_root = tmp_path / "worker-transcripts"
                transcript_root.mkdir()
                transcript_path = transcript_root / "selected.jsonl"
                write_agent_transcript_export(
                    transcript_path,
                    ConversationHeader(
                        conversation_id="worker-candidate",
                        version=1,
                        created_at="2026-09-27T00:00:00Z",
                        metadata={"cwd": str(workspace)},
                    ),
                    [],
                )
                transcript_reader = CodingWorkerTranscriptDiscoveryReader(
                    directory=AgentTranscriptDirectoryRuntime(
                        session_dir=transcript_root
                    ),
                    gc_gate=product.gc_gate,
                    session_id="worker-candidate",
                )
                transcript_receipt_owner = CodingWorkerProductReceiptOwner(
                    product_owner=worker_product,
                    runtime=runtime,
                    selected=selected,
                    opt_in_journal=opt_in_journal,
                    native_closure_reader=native_reader,
                    session_discovery_reader=transcript_reader,
                )
                transcript_receipt = transcript_receipt_owner.issue()
                assert transcript_receipt is not None
                assert transcript_receipt.policy.session_route == "selected"
                assert (
                    transcript_receipt_owner.current_witness(transcript_receipt)
                    == transcript_receipt.authority_witness
                )
                transcript_path.unlink()
                assert (
                    transcript_receipt_owner.current_witness(transcript_receipt)
                    != transcript_receipt.authority_witness
                )
                discovery = SessionDiscoveryMetadata(
                    locator=SessionLocator(
                        source_id="coding-session",
                        conversation_id="worker-candidate",
                        session_file=tmp_path / "selected-session.jsonl",
                        revision="locator:1",
                    ),
                    mode="canonical",
                    origin="cwd",
                    health="available",
                )
                discovery_reader = _ProductSessionDiscoveryReader(
                    product.gc_gate, discovery
                )
                selected_receipt_owner = CodingWorkerProductReceiptOwner(
                    product_owner=worker_product,
                    runtime=runtime,
                    selected=selected,
                    opt_in_journal=opt_in_journal,
                    native_closure_reader=native_reader,
                    session_discovery_reader=discovery_reader,
                )
                selected_receipt = selected_receipt_owner.issue()
                assert selected_receipt is not None
                assert selected_receipt.policy.session_route == "selected"
                assert selected_receipt_owner.current_witness(selected_receipt) == (
                    selected_receipt.authority_witness
                )
                discovery_reader.change(
                    replace(
                        discovery,
                        locator=replace(discovery.locator, revision="locator:2"),
                    )
                )
                assert selected_receipt_owner.current_witness(selected_receipt) != (
                    selected_receipt.authority_witness
                )
                selected_receipt_updated = selected_receipt_owner.issue()
                assert selected_receipt_updated is not None
                assert selected_receipt_updated.fingerprint != (
                    selected_receipt.fingerprint
                )
                discovery_reader.change(replace(discovery, health="conflict"))
                assert (
                    selected_receipt_owner.current_witness(selected_receipt_updated)
                    != selected_receipt_updated.authority_witness
                )
                with pytest.raises(CodingWorkerPolicySelectionError) as conflicted:
                    selected_receipt_owner.issue()
                assert conflicted.value.code == "coding_worker_session_invalid"
                assert (
                    receipt_owner.current_witness(
                        replace(receipt, issue_nonce="forged")
                    )
                    != receipt.authority_witness
                )
                assert receipt_owner.latch_kill_switch(expected_generation=0) == 1
                assert receipt_owner.latch_kill_switch(expected_generation=0) == 1
                assert receipt_owner.current_witness(receipt) != (
                    receipt.authority_witness
                )
                assert receipt_owner.issue() is None
                allowed_again = opt_in_journal.change(
                    plugin_id=_PLUGIN,
                    operation_id="worker-candidate-opt-in-again",
                    expected_generation=2,
                    action="allow",
                    opt_in=replace(
                        opt_in,
                        owner_selection_generation=3,
                        kill_switch_generation=1,
                    ),
                )
                assert allowed_again.opt_in is not None
                receipt_after_reallow = receipt_owner.issue()
                assert receipt_after_reallow is not None
                assert receipt_after_reallow.fingerprint != receipt.fingerprint
                assert (
                    product.state_root / "worker-activation-receipts.segments.json"
                ).is_file()
                if shape == "valid":
                    assert (
                        product.state_root / "worker-opt-in.segments.json"
                    ).is_file()
                historical_receipt = read_coding_product_worker_receipt_record(
                    worker_product, receipt_fingerprint=receipt.fingerprint
                )
                assert historical_receipt is not None
                assert historical_receipt.receipt == receipt
                assert receipt_owner.current_witness(receipt_after_reallow) == (
                    receipt_after_reallow.authority_witness
                )
                native_reader.change(
                    replace(
                        native_closure,
                        containment_profile_digest=sha256(
                            b"containment-updated"
                        ).hexdigest(),
                    )
                )
                assert receipt_owner.current_witness(receipt_after_reallow) != (
                    receipt_after_reallow.authority_witness
                )
                receipt_after_native_change = receipt_owner.issue()
                assert receipt_after_native_change is not None
                assert receipt_after_native_change.fingerprint != (
                    receipt_after_reallow.fingerprint
                )
                assert receipt_owner.current_witness(receipt_after_native_change) == (
                    receipt_after_native_change.authority_witness
                )
                kill_switch_policy = derive(replace(opt_in, kill_switch_generation=1))
                assert kill_switch_policy is not None
                assert kill_switch_policy.kill_switch_generation == 1
                assert kill_switch_policy.fingerprint != worker_policy.fingerprint
                with pytest.raises(CodingWorkerPolicySelectionError) as stale_trust:
                    derive_coding_selected_worker_policy(
                        runtime=runtime,
                        product_policy=replace(
                            policy, policy_revision="changed-policy:2"
                        ),
                        selected=selected,
                        session_id="worker-candidate",
                        product_runtime_id="worker-candidate",
                        opt_in=opt_in,
                        native_closure=native_closure,
                    )
                assert stale_trust.value.code == "coding_worker_product_trust_changed"
                update_payload = build_coding_local_worker_candidate_wheel(
                    plugin_id=_PLUGIN,
                    version="2",
                    contribution_id=_CONTRIBUTION,
                    owner_id=_OWNER,
                    native_platform="linux-x86_64",
                    wheel_tag=_TAG,
                    executable=_static_worker_executable(),
                )
                update_source = product.policy.source_root / f"{_PLUGIN}-2-{_TAG}.whl"
                update_source.write_bytes(update_payload)
                update_binding = replace(
                    binding,
                    source_identity=str(update_source),
                    requested_package=f"{_PLUGIN}==2",
                    artifact_digest=sha256(update_payload).hexdigest(),
                )
                update_policy = replace(
                    policy,
                    bindings=tuple(
                        sorted(
                            (*policy.bindings, update_binding),
                            key=lambda item: item.source_identity,
                        )
                    ),
                )
                update_product = replace(product, policy=update_policy)
                update_runtime = update_product.factory_for_session(
                    session_id="worker-update",
                    cwd=workspace,
                    runtime_id="worker-update",
                ).create(
                    PackageProductRuntimeRequestV1(
                        product_id="coding",
                        session_id="worker-update",
                        cwd=str(workspace),
                    )
                )
                try:
                    update_runtime.activate()
                    update = update_runtime.lifecycle.route(
                        PackageProductLifecycleIntentV1(
                            operation_id="worker-candidate-update",
                            action="update",
                            source=str(update_source),
                            scope="project",
                        ),
                        entrypoint="cli",
                    )
                    assert update.handled
                    assert update.record is not None
                    assert update.record.lifecycle == "installed"
                    with pytest.raises(PackageProductRuntimeReadError) as old_revision:
                        runtime.assert_selected_plugin_manifest_current(selected)
                    assert (
                        old_revision.value.code
                        == "package_product_root_selection_changed"
                    )
                    with pytest.raises(PackageProductRuntimeReadError):
                        derive(opt_in)
                    assert receipt_owner.current_witness(
                        receipt_after_native_change
                    ) != (receipt_after_native_change.authority_witness)
                    selected_v2 = update_runtime.capture_selected_plugin_manifest_for(
                        _PLUGIN, max_files=16, max_total_bytes=16 * 1024 * 1024
                    )
                    assert selected_v2.manifest.version == "2"
                    assert (
                        verify_product_selected_worker_candidate(
                            selected_v2,
                            contribution_id=_CONTRIBUTION,
                            native_platform="linux-x86_64",
                        ).plugin_version
                        == "2"
                    )
                    rejected_payload = _worker_wheel(shape="extra_file", version="3")
                    rejected_source = (
                        product.policy.source_root / f"{_PLUGIN}-3-{_TAG}.whl"
                    )
                    rejected_source.write_bytes(rejected_payload)
                    rejected_binding = replace(
                        binding,
                        source_identity=str(rejected_source),
                        requested_package=f"{_PLUGIN}==3",
                        artifact_digest=sha256(rejected_payload).hexdigest(),
                    )
                    rejected_policy = replace(
                        update_policy,
                        bindings=tuple(
                            sorted(
                                (*update_policy.bindings, rejected_binding),
                                key=lambda item: item.source_identity,
                            )
                        ),
                    )
                    rejected_product = replace(product, policy=rejected_policy)
                    rejected_runtime = rejected_product.factory_for_session(
                        session_id="worker-rejected-update",
                        cwd=workspace,
                        runtime_id="worker-rejected-update",
                    ).create(
                        PackageProductRuntimeRequestV1(
                            product_id="coding",
                            session_id="worker-rejected-update",
                            cwd=str(workspace),
                        )
                    )
                    try:
                        rejected_runtime.activate()
                        rejected = rejected_runtime.lifecycle.route(
                            PackageProductLifecycleIntentV1(
                                operation_id="worker-candidate-rejected-update",
                                action="update",
                                source=str(rejected_source),
                                scope="project",
                            ),
                            entrypoint="cli",
                        )
                        assert rejected.handled
                        assert rejected.record is not None
                        assert rejected.record.lifecycle == "failed"
                        update_runtime.assert_selected_plugin_manifest_current(
                            selected_v2
                        )
                    finally:
                        rejected_runtime.dispose_runtime()
                    v2_opt_in = replace(
                        opt_in,
                        artifact_digest=selected_v2.snapshot.root_ref.artifact_digest,
                        owner_selection_generation=4,
                        kill_switch_generation=1,
                    )
                    opt_in_journal.change(
                        plugin_id=_PLUGIN,
                        operation_id="worker-candidate-opt-in-v2",
                        expected_generation=3,
                        action="allow",
                        opt_in=v2_opt_in,
                    )
                    v2_receipt_owner = CodingWorkerProductReceiptOwner(
                        product_owner=update_product,
                        runtime=update_runtime,
                        selected=selected_v2,
                        opt_in_journal=opt_in_journal,
                        native_closure_reader=native_reader,
                    )
                    v2_receipt = v2_receipt_owner.issue()
                    assert v2_receipt is not None
                    assert v2_receipt_owner.current_witness(v2_receipt) == (
                        v2_receipt.authority_witness
                    )
                    gc = open_posix_local_wheel_product_root_gc(worker_product)
                    gc_started = Event()

                    def prepare_gc_with_live_worker_session():
                        gc_started.set()
                        return gc.prepare()

                    with ThreadPoolExecutor(max_workers=1) as pool:
                        with v2_receipt_owner.serialized_admission():
                            pending_gc = pool.submit(
                                prepare_gc_with_live_worker_session
                            )
                            assert gc_started.wait(timeout=5)
                            with pytest.raises(
                                PackageProductGcExecutionError
                            ) as concurrent_gc:
                                pending_gc.result(timeout=15)
                            assert (
                                concurrent_gc.value.code
                                == "plugin_package_gc_runtime_active"
                            )
                            update_runtime.assert_selected_plugin_manifest_current(
                                selected_v2
                            )
                            assert v2_receipt_owner.current_witness(v2_receipt) == (
                                v2_receipt.authority_witness
                            )
                    selected_state = product.desired_state.snapshot()
                    disable_started = Event()

                    def disable_selected_worker():
                        disable_started.set()
                        return product.management.submit(
                            PluginManagementCommandV1(
                                action="disable",
                                mutation=PluginDesiredStateMutationV1(
                                    operation_id="worker-candidate-disable",
                                    idempotency_key="worker-candidate-disable",
                                    expected_inventory_revision=(
                                        selected_state.inventory_revision
                                    ),
                                    installation_key=installed[0].installation_key,
                                    desired_state="installed_disabled",
                                    package_revision=None,
                                    actor_id=product.actor_id,
                                    policy_revision=product.desired_policy_revision,
                                ),
                            )
                        )

                    with ThreadPoolExecutor(max_workers=1) as pool:
                        with v2_receipt_owner.serialized_admission():
                            pending_disable = pool.submit(disable_selected_worker)
                            assert disable_started.wait(timeout=5)
                            assert not pending_disable.done()
                            assert v2_receipt_owner.current_witness(v2_receipt) == (
                                v2_receipt.authority_witness
                            )
                        disabled_again = pending_disable.result(timeout=15)
                    assert disabled_again.status == "terminal"
                    assert v2_receipt_owner.current_witness(v2_receipt) != (
                        v2_receipt.authority_witness
                    )
                finally:
                    update_runtime.dispose_runtime()
                gc = open_posix_local_wheel_product_root_gc(
                    worker_product,
                    worker_history_authority=CodingPosixWorkerGcHistoryAuthority(
                        worker_product
                    ),
                )
                with pytest.raises(PackageProductGcExecutionError) as live_gc:
                    gc.prepare()
                assert live_gc.value.code == "plugin_package_gc_runtime_active"
                with pytest.raises(PackageProductRuntimeReadError) as stale:
                    runtime.assert_selected_plugin_manifest_current(selected)
                assert stale.value.code == "package_product_root_not_selected"
                retained_receipts = (
                    product.state_root / "retained-worker-activation-receipts.jsonl"
                )
                receipt_owner.path.rename(retained_receipts)
                receipt_victim = tmp_path / "receipt-victim"
                receipt_victim.write_bytes(b"private-data")
                receipt_owner.path.symlink_to(receipt_victim)
                with pytest.raises(
                    CodingWorkerReceiptError if shape == "valid" else OSError
                ) as unsafe_receipt:
                    receipt_owner.current_witness(receipt_after_native_change)
                if shape == "valid":
                    assert unsafe_receipt.value.code == (
                        "coding_worker_sealed_segment_changed"
                    )
                assert receipt_victim.read_bytes() == b"private-data"
                receipt_owner.path.unlink()
                retained_receipts.rename(receipt_owner.path)
        finally:
            runtime.dispose_runtime()
        if shape == "valid":
            gc = open_posix_local_wheel_product_root_gc(
                worker_product,
                worker_history_authority=CodingPosixWorkerGcHistoryAuthority(
                    worker_product
                ),
            )
            gc.prepare()
            old_candidate = next(
                item
                for item in gc.candidates()
                if item.package_revision.plugin_id == _PLUGIN
                and item.package_revision.plugin_version == "1"
            )
            executor = gc.application.executor
            old_target = resolve_plugin_package_gc_root_target(
                old_candidate.package_revision,
                bindings=product.gc_bindings.records(),
                claims=product.gc_bindings.claims(),
                committed_sets=executor.committed_sets.records(),
                settlements=executor.root_settlements.records(),
            )
            current_revision = (
                product.desired_state.snapshot()
                .installation(installed[0].installation_key)
                .selection.package_revision
            )
            assert current_revision is not None
            assert current_revision.plugin_version == "2"
            current_target = resolve_plugin_package_gc_root_target(
                current_revision,
                bindings=product.gc_bindings.records(),
                claims=product.gc_bindings.claims(),
                committed_sets=executor.committed_sets.records(),
                settlements=executor.root_settlements.records(),
            )
            old_root = product.plugin_store_root / old_target.settlement.final_name
            current_root = (
                product.plugin_store_root / current_target.settlement.final_name
            )
            assert old_root.is_dir() and current_root.is_dir()
            command = PackageProductRootGcCommandV1(
                candidate=old_candidate,
                reservation_operation_id="worker-candidate-gc-reserve-v1",
                reservation_idempotency_key="worker-candidate-gc-reserve-v1",
                attempt_operation_id="worker-candidate-gc-delete-v1",
                attempt_idempotency_key="worker-candidate-gc-delete-v1",
            )
            result = gc.execute(command)
            assert result.disposition == "succeeded"
            assert not old_root.exists()
            assert current_root.is_dir()
            assert gc.execute(command) == result
            disabled_state = product.desired_state.snapshot()
            reenabled = product.management.submit(
                PluginManagementCommandV1(
                    action="enable",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id="worker-candidate-reenable-after-gc",
                        idempotency_key="worker-candidate-reenable-after-gc",
                        expected_inventory_revision=disabled_state.inventory_revision,
                        installation_key=installed[0].installation_key,
                        desired_state="installed_enabled",
                        package_revision=None,
                        actor_id=product.actor_id,
                        policy_revision=product.desired_policy_revision,
                    ),
                )
            )
            assert reenabled.status == "terminal"
            fresh_runtime = update_product.factory_for_session(
                session_id="worker-after-gc",
                cwd=workspace,
                runtime_id="worker-after-gc",
            ).create(
                PackageProductRuntimeRequestV1(
                    product_id="coding",
                    session_id="worker-after-gc",
                    cwd=str(workspace),
                )
            )
            try:
                fresh_runtime.activate()
                selected_after_gc = fresh_runtime.capture_selected_plugin_manifest_for(
                    _PLUGIN, max_files=16, max_total_bytes=16 * 1024 * 1024
                )
                assert selected_after_gc.manifest.version == "2"
                fresh_runtime.assert_selected_plugin_manifest_current(selected_after_gc)
            finally:
                fresh_runtime.dispose_runtime()
    finally:
        owner.close()


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux Product payload custody"
)
def test_worker_payload_gc_scan_keeps_original_product_root_during_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
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
        namespace_id="a" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        worker_candidates=True,
    )
    try:
        product = owner.runtime_owner.product_owner
        state_root = product.state_root
        (state_root / ("worker-payload-" + "a" * 32)).mkdir(mode=0o700)
        detached = state_root.with_name(state_root.name + "-detached")
        decoy = state_root.with_name(state_root.name + "-decoy")
        decoy.mkdir(mode=0o700)
        original_listdir = os.listdir

        def swap_during_scan(path: str | bytes | int | os.PathLike[str]) -> list[str]:
            if path != state_root and not isinstance(path, int):
                return original_listdir(path)
            state_root.rename(detached)
            decoy.rename(state_root)
            try:
                return original_listdir(path)
            finally:
                state_root.rename(decoy)
                detached.rename(state_root)

        gc = open_posix_local_wheel_product_root_gc(product)
        monkeypatch.setattr(
            root_gc_module, "os", SimpleNamespace(listdir=swap_during_scan)
        )
        with pytest.raises(PackageProductGcExecutionError) as blocked:
            gc._require_no_worker_payload_debt()
        assert blocked.value.code == "plugin_package_gc_worker_payload_unsettled"
    finally:
        owner.close()


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux Product Worker GC history"
)
def test_worker_package_gc_refuses_unsettled_history_without_payload(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
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
        namespace_id="a" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        worker_candidates=True,
    )
    try:
        product = owner.runtime_owner.product_owner
        gc = open_posix_local_wheel_product_root_gc(product)
        gc.prepare()
        authority = CodingPosixWorkerGcHistoryAuthority(product)
        with_authority = open_posix_local_wheel_product_root_gc(
            product, worker_history_authority=authority
        )
        entries_before_read = set(os.listdir(product.state_root))
        authority.require_settled(observed_names=tuple(os.listdir(product.state_root)))
        assert set(os.listdir(product.state_root)) == entries_before_read
        unknown_before_attempt = product.state_root / "worker-future-reference.json"
        unknown_before_attempt.write_bytes(b"unknown owner")
        with pytest.raises(PackageProductGcExecutionError) as unknown_unbound:
            gc.prepare()
        assert unknown_unbound.value.code == "plugin_package_gc_worker_history_unsettled"
        with pytest.raises(PackageProductGcExecutionError) as unknown_bound:
            with_authority.prepare()
        assert unknown_bound.value.code == "plugin_package_gc_worker_history_unsettled"
        with pytest.raises(ValueError, match="reference owner is unrecognized"):
            authority.require_settled(
                observed_names=tuple(os.listdir(product.state_root))
            )
        unknown_before_attempt.unlink()
        repair_before_attempt = (
            product.state_root / f"worker-empty-repair-{'36' * 16}.json"
        )
        repair_before_attempt.write_bytes(b"retained repair")
        with pytest.raises(PackageProductGcExecutionError) as repair_blocked:
            with_authority.prepare()
        assert repair_blocked.value.code == "plugin_package_gc_worker_history_unsettled"
        with pytest.raises(CodingWorkerPayloadMaterializationError) as bad_repair:
            authority.require_settled(
                observed_names=tuple(os.listdir(product.state_root))
            )
        assert bad_repair.value.code == "coding_worker_payload_empty_repair_unverified"
        repair_before_attempt.unlink()
        attempt_id = "35" * 16
        identity = WorkerLaunchIdentityV1(
            plugin_id="workerprobe",
            plugin_revision_digest="a" * 64,
            contribution_id="query-provider",
            owner_id="coding",
            product_id="coding",
            scope_id="test-scope",
            owner_generation=1,
            declaration_fingerprint="b" * 64,
            worker_configuration_fingerprint="c" * 64,
            attempt_id=attempt_id,
            supervisor_epoch=1,
            session_nonce="d" * 64,
        )
        attempt = open_coding_product_worker_supervisor_journal(product).claim(
            identity, max_attempts=1
        )
        assert not attempt.process_settled
        review = review_coding_product_worker_history_retention(
            product, attempt_id=attempt_id
        )
        assert review.unbound_supervisor_attempt_ids == (attempt_id,)
        assert review.retained_start_gate_attempt_ids == ()
        assert review.retained_supervisor_attempt_ids == (attempt_id,)
        assert review.retained_receipt_fingerprints == ()
        assert review.supervisor_epoch_high_water == ((attempt.supervisor_key, 1),)
        assert review.supervisor_history_revision == attempt.record_revision
        assert review.start_gate_history_revision == 0
        assert review.opt_in_history_revision == 0
        assert review.retained_opt_in_operation_ids == ()
        assert "supervisor_gate_reference_unverified" in review.missing_proofs
        unknown = product.state_root / "worker-future-reference.json"
        unknown.write_bytes(b"unknown owner")
        unrecognized = review_coding_product_worker_history_retention(
            product, attempt_id=attempt_id
        )
        assert unrecognized.unrecognized_worker_state_names == (unknown.name,)
        assert "worker_reference_owner_unrecognized" in unrecognized.missing_proofs
        unknown.unlink()
        assert not tuple(product.state_root.glob("worker-payload-*"))
        with pytest.raises(PackageProductGcExecutionError) as blocked:
            gc.prepare()
        assert blocked.value.code == "plugin_package_gc_worker_history_unsettled"
        with pytest.raises(PackageProductGcExecutionError) as unsettled:
            with_authority.prepare()
        assert unsettled.value.code == "plugin_package_gc_worker_history_unsettled"
    finally:
        owner.close()


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux Product Worker GC history"
)
def test_worker_gc_revision_join_keeps_all_same_artifact_pins() -> None:
    reference = history_retention_module.CodingWorkerAttemptReferenceV1(
        attempt_id="1" * 32,
        plugin_id="workerprobe",
        receipt_fingerprint="2" * 64,
        selected_package_revision_digest="a" * 64,
        selected_locator_revision="selected-v1",
        native_platform="linux",
        gate_revision=1,
        gate_phase="bound",
    )
    matching = tuple(
        PluginPackageRevisionRefV1(
            plugin_id="workerprobe",
            plugin_version="1",
            package_content_digest="a" * 64,
            dependency_lock_digest=lock,
            package_source_identity="source-" + lock[0],
        )
        for lock in ("b" * 64, "c" * 64)
    )
    other_plugin = replace(matching[0], plugin_id="another")
    other_artifact = replace(matching[0], package_content_digest="d" * 64)
    same_lock_newer_version = replace(matching[0], plugin_version="2")
    assert history_retention_module._matching_gc_revision_refs(
        reference,
        frozenset(
            (*matching, other_plugin, other_artifact, same_lock_newer_version)
        ),
    ) == (matching[0], same_lock_newer_version, matching[1])


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux Product Worker GC history"
)
def test_worker_package_gc_refuses_compacted_c5_attempt_without_gate(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
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
        namespace_id="a" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        worker_candidates=True,
    )
    try:
        product = owner.runtime_owner.product_owner
        receipt = "a" * 64
        attempt_id = "b" * 32
        key = _AttemptKey(receipt, attempt_id, 1).encoded
        attempt = _registered_attempt(receipt=receipt, attempt_id=attempt_id)
        initial = _initial_state(restart_budget=3)
        registered = _next_state(initial)
        registered["attempts"] = {key: attempt}
        settled = _next_state(registered)
        settled_attempt = dict(attempt)
        settled_attempt.update(
            phase="settled",
            domainRetired=True,
            protocolTerminal=True,
            cleanupSettlement=WorkerCleanupSettlementV1(
                receipt_fingerprint=receipt,
                attempt_id=attempt_id,
                owner_generation=1,
                host_identity="host-a",
                boot_identity="boot-a",
                protocol_terminal=True,
                domain_retired=True,
                tree_settled=True,
            ).to_dict(),
        )
        settled["attempts"] = {key: settled_attempt}
        compacted = _next_state(settled)
        compacted["attempts"] = {}
        journal = activation_state_journal_module.CodingProductWorkerActivationStateJournal(
            product.state_root / "worker-activation-state.jsonl"
        )
        for revision, state in enumerate(
            (initial, registered, settled, compacted)
        ):
            assert journal.compare_and_swap(expected_revision=revision, document=state)
        assert journal.load_read_only() == compacted
        assert len(journal.retained_attempts_read_only()) == 1
        review = review_coding_product_worker_history_retention(
            product, attempt_id=attempt_id
        )
        assert review.gate_record is None
        assert tuple(
            reference.attempt_id
            for reference in review.retained_activation_references
        ) == (attempt_id,)
        assert not review.retained_activation_references[0].current
        assert review.unverified_activation_references == (
            (attempt_id, "activation_reference_gate_absent"),
        )
        elsewhere = review_coding_product_worker_history_retention(
            product, attempt_id="c" * 32
        )
        assert elsewhere.unverified_activation_references == ()
        assert elsewhere.global_unverified_activation_references == (
            (attempt_id, "activation_reference_gate_absent"),
        )
        assert "global_activation_reference_unverified" in elsewhere.missing_proofs
        assert "start_gate_absent" in review.missing_proofs
        authority = CodingPosixWorkerGcHistoryAuthority(product)
        with pytest.raises(ValueError, match="C5 attempt history is incomplete"):
            authority.require_settled(
                observed_names=tuple(os.listdir(product.state_root))
            )
    finally:
        owner.close()


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux Product Worker history"
)
def test_worker_history_review_refuses_swapped_product_state_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
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
        namespace_id="a" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        worker_candidates=True,
    )
    product = owner.runtime_owner.product_owner
    source = product.policy.source_root / f"{_PLUGIN}-{_VERSION}-{_TAG}.whl"
    wheel = _worker_wheel(shape="valid", tag=_TAG)
    source.write_bytes(wheel)
    binding = PackageProductLocalWheelBindingV1(
        source_identity=str(source),
        requested_package=f"{_PLUGIN}=={_VERSION}",
        plugin_id=_PLUGIN,
        artifact_digest=sha256(wheel).hexdigest(),
        plugin_manifest_path=f"{_PLUGIN}/plugin.json",
        source_trust_class="local-worker-candidate",
        worker_admission=PackageProductLocalWorkerAdmissionV1(
            contribution_id=_CONTRIBUTION,
            owner_id=_OWNER,
            native_platform="linux-x86_64",
        ),
    )
    product = replace(
        product,
        policy=replace(
            product.policy,
            bindings=tuple(
                sorted(
                    (*product.policy.bindings, binding),
                    key=lambda item: item.source_identity,
                )
            ),
        ),
    )
    state_root = product.state_root
    (state_root / ("worker-payload-" + "a" * 32)).mkdir(mode=0o700)
    detached = state_root.with_name(state_root.name + "-detached")
    decoy = state_root.with_name(state_root.name + "-decoy")
    decoy.mkdir(mode=0o700)

    class SwappingOs:
        swapped = False

        def __getattr__(self, name: str) -> object:
            return getattr(os, name)

        def open(self, path: object, flags: int, **kwargs: object) -> int:
            if path == state_root and not self.swapped:
                state_root.rename(detached)
                decoy.rename(state_root)
                self.swapped = True
            return os.open(path, flags, **kwargs)

        def listdir(self, path: object) -> list[str]:
            if self.swapped:
                state_root.rename(decoy)
                detached.rename(state_root)
                self.swapped = False
            return os.listdir(path)

    swapping_os = SwappingOs()
    monkeypatch.setattr(history_retention_module, "os", swapping_os)
    monkeypatch.setattr(local_wheel_runtime_module, "os", swapping_os)
    try:
        with pytest.raises(ValueError, match="state root descriptor changed"):
            review_coding_product_worker_history_retention(product, attempt_id="a" * 32)
    finally:
        if swapping_os.swapped:
            state_root.rename(decoy)
            detached.rename(state_root)
        owner.close()


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux Product payload custody"
)
def test_empty_worker_payload_debt_requires_absent_supervisor_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
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
        namespace_id="a" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        worker_candidates=True,
    )
    try:
        product = owner.runtime_owner.product_owner
        attempt_id = "12" * 16
        stage = product.state_root / f"worker-payload-{attempt_id}"
        stage.mkdir(mode=0o700)
        gc = open_posix_local_wheel_product_root_gc(product)
        with pytest.raises(PackageProductGcExecutionError) as blocked_gc:
            gc.prepare()
        assert blocked_gc.value.code == "plugin_package_gc_worker_payload_unsettled"
        with pytest.raises(CodingWorkerPayloadMaterializationError) as inventory:
            list_coding_product_worker_payload_debts(product)
        assert inventory.value.code == "coding_worker_payload_debt_unverified"
        plan = preview_coding_product_worker_empty_payload_debt(
            product, attempt_id=attempt_id
        )
        assert plan.attempt_id == attempt_id
        (stage / "foreign").write_bytes(b"foreign")
        with pytest.raises(CodingWorkerPayloadMaterializationError) as occupied:
            repair_coding_product_worker_empty_payload_debt(product, expected_plan=plan)
        assert occupied.value.code == "coding_worker_payload_empty_debt_unverified"
        (stage / "foreign").unlink()
        with pytest.raises(CodingWorkerPayloadMaterializationError) as stale:
            repair_coding_product_worker_empty_payload_debt(
                product, expected_plan=replace(plan, stage_inode=plan.stage_inode + 1)
            )
        assert stale.value.code == "coding_worker_payload_debt_plan_stale"
        held = product.state_root / "held-empty-worker-stage"
        stage.rename(held)
        stage.mkdir(mode=0o700)
        with pytest.raises(CodingWorkerPayloadMaterializationError) as replaced:
            repair_coding_product_worker_empty_payload_debt(product, expected_plan=plan)
        assert replaced.value.code == "coding_worker_payload_debt_plan_stale"
        assert stage.is_dir() and held.is_dir()
        stage.rmdir()
        held.rename(stage)
        with product.gc_gate.read_snapshot_guard():
            assert preview_coding_product_worker_empty_payload_debt(
                product, attempt_id=attempt_id
            ) == plan
            with pytest.raises(PluginPackageGcReservationError) as blocked_write:
                repair_coding_product_worker_empty_payload_debt(
                    product, expected_plan=plan
                )
            assert blocked_write.value.code == "plugin_package_gc_read_guard_nested"
            assert stage.is_dir()
        replacement_stage = product.state_root / "replacement-empty-worker-stage"
        replacement_stage.mkdir(mode=0o700)
        assert (
            repair_coding_product_worker_empty_payload_debt(product, expected_plan=plan)
            == plan
        )
        assert not stage.exists()
        assert list_coding_product_worker_payload_debts(product) == ()
        intent = product.state_root / f"worker-empty-repair-{attempt_id}.json"
        review = review_coding_product_worker_history_retention(
            product, attempt_id=attempt_id
        )
        assert review.retained_payload_repair_reference_names == (intent.name,)
        assert "payload_repair_reference_retained" in review.missing_proofs
        staging_intent = product.state_root / (
            f".worker-empty-repair-{attempt_id}.json.stage"
        )
        os.link(intent, staging_intent)
        assert (
            reopen_coding_product_worker_empty_payload_repair(
                product, attempt_id=attempt_id
            )
            == plan
        )
        assert (
            repair_coding_product_worker_empty_payload_debt(product, expected_plan=plan)
            == plan
        )
        assert not staging_intent.exists()
        replacement_stage.rename(stage)
        assert (
            reopen_coding_product_worker_empty_payload_repair(
                product, attempt_id=attempt_id
            )
            is None
        )
        with pytest.raises(CodingWorkerPayloadMaterializationError) as reused_stage:
            repair_coding_product_worker_empty_payload_debt(product, expected_plan=plan)
        assert reused_stage.value.code == "coding_worker_payload_debt_plan_stale"
        assert stage.is_dir()
        stage.rmdir()
        intent_bytes = intent.read_bytes()
        intent.write_bytes(intent_bytes + b" ")
        with pytest.raises(CodingWorkerPayloadMaterializationError) as changed_intent:
            reopen_coding_product_worker_empty_payload_repair(
                product, attempt_id=attempt_id
            )
        assert changed_intent.value.code == (
            "coding_worker_payload_empty_repair_unverified"
        )
        intent.write_bytes(intent_bytes)
        held_intent = product.state_root / "held-empty-repair-intent"
        intent.rename(held_intent)
        intent.symlink_to(held_intent)
        with pytest.raises(CodingWorkerPayloadMaterializationError) as linked_intent:
            reopen_coding_product_worker_empty_payload_repair(
                product, attempt_id=attempt_id
            )
        assert linked_intent.value.code == (
            "coding_worker_payload_empty_repair_unverified"
        )
        intent.unlink()
        held_intent.rename(intent)
        with pytest.raises(PackageProductGcExecutionError) as no_repair_authority:
            gc.prepare()
        assert no_repair_authority.value.code == (
            "plugin_package_gc_worker_history_unsettled"
        )
        open_posix_local_wheel_product_root_gc(
            product,
            worker_history_authority=CodingPosixWorkerGcHistoryAuthority(product),
        ).prepare()

        crash_attempt = "56" * 16
        crash_stage = product.state_root / f"worker-payload-{crash_attempt}"
        crash_stage.mkdir(mode=0o700)
        crash_plan = preview_coding_product_worker_empty_payload_debt(
            product, attempt_id=crash_attempt
        )
        remove_empty_stage = worker_payload_module._remove_empty_stage

        def crash_after_removal(root_fd: int, stage_name: str) -> None:
            remove_empty_stage(root_fd, stage_name)
            if stage_name == f"worker-payload-{crash_attempt}":
                raise OSError("injected post-remove interruption")

        with monkeypatch.context() as patch:
            patch.setattr(
                worker_payload_module, "_remove_empty_stage", crash_after_removal
            )
            with pytest.raises(OSError, match="post-remove interruption"):
                repair_coding_product_worker_empty_payload_debt(
                    product, expected_plan=crash_plan
                )
        assert not crash_stage.exists()
        assert (
            reopen_coding_product_worker_empty_payload_repair(
                product, attempt_id=crash_attempt
            )
            == crash_plan
        )
        assert (
            repair_coding_product_worker_empty_payload_debt(
                product, expected_plan=crash_plan
            )
            == crash_plan
        )

        partial_attempt = "78" * 16
        partial_stage = product.state_root / f"worker-payload-{partial_attempt}"
        partial_stage.mkdir(mode=0o700)
        partial_plan = preview_coding_product_worker_empty_payload_debt(
            product, attempt_id=partial_attempt
        )
        partial_intent = product.state_root / (
            f".worker-empty-repair-{partial_attempt}.json.stage"
        )
        partial_intent.write_bytes(b"partial")
        partial_intent.chmod(0o600)
        with pytest.raises(CodingWorkerPayloadMaterializationError) as incomplete:
            repair_coding_product_worker_empty_payload_debt(
                product, expected_plan=partial_plan
            )
        assert incomplete.value.code == (
            "coding_worker_payload_empty_repair_unverified"
        )
        assert partial_stage.is_dir()
        partial_intent.unlink()
        partial_stage.rmdir()

        claimed_attempt = "34" * 16
        claimed_stage = product.state_root / f"worker-payload-{claimed_attempt}"
        claimed_stage.mkdir(mode=0o700)
        claimed_plan = preview_coding_product_worker_empty_payload_debt(
            product, attempt_id=claimed_attempt
        )
        identity = WorkerLaunchIdentityV1(
            plugin_id="workerprobe",
            plugin_revision_digest="a" * 64,
            contribution_id="query-provider",
            owner_id="coding",
            product_id="coding",
            scope_id="test-scope",
            owner_generation=1,
            declaration_fingerprint="b" * 64,
            worker_configuration_fingerprint="c" * 64,
            attempt_id=claimed_attempt,
            supervisor_epoch=1,
            session_nonce="d" * 64,
        )
        open_coding_product_worker_supervisor_journal(product).claim(
            identity, max_attempts=1
        )
        with pytest.raises(CodingWorkerPayloadMaterializationError) as claimed:
            repair_coding_product_worker_empty_payload_debt(
                product, expected_plan=claimed_plan
            )
        assert claimed.value.code == "coding_worker_payload_attempt_claimed"
        assert claimed_stage.exists()
        claimed_stage.rmdir()
    finally:
        owner.close()


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux Product payload custody"
)
@pytest.mark.parametrize(
    "interruption", ("before", "leaf", "parent", "marker", "removed")
)
def test_complete_worker_payload_repair_resumes_partial_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interruption: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
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
        namespace_id="a" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        worker_candidates=True,
    )
    try:
        product = owner.runtime_owner.product_owner
        attempt_id = "9a" * 16
        stage = product.state_root / f"worker-payload-{attempt_id}"
        stage.mkdir(mode=0o700)
        body = b"settled Worker payload fixture"
        stage_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            worker_payload_module._write_payload(stage_fd, "bin/worker", body)
            stage_stat = os.fstat(stage_fd)
            plan = CodingWorkerPayloadDebtPlanV1(
                attempt_id=attempt_id,
                entrypoint="bin/worker",
                payload_digest=sha256(body).hexdigest(),
                payload_size=len(body),
                receipt_fingerprint="f" * 64,
                stage_device=stage_stat.st_dev,
                stage_inode=stage_stat.st_ino,
            )
            worker_payload_module._write_marker(stage_fd, plan)
        finally:
            os.close(stage_fd)
        journal = open_coding_product_worker_supervisor_journal(product)
        identity = WorkerLaunchIdentityV1(
            plugin_id="workerprobe",
            plugin_revision_digest="a" * 64,
            contribution_id="query-provider",
            owner_id="coding",
            product_id="coding",
            scope_id="test-scope",
            owner_generation=1,
            declaration_fingerprint="b" * 64,
            worker_configuration_fingerprint="c" * 64,
            attempt_id=attempt_id,
            supervisor_epoch=1,
            session_nonce="d" * 64,
        )
        claimed = journal.claim(identity, max_attempts=1)
        failed = journal.transition(
            attempt_id,
            expected_phase="claimed",
            next_phase="failed",
            expected_record_revision=claimed.record_revision,
            expected_supervisor_epoch=1,
            failure_code="worker_launch_failed",
        )
        settled = journal.transition(
            attempt_id,
            expected_phase="failed",
            next_phase="process_settled",
            expected_record_revision=failed.record_revision,
            expected_supervisor_epoch=1,
            failure_code=failed.failure_code,
        )
        assert settled.process_settled
        assert (
            preview_coding_product_worker_payload_debt(product, attempt_id=attempt_id)
            == plan
        )
        gc = open_posix_local_wheel_product_root_gc(
            product,
            worker_history_authority=CodingPosixWorkerGcHistoryAuthority(product),
        )
        with pytest.raises(PackageProductGcExecutionError):
            gc.prepare()
        replacement_stage = product.state_root / "replacement-complete-worker-stage"
        replacement_stage.mkdir(mode=0o700)

        def interrupted_removal(
            root_fd: int,
            opened_stage_fd: int,
            stage_name: str,
            expected: CodingWorkerPayloadDebtPlanV1,
        ) -> None:
            assert stage_name == f"worker-payload-{attempt_id}"
            assert expected == plan
            if interruption == "before":
                raise OSError("injected partial payload deletion")
            parent_fd = os.open(
                "bin",
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=opened_stage_fd,
            )
            try:
                os.unlink("worker", dir_fd=parent_fd)
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
            if interruption in {"parent", "marker", "removed"}:
                os.rmdir("bin", dir_fd=opened_stage_fd)
                os.fsync(opened_stage_fd)
            if interruption in {"marker", "removed"}:
                os.unlink("product-payload.json", dir_fd=opened_stage_fd)
                os.fsync(opened_stage_fd)
            if interruption == "removed":
                os.rmdir(stage_name, dir_fd=root_fd)
                os.fsync(root_fd)
            raise OSError("injected partial payload deletion")

        with monkeypatch.context() as patch:
            patch.setattr(
                worker_payload_module, "_remove_verified_stage", interrupted_removal
            )
            with pytest.raises(OSError, match="partial payload deletion"):
                repair_coding_product_worker_payload_debt(product, expected_plan=plan)
        owner.close()
        owner = open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
            worker_candidates=True,
        )
        product = owner.runtime_owner.product_owner
        gc = open_posix_local_wheel_product_root_gc(product)
        assert stage.is_dir() == (interruption != "removed")
        assert (stage / "bin" / "worker").exists() == (interruption == "before")
        assert (stage / "product-payload.json").is_file() == (
            interruption in {"before", "leaf", "parent"}
        )
        if interruption == "before":
            assert (
                preview_coding_product_worker_payload_debt(
                    product, attempt_id=attempt_id
                )
                == plan
            )
        else:
            with pytest.raises(CodingWorkerPayloadMaterializationError):
                preview_coding_product_worker_payload_debt(
                    product, attempt_id=attempt_id
                )
        assert reopen_coding_product_worker_payload_repair(
            product, attempt_id=attempt_id
        ) == (plan if interruption == "removed" else None)
        if interruption == "leaf":
            held_stage = product.state_root / "held-complete-worker-stage"
            stage.rename(held_stage)
            stage.mkdir(mode=0o700)
            with pytest.raises(CodingWorkerPayloadMaterializationError) as replaced:
                repair_coding_product_worker_payload_debt(product, expected_plan=plan)
            assert replaced.value.code == "coding_worker_payload_debt_unverified"
            assert stage.is_dir() and held_stage.is_dir()
            stage.rmdir()
            held_stage.rename(stage)
            (stage / "foreign").write_bytes(b"foreign")
            with pytest.raises(CodingWorkerPayloadMaterializationError) as foreign:
                repair_coding_product_worker_payload_debt(product, expected_plan=plan)
            assert foreign.value.code == "coding_worker_payload_debt_unverified"
            (stage / "foreign").unlink()
            marker = stage / "product-payload.json"
            marker_body = marker.read_bytes()
            marker.write_bytes(b"changed")
            with pytest.raises(CodingWorkerPayloadMaterializationError) as changed:
                repair_coding_product_worker_payload_debt(product, expected_plan=plan)
            assert changed.value.code == "coding_worker_payload_debt_unverified"
            marker.write_bytes(marker_body)
        if interruption == "before":
            payload = stage / "bin" / "worker"
            payload.chmod(0o600)
            payload.write_bytes(b"changed")
            payload.chmod(0o500)
            with pytest.raises(CodingWorkerPayloadMaterializationError) as changed:
                repair_coding_product_worker_payload_debt(product, expected_plan=plan)
            assert changed.value.code == "coding_worker_payload_debt_unverified"
            payload.chmod(0o600)
            payload.write_bytes(body)
            payload.chmod(0o500)
            with product.gc_gate.read_snapshot_guard():
                with pytest.raises(PluginPackageGcReservationError) as blocked_write:
                    repair_coding_product_worker_payload_debt(
                        product, expected_plan=plan
                    )
                assert blocked_write.value.code == "plugin_package_gc_read_guard_nested"
                assert stage.is_dir()
        assert (
            repair_coding_product_worker_payload_debt(product, expected_plan=plan)
            == plan
        )
        assert not stage.exists()
        assert (
            reopen_coding_product_worker_payload_repair(product, attempt_id=attempt_id)
            == plan
        )
        assert (
            repair_coding_product_worker_payload_debt(product, expected_plan=plan)
            == plan
        )
        if interruption == "before":
            replacement_stage.rename(stage)
            assert (
                reopen_coding_product_worker_payload_repair(
                    product, attempt_id=attempt_id
                )
                is None
            )
            with pytest.raises(CodingWorkerPayloadMaterializationError) as reused:
                repair_coding_product_worker_payload_debt(product, expected_plan=plan)
            assert reused.value.code == "coding_worker_payload_debt_unverified"
            assert stage.is_dir()
            stage.rmdir()
            intent = product.state_root / (f"worker-complete-repair-{attempt_id}.json")
            staging_intent = product.state_root / (
                f".worker-complete-repair-{attempt_id}.json.stage"
            )
            os.link(intent, staging_intent)
            assert (
                reopen_coding_product_worker_payload_repair(
                    product, attempt_id=attempt_id
                )
                == plan
            )
            assert (
                repair_coding_product_worker_payload_debt(product, expected_plan=plan)
                == plan
            )
            assert not staging_intent.exists()
            intent_bytes = intent.read_bytes()
            intent.write_bytes(intent_bytes + b" ")
            with pytest.raises(CodingWorkerPayloadMaterializationError) as changed:
                reopen_coding_product_worker_payload_repair(
                    product, attempt_id=attempt_id
                )
            assert changed.value.code == (
                "coding_worker_payload_complete_repair_unverified"
            )
            intent.write_bytes(intent_bytes)
            held_intent = product.state_root / "held-complete-repair-intent"
            intent.rename(held_intent)
            intent.symlink_to(held_intent)
            with pytest.raises(CodingWorkerPayloadMaterializationError) as linked:
                reopen_coding_product_worker_payload_repair(
                    product, attempt_id=attempt_id
                )
            assert linked.value.code == (
                "coding_worker_payload_complete_repair_unverified"
            )
            intent.unlink()
            held_intent.rename(intent)
        else:
            replacement_stage.rmdir()
        with pytest.raises(PackageProductGcExecutionError) as orphan_history:
            gc.prepare()
        assert orphan_history.value.code == (
            "plugin_package_gc_worker_history_unsettled"
        )
        with pytest.raises(PackageProductGcExecutionError) as bound_orphan:
            open_posix_local_wheel_product_root_gc(
                product,
                worker_history_authority=CodingPosixWorkerGcHistoryAuthority(product),
            ).prepare()
        assert bound_orphan.value.code == "plugin_package_gc_worker_history_unsettled"
    finally:
        owner.close()


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux Product payload custody"
)
def test_unmarked_worker_payload_review_is_bounded_and_read_only(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
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
        namespace_id="a" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        worker_candidates=True,
    )
    try:
        product = owner.runtime_owner.product_owner
        attempt_id = "ab" * 16
        stage = product.state_root / f"worker-payload-{attempt_id}"
        stage.mkdir(mode=0o700)
        payload_dir = stage / "bin"
        payload_dir.mkdir(mode=0o700)
        payload = payload_dir / "worker"
        payload.write_bytes(b"partial Worker payload")
        payload.chmod(0o600)
        with pytest.raises(CodingWorkerPayloadMaterializationError):
            list_coding_product_worker_payload_debts(product)
        with pytest.raises(PackageProductGcExecutionError):
            open_posix_local_wheel_product_root_gc(product).prepare()
        review = review_coding_product_worker_unmarked_payload_debt(
            product, attempt_id=attempt_id
        )
        assert tuple(item.relative_path for item in review.members) == (
            "bin",
            "bin/worker",
        )
        assert tuple(item.kind for item in review.members) == ("directory", "file")
        assert review.members[-1].digest == sha256(payload.read_bytes()).hexdigest()
        assert (
            review.fingerprint
            == review_coding_product_worker_unmarked_payload_debt(
                product, attempt_id=attempt_id
            ).fingerprint
        )
        payload.write_bytes(b"changed partial Worker payload")
        changed = review_coding_product_worker_unmarked_payload_debt(
            product, attempt_id=attempt_id
        )
        assert changed.fingerprint != review.fingerprint
        payload.write_bytes(b"partial Worker payload")
        foreign = stage / "foreign"
        foreign.write_bytes(b"foreign")
        with pytest.raises(CodingWorkerPayloadMaterializationError) as extra:
            review_coding_product_worker_unmarked_payload_debt(
                product, attempt_id=attempt_id
            )
        assert extra.value.code == "coding_worker_payload_unmarked_debt_unverified"
        foreign.unlink()
        held = product.state_root / "held-unmarked-worker"
        payload.rename(held)
        payload.symlink_to(held)
        with pytest.raises(CodingWorkerPayloadMaterializationError) as linked:
            review_coding_product_worker_unmarked_payload_debt(
                product, attempt_id=attempt_id
            )
        assert linked.value.code == "coding_worker_payload_unmarked_debt_unverified"
        payload.unlink()
        held.rename(payload)

        directory_attempt = "cd" * 16
        directory_stage = product.state_root / f"worker-payload-{directory_attempt}"
        directory_stage.mkdir(mode=0o700)
        (directory_stage / "bin").mkdir(mode=0o700)
        directory_review = review_coding_product_worker_unmarked_payload_debt(
            product, attempt_id=directory_attempt
        )
        assert tuple(item.relative_path for item in directory_review.members) == (
            "bin",
        )
        marker_attempt = "ef" * 16
        marker_stage = product.state_root / f"worker-payload-{marker_attempt}"
        marker_stage.mkdir(mode=0o700)
        (marker_stage / "product-payload.json").write_bytes(b"partial")
        with pytest.raises(CodingWorkerPayloadMaterializationError):
            review_coding_product_worker_unmarked_payload_debt(
                product, attempt_id=marker_attempt
            )

        identity = WorkerLaunchIdentityV1(
            plugin_id="workerprobe",
            plugin_revision_digest="a" * 64,
            contribution_id="query-provider",
            owner_id="coding",
            product_id="coding",
            scope_id="test-scope",
            owner_generation=1,
            declaration_fingerprint="b" * 64,
            worker_configuration_fingerprint="c" * 64,
            attempt_id=attempt_id,
            supervisor_epoch=1,
            session_nonce="d" * 64,
        )
        open_coding_product_worker_supervisor_journal(product).claim(
            identity, max_attempts=1
        )
        with pytest.raises(CodingWorkerPayloadMaterializationError) as claimed:
            review_coding_product_worker_unmarked_payload_debt(
                product, attempt_id=attempt_id
            )
        assert claimed.value.code == "coding_worker_payload_attempt_claimed"
        with pytest.raises(CodingWorkerPayloadMaterializationError) as claimed_repair:
            repair_coding_product_worker_unmarked_payload_debt(
                product, expected_review=changed
            )
        assert claimed_repair.value.code == "coding_worker_payload_attempt_claimed"
    finally:
        owner.close()


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux Product payload custody"
)
@pytest.mark.parametrize("interruption", ["before", "file", "directory", "removed"])
def test_unmarked_worker_payload_repair_resumes_exact_partial_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interruption: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
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
        namespace_id="a" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        worker_candidates=True,
    )
    try:
        product = owner.runtime_owner.product_owner
        attempt_id = "ab" * 16
        stage = product.state_root / f"worker-payload-{attempt_id}"
        stage.mkdir(mode=0o700)
        (stage / "bin").mkdir(mode=0o700)
        payload = stage / "bin" / "worker"
        payload.write_bytes(b"incomplete Worker payload")
        payload.chmod(0o600)
        review = review_coding_product_worker_unmarked_payload_debt(
            product, attempt_id=attempt_id
        )
        gc = open_posix_local_wheel_product_root_gc(product)
        with pytest.raises(PackageProductGcExecutionError):
            gc.prepare()

        def interrupted_removal(
            root_fd: int,
            stage_fd: int,
            stage_name: str,
            expected: object,
            *,
            allow_partial: bool,
        ) -> None:
            assert stage_name == f"worker-payload-{attempt_id}"
            assert expected == review and allow_partial
            if interruption in {"file", "directory", "removed"}:
                parent_fd = os.open(
                    "bin",
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=stage_fd,
                )
                try:
                    os.unlink("worker", dir_fd=parent_fd)
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
            if interruption in {"directory", "removed"}:
                os.rmdir("bin", dir_fd=stage_fd)
                os.fsync(stage_fd)
            if interruption == "removed":
                os.rmdir(stage_name, dir_fd=root_fd)
                os.fsync(root_fd)
            raise OSError("injected unmarked payload interruption")

        with monkeypatch.context() as patch:
            patch.setattr(
                worker_payload_module,
                "_remove_unmarked_repair_remainder",
                interrupted_removal,
            )
            with pytest.raises(OSError, match="unmarked payload interruption"):
                repair_coding_product_worker_unmarked_payload_debt(
                    product, expected_review=review
                )
        owner.close()
        owner = open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
            worker_candidates=True,
        )
        product = owner.runtime_owner.product_owner
        assert reopen_coding_product_worker_unmarked_payload_repair(
            product, attempt_id=attempt_id
        ) == (review if interruption == "removed" else None)
        if interruption == "file":
            (stage / "foreign").write_bytes(b"foreign")
            with pytest.raises(CodingWorkerPayloadMaterializationError):
                repair_coding_product_worker_unmarked_payload_debt(
                    product, expected_review=review
                )
            (stage / "foreign").unlink()
            held_directory = product.state_root / "held-unmarked-bin"
            (stage / "bin").rename(held_directory)
            (stage / "bin").mkdir(mode=0o700)
            with pytest.raises(CodingWorkerPayloadMaterializationError) as replaced:
                repair_coding_product_worker_unmarked_payload_debt(
                    product, expected_review=review
                )
            assert replaced.value.code == "coding_worker_payload_debt_plan_stale"
            (stage / "bin").rmdir()
            held_directory.rename(stage / "bin")
        if interruption == "before":
            payload.write_bytes(b"changed Worker payload")
            with pytest.raises(CodingWorkerPayloadMaterializationError):
                repair_coding_product_worker_unmarked_payload_debt(
                    product, expected_review=review
                )
            payload.write_bytes(b"incomplete Worker payload")
            with product.gc_gate.read_snapshot_guard():
                with pytest.raises(PluginPackageGcReservationError) as blocked_write:
                    repair_coding_product_worker_unmarked_payload_debt(
                        product, expected_review=review
                    )
                assert blocked_write.value.code == "plugin_package_gc_read_guard_nested"
                assert stage.is_dir()
        assert (
            repair_coding_product_worker_unmarked_payload_debt(
                product, expected_review=review
            )
            == review
        )
        assert not stage.exists()
        assert (
            reopen_coding_product_worker_unmarked_payload_repair(
                product, attempt_id=attempt_id
            )
            == review
        )
        assert (
            repair_coding_product_worker_unmarked_payload_debt(
                product, expected_review=review
            )
            == review
        )
        if interruption == "before":
            intent = product.state_root / f"worker-unmarked-repair-{attempt_id}.json"
            body = intent.read_bytes()
            intent.write_bytes(body + b" ")
            with pytest.raises(CodingWorkerPayloadMaterializationError) as changed:
                reopen_coding_product_worker_unmarked_payload_repair(
                    product, attempt_id=attempt_id
                )
            assert (
                changed.value.code == "coding_worker_payload_unmarked_repair_unverified"
            )
            intent.write_bytes(body)
            held_intent = product.state_root / "held-unmarked-repair-intent"
            intent.rename(held_intent)
            intent.symlink_to(held_intent)
            with pytest.raises(CodingWorkerPayloadMaterializationError) as linked:
                reopen_coding_product_worker_unmarked_payload_repair(
                    product, attempt_id=attempt_id
                )
            assert (
                linked.value.code == "coding_worker_payload_unmarked_repair_unverified"
            )
            intent.unlink()
            held_intent.rename(intent)
        with pytest.raises(PackageProductGcExecutionError) as no_repair_authority:
            open_posix_local_wheel_product_root_gc(product).prepare()
        assert no_repair_authority.value.code == (
            "plugin_package_gc_worker_history_unsettled"
        )
        open_posix_local_wheel_product_root_gc(
            product,
            worker_history_authority=CodingPosixWorkerGcHistoryAuthority(product),
        ).prepare()
    finally:
        owner.close()
