from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import stat
import subprocess
import sys
import time
import zipfile
from base64 import urlsafe_b64encode
from collections.abc import AsyncIterator
from contextlib import contextmanager, suppress
from dataclasses import replace
from hashlib import sha256
from importlib.metadata import version
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast

import pytest

from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.json_codec import serialize_message
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.prepared_request import PreparedModelRequest
from loushang.ai.provider.protocol import ProviderRequest
from loushang.coding._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.bootstrap import create_agent_session, create_services
from loushang.coding.cli.application import run_cli
from loushang.coding.cli.package_repair import main as package_repair_main
from loushang.coding.package_epoch_layout import resolve_coding_package_epoch_layout
from loushang.coding.package_external_data_wheel import (
    CodingExternalDataWheelCatalog,
    CodingExternalDataWheelError,
)
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.package_product_management_cli import (
    build_coding_fenced_product_management_cli_ports,
    explain_coding_fenced_package_operation,
)
from loushang.coding.package_product_preview import (
    CodingFencedProductReadOnlyPreviewOwner,
)
from loushang.coding.package_product_repair import open_coding_package_repair_client
from loushang.coding.package_product_runtime import (
    CodingFencedProductApplicationSelection,
    admit_coding_external_data_wheel,
    open_coding_fenced_product_application_owner,
)
from loushang.coding.plugin_management_cli import (
    build_coding_plugin_management_cli_binding,
    build_coding_plugin_management_cli_read_binding,
)
from loushang.coding.plugin_management_command_rpc import (
    bind_coding_plugin_desired_rpc_client,
)
from loushang.coding.plugin_management_command_sdk import (
    CodingPluginManagementCommandClientV1,
    CodingPluginManagementCommandSdkError,
    open_coding_plugin_management_command_client,
)
from loushang.coding.plugin_management_explanation import (
    bind_coding_plugin_operation_explanation_query,
)
from loushang.coding.plugin_management_preview import (
    CodingCurrentPreviewError,
    bind_coding_current_preview_query,
)
from loushang.coding.plugin_management_read_sdk import (
    bind_coding_plugin_management_rpc_query,
    open_coding_plugin_management_read_client,
)
from loushang.coding.plugin_management_rpc_scope import CodingPluginRpcSessionScope
from loushang.coding.session_manager import SessionManager
from loushang.coding.ui import mode as coding_tui_mode
from loushang.coding.ui.plugin_theme import select_coding_plugin_theme
from loushang.harness.capabilities.consumer_requirements import ProductCompositionError
from loushang.harness.cli.plugin_listing import list_plugin_records
from loushang.harness.cli.resource_toggles import (
    ResourceToggleRequest,
    apply_resource_toggles,
)
from loushang.harness.config.agent import ControlConfig, SettingsManager
from loushang.harness.host.rpc import RpcHost
from loushang.harness.journal import journal_file_lock
from loushang.harness.package_product.product_rebind_cleanup import (
    PackageProductRebindCleanupReadError,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
    PackageProductRuntimeRequestV1,
)
from loushang.harness.package_product.product_worker_candidate import (
    verify_product_selected_worker_candidate,
)
from loushang.harness.plugin_management import (
    PluginDesiredStateMutationV1,
    PluginManagementApplicationCommandV1,
    PluginManagementCommandV1,
    PluginManagementOperationEventV1,
    PluginManagementQueryV1,
    PluginRetirementIntentLedger,
    PluginRetirementSetLedger,
)
from loushang.harness.plugin_management.application import (
    PluginManagementApplicationResultV1,
)
from loushang.harness.plugin_management.current_preview import (
    PluginCurrentPreviewRequestV1,
)
from loushang.harness.plugin_management.desired_command import (
    PluginDesiredCommandAuthorityV1,
    PluginDesiredCommandRepairError,
    PluginDesiredCommandRequestV1,
    submit_plugin_desired_command,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.operation_explanation import (
    PluginOperationExplanationProjector,
    PluginOperationExplanationRequestV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    PackageAcquisitionBudgetV1,
    PackageAcquisitionOwner,
    PackageAcquisitionRequestV1,
    PackageQuarantineStore,
)
from loushang.harness.resources.packages.plugin_lifecycle.cleanup import (
    PackageQuarantineCleanupJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    NormalizedPackageRequirementV1,
    VerifiedClosurePlanNodeV2,
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_journal import (
    PackageClosureResolutionBasisV1,
    PackageClosureResolutionJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_owner import (
    PackageDependencySelectionRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_runtime import (
    PackageClosureLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_admission import (
    PackageCommitLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.owner import (
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.phase_evidence import (
    PackageArtifactEvidenceJournal,
    PackageAuthenticatedSourceEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_materialization import (
    PosixPackagePluginRootMaterializationStore,
)
from loushang.harness.resources.packages.plugin_lifecycle.product_retention import (
    PackageProductRetentionSettlementOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleIngressRequestV2,
    PackageLifecycleRequestV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageRetentionHandoffJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging import (
    PackageArtifactStagingJournal,
    PackageArtifactStagingJournalError,
    PackageArtifactStagingReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging_set_runtime import (
    PackageStagingCheckpointError,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreSettlementJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinJournal,
    PackageTransactionPinReceiptV1,
    PackageTransactionPinRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    PackageInspectionBudgetV1,
    PackageWheelVerifier,
    VerifiedWheelCandidate,
)
from loushang.harness.resources.packages.product_activation import (
    PackageProductActivationError,
)
from loushang.harness.resources.packages.product_admission_binding import (
    PackageProductAdmissionBindingJournal,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleIntentV1,
)
from loushang.harness.resources.packages.product_handoff import (
    PackageProductHandoffFinalizer,
)
from loushang.harness.resources.packages.product_lifecycle import (
    PackageProductPinnedAdoptedRouteRequestV1,
    PackageProductRouteContractError,
    require_rebound_decision,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelDependencyV1,
    PackageProductRebindSourceError,
)
from loushang.harness.resources.packages.product_staging_adoption_binding import (
    PackageProductStagingAdoptionBindingJournal,
)
from loushang.harness.worker.package_candidate import WorkerPackageCandidateError
from loushang.plugin import (
    ResourceItemSpec,
    build_coding_data_prompt_wheel,
    build_coding_data_theme_wheel,
    package,
    resource,
    skill_action,
)
from loushang.plugin.__main__ import main as plugin_cli_main
from loushang.tui import LoushangWelcomePanel, RenderConstraints


def _data_wheel(
    *,
    version: str = "1",
    plugin_id: str = "reviewpack",
    skill_name: str = "review",
    executable_member: bool = False,
    actions_member: bool = False,
    requires_dist: bool = False,
    manifest_bytes: bytes | None = None,
    extra_enabled_field: bool | None = None,
    managed_actions_reservation: bool = False,
    skill_size: int | None = None,
) -> bytes:
    compiled = package(
        id=plugin_id,
        version=version,
        contributions=(
            resource.skill(
                contribution_id=f"{skill_name}-skill",
                locator=f"skills/{skill_name}",
                actions=(
                    skill_action(
                        id=skill_name,
                        script=f"scripts/{skill_name}.py",
                        script_digest=sha256(b"print('review')\n").hexdigest(),
                        runtime="python",
                    ),
                )
                if managed_actions_reservation
                else (),
            ),
        ),
    )
    files = {
        f"{plugin_id}/{item.path}": item.content
        for item in compiled.artifacts
        if not (managed_actions_reservation and item.path.endswith("/actions.json"))
    }
    if manifest_bytes is not None:
        files[f"{plugin_id}/plugin.json"] = manifest_bytes
    if extra_enabled_field is not None:
        manifest_path = f"{plugin_id}/plugin.json"
        manifest_document = json.loads(files[manifest_path])
        manifest_document["enabled"] = extra_enabled_field
        files[manifest_path] = json.dumps(
            manifest_document, sort_keys=True, separators=(",", ":")
        ).encode()
    skill_path = f"{plugin_id}/skills/{skill_name}/SKILL.md"
    files[skill_path] = (
        f"---\nname: {skill_name}\ndescription: {skill_name} files v{version}\n---\n"
        f"# {skill_name.title()} v{version}\n"
    ).encode()
    if skill_size is not None:
        files[skill_path] = files[skill_path].ljust(skill_size, b" ")
    if executable_member:
        files[f"{plugin_id}/entry.py"] = b"raise RuntimeError('must never execute')\n"
    if actions_member:
        files[f"{plugin_id}/skills/{skill_name}/actions.json"] = b"{}\n"
    files[f"{plugin_id}-{version}.dist-info/METADATA"] = (
        f"Metadata-Version: 2.1\nName: {plugin_id}\nVersion: {version}\n"
        + ("Requires-Dist: requests\n" if requires_dist else "")
        + "\n"
    ).encode()
    files[f"{plugin_id}-{version}.dist-info/WHEEL"] = (
        b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n"
    )
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name, body in sorted(files.items()):
        digest = urlsafe_b64encode(sha256(body).digest()).rstrip(b"=").decode("ascii")
        writer.writerow((name, f"sha256={digest}", str(len(body))))
    writer.writerow((f"{plugin_id}-{version}.dist-info/RECORD", "", ""))
    files[f"{plugin_id}-{version}.dist-info/RECORD"] = record.getvalue().encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, body in sorted(files.items()):
            member = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            member.create_system = 3
            member.external_attr = (stat.S_IFREG | 0o644) << 16
            member.compress_type = zipfile.ZIP_STORED
            archive.writestr(member, body)
    return output.getvalue()


def _library_wheel(*, project: str, version: str) -> bytes:
    dist_info = f"{project}-{version}.dist-info"
    files = {
        f"{project}/__init__.py": b"VALUE = 1\n",
        f"{dist_info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {project}\nVersion: {version}\n\n"
        ).encode(),
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n"
        ),
    }
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name, body in sorted(files.items()):
        digest = urlsafe_b64encode(sha256(body).digest()).rstrip(b"=").decode()
        writer.writerow((name, f"sha256={digest}", str(len(body))))
    writer.writerow((f"{dist_info}/RECORD", "", ""))
    files[f"{dist_info}/RECORD"] = record.getvalue().encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, body in sorted(files.items()):
            member = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            member.create_system = 3
            member.external_attr = (stat.S_IFREG | 0o644) << 16
            member.compress_type = zipfile.ZIP_STORED
            archive.writestr(member, body)
    return output.getvalue()


def _unsupported_resource_wheel(*, kind: Literal["method", "theme"]) -> bytes:
    plugin_id = f"{kind}pack"
    suffix = "json" if kind == "theme" else "md"
    locator = f"{kind}s/review.{suffix}"
    spec = ResourceItemSpec(
        contribution_id=f"review-{kind}",
        locator=locator,
        locator_kind="file",
        media_type="application/json" if kind == "theme" else "text/markdown",
        owner_namespace=f"resources.{kind}",
        resource_kind=kind,
        schema_id=f"loushang.resource.{kind}",
        schema_version=1,
    )
    generated = package(id=plugin_id, version="1", contributions=(spec,))
    files = {f"{plugin_id}/{item.path}": item.content for item in generated.artifacts}
    files[f"{plugin_id}/{locator}"] = (
        b"{}\n" if kind == "theme" else b"# Review method\n"
    )
    dist_info = f"{plugin_id}-1.dist-info"
    files[f"{dist_info}/METADATA"] = (
        f"Metadata-Version: 2.1\nName: {plugin_id}\nVersion: 1\n\n"
    ).encode()
    files[f"{dist_info}/WHEEL"] = (
        b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n"
    )
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name, body in sorted(files.items()):
        digest = urlsafe_b64encode(sha256(body).digest()).rstrip(b"=").decode("ascii")
        writer.writerow((name, f"sha256={digest}", str(len(body))))
    writer.writerow((f"{dist_info}/RECORD", "", ""))
    files[f"{dist_info}/RECORD"] = record.getvalue().encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, body in sorted(files.items()):
            member = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            member.create_system = 3
            member.external_attr = (stat.S_IFREG | 0o644) << 16
            member.compress_type = zipfile.ZIP_STORED
            archive.writestr(member, body)
    return output.getvalue()


def _p2_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    home: Path | None = None,
) -> tuple[Path, CodingPluginLifecycleStateLayout, SettingsManager]:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv(
        "LOUSHANG_HOME", str(tmp_path / "home" if home is None else home)
    )
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout,
        settings,
        workspace=workspace,
        namespace_id="9" * 64,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    return workspace, layout, settings


def _p2_cli(workspace: Path, *args: str) -> tuple[int, str, str]:
    stdout, stderr = StringIO(), StringIO()
    result = asyncio.run(
        run_cli(
            list(args),
            cwd=workspace,
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
        )
    )
    return result, stdout.getvalue(), stderr.getvalue()


def _p2_session(workspace: Path, settings: SettingsManager, path: Path):
    manager = asyncio.run(
        SessionManager.new(
            session_dir=path,
            cwd=str(workspace),
            persist=False,
        )
    )
    return create_agent_session(
        session_manager=manager,
        model=Model(
            id="multi-data-skill-model",
            name="Multi Data Skill Model",
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
    )


def _p2_wheel_source(
    tmp_path: Path,
    *,
    plugin_id: str,
    skill_name: str,
    version_id: str = "1",
    executable_member: bool = False,
) -> Path:
    source = tmp_path / f"{plugin_id}-{version_id}-py3-none-any.whl"
    if executable_member:
        source.write_bytes(
            _data_wheel(
                plugin_id=plugin_id,
                skill_name=skill_name,
                version=version_id,
                executable_member=True,
            )
        )
    else:
        skill_root = tmp_path / f"{plugin_id}-source" / "skills" / skill_name
        skill_root.mkdir(parents=True, exist_ok=True)
        skill_file = skill_root / "SKILL.md"
        skill_file.write_text(
            f"---\nname: {skill_name}\ndescription: {skill_name} files v{version_id}\n---\n"
            f"# {skill_name.title()} v{version_id}\n",
            encoding="utf-8",
        )
        assert (
            plugin_cli_main(
                [
                    "build-coding-skill",
                    str(skill_file),
                    "--plugin-id",
                    plugin_id,
                    "--version",
                    version_id,
                    "--output-dir",
                    str(tmp_path),
                ]
            )
            == 0
        )
    return source


def _p2_preflight(session, skill_name: str):  # type: ignore[no-untyped-def]
    async def inspect():  # type: ignore[no-untyped-def]
        await session.prepare_model_call_runtime()
        return await session._preflight_user_input_async(f"/skill:{skill_name}")

    return asyncio.run(inspect())


def _p2_list_plugins(workspace: Path) -> dict[str, dict[str, object]]:
    code, stdout, stderr = _p2_cli(
        workspace, "--list-plugins", "--list-plugins-format", "json"
    )
    assert code == 0, stderr
    return {str(item["name"]): item for item in json.loads(stdout)}


def _p2_installation(
    layout: CodingPluginLifecycleStateLayout, workspace: Path, plugin_id: str
):
    owner = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    try:
        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=layout.scope_id,
            plugin_id=plugin_id,
        )
        return owner.runtime_owner.product_owner.desired_state.snapshot().installation(
            key
        )
    finally:
        owner.close()


def test_external_catalog_read_records_never_creates_or_repairs(tmp_path: Path) -> None:
    catalog = CodingExternalDataWheelCatalog(
        tmp_path / "bindings.jsonl",
        source_root=tmp_path / "sources",
        store_id="coding-store",
        namespace_id="d" * 64,
        scope_id="workspace:read-only",
        read_only=True,
    )
    lock = catalog.path.with_name(f"{catalog.path.name}.lock")
    assert catalog.read_records() == ()
    assert not catalog.path.exists()
    assert not lock.exists()

    catalog.path.write_bytes(b'{"partial":')
    with journal_file_lock(catalog.path, "exclusive"):
        pass
    original = catalog.path.read_bytes()
    with pytest.raises(CodingExternalDataWheelError, match="corrupt"):
        catalog.read_records()
    assert catalog.path.read_bytes() == original


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_external_data_wheel_capture_reopens_exact_product_binding(
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
    source = tmp_path / "reviewpack-1-py3-none-any.whl"
    body = b"wheel bytes are still untrusted at Source authorization"
    source.write_bytes(body)

    record = admit_coding_external_data_wheel(lifecycle, source=source)
    assert admit_coding_external_data_wheel(lifecycle, source=source) == record
    assert record.original_source == str(source)
    assert record.artifact_digest == sha256(body).hexdigest()

    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        [binding] = [
            item
            for item in owner.runtime_owner.product_owner.policy.bindings
            if item.plugin_id == "reviewpack"
        ]
        assert binding.source_identity != str(source)
        assert Path(binding.source_identity).read_bytes() == body
        assert binding.artifact_digest == record.artifact_digest
        assert binding.plugin_manifest_path == "reviewpack/plugin.json"
        assert binding.source_trust_class == "local-data-only"
        product = owner.runtime_owner.product_owner
        before_preview = tuple(
            sorted(
                (str(path.relative_to(tmp_path)), path.read_bytes())
                for path in tmp_path.rglob("*")
                if path.is_file()
            )
        )
        with CodingFencedProductReadOnlyPreviewOwner.open(lifecycle) as preview:
            assert preview.policy == product.policy
            selected_base = (
                preview.selected_manifests.capture_selected_manifest_for_plugin(
                    "coding.base", max_files=64, max_total_bytes=1024 * 1024
                )
            )
            assert selected_base.verified_manifest().name == "coding.base"
        assert before_preview == tuple(
            sorted(
                (str(path.relative_to(tmp_path)), path.read_bytes())
                for path in tmp_path.rglob("*")
                if path.is_file()
            )
        )
        factory = product.factory_for_session(
            session_id="external-malformed",
            cwd=workspace,
            runtime_id="external-malformed",
        )
        runtime = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id="external-malformed", cwd=str(workspace)
            )
        )
        try:
            runtime.activate()
            outcome = runtime.lifecycle.route(
                PackageProductLifecycleIntentV1(
                    operation_id="external-malformed-install",
                    action="install",
                    source=binding.source_identity,
                    scope="project",
                ),
                entrypoint="cli",
            )
            assert outcome.handled
            assert outcome.record is not None
            assert outcome.record.lifecycle == "failed"
        finally:
            runtime.dispose_runtime()
        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=lifecycle.scope_id,
            plugin_id="reviewpack",
        )
        assert (
            product.desired_state.snapshot().installation(key).selection.desired_state
            == "absent"
        )
    finally:
        owner.close()

    source.write_bytes(b"changed after Product capture")
    reopened = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        [binding] = [
            item
            for item in reopened.runtime_owner.product_owner.policy.bindings
            if item.plugin_id == "reviewpack"
        ]
        assert Path(binding.source_identity).read_bytes() == body
    finally:
        reopened.close()
    Path(binding.source_identity).unlink()
    projection = build_coding_fenced_product_management_cli_ports(
        lifecycle
    ).queries.snapshot(
        PluginManagementQueryV1(
            correlation_id="test:missing-source",
            product_id="coding",
            installation_scope="workspace",
            scope_id=lifecycle.scope_id,
            plugin_ids=("reviewpack",),
        )
    )
    [installation] = projection.installations
    assert installation.source is not None
    assert installation.source.availability == "unavailable"


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product runtime")
@pytest.mark.parametrize(
    "abandoned_phase",
    [
        None,
        "classified",
        "acquiring",
        "acquired",
        "inspecting",
        "extracted",
        "resolving_closure",
        "resolving_dependency",
        "closure_verified",
        "transaction_pinned",
        "transaction_pinned_execute",
        "transaction_pinned_handoff_crash",
        "transaction_pinned_selected_crash",
        "transaction_pinned_stage_crash",
        "transaction_pinned_stage_cli_crash",
        "transaction_pinned_stage_rpc_crash",
        "transaction_pinned_stage_ui_crash",
        "transaction_pinned_stage_handoff_crash",
        "transaction_pinned_stage_partial_crash",
        "transaction_pinned_published_crash",
        "transaction_pinned_published_selection_crash",
        "transaction_pinned_published_cli_crash",
        "transaction_pinned_published_rpc_crash",
        "transaction_pinned_published_ui_crash",
        "cli_retryable",
        "sdk_retryable",
        "rpc_retryable",
        "ui_retryable",
        "cli_unstarted",
        "cli_acquired",
        "cli_resolving",
        "cli_verified",
        "cli_pinned",
        "rpc_unstarted",
        "rpc_acquired",
        "rpc_resolving",
        "rpc_verified",
        "rpc_pinned",
        "ui_unstarted",
        "ui_acquired",
        "ui_resolving",
        "ui_verified",
        "ui_pinned",
    ],
)
def test_reopened_coding_product_selected_cross_runtime_rebind_and_preflight(
    tmp_path: Path,
    abandoned_phase: str | None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scenario = abandoned_phase
    cli_claimed_phase = {
        "cli_unstarted": "classified",
        "cli_acquired": "acquired",
        "cli_resolving": "resolving_closure",
        "cli_verified": "closure_verified",
        "cli_pinned": "transaction_pinned",
    }
    transport_claimed_phase = {
        f"{transport}_{name}": phase
        for transport in ("rpc", "ui")
        for name, phase in (
            ("unstarted", "classified"),
            ("acquired", "acquired"),
            ("resolving", "resolving_closure"),
            ("verified", "closure_verified"),
            ("pinned", "transaction_pinned"),
        )
    }
    abandoned_phase = {**cli_claimed_phase, **transport_claimed_phase}.get(
        scenario, abandoned_phase
    )
    execute_pinned = abandoned_phase in {
        "transaction_pinned_execute",
        "transaction_pinned_handoff_crash",
        "transaction_pinned_selected_crash",
        "transaction_pinned_stage_crash",
        "transaction_pinned_stage_cli_crash",
        "transaction_pinned_stage_rpc_crash",
        "transaction_pinned_stage_ui_crash",
        "transaction_pinned_stage_handoff_crash",
        "transaction_pinned_stage_partial_crash",
        "transaction_pinned_published_crash",
        "transaction_pinned_published_selection_crash",
        "transaction_pinned_published_cli_crash",
        "transaction_pinned_published_rpc_crash",
        "transaction_pinned_published_ui_crash",
    }
    crash_handoff = abandoned_phase == "transaction_pinned_handoff_crash"
    crash_before_execution = abandoned_phase == "transaction_pinned_selected_crash"
    crash_after_stage_receipt = abandoned_phase in {
        "transaction_pinned_stage_crash",
        "transaction_pinned_stage_cli_crash",
        "transaction_pinned_stage_rpc_crash",
        "transaction_pinned_stage_ui_crash",
        "transaction_pinned_stage_handoff_crash",
    }
    crash_before_stage_effect = (
        abandoned_phase == "transaction_pinned_stage_partial_crash"
    )
    crash_during_stage = crash_after_stage_receipt or crash_before_stage_effect
    crash_after_stage_commit = (
        abandoned_phase == "transaction_pinned_stage_handoff_crash"
    )
    crash_after_published_set = abandoned_phase in {
        "transaction_pinned_published_crash",
        "transaction_pinned_published_selection_crash",
        "transaction_pinned_published_cli_crash",
        "transaction_pinned_published_rpc_crash",
        "transaction_pinned_published_ui_crash",
    }
    if execute_pinned:
        abandoned_phase = "transaction_pinned"
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    if scenario in {
        "cli_retryable",
        "sdk_retryable",
        "rpc_retryable",
        "ui_retryable",
        "transaction_pinned_stage_cli_crash",
        "transaction_pinned_stage_rpc_crash",
        "transaction_pinned_stage_ui_crash",
        "transaction_pinned_published_cli_crash",
        "transaction_pinned_published_rpc_crash",
        "transaction_pinned_published_ui_crash",
        *cli_claimed_phase,
        *transport_claimed_phase,
    }:
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
        layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    else:
        layout = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
            tmp_path / "session-state", cwd=workspace
        )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout,
        settings,
        workspace=workspace,
        namespace_id="a" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    source = tmp_path / "retryable-1-py3-none-any.whl"
    with_dependency = abandoned_phase == "resolving_dependency"
    source.write_bytes(
        _data_wheel(
            plugin_id="retryable",
            skill_name="retry",
            requires_dist=with_dependency,
        )
    )
    admit_coding_external_data_wheel(layout, source=source)
    operation_id = "operation:real-cross-runtime-rebind"

    def selected_product(product):
        if not with_dependency:
            return product
        dependency_source = product.policy.source_root / "requests-2.0-py3-none-any.whl"
        payload = _library_wheel(project="requests", version="2.0")
        if dependency_source.exists():
            assert dependency_source.read_bytes() == payload
        else:
            dependency_source.write_bytes(payload)
        dependency = PackageProductLocalWheelDependencyV1(
            source_identity=str(dependency_source),
            project_name="requests",
            version="2.0",
            artifact_digest=sha256(payload).hexdigest(),
        )
        return replace(
            product,
            policy=replace(
                product.policy,
                dependencies=tuple(
                    sorted(
                        (*product.policy.dependencies, dependency),
                        key=lambda item: item.project_name,
                    )
                ),
            ),
        )

    first_owner = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    first_runtime = None
    try:
        product = selected_product(first_owner.runtime_owner.product_owner)
        binding = next(
            item for item in product.policy.bindings if item.plugin_id == "retryable"
        )
        first_runtime = product.factory_for_session(
            session_id="rebind-first", cwd=workspace, runtime_id="rebind-first"
        ).create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id="rebind-first", cwd=str(workspace)
            )
        )
        first_runtime.activate()
        receipt = first_runtime.lifecycle.activate()
        intent = PackageProductLifecycleIntentV1(
            operation_id=operation_id,
            action="install",
            source=binding.source_identity,
            scope="project",
        )
        ingress = PackageLifecycleIngressRequestV2.bind_runtime_admission(
            product.policy.create(intent),
            runtime_admission_request_id=receipt.request.admission_request_id,
        )
        journal = PackageLifecycleJournal(product.state_root / "lifecycle.jsonl")
        kernel = PackageLifecycleOwner(
            journal=journal, classification_authority=product.policy, enabled=True
        )
        classified = kernel.submit(ingress)
        original = journal.read_operation(operation_id)
        assert original is not None
        assert isinstance(original[0], PackageLifecycleRequestV2)
        PackageProductAdmissionBindingJournal(
            product.state_root / "admission-bindings.jsonl"
        ).bind(original[0], classified, receipt)
        failed = kernel.interrupt(
            operation_id,
            expected_phase=classified.phase,
            expected_journal_revision=classified.journal_revision,
            expected_attempt_epoch=classified.attempt_epoch,
        )
        assert failed.disposition == "retryable_failure"
    finally:
        if first_runtime is not None:
            first_runtime.dispose_runtime()
        first_owner.close()

    if abandoned_phase == "cli_retryable":
        from loushang.coding.cli import package_repair

        monkeypatch.setattr(package_repair, "version", lambda _name: "2.0.0")
        pinned_source = Path(binding.source_identity)
        pinned_bytes = pinned_source.read_bytes()
        lifecycle_path = product.state_root / "lifecycle.jsonl"
        before_refusal = lifecycle_path.read_bytes()
        open_owner = package_repair.open_coding_fenced_product_application_owner

        def open_then_change_source(*args, **kwargs):
            owner = open_owner(*args, **kwargs)
            pinned_source.write_bytes(b"changed after Product open")
            return owner

        monkeypatch.setattr(
            package_repair,
            "open_coding_fenced_product_application_owner",
            open_then_change_source,
        )
        try:
            assert (
                package_repair.main(
                    ["--workspace", str(workspace), "repair-retryable", operation_id]
                )
                == 1
            )
            assert "package_source_digest_mismatch" in capsys.readouterr().err
            assert lifecycle_path.read_bytes() == before_refusal
            assert not (product.state_root / "rebind-admissions.jsonl").exists()
        finally:
            monkeypatch.setattr(
                package_repair,
                "open_coding_fenced_product_application_owner",
                open_owner,
            )
            pinned_source.write_bytes(pinned_bytes)
        execute_rebind = PackageProductRuntimeBindingV1.execute_rebind_decision

        def crash_after_rebind_selection(
            self: PackageProductRuntimeBindingV1,
            selected_operation_id: str,
            *,
            max_bytes: int,
        ) -> object:
            assert selected_operation_id == operation_id
            assert max_bytes == 2 * 1024 * 1024
            raise RuntimeError("crash after CLI rebind selection")

        monkeypatch.setattr(
            PackageProductRuntimeBindingV1,
            "execute_rebind_decision",
            crash_after_rebind_selection,
        )
        try:
            assert (
                package_repair.main(
                    ["--workspace", str(workspace), "repair-retryable", operation_id]
                )
                == 1
            )
            assert "package_repair_unavailable" in capsys.readouterr().err
        finally:
            monkeypatch.setattr(
                PackageProductRuntimeBindingV1,
                "execute_rebind_decision",
                execute_rebind,
            )
        assert lifecycle_path.read_bytes() != before_refusal
        assert (product.state_root / "rebind-admissions.jsonl").exists()
        assert (
            package_repair.main(
                ["--workspace", str(workspace), "repair-retryable", operation_id]
            )
            == 0
        )
        repaired = json.loads(capsys.readouterr().out)
        assert repaired["disposition"] == "committed"
        assert repaired["phase"] == "committed"
        assert PackageLifecycleJournal(lifecycle_path).status(
            operation_id
        ).disposition == ("committed")
        installation = product.desired_state.snapshot().installation(
            PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=layout.scope_id,
                plugin_id="retryable",
            )
        )
        assert installation.selection.desired_state == "installed_disabled"
        return

    if scenario == "sdk_retryable":
        from loushang.coding.package_product_repair import (
            open_coding_package_repair_client,
        )

        client = open_coding_package_repair_client(workspace, runtime_version="2.0.0")
        lifecycle_path = product.state_root / "lifecycle.jsonl"
        before_refusal = lifecycle_path.read_bytes()
        with pytest.raises(RuntimeError):
            asyncio.run(client.aperform("repair-pinned", operation_id))
        assert lifecycle_path.read_bytes() == before_refusal
        repaired = client.perform("repair-retryable", operation_id)
        assert repaired.committed
        assert repaired.to_dict()["disposition"] == "committed"
        assert PackageLifecycleJournal(lifecycle_path).status(
            operation_id
        ).disposition == ("committed")
        installation = product.desired_state.snapshot().installation(
            PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=layout.scope_id,
                plugin_id="retryable",
            )
        )
        assert installation.selection.desired_state == "installed_disabled"
        return

    if scenario == "rpc_retryable":
        from loushang.coding.package_product_repair import (
            open_coding_package_repair_client,
        )
        from loushang.coding.package_product_repair_rpc import (
            CodingPackageRepairRpcClientV1,
        )

        lifecycle_path = product.state_root / "lifecycle.jsonl"
        before_refusal = lifecycle_path.read_bytes()
        session = _p2_session(workspace, settings, tmp_path / "rpc-sessions")

        class CurrentSessionRuntime:
            def get_current_session(self):  # type: ignore[no-untyped-def]
                return session

        stdout = StringIO()
        host = RpcHost(
            runtime=CurrentSessionRuntime(),
            stdin=StringIO(),
            stdout=stdout,
            package_repair_factory=lambda cwd: CodingPackageRepairRpcClientV1(
                local=open_coding_package_repair_client(cwd, runtime_version="2.0.0")
            ),
        )
        payload = {
            "productId": "coding",
            "scopeId": layout.scope_id,
            "action": "repair-retryable",
            "operationId": operation_id,
        }
        try:
            assert (
                asyncio.run(
                    host.submit_input(
                        json.dumps(
                            {
                                "id": "rpc:wrong-scope",
                                "type": "repair_plugin_package_v1",
                                **payload,
                                "scopeId": "workspace:other",
                            }
                        )
                    )
                )
                == 0
            )
            assert lifecycle_path.read_bytes() == before_refusal
            assert (
                asyncio.run(
                    host.submit_input(
                        json.dumps(
                            {
                                "id": "rpc:repair",
                                "type": "repair_plugin_package_v1",
                                **payload,
                            }
                        )
                    )
                )
                == 0
            )
        finally:
            asyncio.run(host.stop())
            asyncio.run(session.dispose())
        responses = {
            item["id"]: item
            for item in (json.loads(line) for line in stdout.getvalue().splitlines())
        }
        assert responses["rpc:wrong-scope"]["errorCode"] == (
            "package_repair_scope_mismatch"
        )
        assert responses["rpc:repair"]["data"]["disposition"] == "committed"
        assert PackageLifecycleJournal(lifecycle_path).status(
            operation_id
        ).disposition == ("committed")
        installation = product.desired_state.snapshot().installation(
            PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=layout.scope_id,
                plugin_id="retryable",
            )
        )
        assert installation.selection.desired_state == "installed_disabled"
        return

    if scenario == "ui_retryable":
        from loushang.coding.ui.product_binding import build_coding_ui_controller
        from loushang.harnesstui.conversation.intents import PromptIntent

        monkeypatch.setattr(
            "loushang.coding.package_product_repair.version",
            lambda _name: "2.0.0",
        )
        lifecycle_path = product.state_root / "lifecycle.jsonl"
        before_refusal = lifecycle_path.read_bytes()
        session = _p2_session(workspace, settings, tmp_path / "ui-sessions")
        controller = build_coding_ui_controller(
            session=session, plugin_workspace=workspace
        )
        try:
            wrong = asyncio.run(
                controller.dispatch(
                    PromptIntent(
                        text=f"/plugins repair-package repair-pinned {operation_id}"
                    )
                )
            )
            assert wrong.error_message is not None
            assert lifecycle_path.read_bytes() == before_refusal
            repaired = asyncio.run(
                controller.dispatch(
                    PromptIntent(
                        text=f"/plugins repair-package repair-retryable {operation_id}"
                    )
                )
            )
            assert repaired.error_message is None
            assert "Package repair committed" in (repaired.status_message or "")
        finally:
            asyncio.run(session.dispose())
        assert PackageLifecycleJournal(lifecycle_path).status(
            operation_id
        ).disposition == ("committed")
        installation = product.desired_state.snapshot().installation(
            PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=layout.scope_id,
                plugin_id="retryable",
            )
        )
        assert installation.selection.desired_state == "installed_disabled"
        return

    second_owner = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    second_runtime = None
    try:
        product = selected_product(second_owner.runtime_owner.product_owner)
        second_runtime = product.factory_for_session(
            session_id="rebind-second", cwd=workspace, runtime_id="rebind-second"
        ).create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id="rebind-second", cwd=str(workspace)
            )
        )
        second_runtime.activate()
        new_receipt = second_runtime.lifecycle.activate()
        preflight = asyncio.run(
            second_runtime.inspect_rebind_preflight(
                operation_id, max_bytes=2 * 1024 * 1024
            )
        )
        assert len(preflight.cleanup.committed_attempts) == 3
        original_attempt = (
            product.state_root
            / "quarantine"
            / preflight.cleanup.committed_attempts[0].attempt_name
        )
        saved_attempt = tmp_path / "saved-committed-attempt"
        original_attempt.rename(saved_attempt)
        original_attempt.mkdir(mode=0o700)
        try:
            with pytest.raises(PackageProductRebindCleanupReadError) as replaced:
                asyncio.run(
                    second_runtime.inspect_rebind_preflight(
                        operation_id, max_bytes=2 * 1024 * 1024
                    )
                )
            assert replaced.value.code == "package_rebind_quarantine_not_empty"
            assert not (product.state_root / "rebind-admissions.jsonl").exists()
        finally:
            original_attempt.rmdir()
            saved_attempt.rename(original_attempt)
        second_runtime.lifecycle.activate()
        decision = second_runtime.prepare_rebind_decision(
            operation_id, max_bytes=2 * 1024 * 1024
        )
        assert decision.decision.new_runtime_admission_request_id == (
            new_receipt.request.admission_request_id
        )
        assert decision.status.disposition == "retryable_failure"
        assert decision.decision.expected_attempt_epoch == failed.attempt_epoch
        assert (
            second_runtime.prepare_rebind_decision(
                operation_id, max_bytes=2 * 1024 * 1024
            )
            == decision
        )
        assert (
            PackageLifecycleJournal(
                product.state_root / "lifecycle.jsonl"
            ).latest_rebind(operation_id)
            == decision
        )
        pinned_source = Path(binding.source_identity)
        pinned_bytes = pinned_source.read_bytes()
        pinned_source.write_bytes(b"changed after the selected decision")
        before_refusal = PackageLifecycleJournal(
            product.state_root / "lifecycle.jsonl"
        ).status(operation_id)
        try:
            with pytest.raises(PackageProductRebindSourceError) as changed_source:
                second_runtime.execute_rebind_decision(
                    operation_id, max_bytes=2 * 1024 * 1024
                )
            assert changed_source.value.code == "package_source_digest_mismatch"
            assert (
                PackageLifecycleJournal(product.state_root / "lifecycle.jsonl").status(
                    operation_id
                )
                == before_refusal
            )
        finally:
            pinned_source.write_bytes(pinned_bytes)
        second_runtime.lifecycle.activate()
        if abandoned_phase is not None:
            decision_owner = second_runtime._rebind_decision_owner
            assert decision_owner is not None
            _selected, claimed, _route = (
                second_runtime.lifecycle.execute_guarded_mutation(
                    lambda receipt: decision_owner.resume(
                        operation_id, max_bytes=2 * 1024 * 1024, admission=receipt
                    )
                )
            )
            assert claimed.disposition == "active"
            assert claimed.phase == "classified"
            if abandoned_phase in {
                "acquiring",
                "acquired",
                "inspecting",
                "extracted",
                "resolving_closure",
                "resolving_dependency",
                "closure_verified",
                "transaction_pinned",
            }:
                claimed = PackageLifecycleOwner(
                    journal=PackageLifecycleJournal(
                        product.state_root / "lifecycle.jsonl"
                    ),
                    classification_authority=product.policy,
                    enabled=True,
                ).advance(
                    operation_id,
                    next_phase="acquiring",
                    expected_phase=claimed.phase,
                    expected_journal_revision=claimed.journal_revision,
                    expected_attempt_epoch=claimed.attempt_epoch,
                )
                assert claimed.phase == "acquiring"
            if abandoned_phase in {
                "acquired",
                "inspecting",
                "extracted",
                "resolving_closure",
                "resolving_dependency",
                "closure_verified",
                "transaction_pinned",
            }:
                quarantine = PackageQuarantineStore(product.state_root / "quarantine")
                source_identity = ingress.source_locator
                candidate = PackageAcquisitionOwner(
                    source_authority=product.policy.source_authority(),
                    quarantine_store=quarantine,
                ).acquire(
                    PackageAcquisitionRequestV1(
                        operation_id=operation_id,
                        attempt_epoch=claimed.attempt_epoch,
                        node_id="root",
                        canonical_source_identity=source_identity,
                        request_fingerprint=claimed.request_fingerprint,
                        requested_locator_digest=sha256(
                            source_identity.encode("utf-8")
                        ).hexdigest(),
                        policy_revision=ingress.policy_revision,
                    ),
                    budgets=PackageAcquisitionBudgetV1(
                        max_transport_bytes=2 * 1024 * 1024,
                        max_requests=1,
                        max_redirects=0,
                        max_wall_time_ms=5000,
                    ),
                )
                evidence = PackageArtifactEvidenceJournal(
                    product.state_root / "artifact-evidence.jsonl"
                )
                evidence.append(
                    request_fingerprint=claimed.request_fingerprint,
                    evidence=PackageAuthenticatedSourceEvidenceV1(
                        attempt_epoch=claimed.attempt_epoch,
                        envelope=candidate.authenticated_envelope,
                    ),
                )
                evidence.append(
                    request_fingerprint=claimed.request_fingerprint,
                    evidence=candidate.receipt,
                )
                if abandoned_phase not in {
                    "extracted",
                    "resolving_closure",
                    "resolving_dependency",
                    "closure_verified",
                    "transaction_pinned",
                }:
                    candidate.suspend_for_recovery()
                claimed = PackageLifecycleOwner(
                    journal=PackageLifecycleJournal(
                        product.state_root / "lifecycle.jsonl"
                    ),
                    classification_authority=product.policy,
                    enabled=True,
                ).advance(
                    operation_id,
                    next_phase="acquired",
                    expected_phase=claimed.phase,
                    expected_journal_revision=claimed.journal_revision,
                    expected_attempt_epoch=claimed.attempt_epoch,
                )
                assert claimed.phase == "acquired"
                if abandoned_phase in {
                    "inspecting",
                    "extracted",
                    "resolving_closure",
                    "resolving_dependency",
                    "closure_verified",
                    "transaction_pinned",
                }:
                    claimed = PackageLifecycleOwner(
                        journal=PackageLifecycleJournal(
                            product.state_root / "lifecycle.jsonl"
                        ),
                        classification_authority=product.policy,
                        enabled=True,
                    ).advance(
                        operation_id,
                        next_phase="inspecting",
                        expected_phase=claimed.phase,
                        expected_journal_revision=claimed.journal_revision,
                        expected_attempt_epoch=claimed.attempt_epoch,
                    )
                    assert claimed.phase == "inspecting"
                if abandoned_phase in {
                    "extracted",
                    "resolving_closure",
                    "resolving_dependency",
                    "closure_verified",
                    "transaction_pinned",
                }:
                    verified = PackageWheelVerifier().verify(
                        candidate,
                        wheel_filename=Path(source_identity).name,
                        supported_tags=frozenset({"py3-none-any"}),
                        budgets=PackageInspectionBudgetV1(),
                    )
                    evidence.append(
                        request_fingerprint=claimed.request_fingerprint,
                        evidence=verified.evidence,
                    )
                    verified.suspend_for_recovery()
                    claimed = PackageLifecycleOwner(
                        journal=PackageLifecycleJournal(
                            product.state_root / "lifecycle.jsonl"
                        ),
                        classification_authority=product.policy,
                        enabled=True,
                    ).advance(
                        operation_id,
                        next_phase="extracted",
                        expected_phase=claimed.phase,
                        expected_journal_revision=claimed.journal_revision,
                        expected_attempt_epoch=claimed.attempt_epoch,
                    )
                    assert claimed.phase == "extracted"
                if abandoned_phase in {
                    "resolving_closure",
                    "resolving_dependency",
                    "closure_verified",
                    "transaction_pinned",
                }:
                    resolution_journal = PackageClosureResolutionJournal(
                        product.state_root / "resolution.jsonl"
                    )
                    resolution_journal.bind_basis(
                        PackageClosureResolutionBasisV1(
                            operation_id=operation_id,
                            attempt_epoch=claimed.attempt_epoch,
                            request_fingerprint=claimed.request_fingerprint,
                            policy_revision=product.policy.policy_revision,
                            quota_profile_revision=product.policy.quota_profile_revision,
                            resolution_environment=product.environment,
                            budgets=product.closure_budgets,
                        )
                    )
                    claimed = PackageLifecycleOwner(
                        journal=PackageLifecycleJournal(
                            product.state_root / "lifecycle.jsonl"
                        ),
                        classification_authority=product.policy,
                        enabled=True,
                    ).advance(
                        operation_id,
                        next_phase="resolving_closure",
                        expected_phase=claimed.phase,
                        expected_journal_revision=claimed.journal_revision,
                        expected_attempt_epoch=claimed.attempt_epoch,
                    )
                    assert claimed.phase == "resolving_closure"
                    if with_dependency:
                        selection_request = PackageDependencySelectionRequestV1(
                            operation_id=operation_id,
                            attempt_epoch=claimed.attempt_epoch,
                            parent_node_id="root",
                            request_fingerprint=claimed.request_fingerprint,
                            resolution_environment_fingerprint=(
                                product.environment.fingerprint
                            ),
                            requirement=NormalizedPackageRequirementV1.parse(
                                "requests"
                            ),
                        )
                        selection = product.policy.resolve(selection_request)
                        resolution_journal.append_selection(
                            selection_request, selection
                        )
                        dependency_candidate = PackageAcquisitionOwner(
                            source_authority=product.policy.source_authority(),
                            quarantine_store=quarantine,
                        ).acquire(
                            PackageAcquisitionRequestV1(
                                operation_id=operation_id,
                                attempt_epoch=claimed.attempt_epoch,
                                node_id=selection.node_id,
                                canonical_source_identity=(
                                    selection.canonical_source_identity
                                ),
                                request_fingerprint=claimed.request_fingerprint,
                                requested_locator_digest=sha256(
                                    selection.canonical_source_identity.encode()
                                ).hexdigest(),
                                policy_revision=product.policy.policy_revision,
                            ),
                            budgets=PackageAcquisitionBudgetV1(
                                max_transport_bytes=2 * 1024 * 1024,
                                max_requests=1,
                                max_redirects=0,
                                max_wall_time_ms=5000,
                            ),
                        )
                        evidence.append(
                            request_fingerprint=claimed.request_fingerprint,
                            evidence=PackageAuthenticatedSourceEvidenceV1(
                                attempt_epoch=claimed.attempt_epoch,
                                envelope=dependency_candidate.authenticated_envelope,
                            ),
                        )
                        evidence.append(
                            request_fingerprint=claimed.request_fingerprint,
                            evidence=dependency_candidate.receipt,
                        )
                        dependency_candidate.suspend_for_recovery()
                    if abandoned_phase in {
                        "closure_verified",
                        "transaction_pinned",
                    }:
                        plan_node = VerifiedClosurePlanNodeV2(
                            node_id="root",
                            role="root",
                            distribution=verified.evidence.distribution,
                            version=verified.evidence.version,
                            canonical_source_identity=source_identity,
                            source_envelope_fingerprint=(
                                candidate.authenticated_envelope.fingerprint
                            ),
                            acquisition_receipt_fingerprint=candidate.receipt.fingerprint,
                            wheel_evidence_fingerprint=verified.evidence.fingerprint,
                            artifact_digest=verified.evidence.artifact_digest,
                            extraction_tree_digest=(
                                verified.evidence.extraction_tree_digest
                            ),
                            selected_extras=(),
                            requirements=(),
                            selected_edges=(),
                        )
                        plan = VerifiedClosurePlanV2.create(
                            operation_id=operation_id,
                            attempt_epoch=claimed.attempt_epoch,
                            root_node_id="root",
                            resolution_environment_fingerprint=(
                                product.environment.fingerprint
                            ),
                            nodes=(plan_node,),
                            max_depth=0,
                        )
                        resolution_journal.append_plan(
                            request_fingerprint=claimed.request_fingerprint, plan=plan
                        )
                        claimed = PackageLifecycleOwner(
                            journal=PackageLifecycleJournal(
                                product.state_root / "lifecycle.jsonl"
                            ),
                            classification_authority=product.policy,
                            enabled=True,
                        ).advance(
                            operation_id,
                            next_phase="closure_verified",
                            expected_phase=claimed.phase,
                            expected_journal_revision=claimed.journal_revision,
                            expected_attempt_epoch=claimed.attempt_epoch,
                        )
                        if abandoned_phase == "transaction_pinned":
                            assert claimed.classification is not None
                            pin_request = PackageTransactionPinRequestV1.create(
                                plan,
                                request_fingerprint=claimed.request_fingerprint,
                                classification_fingerprint=(
                                    claimed.classification.evidence_ref
                                ),
                                recovery_identity=product.recovery_identity,
                            )
                            PackageTransactionPinJournal(
                                product.state_root / "transaction-pins.jsonl"
                            ).append(
                                PackageTransactionPinReceiptV1.acquire(
                                    pin_request,
                                    pin_id="a" * 64,
                                    owner_identity="package-transaction-retention",
                                    owner_revision=1,
                                    lease_id=f"lease:{pin_request.pin_request_id}",
                                    lease_revision=1,
                                )
                            )
                            claimed = PackageLifecycleOwner(
                                journal=PackageLifecycleJournal(
                                    product.state_root / "lifecycle.jsonl"
                                ),
                                classification_authority=product.policy,
                                enabled=True,
                            ).advance(
                                operation_id,
                                next_phase="transaction_pinned",
                                expected_phase=claimed.phase,
                                expected_journal_revision=claimed.journal_revision,
                                expected_attempt_epoch=claimed.attempt_epoch,
                            )
        else:
            committed = second_runtime.execute_rebind_decision(
                operation_id, max_bytes=2 * 1024 * 1024
            )
            assert committed.disposition == "committed", committed.failure
            assert committed.attempt_epoch == failed.attempt_epoch + 1
            installation = product.desired_state.snapshot().installation(
                PluginInstallationKeyV1(
                    product_id="coding",
                    installation_scope="workspace",
                    scope_id=layout.scope_id,
                    plugin_id="retryable",
                )
            )
            assert installation.selection.desired_state == "installed_disabled"
    finally:
        if second_runtime is not None:
            second_runtime.dispose_runtime()
        second_owner.close()
    if scenario in cli_claimed_phase:
        from loushang.coding.cli import package_repair

        monkeypatch.setattr(package_repair, "version", lambda _name: "2.0.0")
        action = scenario.replace("cli_", "repair-", 1)
        lifecycle_path = product.state_root / "lifecycle.jsonl"
        source_path = Path(binding.source_identity)
        source_bytes = source_path.read_bytes()
        before_refusal = lifecycle_path.read_bytes()
        wrong_action = (
            "repair-acquired" if scenario == "cli_unstarted" else "repair-unstarted"
        )
        assert (
            package_repair.main(
                ["--workspace", str(workspace), wrong_action, operation_id]
            )
            == 1
        )
        assert "refused" in capsys.readouterr().err
        assert lifecycle_path.read_bytes() == before_refusal
        open_owner = package_repair.open_coding_fenced_product_application_owner

        def open_then_change_source(*args, **kwargs):
            owner = open_owner(*args, **kwargs)
            source_path.write_bytes(b"changed after Product open")
            return owner

        monkeypatch.setattr(
            package_repair,
            "open_coding_fenced_product_application_owner",
            open_then_change_source,
        )
        try:
            assert (
                package_repair.main(
                    ["--workspace", str(workspace), action, operation_id]
                )
                == 1
            )
            assert "package_source_digest_mismatch" in capsys.readouterr().err
            assert lifecycle_path.read_bytes() == before_refusal
        finally:
            monkeypatch.setattr(
                package_repair,
                "open_coding_fenced_product_application_owner",
                open_owner,
            )
            source_path.write_bytes(source_bytes)
        assert (
            package_repair.main(["--workspace", str(workspace), action, operation_id])
            == 0
        )
        repaired = json.loads(capsys.readouterr().out)
        assert repaired["disposition"] == "committed"
        assert repaired["phase"] == "committed"
        assert PackageLifecycleJournal(lifecycle_path).status(
            operation_id
        ).disposition == ("committed")
        installation = product.desired_state.snapshot().installation(
            PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=layout.scope_id,
                plugin_id="retryable",
            )
        )
        assert installation.selection.desired_state == "installed_disabled"
        return
    if scenario in transport_claimed_phase:
        action = "repair-" + scenario.split("_", 1)[1]
        wrong_action = (
            "repair-acquired" if scenario.endswith("_unstarted") else "repair-unstarted"
        )
        lifecycle_path = product.state_root / "lifecycle.jsonl"
        before_refusal = lifecycle_path.read_bytes()
        session = _p2_session(
            workspace, settings, tmp_path / f"{scenario}-repair-session"
        )
        try:
            if scenario.startswith("rpc_"):
                from loushang.coding.package_product_repair import (
                    open_coding_package_repair_client,
                )
                from loushang.coding.package_product_repair_rpc import (
                    CodingPackageRepairRpcClientV1,
                )

                class CurrentSessionRuntime:
                    def get_current_session(self):  # type: ignore[no-untyped-def]
                        return session

                stdout = StringIO()
                host = RpcHost(
                    runtime=CurrentSessionRuntime(),
                    stdin=StringIO(),
                    stdout=stdout,
                    package_repair_factory=lambda cwd: CodingPackageRepairRpcClientV1(
                        local=open_coding_package_repair_client(
                            cwd, runtime_version="2.0.0"
                        )
                    ),
                )
                payload = {
                    "productId": "coding",
                    "scopeId": layout.scope_id,
                    "operationId": operation_id,
                }
                try:
                    for request_id, selected_action in (
                        ("rpc:wrong", wrong_action),
                        ("rpc:repair", action),
                    ):
                        assert (
                            asyncio.run(
                                host.submit_input(
                                    json.dumps(
                                        {
                                            "id": request_id,
                                            "type": "repair_plugin_package_v1",
                                            "action": selected_action,
                                            **payload,
                                        }
                                    )
                                )
                            )
                            == 0
                        )
                        if request_id == "rpc:wrong":
                            assert lifecycle_path.read_bytes() == before_refusal
                finally:
                    asyncio.run(host.stop())
                responses = {
                    item["id"]: item
                    for item in (
                        json.loads(line) for line in stdout.getvalue().splitlines()
                    )
                }
                assert responses["rpc:wrong"]["errorCode"]
                assert responses["rpc:repair"]["data"]["disposition"] == "committed"
            else:
                from loushang.coding.ui.product_binding import (
                    build_coding_ui_controller,
                )
                from loushang.harnesstui.conversation.intents import PromptIntent

                monkeypatch.setattr(
                    "loushang.coding.package_product_repair.version",
                    lambda _name: "2.0.0",
                )
                controller = build_coding_ui_controller(
                    session=session, plugin_workspace=workspace
                )
                wrong = asyncio.run(
                    controller.dispatch(
                        PromptIntent(
                            text=f"/plugins repair-package {wrong_action} {operation_id}"
                        )
                    )
                )
                assert wrong.error_message is not None
                assert lifecycle_path.read_bytes() == before_refusal
                repaired = asyncio.run(
                    controller.dispatch(
                        PromptIntent(
                            text=f"/plugins repair-package {action} {operation_id}"
                        )
                    )
                )
                assert repaired.error_message is None
                assert "Package repair committed" in (repaired.status_message or "")
        finally:
            asyncio.run(session.dispose())
        assert PackageLifecycleJournal(lifecycle_path).status(
            operation_id
        ).disposition == ("committed")
        installation = product.desired_state.snapshot().installation(
            PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=layout.scope_id,
                plugin_id="retryable",
            )
        )
        assert installation.selection.desired_state == "installed_disabled"
        return
    if abandoned_phase is not None:
        third_owner = open_coding_fenced_product_application_owner(
            layout,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )
        third_runtime = None
        try:
            product = selected_product(third_owner.runtime_owner.product_owner)
            third_runtime = product.factory_for_session(
                session_id="rebind-third", cwd=workspace, runtime_id="rebind-third"
            ).create(
                PackageProductRuntimeRequestV1(
                    product_id="coding", session_id="rebind-third", cwd=str(workspace)
                )
            )
            third_runtime.activate()
            if abandoned_phase == "transaction_pinned":
                pinned_read = asyncio.run(
                    third_runtime.inspect_pinned_rebind_claim(
                        operation_id, max_bytes=2 * 1024 * 1024
                    )
                )
                assert pinned_read.cleanup.closure.status.phase == "transaction_pinned"
                assert pinned_read.cleanup.pin.state == "acquired"
                assert tuple(
                    node.attempt.node_id for node in pinned_read.cleanup.closure.nodes
                ) == ("root",)
                source_path = Path(ingress.source_locator)
                source_bytes = source_path.read_bytes()
                lifecycle_path = product.state_root / "lifecycle.jsonl"
                pin_path = product.state_root / "transaction-pins.jsonl"
                before = (lifecycle_path.read_bytes(), pin_path.read_bytes())
                source_path.write_bytes(b"changed pinned Source")
                try:
                    with pytest.raises(PackageProductRebindSourceError) as drift:
                        asyncio.run(
                            third_runtime.inspect_pinned_rebind_claim(
                                operation_id, max_bytes=2 * 1024 * 1024
                            )
                        )
                    assert drift.value.code == "package_source_digest_mismatch"
                    assert (
                        lifecycle_path.read_bytes(),
                        pin_path.read_bytes(),
                    ) == before
                finally:
                    source_path.write_bytes(source_bytes)
                third_runtime.lifecycle.activate()
                adopted = third_runtime.prepare_pinned_adoption(
                    operation_id, max_bytes=2 * 1024 * 1024
                )
                assert adopted.status.phase == "transaction_pinned"
                assert adopted.status.attempt_epoch == (
                    pinned_read.cleanup.closure.status.attempt_epoch
                )
                assert adopted.decision.pin_receipt_id == (
                    pinned_read.cleanup.pin.receipt_id
                )
                before_replay = lifecycle_path.read_bytes()
                assert (
                    third_runtime.prepare_pinned_adoption(
                        operation_id, max_bytes=2 * 1024 * 1024
                    )
                    == adopted
                )
                assert lifecycle_path.read_bytes() == before_replay
                if execute_pinned:
                    if crash_during_stage:
                        original_append = PackageArtifactStagingJournal.append
                        crashed = False

                        def fail_after_append(
                            self: PackageArtifactStagingJournal,
                            receipt: PackageArtifactStagingReceiptV1,
                        ) -> PackageArtifactStagingReceiptV1:
                            nonlocal crashed
                            persisted = original_append(self, receipt)
                            if not crashed:
                                crashed = True
                                raise RuntimeError("crash after staging receipt")
                            return persisted

                        if crash_before_stage_effect:
                            original_stage_root = (
                                PosixPackagePluginRootMaterializationStore.stage_root
                            )

                            def fail_before_stage_root(
                                self: PosixPackagePluginRootMaterializationStore,
                                request: object,
                                candidate: object,
                            ) -> None:
                                raise RuntimeError("crash before staging root")

                            monkeypatch.setattr(
                                PosixPackagePluginRootMaterializationStore,
                                "stage_root",
                                fail_before_stage_root,
                            )
                            try:
                                with pytest.raises(
                                    RuntimeError,
                                    match="crash before staging root",
                                ):
                                    third_runtime.execute_pinned_adoption(
                                        operation_id, max_bytes=2 * 1024 * 1024
                                    )
                            finally:
                                monkeypatch.setattr(
                                    PosixPackagePluginRootMaterializationStore,
                                    "stage_root",
                                    original_stage_root,
                                )
                        else:
                            monkeypatch.setattr(
                                PackageArtifactStagingJournal,
                                "append",
                                fail_after_append,
                            )
                            try:
                                with pytest.raises(
                                    RuntimeError, match="crash after staging receipt"
                                ):
                                    third_runtime.execute_pinned_adoption(
                                        operation_id, max_bytes=2 * 1024 * 1024
                                    )
                            finally:
                                monkeypatch.setattr(
                                    PackageArtifactStagingJournal,
                                    "append",
                                    original_append,
                                )
                            assert crashed
                        stage_path = product.state_root / "staging.jsonl"
                        if crash_before_stage_effect:
                            stage_path.write_bytes(b"")
                        assert len(
                            PackageArtifactStagingJournal(stage_path).receipts(
                                operation_id
                            )
                        ) == (0 if crash_before_stage_effect else 1)
                        staged_status = PackageLifecycleJournal(lifecycle_path).status(
                            operation_id
                        )
                        assert staged_status is not None
                        assert staged_status.phase == "transaction_pinned"
                        before_refusal = lifecycle_path.read_bytes()
                        stage_before_refusal = stage_path.read_bytes()
                        third_runtime.dispose_runtime()
                        third_runtime = None
                        third_owner.close()
                        if scenario == "transaction_pinned_stage_cli_crash":
                            from loushang.coding.cli import package_repair

                            monkeypatch.setattr(
                                package_repair, "version", lambda _name: "2.0.0"
                            )
                            assert (
                                package_repair.main(
                                    [
                                        "--workspace",
                                        str(workspace),
                                        "inspect-staging",
                                        operation_id,
                                    ]
                                )
                                == 0
                            )
                            inspected = json.loads(capsys.readouterr().out)
                            assert inspected["phase"] == "transaction_pinned"
                            assert inspected["missingNodeIds"] == []
                            assert inspected["stagedNodeCount"] == 1
                            open_owner = package_repair.open_coding_fenced_product_application_owner

                            def open_then_change_source(*args, **kwargs):
                                owner = open_owner(*args, **kwargs)
                                source_path.write_bytes(b"changed after Product open")
                                return owner

                            monkeypatch.setattr(
                                package_repair,
                                "open_coding_fenced_product_application_owner",
                                open_then_change_source,
                            )
                            try:
                                assert (
                                    package_repair.main(
                                        [
                                            "--workspace",
                                            str(workspace),
                                            "repair-staging",
                                            operation_id,
                                        ]
                                    )
                                    == 1
                                )
                                assert "package_source_digest_mismatch" in (
                                    capsys.readouterr().err
                                )
                                assert lifecycle_path.read_bytes() == before_refusal
                                assert stage_path.read_bytes() == stage_before_refusal
                            finally:
                                monkeypatch.setattr(
                                    package_repair,
                                    "open_coding_fenced_product_application_owner",
                                    open_owner,
                                )
                                source_path.write_bytes(source_bytes)
                            original_execute = (
                                PackageProductRuntimeBindingV1.execute_staging_adoption
                            )

                            def crash_after_selection(
                                self: PackageProductRuntimeBindingV1,
                                selected_operation_id: str,
                                *,
                                max_bytes: int,
                            ) -> object:
                                assert selected_operation_id == operation_id
                                assert max_bytes == 2 * 1024 * 1024
                                raise RuntimeError("crash after CLI selection")

                            monkeypatch.setattr(
                                PackageProductRuntimeBindingV1,
                                "execute_staging_adoption",
                                crash_after_selection,
                            )
                            try:
                                assert (
                                    package_repair.main(
                                        [
                                            "--workspace",
                                            str(workspace),
                                            "repair-staging",
                                            operation_id,
                                        ]
                                    )
                                    == 1
                                )
                                assert "package_repair_unavailable" in (
                                    capsys.readouterr().err
                                )
                            finally:
                                monkeypatch.setattr(
                                    PackageProductRuntimeBindingV1,
                                    "execute_staging_adoption",
                                    original_execute,
                                )
                            assert lifecycle_path.read_bytes() != before_refusal
                            assert stage_path.read_bytes() == stage_before_refusal
                            assert (
                                package_repair.main(
                                    [
                                        "--workspace",
                                        str(workspace),
                                        "repair-staging",
                                        operation_id,
                                    ]
                                )
                                == 0
                            )
                            repaired = json.loads(capsys.readouterr().out)
                            assert repaired["disposition"] == "committed"
                            assert repaired["phase"] == "committed"
                            assert (
                                PackageLifecycleJournal(lifecycle_path)
                                .status(operation_id)
                                .disposition
                                == "committed"
                            )
                            return
                        if scenario in {
                            "transaction_pinned_stage_rpc_crash",
                            "transaction_pinned_stage_ui_crash",
                        }:
                            before_wrong_action = lifecycle_path.read_bytes()
                            session = _p2_session(
                                workspace, settings, tmp_path / f"{scenario}-sessions"
                            )
                            if scenario == "transaction_pinned_stage_rpc_crash":
                                from loushang.coding.package_product_repair import (
                                    open_coding_package_repair_client,
                                )
                                from loushang.coding.package_product_repair_rpc import (
                                    CodingPackageRepairRpcClientV1,
                                )

                                class CurrentSessionRuntime:
                                    def get_current_session(self):  # type: ignore[no-untyped-def]
                                        return session

                                stdout = StringIO()
                                host = RpcHost(
                                    runtime=CurrentSessionRuntime(),
                                    stdin=StringIO(),
                                    stdout=stdout,
                                    package_repair_factory=lambda cwd: (
                                        CodingPackageRepairRpcClientV1(
                                            local=open_coding_package_repair_client(
                                                cwd, runtime_version="2.0.0"
                                            )
                                        )
                                    ),
                                )
                                payload = {
                                    "productId": "coding",
                                    "scopeId": layout.scope_id,
                                    "operationId": operation_id,
                                }
                                try:
                                    for request_id, action in (
                                        ("rpc:inspect", "inspect-staging"),
                                        ("rpc:wrong", "repair-published"),
                                    ):
                                        assert (
                                            asyncio.run(
                                                host.submit_input(
                                                    json.dumps(
                                                        {
                                                            "id": request_id,
                                                            "type": "repair_plugin_package_v1",
                                                            "action": action,
                                                            **payload,
                                                        }
                                                    )
                                                )
                                            )
                                            == 0
                                        )
                                        assert (
                                            lifecycle_path.read_bytes()
                                            == before_wrong_action
                                        )
                                    assert (
                                        asyncio.run(
                                            host.submit_input(
                                                json.dumps(
                                                    {
                                                        "id": "rpc:repair",
                                                        "type": "repair_plugin_package_v1",
                                                        "action": "repair-staging",
                                                        **payload,
                                                    }
                                                )
                                            )
                                        )
                                        == 0
                                    )
                                finally:
                                    asyncio.run(host.stop())
                                    asyncio.run(session.dispose())
                                responses = {
                                    item["id"]: item
                                    for item in (
                                        json.loads(line)
                                        for line in stdout.getvalue().splitlines()
                                    )
                                }
                                inspected = responses["rpc:inspect"]["data"]
                                assert inspected["phase"] == "transaction_pinned"
                                assert inspected["missingNodeIds"] == []
                                assert inspected["stagedNodeCount"] == 1
                                assert responses["rpc:wrong"]["errorCode"]
                                assert responses["rpc:repair"]["data"][
                                    "disposition"
                                ] == ("committed")
                            else:
                                from loushang.coding.ui.product_binding import (
                                    build_coding_ui_controller,
                                )
                                from loushang.harnesstui.conversation.intents import (
                                    PromptIntent,
                                )

                                monkeypatch.setattr(
                                    "loushang.coding.package_product_repair.version",
                                    lambda _name: "2.0.0",
                                )
                                controller = build_coding_ui_controller(
                                    session=session, plugin_workspace=workspace
                                )
                                try:
                                    inspected = asyncio.run(
                                        controller.dispatch(
                                            PromptIntent(
                                                text=f"/plugins repair-package inspect-staging {operation_id}"
                                            )
                                        )
                                    )
                                    assert "Package staging" in (
                                        inspected.status_message or ""
                                    )
                                    assert (
                                        lifecycle_path.read_bytes()
                                        == before_wrong_action
                                    )
                                    wrong = asyncio.run(
                                        controller.dispatch(
                                            PromptIntent(
                                                text=f"/plugins repair-package repair-published {operation_id}"
                                            )
                                        )
                                    )
                                    assert wrong.error_message is not None
                                    assert (
                                        lifecycle_path.read_bytes()
                                        == before_wrong_action
                                    )
                                    repaired = asyncio.run(
                                        controller.dispatch(
                                            PromptIntent(
                                                text=f"/plugins repair-package repair-staging {operation_id}"
                                            )
                                        )
                                    )
                                    assert repaired.error_message is None
                                    assert "Package repair committed" in (
                                        repaired.status_message or ""
                                    )
                                finally:
                                    asyncio.run(session.dispose())
                            assert (
                                PackageLifecycleJournal(lifecycle_path)
                                .status(operation_id)
                                .disposition
                                == "committed"
                            )
                            return
                        fourth_owner = open_coding_fenced_product_application_owner(
                            layout,
                            workspace=workspace,
                            runtime_version="2.0.0",
                            runtime_protocol_epoch=2,
                        )
                        fourth_runtime = None
                        try:
                            reopened_product = selected_product(
                                fourth_owner.runtime_owner.product_owner
                            )
                            fourth_runtime = reopened_product.factory_for_session(
                                session_id="rebind-fourth",
                                cwd=workspace,
                                runtime_id="rebind-fourth",
                            ).create(
                                PackageProductRuntimeRequestV1(
                                    product_id="coding",
                                    session_id="rebind-fourth",
                                    cwd=str(workspace),
                                )
                            )
                            fourth_runtime.activate()
                            checkpoint = asyncio.run(
                                fourth_runtime.inspect_staging_checkpoint(operation_id)
                            )
                            assert checkpoint.status == staged_status
                            assert checkpoint.missing_node_ids == (
                                ("root",) if crash_before_stage_effect else ()
                            )
                            assert len(checkpoint.receipts) == (
                                0 if crash_before_stage_effect else 1
                            )
                            preflight = asyncio.run(
                                fourth_runtime.inspect_staging_rebind_claim(
                                    operation_id, max_bytes=2 * 1024 * 1024
                                )
                            )
                            assert preflight.checkpoint == checkpoint
                            assert preflight.source.attempt_epoch == (
                                staged_status.attempt_epoch
                            )
                            source_path.write_bytes(b"changed after staging")
                            try:
                                with pytest.raises(
                                    PackageProductRebindSourceError
                                ) as changed_source:
                                    asyncio.run(
                                        fourth_runtime.inspect_staging_rebind_claim(
                                            operation_id,
                                            max_bytes=2 * 1024 * 1024,
                                        )
                                    )
                                assert changed_source.value.code == (
                                    "package_source_digest_mismatch"
                                )
                                assert stage_path.read_bytes() == stage_before_refusal
                            finally:
                                source_path.write_bytes(source_bytes)
                            fourth_runtime.lifecycle.activate()
                            if not crash_before_stage_effect:
                                stage_path.write_bytes(b"")
                                try:
                                    with pytest.raises(
                                        PackageStagingCheckpointError
                                    ) as unmatched:
                                        asyncio.run(
                                            fourth_runtime.inspect_staging_checkpoint(
                                                operation_id
                                            )
                                        )
                                    assert unmatched.value.code == (
                                        "package_staging_checkpoint_store_unmatched"
                                    )
                                    assert stage_path.read_bytes() == b""
                                finally:
                                    stage_path.write_bytes(stage_before_refusal)
                                fourth_runtime.lifecycle.activate()
                            assert (
                                asyncio.run(
                                    fourth_runtime.inspect_staging_checkpoint(
                                        operation_id
                                    )
                                )
                                == checkpoint
                            )
                            if not crash_before_stage_effect:
                                with pytest.raises(
                                    PackageProductRebindCleanupReadError
                                ) as refused:
                                    fourth_runtime.prepare_pinned_adoption(
                                        operation_id, max_bytes=2 * 1024 * 1024
                                    )
                                assert (
                                    refused.value.code == "package_rebind_later_effects"
                                )
                                assert lifecycle_path.read_bytes() == before_refusal
                                assert stage_path.read_bytes() == stage_before_refusal
                                fourth_runtime.lifecycle.activate()
                            adopted_stage = fourth_runtime.prepare_staging_adoption(
                                operation_id, max_bytes=2 * 1024 * 1024
                            )
                            assert adopted_stage.decision.staging_checkpoint_id == (
                                checkpoint.checkpoint_id
                            )
                            assert adopted_stage.status.attempt_epoch == (
                                staged_status.attempt_epoch
                            )
                            assert adopted_stage.status.attempt_revision > (
                                staged_status.attempt_revision
                            )
                            assert (
                                asyncio.run(
                                    fourth_runtime.inspect_staging_checkpoint(
                                        operation_id
                                    )
                                ).checkpoint_id
                                == checkpoint.checkpoint_id
                            )
                            selected_bytes = lifecycle_path.read_bytes()
                            assert (
                                fourth_runtime.prepare_staging_adoption(
                                    operation_id, max_bytes=2 * 1024 * 1024
                                )
                                == adopted_stage
                            )
                            assert lifecycle_path.read_bytes() == selected_bytes
                            assert stage_path.read_bytes() == stage_before_refusal
                            selected_claim = asyncio.run(
                                fourth_runtime.inspect_staging_rebind_claim(
                                    operation_id, max_bytes=2 * 1024 * 1024
                                )
                            )
                            assert selected_claim.lease.pending_staging_decision_id == (
                                adopted_stage.decision.decision_id
                            )
                            assert selected_claim.checkpoint.checkpoint_id == (
                                checkpoint.checkpoint_id
                            )
                            proposal = PackageProductStagingAdoptionBindingJournal(
                                product.state_root / "staging-admissions.jsonl"
                            ).read_decision(adopted_stage.decision.decision_id)
                            assert proposal is not None
                            staging_owner = fourth_runtime._staging_adoption_owner
                            assert staging_owner is not None
                            direct_route = staging_owner.route(
                                adopted_stage,
                                proposal.admission,
                                missing_node_ids=checkpoint.missing_node_ids,
                            )
                            assert direct_route.missing_node_ids == (
                                checkpoint.missing_node_ids
                            )
                            before_direct = lifecycle_path.read_bytes()
                            with pytest.raises(
                                PackageProductRouteContractError
                            ) as unpermitted:
                                fourth_runtime.lifecycle._router.route_staging_adopted(
                                    direct_route, current=adopted_stage.status
                                )
                            assert unpermitted.value.code == (
                                "package_staging_adoption_execution_not_available"
                            )
                            assert lifecycle_path.read_bytes() == before_direct
                            assert stage_path.read_bytes() == stage_before_refusal
                            if crash_before_stage_effect:
                                original_reacquire = (
                                    PackageClosureLifecycleOwner.reacquire
                                )

                                def corrupt_after_reacquire(self, execution):
                                    result = original_reacquire(self, execution)
                                    stage_path.write_bytes(b'{"partial":')
                                    return result

                                monkeypatch.setattr(
                                    PackageClosureLifecycleOwner,
                                    "reacquire",
                                    corrupt_after_reacquire,
                                )
                                try:
                                    with pytest.raises(
                                        PackageArtifactStagingJournalError
                                    ):
                                        fourth_runtime.execute_staging_adoption(
                                            operation_id,
                                            max_bytes=2 * 1024 * 1024,
                                        )
                                finally:
                                    monkeypatch.setattr(
                                        PackageClosureLifecycleOwner,
                                        "reacquire",
                                        original_reacquire,
                                    )
                                    stage_path.write_bytes(stage_before_refusal)
                                assert lifecycle_path.read_bytes() == before_direct
                                assert not tuple(
                                    receipt
                                    for receipt in PackageStoreSettlementJournal(
                                        product.state_root / "root-settlements.jsonl"
                                    ).records()
                                    if receipt.receipt.operation_id == operation_id
                                )
                                fourth_runtime.lifecycle.activate()
                            if crash_after_stage_commit:
                                original_finalize = (
                                    PackageProductHandoffFinalizer.finalize
                                )

                                def fail_stage_handoff_once(
                                    self: PackageProductHandoffFinalizer,
                                    request: object,
                                    *,
                                    current: object,
                                ) -> None:
                                    raise RuntimeError("crash before staging handoff")

                                monkeypatch.setattr(
                                    PackageProductHandoffFinalizer,
                                    "finalize",
                                    fail_stage_handoff_once,
                                )
                                try:
                                    with pytest.raises(
                                        RuntimeError,
                                        match="crash before staging handoff",
                                    ):
                                        fourth_runtime.execute_staging_adoption(
                                            operation_id,
                                            max_bytes=2 * 1024 * 1024,
                                        )
                                finally:
                                    monkeypatch.setattr(
                                        PackageProductHandoffFinalizer,
                                        "finalize",
                                        original_finalize,
                                    )
                                committed_read = PackageLifecycleJournal(
                                    lifecycle_path
                                ).read_operation(operation_id)
                                assert committed_read is not None
                                assert committed_read[1].disposition == "committed"
                                assert (
                                    PackageRetentionHandoffJournal(
                                        product.state_root / "handoff.jsonl"
                                    ).read_operation(operation_id)
                                    is None
                                )
                                fourth_runtime.dispose_runtime()
                                fourth_runtime = None
                                fourth_owner.close()
                                fifth_owner = (
                                    open_coding_fenced_product_application_owner(
                                        layout,
                                        workspace=workspace,
                                        runtime_version="2.0.0",
                                        runtime_protocol_epoch=2,
                                    )
                                )
                                fifth_runtime = None
                                try:
                                    fifth_product = selected_product(
                                        fifth_owner.runtime_owner.product_owner
                                    )
                                    fifth_runtime = fifth_product.factory_for_session(
                                        session_id="rebind-fifth",
                                        cwd=workspace,
                                        runtime_id="rebind-fifth",
                                    ).create(
                                        PackageProductRuntimeRequestV1(
                                            product_id="coding",
                                            session_id="rebind-fifth",
                                            cwd=str(workspace),
                                        )
                                    )
                                    fifth_runtime.activate()
                                    recovered_handoff = PackageRetentionHandoffJournal(
                                        product.state_root / "handoff.jsonl"
                                    ).read_operation(operation_id)
                                    assert recovered_handoff is not None
                                    assert recovered_handoff.state == "settled"
                                    assert (
                                        PackageLifecycleJournal(
                                            lifecycle_path
                                        ).read_operation(operation_id)
                                        == committed_read
                                    )
                                finally:
                                    if fifth_runtime is not None:
                                        fifth_runtime.dispose_runtime()
                                    fifth_owner.close()
                            else:
                                committed = fourth_runtime.execute_staging_adoption(
                                    operation_id, max_bytes=2 * 1024 * 1024
                                )
                                assert committed.phase == "committed"
                                assert committed.disposition == "committed"
                                assert committed.attempt_epoch == (
                                    staged_status.attempt_epoch
                                )
                                handoff_receipt = PackageRetentionHandoffJournal(
                                    product.state_root / "handoff.jsonl"
                                ).read_operation(operation_id)
                                assert handoff_receipt is not None
                                assert handoff_receipt.state == "settled"
                        finally:
                            if fourth_runtime is not None:
                                fourth_runtime.dispose_runtime()
                            fourth_owner.close()
                        return
                    if crash_after_published_set:
                        prior_admission = third_runtime.lifecycle.activate()
                        original_commit = PackageCommitLifecycleOwner.commit

                        def stop_after_published_set(
                            self: PackageCommitLifecycleOwner,
                            selected_operation_id: str,
                        ) -> None:
                            assert selected_operation_id == operation_id
                            raise RuntimeError("crash after published set")

                        monkeypatch.setattr(
                            PackageCommitLifecycleOwner,
                            "commit",
                            stop_after_published_set,
                        )
                        try:
                            with pytest.raises(
                                RuntimeError, match="crash after published set"
                            ):
                                third_runtime.execute_pinned_adoption(
                                    operation_id, max_bytes=2 * 1024 * 1024
                                )
                        finally:
                            monkeypatch.setattr(
                                PackageCommitLifecycleOwner, "commit", original_commit
                            )
                        published = PackageLifecycleJournal(lifecycle_path).status(
                            operation_id
                        )
                        assert published is not None
                        assert published.phase == "set_published"
                        assert published.disposition == "active"
                        third_runtime.dispose_runtime()
                        third_runtime = None
                        third_owner.close()

                        def assert_published_repair_committed() -> None:
                            assert (
                                PackageLifecycleJournal(lifecycle_path)
                                .status(operation_id)
                                .disposition
                                == "committed"
                            )
                            installation = (
                                product.desired_state.snapshot().installation(
                                    PluginInstallationKeyV1(
                                        product_id="coding",
                                        installation_scope="workspace",
                                        scope_id=layout.scope_id,
                                        plugin_id="retryable",
                                    )
                                )
                            )
                            assert installation.selection.desired_state == (
                                "installed_disabled"
                            )

                        if scenario == "transaction_pinned_published_cli_crash":
                            from loushang.coding.cli import package_repair

                            monkeypatch.setattr(
                                package_repair, "version", lambda _name: "2.0.0"
                            )
                            assert (
                                package_repair.main(
                                    [
                                        "--workspace",
                                        str(workspace),
                                        "inspect-published",
                                        operation_id,
                                    ]
                                )
                                == 0
                            )
                            inspected = json.loads(capsys.readouterr().out)
                            assert inspected["phase"] == "set_published"
                            assert inspected["missingNodeIds"] == []
                            assert inspected["stagedNodeCount"] == 1
                            before_wrong_action = lifecycle_path.read_bytes()
                            assert (
                                package_repair.main(
                                    [
                                        "--workspace",
                                        str(workspace),
                                        "repair-staging",
                                        operation_id,
                                    ]
                                )
                                == 1
                            )
                            capsys.readouterr()
                            assert lifecycle_path.read_bytes() == before_wrong_action
                            original_execute = (
                                PackageProductRuntimeBindingV1.execute_staging_adoption
                            )

                            def crash_after_published_selection(
                                self: PackageProductRuntimeBindingV1,
                                selected_operation_id: str,
                                *,
                                max_bytes: int,
                            ) -> object:
                                assert selected_operation_id == operation_id
                                assert max_bytes == 2 * 1024 * 1024
                                raise RuntimeError(
                                    "crash after published CLI selection"
                                )

                            monkeypatch.setattr(
                                PackageProductRuntimeBindingV1,
                                "execute_staging_adoption",
                                crash_after_published_selection,
                            )
                            try:
                                assert (
                                    package_repair.main(
                                        [
                                            "--workspace",
                                            str(workspace),
                                            "repair-published",
                                            operation_id,
                                        ]
                                    )
                                    == 1
                                )
                                assert "package_repair_unavailable" in (
                                    capsys.readouterr().err
                                )
                            finally:
                                monkeypatch.setattr(
                                    PackageProductRuntimeBindingV1,
                                    "execute_staging_adoption",
                                    original_execute,
                                )
                            selected = PackageLifecycleJournal(
                                lifecycle_path
                            ).latest_staging_adoption(operation_id)
                            assert selected is not None
                            assert selected.status.phase == "set_published"
                            assert (
                                PackageLifecycleJournal(lifecycle_path)
                                .status(operation_id)
                                .phase
                                == "set_published"
                            )
                            assert (
                                package_repair.main(
                                    [
                                        "--workspace",
                                        str(workspace),
                                        "repair-published",
                                        operation_id,
                                    ]
                                )
                                == 0
                            )
                            repaired = json.loads(capsys.readouterr().out)
                            assert repaired["phase"] == "committed"
                            assert repaired["disposition"] == "committed"
                            assert_published_repair_committed()
                            return
                        if scenario == "transaction_pinned_published_rpc_crash":
                            from loushang.coding.package_product_repair import (
                                open_coding_package_repair_client,
                            )
                            from loushang.coding.package_product_repair_rpc import (
                                CodingPackageRepairRpcClientV1,
                            )

                            before_wrong_action = lifecycle_path.read_bytes()
                            session = _p2_session(
                                workspace, settings, tmp_path / "published-rpc-sessions"
                            )

                            class CurrentSessionRuntime:
                                def get_current_session(self):  # type: ignore[no-untyped-def]
                                    return session

                            stdout = StringIO()
                            host = RpcHost(
                                runtime=CurrentSessionRuntime(),
                                stdin=StringIO(),
                                stdout=stdout,
                                package_repair_factory=lambda cwd: (
                                    CodingPackageRepairRpcClientV1(
                                        local=open_coding_package_repair_client(
                                            cwd, runtime_version="2.0.0"
                                        )
                                    )
                                ),
                            )
                            payload = {
                                "productId": "coding",
                                "scopeId": layout.scope_id,
                                "operationId": operation_id,
                            }
                            try:
                                for request_id, action in (
                                    ("rpc:inspect", "inspect-published"),
                                    ("rpc:wrong", "repair-staging"),
                                ):
                                    assert (
                                        asyncio.run(
                                            host.submit_input(
                                                json.dumps(
                                                    {
                                                        "id": request_id,
                                                        "type": "repair_plugin_package_v1",
                                                        "action": action,
                                                        **payload,
                                                    }
                                                )
                                            )
                                        )
                                        == 0
                                    )
                                    assert (
                                        lifecycle_path.read_bytes()
                                        == before_wrong_action
                                    )
                                assert (
                                    asyncio.run(
                                        host.submit_input(
                                            json.dumps(
                                                {
                                                    "id": "rpc:repair",
                                                    "type": "repair_plugin_package_v1",
                                                    "action": "repair-published",
                                                    **payload,
                                                }
                                            )
                                        )
                                    )
                                    == 0
                                )
                            finally:
                                asyncio.run(host.stop())
                                asyncio.run(session.dispose())
                            responses = {
                                item["id"]: item
                                for item in (
                                    json.loads(line)
                                    for line in stdout.getvalue().splitlines()
                                )
                            }
                            assert responses["rpc:inspect"]["data"]["phase"] == (
                                "set_published"
                            )
                            assert (
                                responses["rpc:inspect"]["data"]["missingNodeIds"] == []
                            )
                            assert responses["rpc:wrong"]["errorCode"]
                            assert responses["rpc:repair"]["data"]["disposition"] == (
                                "committed"
                            )
                            assert_published_repair_committed()
                            return
                        if scenario == "transaction_pinned_published_ui_crash":
                            from loushang.coding.ui.product_binding import (
                                build_coding_ui_controller,
                            )
                            from loushang.harnesstui.conversation.intents import (
                                PromptIntent,
                            )

                            monkeypatch.setattr(
                                "loushang.coding.package_product_repair.version",
                                lambda _name: "2.0.0",
                            )
                            before_wrong_action = lifecycle_path.read_bytes()
                            session = _p2_session(
                                workspace, settings, tmp_path / "published-ui-sessions"
                            )
                            controller = build_coding_ui_controller(
                                session=session, plugin_workspace=workspace
                            )
                            try:
                                inspected = asyncio.run(
                                    controller.dispatch(
                                        PromptIntent(
                                            text=f"/plugins repair-package inspect-published {operation_id}"
                                        )
                                    )
                                )
                                assert "Package published set" in (
                                    inspected.status_message or ""
                                )
                                assert (
                                    lifecycle_path.read_bytes() == before_wrong_action
                                )
                                wrong = asyncio.run(
                                    controller.dispatch(
                                        PromptIntent(
                                            text=f"/plugins repair-package repair-staging {operation_id}"
                                        )
                                    )
                                )
                                assert wrong.error_message is not None
                                assert (
                                    lifecycle_path.read_bytes() == before_wrong_action
                                )
                                repaired = asyncio.run(
                                    controller.dispatch(
                                        PromptIntent(
                                            text=f"/plugins repair-package repair-published {operation_id}"
                                        )
                                    )
                                )
                                assert repaired.error_message is None
                                assert "Package repair committed" in (
                                    repaired.status_message or ""
                                )
                            finally:
                                asyncio.run(session.dispose())
                            assert_published_repair_committed()
                            return
                        fourth_owner = open_coding_fenced_product_application_owner(
                            layout,
                            workspace=workspace,
                            runtime_version="2.0.0",
                            runtime_protocol_epoch=2,
                        )
                        fourth_runtime = None
                        try:
                            reopened_product = selected_product(
                                fourth_owner.runtime_owner.product_owner
                            )
                            fourth_runtime = reopened_product.factory_for_session(
                                session_id="rebind-published",
                                cwd=workspace,
                                runtime_id="rebind-published",
                            ).create(
                                PackageProductRuntimeRequestV1(
                                    product_id="coding",
                                    session_id="rebind-published",
                                    cwd=str(workspace),
                                )
                            )
                            fourth_runtime.activate()
                            before_read = lifecycle_path.read_bytes()
                            preflight = asyncio.run(
                                fourth_runtime.inspect_published_set_rebind_claim(
                                    operation_id, max_bytes=2 * 1024 * 1024
                                )
                            )
                            assert preflight.checkpoint.status == published
                            assert len(preflight.checkpoint.receipts) == 1
                            assert preflight.checkpoint.committed_set.operation_id == (
                                operation_id
                            )
                            assert lifecycle_path.read_bytes() == before_read
                            source_bytes = source_path.read_bytes()
                            source_path.write_bytes(b"changed after published set")
                            try:
                                with pytest.raises(PackageProductRebindSourceError):
                                    asyncio.run(
                                        fourth_runtime.inspect_published_set_rebind_claim(
                                            operation_id,
                                            max_bytes=2 * 1024 * 1024,
                                        )
                                    )
                                fourth_runtime.lifecycle.activate()
                                with pytest.raises(PackageProductRebindSourceError):
                                    fourth_runtime.prepare_staging_adoption(
                                        operation_id, max_bytes=2 * 1024 * 1024
                                    )
                                assert lifecycle_path.read_bytes() == before_read
                            finally:
                                source_path.write_bytes(source_bytes)
                            fourth_runtime.lifecycle.activate()
                            selected_published = (
                                fourth_runtime.prepare_staging_adoption(
                                    operation_id, max_bytes=2 * 1024 * 1024
                                )
                            )
                            assert selected_published.status.phase == "set_published"
                            assert (
                                selected_published.decision.staging_checkpoint_id
                                == (preflight.checkpoint.checkpoint_id)
                            )
                            assert (
                                selected_published.decision.previous_selected_decision_id
                                is None
                            )
                            assert (
                                fourth_runtime.prepare_staging_adoption(
                                    operation_id, max_bytes=2 * 1024 * 1024
                                )
                                == selected_published
                            )
                            prior_route = PackageProductPinnedAdoptedRouteRequestV1(
                                entrypoint="operations",
                                ingress=ingress,
                                admission=prior_admission,
                                decision=adopted.decision,
                            )
                            selected_status = PackageLifecycleJournal(
                                lifecycle_path
                            ).status(operation_id)
                            assert selected_status is not None
                            with pytest.raises(
                                PackageProductRouteContractError
                            ) as old_route:
                                require_rebound_decision(
                                    prior_route,
                                    selected_status,
                                    PackageLifecycleJournal(lifecycle_path),
                                )
                            assert old_route.value.code == (
                                "package_staging_adoption_route_required"
                            )
                            if (
                                scenario
                                == "transaction_pinned_published_selection_crash"
                            ):
                                fourth_runtime.dispose_runtime()
                                fourth_runtime = None
                                fourth_owner.close()
                                fourth_owner = None
                                fifth_owner = (
                                    open_coding_fenced_product_application_owner(
                                        layout,
                                        workspace=workspace,
                                        runtime_version="2.0.0",
                                        runtime_protocol_epoch=2,
                                    )
                                )
                                fifth_runtime = None
                                try:
                                    fifth_product = selected_product(
                                        fifth_owner.runtime_owner.product_owner
                                    )
                                    fifth_runtime = fifth_product.factory_for_session(
                                        session_id="rebind-published-fifth",
                                        cwd=workspace,
                                        runtime_id="rebind-published-fifth",
                                    ).create(
                                        PackageProductRuntimeRequestV1(
                                            product_id="coding",
                                            session_id="rebind-published-fifth",
                                            cwd=str(workspace),
                                        )
                                    )
                                    fifth_runtime.activate()
                                    superseded = fifth_runtime.prepare_staging_adoption(
                                        operation_id, max_bytes=2 * 1024 * 1024
                                    )
                                    assert superseded.status.phase == "set_published"
                                    assert (
                                        superseded.decision.previous_selected_decision_id
                                        == selected_published.decision.decision_id
                                    )
                                    assert (
                                        superseded.decision.staging_checkpoint_id
                                        == (preflight.checkpoint.checkpoint_id)
                                    )
                                    committed = fifth_runtime.execute_staging_adoption(
                                        operation_id, max_bytes=2 * 1024 * 1024
                                    )
                                finally:
                                    if fifth_runtime is not None:
                                        fifth_runtime.dispose_runtime()
                                    fifth_owner.close()
                            else:
                                committed = fourth_runtime.execute_staging_adoption(
                                    operation_id, max_bytes=2 * 1024 * 1024
                                )
                            assert committed.phase == "committed"
                            assert committed.disposition == "committed"
                            handoff_receipt = PackageRetentionHandoffJournal(
                                reopened_product.state_root / "handoff.jsonl"
                            ).read_operation(operation_id)
                            assert handoff_receipt is not None
                            assert handoff_receipt.state == "settled"
                        finally:
                            if fourth_runtime is not None:
                                fourth_runtime.dispose_runtime()
                            if fourth_owner is not None:
                                fourth_owner.close()
                        return
                    if crash_before_execution:
                        third_runtime.dispose_runtime()
                        third_runtime = None
                        third_owner.close()
                        fourth_owner = open_coding_fenced_product_application_owner(
                            layout,
                            workspace=workspace,
                            runtime_version="2.0.0",
                            runtime_protocol_epoch=2,
                        )
                        fourth_runtime = None
                        try:
                            reopened_product = selected_product(
                                fourth_owner.runtime_owner.product_owner
                            )
                            fourth_runtime = reopened_product.factory_for_session(
                                session_id="rebind-fourth",
                                cwd=workspace,
                                runtime_id="rebind-fourth",
                            ).create(
                                PackageProductRuntimeRequestV1(
                                    product_id="coding",
                                    session_id="rebind-fourth",
                                    cwd=str(workspace),
                                )
                            )
                            fourth_runtime.activate()
                            superseded = fourth_runtime.prepare_pinned_adoption(
                                operation_id, max_bytes=2 * 1024 * 1024
                            )
                            assert superseded.record_kind == (
                                "pinned_adoption_supersession"
                            )
                            assert superseded.supersedes_decision_id == (
                                adopted.decision.decision_id
                            )
                            committed = fourth_runtime.execute_pinned_adoption(
                                operation_id, max_bytes=2 * 1024 * 1024
                            )
                            assert committed.disposition == "committed"
                            assert (
                                committed.attempt_epoch == adopted.status.attempt_epoch
                            )
                        finally:
                            if fourth_runtime is not None:
                                fourth_runtime.dispose_runtime()
                            fourth_owner.close()
                        return
                    if crash_handoff:
                        original_finalize = PackageProductHandoffFinalizer.finalize
                        crashed = False

                        def fail_once(
                            self: PackageProductHandoffFinalizer,
                            request: object,
                            *,
                            current: object,
                        ) -> None:
                            nonlocal crashed
                            if not crashed:
                                crashed = True
                                raise RuntimeError("crash before pinned handoff")
                            original_finalize(self, request, current=current)  # type: ignore[arg-type]

                        monkeypatch.setattr(
                            PackageProductHandoffFinalizer,
                            "finalize",
                            fail_once,
                        )
                        with pytest.raises(
                            RuntimeError, match="crash before pinned handoff"
                        ):
                            third_runtime.execute_pinned_adoption(
                                operation_id, max_bytes=2 * 1024 * 1024
                            )
                        monkeypatch.setattr(
                            PackageProductHandoffFinalizer,
                            "finalize",
                            original_finalize,
                        )
                        committed_read = PackageLifecycleJournal(
                            lifecycle_path
                        ).read_operation(operation_id)
                        assert committed_read is not None
                        assert committed_read[1].disposition == "committed"
                        assert (
                            PackageRetentionHandoffJournal(
                                product.state_root / "handoff.jsonl"
                            ).read_operation(operation_id)
                            is None
                        )
                        third_runtime.dispose_runtime()
                        third_runtime = None
                        third_owner.close()
                        fourth_owner = open_coding_fenced_product_application_owner(
                            layout,
                            workspace=workspace,
                            runtime_version="2.0.0",
                            runtime_protocol_epoch=2,
                        )
                        fourth_runtime = None
                        try:
                            reopened_product = selected_product(
                                fourth_owner.runtime_owner.product_owner
                            )
                            fourth_runtime = reopened_product.factory_for_session(
                                session_id="rebind-fourth",
                                cwd=workspace,
                                runtime_id="rebind-fourth",
                            ).create(
                                PackageProductRuntimeRequestV1(
                                    product_id="coding",
                                    session_id="rebind-fourth",
                                    cwd=str(workspace),
                                )
                            )
                            fourth_runtime.activate()
                            recovered_receipt = PackageRetentionHandoffJournal(
                                product.state_root / "handoff.jsonl"
                            ).read_operation(operation_id)
                            assert recovered_receipt is not None
                            assert recovered_receipt.state == "settled"
                            assert (
                                PackageLifecycleJournal(lifecycle_path).read_operation(
                                    operation_id
                                )
                                == committed_read
                            )
                        finally:
                            if fourth_runtime is not None:
                                fourth_runtime.dispose_runtime()
                            fourth_owner.close()
                        return
                    committed = third_runtime.execute_pinned_adoption(
                        operation_id, max_bytes=2 * 1024 * 1024
                    )
                    assert committed.phase == "committed"
                    assert committed.disposition == "committed"
                    return
                before = (before_replay, pin_path.read_bytes())
                PackageTransactionPinJournal(pin_path).append(
                    PackageTransactionPinReceiptV1.transition(
                        pinned_read.cleanup.pin,
                        state="released",
                        owner_revision=pinned_read.cleanup.pin.owner_revision + 1,
                        lease_revision=pinned_read.cleanup.pin.lease_revision + 1,
                        transition_evidence_ref="b" * 64,
                    )
                )
                with pytest.raises(PackageProductRebindCleanupReadError) as released:
                    asyncio.run(
                        third_runtime.inspect_pinned_rebind_claim(
                            operation_id, max_bytes=2 * 1024 * 1024
                        )
                    )
                assert released.value.code == "package_rebind_pin_evidence_changed"
                assert lifecycle_path.read_bytes() == before[0]
                third_runtime.lifecycle.activate()
                with pytest.raises(PackageProductRebindCleanupReadError) as blocked:
                    third_runtime.prepare_pinned_adoption(
                        operation_id, max_bytes=2 * 1024 * 1024
                    )
                assert blocked.value.code == "package_rebind_pin_evidence_changed"
                assert lifecycle_path.read_bytes() == before[0]
                return
            if abandoned_phase in {
                "resolving_closure",
                "resolving_dependency",
                "closure_verified",
            }:
                resolving_read = asyncio.run(
                    third_runtime.inspect_verified_rebind_claim(
                        operation_id, max_bytes=2 * 1024 * 1024
                    )
                    if abandoned_phase == "closure_verified"
                    else third_runtime.inspect_resolving_rebind_claim(
                        operation_id, max_bytes=2 * 1024 * 1024
                    )
                )
                assert resolving_read.cleanup.status.phase == (
                    "closure_verified"
                    if abandoned_phase == "closure_verified"
                    else "resolving_closure"
                )
                recover_claim = (
                    third_runtime.recover_verified_rebind
                    if abandoned_phase == "closure_verified"
                    else third_runtime.recover_resolving_rebind
                )
                node_ids = tuple(
                    node.attempt.node_id for node in resolving_read.cleanup.nodes
                )
                assert len(node_ids) == (2 if with_dependency else 1)
                assert "root" in node_ids
                assert resolving_read.source.resolution_evidence_refs == (
                    resolving_read.cleanup.resolution_evidence_refs
                )
                pinned_source = Path(
                    product.policy.dependencies[0].source_identity
                    if with_dependency
                    else ingress.source_locator
                )
                pinned_bytes = pinned_source.read_bytes()
                lifecycle_path = product.state_root / "lifecycle.jsonl"
                before_refusal = lifecycle_path.read_bytes()
                pinned_source.write_bytes(b"changed resolving Source")
                try:
                    with pytest.raises(PackageProductRebindSourceError) as drift:
                        recover_claim(operation_id, max_bytes=2 * 1024 * 1024)
                    assert drift.value.code == "package_source_digest_mismatch"
                    assert lifecycle_path.read_bytes() == before_refusal
                finally:
                    pinned_source.write_bytes(pinned_bytes)
                third_runtime.lifecycle.activate()
                restart = recover_claim(operation_id, max_bytes=2 * 1024 * 1024)
                recovered = restart.status
                assert recovered.phase == "classified"
                tombstones = PackageQuarantineCleanupJournal(
                    product.state_root / "cleanup.jsonl"
                ).read_operation_tombstones(operation_id)
                assert len(tombstones) == len(node_ids)
                assert {item.target.node_id for item in tombstones} == set(node_ids)
                assert all(
                    item.disposition == "cleanup_complete" for item in tombstones
                )
                assert recover_claim(operation_id, max_bytes=2 * 1024 * 1024) == restart
            elif abandoned_phase in {"acquired", "inspecting", "extracted"}:
                acquired_read = asyncio.run(
                    third_runtime.inspect_acquired_rebind_claim(
                        operation_id, max_bytes=2 * 1024 * 1024
                    )
                )
                assert acquired_read.cleanup.status.phase == abandoned_phase
                pinned_source = Path(ingress.source_locator)
                pinned_bytes = pinned_source.read_bytes()
                lifecycle_path = product.state_root / "lifecycle.jsonl"
                before_refusal = lifecycle_path.read_bytes()
                pinned_source.write_bytes(b"changed acquired Source")
                try:
                    with pytest.raises(PackageProductRebindSourceError) as drift:
                        third_runtime.recover_acquired_rebind(
                            operation_id, max_bytes=2 * 1024 * 1024
                        )
                    assert drift.value.code == "package_source_digest_mismatch"
                    assert lifecycle_path.read_bytes() == before_refusal
                    assert (
                        PackageQuarantineCleanupJournal(
                            product.state_root / "cleanup.jsonl"
                        ).read_operation_tombstones(operation_id)
                        == ()
                    )
                finally:
                    pinned_source.write_bytes(pinned_bytes)
                third_runtime.lifecycle.activate()
                restart = third_runtime.recover_acquired_rebind(
                    operation_id, max_bytes=2 * 1024 * 1024
                )
                recovered = restart.status
                assert recovered.phase == "classified"
                assert (
                    third_runtime.recover_acquired_rebind(
                        operation_id, max_bytes=2 * 1024 * 1024
                    )
                    == restart
                )
            else:
                recovered = third_runtime.recover_unstarted_rebind(
                    operation_id, max_bytes=2 * 1024 * 1024
                )
                assert recovered.phase == abandoned_phase
            assert recovered.disposition == "retryable_failure"
            assert recovered.attempt_epoch == failed.attempt_epoch + 1
            new_decision = third_runtime.prepare_rebind_decision(
                operation_id, max_bytes=2 * 1024 * 1024
            )
            assert new_decision.decision.expected_attempt_epoch == (
                recovered.attempt_epoch
            )
            committed = third_runtime.execute_rebind_decision(
                operation_id, max_bytes=2 * 1024 * 1024
            )
            if with_dependency:
                # Recovery must succeed, while Coding's data-only Product
                # boundary still refuses executable dependency closures.
                assert committed.disposition == "rejected"
                assert committed.failure is not None
                assert committed.failure.code == "package_plugin_contribution_rejected"
                assert committed.phase == "closure_verified"
            else:
                assert committed.disposition == "committed", committed.failure
                assert committed.attempt_epoch == failed.attempt_epoch + 2
                installation = product.desired_state.snapshot().installation(
                    PluginInstallationKeyV1(
                        product_id="coding",
                        installation_scope="workspace",
                        scope_id=layout.scope_id,
                        plugin_id="retryable",
                    )
                )
                assert installation.selection.desired_state == "installed_disabled"
        finally:
            if third_runtime is not None:
                third_runtime.dispose_runtime()
            third_owner.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_external_data_wheel_refuses_symlink_and_oversize_before_capture(
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
        namespace_id="b" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    source = tmp_path / "reviewpack-1-py3-none-any.whl"
    real = tmp_path / "real-wheel"
    real.write_bytes(b"bytes")
    source.symlink_to(real)
    with pytest.raises(CodingExternalDataWheelError, match="Source changed"):
        admit_coding_external_data_wheel(lifecycle, source=source)
    source.unlink()
    source.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(CodingExternalDataWheelError, match="exceeds budget"):
        admit_coding_external_data_wheel(lifecycle, source=source)


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
@pytest.mark.parametrize(
    "executable_member,cleanup_failure,extra_enabled_field",
    [
        (False, False, None),
        (True, False, None),
        (True, True, None),
        (False, False, False),
    ],
)
def test_external_data_wheel_product_admits_skill_and_rejects_unsupported_shape(
    tmp_path: Path,
    executable_member: bool,
    cleanup_failure: bool,
    extra_enabled_field: bool | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejected = executable_member or extra_enabled_field is not None
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
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
    )
    source = tmp_path / "reviewpack-1-py3-none-any.whl"
    source.write_bytes(
        _data_wheel(
            executable_member=executable_member,
            extra_enabled_field=extra_enabled_field,
        )
    )
    if cleanup_failure:

        def fail_cleanup(_candidate: VerifiedWheelCandidate) -> None:
            raise OSError("injected quarantine removal failure")

        monkeypatch.setattr(VerifiedWheelCandidate, "cleanup", fail_cleanup)
    admit_coding_external_data_wheel(lifecycle, source=source)
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        product = owner.runtime_owner.product_owner
        binding = next(
            item for item in product.policy.bindings if item.plugin_id == "reviewpack"
        )
        factory = product.factory_for_session(
            session_id="external-skill", cwd=workspace, runtime_id="external-skill"
        )
        runtime = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id="external-skill", cwd=str(workspace)
            )
        )
        try:
            runtime.activate()
            outcome = runtime.lifecycle.route(
                PackageProductLifecycleIntentV1(
                    operation_id="external-skill-install",
                    action="install",
                    source=binding.source_identity,
                    scope="project",
                ),
                entrypoint="cli",
            )
        finally:
            runtime.dispose_runtime()
        assert outcome.handled and outcome.record is not None
        assert outcome.record.lifecycle == ("failed" if rejected else "installed")
        if rejected:
            assert outcome.evidence is not None
            assert (
                outcome.evidence.failure_code == "package_plugin_contribution_rejected"
            )
        if cleanup_failure:
            cleanup = PackageQuarantineCleanupJournal(
                product.state_root / "cleanup.jsonl"
            )
            assert any(
                item.status.rejection_code == "package_plugin_contribution_rejected"
                and item.status.disposition == "cleanup_retryable"
                for item in cleanup.records()
            )
        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=lifecycle.scope_id,
            plugin_id="reviewpack",
        )
        assert product.desired_state.snapshot().installation(
            key
        ).selection.desired_state == ("absent" if rejected else "installed_disabled")
    finally:
        owner.close()

    if not rejected:
        binding = build_coding_plugin_management_cli_read_binding(workspace, settings)
        assert binding.fresh_product
        with pytest.raises(PermissionError, match="read binding"):
            binding.ports.commands.submit(
                cast(PluginManagementApplicationCommandV1, object())
            )
        listing = list_plugin_records(binding)
        record = next(item for item in listing if item["name"] == "reviewpack")
        assert record["desiredState"] == "installed_disabled"
        command = build_coding_plugin_management_cli_binding(workspace, settings)
        apply_resource_toggles(
            None,
            ResourceToggleRequest(enable_plugins=("reviewpack",)),
            plugin_management=command,
        )
        record = next(
            item
            for item in list_plugin_records(binding)
            if item["name"] == "reviewpack"
        )
        assert record["desiredState"] == "installed_enabled"


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_external_data_wheel_installs_through_real_coding_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout,
        settings,
        workspace=workspace,
        namespace_id="d" * 64,
        runtime_version="0.1.0",
        runtime_protocol_epoch=2,
    )
    source = tmp_path / "reviewpack-1-py3-none-any.whl"
    source.write_bytes(_data_wheel())
    stdout = StringIO()
    stderr = StringIO()
    result = asyncio.run(
        run_cli(
            ["--install-package", str(source), "--package-scope", "project"],
            cwd=workspace,
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
        )
    )
    assert result == 0, stderr.getvalue()
    listing = list_plugin_records(
        build_coding_plugin_management_cli_read_binding(workspace, settings)
    )
    assert (
        next(item for item in listing if item["name"] == "reviewpack")["desiredState"]
        == "installed_disabled"
    )
    lifecycle_path = (
        resolve_coding_package_epoch_layout(layout).control_root
        / "product-state"
        / "lifecycle.jsonl"
    )
    install_ids = {
        document["request"]["operationId"]
        for line in lifecycle_path.read_bytes().splitlines()
        if (document := json.loads(line))["request"]["requestedPluginId"]
        == "reviewpack"
        and document["request"]["action"] == "install"
    }
    assert len(install_ids) == 1
    [install_id] = install_ids
    before_explain = tuple(
        sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    )
    operation = PluginOperationExplanationProjector(
        package_operations=PackageLifecycleJournal(lifecycle_path),
        management_commands=build_coding_plugin_management_cli_read_binding(
            workspace, settings
        ).ports.commands,
        handoffs=PackageRetentionHandoffJournal(
            lifecycle_path.parent / "handoff.jsonl"
        ),
    ).explain_operation(install_id, correlation_id="test:installed-package-explain")
    assert operation.join_status == "same_identity"
    assert operation.management_operation_id.startswith("package:")
    assert operation.management_disposition == "succeeded"
    assert operation.package.disposition == "committed"
    assert operation.handoff_evidence == "settled"
    assert operation.handoff_receipt_id is not None
    assert "package_product_handoff" not in operation.evidence_gaps
    management_commands = build_coding_plugin_management_cli_read_binding(
        workspace, settings
    ).ports.commands
    original = management_commands.operation(
        operation.management_operation_id,
        correlation_id="test:forged-management-read",
    )
    assert original is not None
    assert isinstance(original.operation.command, PluginManagementCommandV1)
    forged_command = replace(
        original.operation.command,
        mutation=replace(
            original.operation.command.mutation,
            idempotency_key="test:wrong-handoff-key",
        ),
    )
    forged_event = PluginManagementOperationEventV1.accepted(
        journal_revision=original.operation.journal_revision,
        command=forged_command,
    )

    class ForgedManagementRead:
        def operation(self, operation_id: str, *, correlation_id: str):
            assert operation_id == forged_command.operation_id
            return PluginManagementApplicationResultV1(
                correlation_id=correlation_id, operation=forged_event
            )

    forged = PluginOperationExplanationProjector(
        package_operations=PackageLifecycleJournal(lifecycle_path),
        management_commands=ForgedManagementRead(),
        handoffs=PackageRetentionHandoffJournal(
            lifecycle_path.parent / "handoff.jsonl"
        ),
    ).explain_operation(install_id, correlation_id="test:forged-handoff-explain")
    assert forged.join_status == "same_identity"
    assert forged.handoff_evidence == "identity_conflict"
    assert "package_product_handoff" in forged.evidence_gaps
    assert (
        tuple(sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*")))
        == before_explain
    )
    explained_stdout = StringIO()
    assert (
        asyncio.run(
            run_cli(
                ["--explain-plugin-operation", install_id],
                cwd=workspace,
                stdin=StringIO(),
                stdout=explained_stdout,
                stderr=stderr,
            )
        )
        == 0
    ), stderr.getvalue()
    public_explanation = json.loads(explained_stdout.getvalue())
    assert public_explanation["handoffEvidence"] == "settled"
    assert public_explanation["joinStatus"] == "same_identity"
    assert "package_product_handoff" not in public_explanation["evidenceGaps"]
    assert str(tmp_path) not in explained_stdout.getvalue()
    sdk_explanation = open_coding_plugin_management_read_client(
        workspace
    ).explain_operation(install_id, correlation_id="test:sdk-installed-package-explain")
    assert sdk_explanation["handoffEvidence"] == "settled"
    assert sdk_explanation["joinStatus"] == "same_identity"
    assert sdk_explanation["snapshotStatus"] == "partial_evidence"
    assert sdk_explanation["correlationId"] == "test:sdk-installed-package-explain"
    assert str(tmp_path) not in json.dumps(sdk_explanation)
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import PromptIntent

    ui_explanation = asyncio.run(
        build_coding_ui_controller(
            session=object(), plugin_workspace=workspace
        ).dispatch(PromptIntent(text=f"/plugins explain {install_id}"))
    )
    assert ui_explanation.error_message is None
    assert "Package: committed / committed" in (ui_explanation.status_message or "")
    assert "Handoff: settled" in (ui_explanation.status_message or "")
    assert str(tmp_path) not in (ui_explanation.status_message or "")
    assert (
        tuple(sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*")))
        == before_explain
    )
    enabled_output = StringIO()
    assert (
        asyncio.run(
            run_cli(
                ["--enable-plugin", "reviewpack"],
                cwd=workspace,
                stdin=StringIO(),
                stdout=enabled_output,
                stderr=stderr,
            )
        )
        == 0
    ), stderr.getvalue()
    listed_output = StringIO()
    assert (
        asyncio.run(
            run_cli(
                ["--list-plugins", "--list-plugins-format", "json"],
                cwd=workspace,
                stdin=StringIO(),
                stdout=listed_output,
                stderr=stderr,
            )
        )
        == 0
    ), stderr.getvalue()
    listed = json.loads(listed_output.getvalue())
    assert (
        next(item for item in listed if item["name"] == "reviewpack")["desiredState"]
        == "installed_enabled"
    )
    skills_output = StringIO()
    assert (
        asyncio.run(
            run_cli(
                ["--list-skills", "--list-skills-format", "json"],
                cwd=workspace,
                stdin=StringIO(),
                stdout=skills_output,
                stderr=stderr,
            )
        )
        == 0
    ), stderr.getvalue()
    assert any(
        item["name"] == "review" and item["source_kind"] == "external_package"
        for item in json.loads(skills_output.getvalue())
    )
    lease_path = (
        resolve_coding_package_epoch_layout(layout).control_root
        / "runtime-leases.jsonl"
    )
    lease_records = [json.loads(line) for line in lease_path.read_text().splitlines()]
    registered = {
        item["lease"]["leaseId"]
        for item in lease_records
        if item["kind"] == "registered"
    }
    released = {
        item["lease"]["leaseId"] for item in lease_records if item["kind"] == "released"
    }
    assert registered == released
    update_source = tmp_path / "reviewpack-2-py3-none-any.whl"
    update_source.write_bytes(_data_wheel(version="2"))
    assert (
        asyncio.run(
            run_cli(
                ["--update-package", str(update_source), "--package-scope", "project"],
                cwd=workspace,
                stdin=StringIO(),
                stdout=StringIO(),
                stderr=stderr,
            )
        )
        == 0
    ), stderr.getvalue()
    listed = list_plugin_records(
        build_coding_plugin_management_cli_read_binding(workspace, settings)
    )
    current = next(item for item in listed if item["name"] == "reviewpack")
    assert (current["version"], current["desiredState"]) == ("2", "installed_enabled")
    assert current["management"]["retirementStates"]
    owner = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version="0.1.0",
        runtime_protocol_epoch=2,
    )
    try:
        factory = owner.runtime_owner.product_owner.factory_for_session(
            session_id="updated-skill", cwd=workspace, runtime_id="updated-skill"
        )
        runtime = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id="updated-skill", cwd=str(workspace)
            )
        )
        try:
            runtime.activate()
            selected = runtime.capture_selected_plugin_manifest_for(
                "reviewpack", max_files=16, max_total_bytes=2 * 1024 * 1024
            )
            assert selected.manifest.version == "2"
            assert len(selected.verified_data_only_declarations()) == 1
            with pytest.raises(WorkerPackageCandidateError) as worker_refusal:
                verify_product_selected_worker_candidate(
                    selected,
                    contribution_id="review",
                    native_platform="linux-x86_64",
                )
            assert worker_refusal.value.code == "worker_candidate_topology_unsupported"
        finally:
            runtime.dispose_runtime()
    finally:
        owner.close()
    assert (
        asyncio.run(
            run_cli(
                ["--disable-plugin", "reviewpack"],
                cwd=workspace,
                stdin=StringIO(),
                stdout=StringIO(),
                stderr=stderr,
            )
        )
        == 0
    ), stderr.getvalue()
    assert (
        asyncio.run(
            run_cli(
                ["--uninstall-package", "reviewpack", "--package-scope", "project"],
                cwd=workspace,
                stdin=StringIO(),
                stdout=StringIO(),
                stderr=stderr,
            )
        )
        == 0
    ), stderr.getvalue()
    listing = list_plugin_records(
        build_coding_plugin_management_cli_read_binding(workspace, settings)
    )
    assert (
        next(item for item in listing if item["name"] == "reviewpack")["desiredState"]
        == "absent"
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_external_data_skill_enters_fenced_session_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class PreparedAdapter:
        api = "external-data-skill-product-test"

        def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
            return PreparedModelRequest.from_provider_request(
                request,
                payload={
                    "system": request.context.system_prompt,
                    "messages": [
                        serialize_message(message)
                        for message in request.context.messages
                    ],
                    "model": request.model.id,
                },
            )

        async def invoke_prepared_raw(
            self, request: ProviderRequest, prepared: PreparedModelRequest
        ) -> AsyncIterator[dict[str, object]]:
            del request
            prepared.payload_for_transport()
            yield {"type": "response_start", "response_id": "external-skill"}
            yield {"type": "text_delta", "text": "reviewed"}
            yield {"type": "stop_reason", "stop_reason": "stop"}
            yield {"type": "response_done"}

        async def invoke_raw(
            self, request: ProviderRequest
        ) -> AsyncIterator[dict[str, object]]:
            prepared = self.prepare_request(request)
            async for part in self.invoke_prepared_raw(request, prepared):
                yield part

    registry = get_default_api_registry()
    registry.register_api_adapter(PreparedAdapter(), source_id=PreparedAdapter.api)

    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout,
        settings,
        workspace=workspace,
        namespace_id="e" * 64,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    source = tmp_path / "reviewpack-1-py3-none-any.whl"
    source.write_bytes(_data_wheel())
    for args in (
        ("--install-package", str(source), "--package-scope", "project"),
        ("--enable-plugin", "reviewpack"),
    ):
        stderr = StringIO()
        assert (
            asyncio.run(
                run_cli(
                    list(args),
                    cwd=workspace,
                    stdin=StringIO(),
                    stdout=StringIO(),
                    stderr=stderr,
                )
            )
            == 0
        ), stderr.getvalue()
    native_skill = workspace / "skills" / "local-review" / "SKILL.md"
    native_skill.parent.mkdir(parents=True)
    native_skill.write_text(
        "---\nname: local-review\ndescription: Workspace review\n---\n# Local review\n",
        encoding="utf-8",
    )
    preview_files_before = tuple(
        sorted(
            (
                str(path.relative_to(tmp_path)),
                path.read_bytes(),
                path.stat().st_mtime_ns,
            )
            for path in tmp_path.rglob("*")
            if path.is_file()
        )
    )
    lifecycle_path = (
        resolve_coding_package_epoch_layout(layout).control_root
        / "product-state"
        / "lifecycle.jsonl"
    )
    install_ids = {
        document["request"]["operationId"]
        for line in lifecycle_path.read_bytes().splitlines()
        if (document := json.loads(line))["request"]["requestedPluginId"]
        == "reviewpack"
        and document["request"]["action"] == "install"
    }
    assert len(install_ids) == 1
    [install_id] = install_ids
    preview_entries_before = tuple(
        sorted(
            (str(path.relative_to(tmp_path)), stat.S_IFMT(path.lstat().st_mode))
            for path in tmp_path.rglob("*")
        )
    )
    with CodingFencedProductReadOnlyPreviewOwner.open(layout) as preview_owner:
        preview = preview_owner.preview_current_data_resources(
            workspace=workspace, composition_set_id="coding-standard"
        )
        minimal_preview = preview_owner.preview_current_data_resources(
            workspace=workspace, composition_set_id="coding-minimal"
        )
    preview_stdout = StringIO()
    preview_stderr = StringIO()
    assert (
        asyncio.run(
            run_cli(
                ["--preview-current-plugins"],
                cwd=workspace,
                stdin=StringIO(),
                stdout=preview_stdout,
                stderr=preview_stderr,
            )
        )
        == 0
    ), preview_stderr.getvalue()
    cli_preview = json.loads(preview_stdout.getvalue())
    assert cli_preview["correlationId"] == "cli:preview-current-plugins"
    assert cli_preview["snapshotStatus"] == "partial_evidence"
    assert "reviewpack" in cli_preview["compiledPluginIds"]
    assert str(tmp_path) not in preview_stdout.getvalue()
    assert preview_files_before == tuple(
        sorted(
            (
                str(path.relative_to(tmp_path)),
                path.read_bytes(),
                path.stat().st_mtime_ns,
            )
            for path in tmp_path.rglob("*")
            if path.is_file()
        )
    )
    assert preview_entries_before == tuple(
        sorted(
            (str(path.relative_to(tmp_path)), stat.S_IFMT(path.lstat().st_mode))
            for path in tmp_path.rglob("*")
        )
    )
    assert preview.snapshot_status == "partial_evidence"
    assert preview.product_id == "coding"
    assert preview.scope_id == layout.scope_id
    assert "reviewpack" in preview.compiled_plugin_ids
    assert ("skill", "review", "external_package") in preview.catalog_resources
    assert any(
        kind == "skill" and name == "local-review"
        for kind, name, _ in preview.catalog_resources
    )
    assert "native_resource_sources" not in preview.evidence_gaps
    assert "embedded_resource_sources" not in preview.evidence_gaps
    assert "coding.lsp.default" in preview.requires_authorized_preflight
    sdk_preview = open_coding_plugin_management_read_client(workspace).preview_current(
        correlation_id="test:sdk-current-preview"
    )
    assert sdk_preview["snapshotStatus"] == "partial_evidence"
    assert sdk_preview["correlationId"] == "test:sdk-current-preview"
    assert "reviewpack" in sdk_preview["compiledPluginIds"]
    assert str(tmp_path) not in json.dumps(sdk_preview)
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import PromptIntent

    ui_result = asyncio.run(
        build_coding_ui_controller(
            session=object(), plugin_workspace=workspace
        ).dispatch(PromptIntent(text="/plugins"))
    )
    assert ui_result.error_message is None
    assert "reviewpack" in (ui_result.status_message or "")
    assert "skill:review" in (ui_result.status_message or "")
    assert "partial" in (ui_result.status_message or "")
    assert str(tmp_path) not in (ui_result.status_message or "")
    ui_list = asyncio.run(
        build_coding_ui_controller(
            session=object(), plugin_workspace=workspace
        ).dispatch(PromptIntent(text="/plugins list"))
    )
    assert ui_list.error_message is None
    assert "reviewpack: installed_enabled" in (ui_list.status_message or "")
    assert "Desired State revision" in (ui_list.status_message or "")
    assert str(tmp_path) not in (ui_list.status_message or "")
    assert preview_files_before == tuple(
        sorted(
            (
                str(path.relative_to(tmp_path)),
                path.read_bytes(),
                path.stat().st_mtime_ns,
            )
            for path in tmp_path.rglob("*")
            if path.is_file()
        )
    )
    assert minimal_preview.disposition == "blocked"
    assert minimal_preview.blocking_owner == "product_composition"
    assert minimal_preview.blocking_code == "coding_base_not_requested"
    assert "coding.lsp.default" not in minimal_preview.requires_authorized_preflight
    preview_json = json.dumps(preview.to_dict(), ensure_ascii=False)
    assert str(tmp_path) not in preview_json
    assert "# Review v1" not in preview_json
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=True
        )
    )
    services = create_services(settings_manager=settings)
    session = create_agent_session(
        session_manager=manager,
        model=Model(
            id="external-skill-model",
            name="External Skill Model",
            provider="test",
            endpoint="external-skill-test",
            api=PreparedAdapter.api,
            base_url="https://provider.test/v1",
            auth=Auth(kind="none"),
            capabilities=Capabilities(
                reasoning=True,
                input=("text",),
                context_window=128000,
                max_tokens=4096,
                output=("text",),
                stream=True,
                tool_use=True,
            ),
        ),
        services=services,
        composition_set="coding-standard",
    )
    try:
        assert session.resource_bundle is not None
        rpc_files_before = tuple(
            sorted(
                (
                    str(path.relative_to(tmp_path)),
                    path.read_bytes(),
                    path.stat().st_mtime_ns,
                )
                for path in tmp_path.rglob("*")
                if path.is_file()
            )
        )

        class CurrentSessionRuntime:
            def get_current_session(self):  # type: ignore[no-untyped-def]
                return session

        fixed_preview_second = int(time.time())
        monkeypatch.setattr(
            "loushang.coding.package_product_preview.time",
            SimpleNamespace(
                time=lambda: fixed_preview_second,
                time_ns=lambda: fixed_preview_second * 1_000_000_000,
            ),
        )
        rpc_stdout = StringIO()
        rpc_host = RpcHost(
            runtime=CurrentSessionRuntime(),
            stdin=StringIO(),
            stdout=rpc_stdout,
            plugin_preview_factory=bind_coding_current_preview_query,
            plugin_explanation_factory=bind_coding_plugin_operation_explanation_query,
        )
        try:
            assert (
                asyncio.run(
                    rpc_host.submit_input(
                        json.dumps(
                            {
                                "id": "rpc-preview-1",
                                "type": "preview_current_plugins",
                                "productId": "coding",
                                "scopeId": layout.scope_id,
                                "compositionSetId": "coding-standard",
                            }
                        )
                    )
                )
                == 0
            )
            assert (
                asyncio.run(
                    rpc_host.submit_input(
                        json.dumps(
                            {
                                "id": "rpc-explain-1",
                                "type": "explain_plugin_operation",
                                "productId": "coding",
                                "scopeId": layout.scope_id,
                                "operationId": install_id,
                            }
                        )
                    )
                )
                == 0
            )
        finally:
            asyncio.run(rpc_host.stop())
        rpc_messages = [json.loads(line) for line in rpc_stdout.getvalue().splitlines()]
        [rpc_response] = [
            item
            for item in rpc_messages
            if item.get("command") == "preview_current_plugins"
        ]
        assert rpc_response["success"] is True
        assert rpc_response["data"]["snapshotStatus"] == "partial_evidence"
        assert "reviewpack" in rpc_response["data"]["compiledPluginIds"]
        [explanation_response] = [
            item
            for item in rpc_messages
            if item.get("command") == "explain_plugin_operation"
        ]
        assert explanation_response["success"] is True
        assert explanation_response["data"]["handoffEvidence"] == "settled"
        assert explanation_response["data"]["joinStatus"] == "same_identity"
        sdk_client = open_coding_plugin_management_read_client(workspace)
        sdk_rpc_preview = sdk_client.preview_current(
            correlation_id="test:conformance-preview"
        )
        sdk_rpc_explanation = sdk_client.explain_operation(
            install_id, correlation_id="test:conformance-explanation"
        )
        cli_explanation_stdout = StringIO()
        assert (
            asyncio.run(
                run_cli(
                    ["--explain-plugin-operation", install_id],
                    cwd=workspace,
                    stdin=StringIO(),
                    stdout=cli_explanation_stdout,
                    stderr=StringIO(),
                )
            )
            == 0
        )
        cli_explanation = json.loads(cli_explanation_stdout.getvalue())

        def without_observation_identity(value: object) -> object:
            if isinstance(value, dict):
                return {
                    key: without_observation_identity(item)
                    for key, item in value.items()
                    if key not in {"correlationId", "observedAtUnixNs"}
                }
            if isinstance(value, list):
                return [without_observation_identity(item) for item in value]
            return value

        assert without_observation_identity(rpc_response["data"]) == (
            without_observation_identity(sdk_rpc_preview)
        )
        assert (
            without_observation_identity(explanation_response["data"])
            == (without_observation_identity(sdk_rpc_explanation))
            == without_observation_identity(cli_explanation)
        )
        assert str(tmp_path) not in rpc_stdout.getvalue()
        assert rpc_files_before == tuple(
            sorted(
                (
                    str(path.relative_to(tmp_path)),
                    path.read_bytes(),
                    path.stat().st_mtime_ns,
                )
                for path in tmp_path.rglob("*")
                if path.is_file()
            )
        )
        assert {
            ("skill", item.name, item.source_kind)
            for item in session.resource_bundle.skills
            if item.enabled
        } == {item for item in preview.catalog_resources if item[0] == "skill"}
        review = next(
            item for item in session.resource_bundle.skills if item.name == "review"
        )
        assert review.source_kind == "external_package"
        inputs = session._capability_composition_inputs
        assert inputs is not None
        assert "reviewpack" in {
            item.plugin_id for item in inputs.product_composition.resource_admissions
        }

        async def inspect_skill() -> None:
            await session.prepare_model_call_runtime()
            preflight = await session._preflight_user_input_async("/skill:review")
            assert "# Review v1" in preflight.text
            [loaded] = preflight.loaded_skills
            assert loaded.summary.source_kind == "external_package"
            assert loaded.receipt.content_digest == (
                loaded.summary.expected_content_digest
            )

        asyncio.run(inspect_skill())
        asyncio.run(session.prompt("/skill:review Review this change"))
        snapshots = [
            entry.payload
            for entry in manager.get_entries()
            if entry.kind == "model.input.prepared"
        ]
        assert len(snapshots) == 1, [entry.kind for entry in manager.get_entries()]
        rebuilt = manager.rebuild_model_input(snapshots[0].snapshot_id)
        assert "# Review v1" in json.dumps(rebuilt.logical_input, ensure_ascii=False)
        old_revision = review.revision_ref
        update_source = tmp_path / "reviewpack-2-py3-none-any.whl"
        update_source.write_bytes(_data_wheel(version="2"))
        stderr = StringIO()
        assert (
            asyncio.run(
                run_cli(
                    [
                        "--update-package",
                        str(update_source),
                        "--package-scope",
                        "project",
                    ],
                    cwd=workspace,
                    stdin=StringIO(),
                    stdout=StringIO(),
                    stderr=stderr,
                )
            )
            == 0
        ), stderr.getvalue()
        assert review.revision_ref == old_revision
        next_manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "next-sessions",
                cwd=str(workspace),
                persist=False,
            )
        )
        next_session = create_agent_session(
            session_manager=next_manager,
            model=Model(
                id="external-skill-model",
                name="External Skill Model",
                provider="test",
                endpoint="anthropic-messages",
                capabilities=Capabilities(
                    reasoning=True,
                    input=("text",),
                    context_window=128000,
                    max_tokens=4096,
                ),
            ),
            services=services,
            composition_set="coding-standard",
        )
        try:
            assert next_session.resource_bundle is not None
            next_review = next(
                item
                for item in next_session.resource_bundle.skills
                if item.name == "review"
            )
            assert next_review.revision_ref != old_revision

            async def inspect_updated_skill() -> None:
                await next_session.prepare_model_call_runtime()
                preflight = await next_session._preflight_user_input_async(
                    "/skill:review"
                )
                assert "# Review v2" in preflight.text

            asyncio.run(inspect_updated_skill())
        finally:
            asyncio.run(next_session.dispose())
        resource_only_manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "resource-only-sessions",
                cwd=str(workspace),
                persist=False,
            )
        )
        resource_only = create_agent_session(
            session_manager=resource_only_manager,
            model=Model(
                id="external-skill-model",
                name="External Skill Model",
                provider="test",
                endpoint="anthropic-messages",
                capabilities=Capabilities(
                    reasoning=True,
                    input=("text",),
                    context_window=128000,
                    max_tokens=4096,
                ),
            ),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(
                        capabilities={
                            "coding.lsp": "disabled",
                            "coding.arch": "disabled",
                        }
                    )
                )
            ),
            composition_set="coding-standard",
        )
        try:
            assert any(
                item.name == "review" and item.source_kind == "external_package"
                for item in resource_only.resource_bundle.skills
            )
        finally:
            asyncio.run(resource_only.dispose())
        settings.set_disabled_skills(("review",), scope="project")
        disabled_preview_files_before = tuple(
            sorted(
                (
                    str(path.relative_to(tmp_path)),
                    path.read_bytes(),
                    path.stat().st_mtime_ns,
                )
                for path in tmp_path.rglob("*")
                if path.is_file()
            )
        )
        disabled_stdout = StringIO()
        disabled_stderr = StringIO()
        assert (
            asyncio.run(
                run_cli(
                    ["--preview-current-plugins"],
                    cwd=workspace,
                    stdin=StringIO(),
                    stdout=disabled_stdout,
                    stderr=disabled_stderr,
                )
            )
            == 0
        ), disabled_stderr.getvalue()
        disabled_preview = json.loads(disabled_stdout.getvalue())
        assert disabled_preview["disabledSkillSettingsRevision"].startswith("sha256:")
        assert "disabled_skill_settings" not in disabled_preview["evidenceGaps"]
        assert not any(
            item["resourceKind"] == "skill" and item["name"] == "review"
            for item in disabled_preview["catalogResources"]
        )
        assert disabled_preview_files_before == tuple(
            sorted(
                (
                    str(path.relative_to(tmp_path)),
                    path.read_bytes(),
                    path.stat().st_mtime_ns,
                )
                for path in tmp_path.rglob("*")
                if path.is_file()
            )
        )
        disabled_manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "disabled-sessions",
                cwd=str(workspace),
                persist=False,
            )
        )
        disabled_session = create_agent_session(
            session_manager=disabled_manager,
            model=Model(
                id="disabled-skill-model",
                name="Disabled Skill Model",
                provider="test",
                endpoint="anthropic-messages",
                capabilities=Capabilities(
                    input=("text",),
                    output=("text",),
                    context_window=128000,
                    max_tokens=4096,
                ),
            ),
            services=services,
            composition_set="coding-standard",
        )
        try:
            assert disabled_session.resource_bundle is not None
            assert {
                ("skill", item.name, item.source_kind)
                for item in disabled_session.resource_bundle.skills
                if item.enabled
            } == {
                (item["resourceKind"], item["name"], item["sourceKind"])
                for item in disabled_preview["catalogResources"]
                if item["resourceKind"] == "skill"
            }
        finally:
            asyncio.run(disabled_session.dispose())
        settings_path = workspace / ".loushang" / "settings.json"
        settings_body = settings_path.read_bytes()
        redirected_settings = tmp_path / "redirected-settings.json"
        redirected_settings.write_bytes(settings_body)
        settings_path.unlink()
        settings_path.symlink_to(redirected_settings)
        symlink_files_before = tuple(
            sorted(
                (
                    str(path.relative_to(tmp_path)),
                    path.read_bytes(),
                    path.stat().st_mtime_ns,
                )
                for path in tmp_path.rglob("*")
                if path.is_file()
            )
        )
        rejected_stdout = StringIO()
        rejected_stderr = StringIO()
        assert (
            asyncio.run(
                run_cli(
                    ["--preview-current-plugins"],
                    cwd=workspace,
                    stdin=StringIO(),
                    stdout=rejected_stdout,
                    stderr=rejected_stderr,
                )
            )
            == 1
        )
        assert rejected_stdout.getvalue() == ""
        assert (
            rejected_stderr.getvalue() == "Error: plugin_preview_settings_unavailable\n"
        )
        assert symlink_files_before == tuple(
            sorted(
                (
                    str(path.relative_to(tmp_path)),
                    path.read_bytes(),
                    path.stat().st_mtime_ns,
                )
                for path in tmp_path.rglob("*")
                if path.is_file()
            )
        )
        settings_path.unlink()
        settings_path.write_bytes(settings_body)
    finally:
        asyncio.run(session.dispose())
        registry.unregister_api_adapters(PreparedAdapter.api)
    session_file = manager.get_session_file()
    assert session_file.is_file()
    resumed = asyncio.run(SessionManager.load(session_file))
    assert "# Review v1" in json.dumps(
        resumed.rebuild_model_input(snapshots[0].snapshot_id).logical_input,
        ensure_ascii=False,
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_external_data_prompt_reaches_persisted_model_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class PreparedAdapter:
        api = "external-data-prompt-product-test"

        def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
            return PreparedModelRequest.from_provider_request(
                request,
                payload={
                    "system": request.context.system_prompt,
                    "messages": [
                        serialize_message(message)
                        for message in request.context.messages
                    ],
                    "model": request.model.id,
                },
            )

        async def invoke_prepared_raw(
            self, request: ProviderRequest, prepared: PreparedModelRequest
        ) -> AsyncIterator[dict[str, object]]:
            del request
            prepared.payload_for_transport()
            yield {"type": "response_start", "response_id": "external-prompt"}
            yield {"type": "text_delta", "text": "reviewed"}
            yield {"type": "stop_reason", "stop_reason": "stop"}
            yield {"type": "response_done"}

        async def invoke_raw(
            self, request: ProviderRequest
        ) -> AsyncIterator[dict[str, object]]:
            prepared = self.prepare_request(request)
            async for part in self.invoke_prepared_raw(request, prepared):
                yield part

    workspace, layout, settings = _p2_workspace(tmp_path, monkeypatch)
    wheel = tmp_path / "promptpack-1-py3-none-any.whl"
    wheel.write_bytes(
        build_coding_data_prompt_wheel(
            plugin_id="promptpack",
            version="1",
            contribution_id="review-prompt",
            prompt_name="review",
            prompt_document=b"# External review\nCheck the change carefully.\n",
        )
    )
    skill_wheel = tmp_path / "reviewpack-1-py3-none-any.whl"
    skill_wheel.write_bytes(_data_wheel(skill_name="quality"))
    for args in (
        ("--install-package", str(wheel), "--package-scope", "project"),
        ("--install-package", str(skill_wheel), "--package-scope", "project"),
        ("--enable-plugin", "promptpack"),
        ("--enable-plugin", "reviewpack"),
    ):
        stderr = StringIO()
        assert (
            asyncio.run(
                run_cli(
                    list(args),
                    cwd=workspace,
                    stdin=StringIO(),
                    stdout=StringIO(),
                    stderr=stderr,
                )
            )
            == 0
        ), stderr.getvalue()

    with CodingFencedProductReadOnlyPreviewOwner.open(layout) as preview_owner:
        preview = preview_owner.preview_current_data_resources(workspace=workspace)
    assert ("prompt", "review", "external_package") in preview.catalog_resources
    assert ("skill", "quality", "external_package") in preview.catalog_resources

    registry = get_default_api_registry()
    registry.register_api_adapter(PreparedAdapter(), source_id=PreparedAdapter.api)
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=True
        )
    )
    session = create_agent_session(
        session_manager=manager,
        model=Model(
            id="external-prompt-model",
            name="External Prompt Model",
            provider="test",
            endpoint="external-prompt-test",
            api=PreparedAdapter.api,
            base_url="https://provider.test/v1",
            auth=Auth(kind="none"),
            capabilities=Capabilities(
                input=("text",),
                output=("text",),
                context_window=128000,
                stream=True,
                tool_use=True,
            ),
        ),
        services=create_services(settings_manager=settings),
        composition_set="coding-standard",
    )
    try:
        assert session.resource_bundle is not None
        assert any(
            item.name == "review" and item.source_kind == "external_package"
            for item in session.resource_bundle.prompts
        )
        assert any(
            item.name == "quality" and item.source_kind == "external_package"
            for item in session.resource_bundle.skills
        )
        asyncio.run(session.prompt("/review Review this change"))
        snapshots = [
            entry.payload
            for entry in manager.get_entries()
            if entry.kind == "model.input.prepared"
        ]
        assert len(snapshots) == 1
        snapshot_id = snapshots[0].snapshot_id
        assert "# External review" in json.dumps(
            manager.rebuild_model_input(snapshot_id).logical_input,
            ensure_ascii=False,
        )
    finally:
        asyncio.run(session.dispose())
        registry.unregister_api_adapters(PreparedAdapter.api)
    resumed = asyncio.run(SessionManager.load(manager.get_session_file()))
    assert "# External review" in json.dumps(
        resumed.rebuild_model_input(snapshot_id).logical_input,
        ensure_ascii=False,
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_two_external_prompts_conflict_until_one_is_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, layout, settings = _p2_workspace(tmp_path, monkeypatch)
    for plugin_id in ("promptpack", "auditpack"):
        wheel = tmp_path / f"{plugin_id}-1-py3-none-any.whl"
        wheel.write_bytes(
            build_coding_data_prompt_wheel(
                plugin_id=plugin_id,
                version="1",
                contribution_id="review-prompt",
                prompt_name="review",
                prompt_document=f"# Review by {plugin_id}\n".encode(),
            )
        )
        for args in (
            ("--install-package", str(wheel), "--package-scope", "project"),
            ("--enable-plugin", plugin_id),
        ):
            code, _stdout, stderr = _p2_cli(workspace, *args)
            assert code == 0, stderr
    with pytest.raises(ProductCompositionError) as collision:
        _p2_session(workspace, settings, tmp_path / "conflict-sessions")
    assert collision.value.code == "duplicate_owner_contribution_identity"
    assert len(set(collision.value.admission_fingerprints)) == 2
    assert _p2_list_plugins(workspace)["auditpack"]["desiredState"] == (
        "installed_enabled"
    )
    code, _stdout, stderr = _p2_cli(workspace, "--disable-plugin", "auditpack")
    assert code == 0, stderr
    with CodingFencedProductReadOnlyPreviewOwner.open(layout) as preview_owner:
        recovered_preview = preview_owner.preview_current_data_resources(
            workspace=workspace, composition_set_id="coding-standard"
        )
    assert recovered_preview.disposition == "projected"
    assert (
        "prompt",
        "review",
        "external_package",
    ) in recovered_preview.catalog_resources
    assert "auditpack" not in recovered_preview.compiled_plugin_ids
    remaining = _p2_session(workspace, settings, tmp_path / "resolved-sessions")
    try:
        assert remaining.resource_bundle is not None
        assert [
            item.name
            for item in remaining.resource_bundle.prompts
            if item.name == "review" and item.source_kind == "external_package"
        ] == ["review"]

        async def inspect() -> None:
            await remaining.prepare_model_call_runtime()
            expanded = await remaining._preflight_user_input_async("/review change")
            assert "# Review by promptpack" in expanded.text

        asyncio.run(inspect())
    finally:
        asyncio.run(remaining.dispose())


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
@pytest.mark.parametrize("kind", ["method", "theme"])
def test_unsupported_method_or_invalid_theme_wheel_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: Literal["method", "theme"],
) -> None:
    workspace, layout, _ = _p2_workspace(tmp_path, monkeypatch)
    plugin_id = f"{kind}pack"
    wheel = tmp_path / f"{plugin_id}-1-py3-none-any.whl"
    wheel.write_bytes(_unsupported_resource_wheel(kind=kind))
    code, _stdout, stderr = _p2_cli(
        workspace, "--install-package", str(wheel), "--package-scope", "project"
    )
    assert code == 1
    assert "package_plugin_contribution_rejected" in stderr
    assert _p2_installation(layout, workspace, plugin_id).selection.desired_state == (
        "absent"
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_external_theme_wheel_reaches_selected_catalog_and_visible_tui_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, layout, settings = _p2_workspace(tmp_path, monkeypatch)
    document = tmp_path / "dusk.json"
    document.write_bytes(
        (
            Path(__file__).resolve().parents[2]
            / "examples/plugins/coding_data_theme/themes/dusk.json"
        ).read_bytes()
    )
    entrypoint = Path(sys.executable).with_name("loushang-plugin")
    assert entrypoint.is_file()
    built = subprocess.run(
        (
            str(entrypoint),
            "build-coding-theme",
            str(document),
            "--plugin-id",
            "themepack",
            "--version",
            "1",
            "--output-dir",
            str(tmp_path),
        ),
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")
            + os.pathsep
            + os.environ.get("PYTHONPATH", ""),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    assert built.returncode == 0, built.stderr
    wheel = tmp_path / "themepack-1-py3-none-any.whl"
    assert json.loads(built.stdout) == {
        "artifactPath": str(wheel),
        "profile": "coding-data-theme-v1",
        "productAdmission": "not_checked",
        "productSelection": "not_checked",
        "productUse": "not_checked",
        "sha256": sha256(wheel.read_bytes()).hexdigest(),
    }
    for args in (
        ("--install-package", str(wheel), "--package-scope", "project"),
        ("--enable-plugin", "themepack"),
    ):
        code, _output, error = _p2_cli(workspace, *args)
        assert code == 0, error
    settings.set_theme("plugin:dusk", scope="project")
    with CodingFencedProductReadOnlyPreviewOwner.open(layout) as preview_owner:
        preview = preview_owner.preview_current_data_resources(workspace=workspace)
    assert ("theme", "dusk", "external_package") in preview.catalog_resources
    session = _p2_session(workspace, settings, tmp_path / "theme-sessions")
    try:
        assert session.resource_bundle is not None
        assert [
            theme.name
            for theme in session.resource_bundle.themes
            if theme.source_kind == "external_package"
        ] == ["dusk"]
        selection = select_coding_plugin_theme(
            settings.get_theme(), session.resource_bundle
        )
        assert selection.disposition == "selected"
        rendered = "\n".join(
            line.text
            for line in LoushangWelcomePanel(theme=selection.welcome_theme)
            .render(RenderConstraints(width=42, max_height=15))
            .lines
        )
        assert "\x1b[1;31m Loushang " in rendered

        class TtyStringIO(StringIO):
            def isatty(self) -> bool:
                return True

        observed: list[str] = []

        async def fake_screen_loop(**kwargs: object) -> int:
            app = kwargs["app"]
            observed.append(app.welcome_theme.resolve("welcome.title")["color"])
            return 0

        runtime = SimpleNamespace(
            get_current_session=lambda: session,
            current_session=session,
            session_dir=tmp_path / "theme-sessions",
        )
        reference = SimpleNamespace(release=lambda: None)
        composition = SimpleNamespace(hub=SimpleNamespace(reference=lambda: reference))
        monkeypatch.setattr(
            coding_tui_mode,
            "get_coding_configured_continuity_composition",
            lambda _runtime: composition,
        )
        assert (
            asyncio.run(
                coding_tui_mode._run_screen_interactive_tui(
                    runtime=runtime,
                    session=session,
                    stdin=TtyStringIO(),
                    stdout=TtyStringIO(),
                    stderr=StringIO(),
                    verbose=False,
                    screen_run_profile=coding_tui_mode.CODING_SCREEN_RUN_PROFILE,
                    prepared_screen_runner=fake_screen_loop,
                )
            )
            == 0
        )
        assert observed == ["red"]
    finally:
        asyncio.run(session.dispose())
    code, _output, error = _p2_cli(workspace, "--disable-plugin", "themepack")
    assert code == 0, error
    with CodingFencedProductReadOnlyPreviewOwner.open(layout) as preview_owner:
        disabled_preview = preview_owner.preview_current_data_resources(
            workspace=workspace
        )
    assert ("theme", "dusk", "external_package") not in (
        disabled_preview.catalog_resources
    )
    next_session = _p2_session(
        workspace, settings, tmp_path / "disabled-theme-sessions"
    )
    try:
        assert next_session.resource_bundle is not None
        selection = select_coding_plugin_theme(
            settings.get_theme(), next_session.resource_bundle
        )
        assert selection.disposition == "unavailable"
        assert selection.welcome_theme.resolve("welcome.title")["color"] == "cyan"
    finally:
        asyncio.run(next_session.dispose())


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_duplicate_external_themes_block_session_until_one_is_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, layout, settings = _p2_workspace(tmp_path, monkeypatch)
    for plugin_id in ("themepack", "nightpack"):
        wheel = tmp_path / f"{plugin_id}-1-py3-none-any.whl"
        wheel.write_bytes(
            build_coding_data_theme_wheel(
                plugin_id=plugin_id,
                version="1",
                contribution_id="dusk-theme",
                theme_name="dusk",
                theme_document=json.dumps(
                    {
                        "schemaVersion": 1,
                        "tokens": {
                            "welcome.title": {
                                "color": "red" if plugin_id == "themepack" else "blue"
                            }
                        },
                    }
                ).encode(),
            )
        )
        for args in (
            ("--install-package", str(wheel), "--package-scope", "project"),
            ("--enable-plugin", plugin_id),
        ):
            code, _output, error = _p2_cli(workspace, *args)
            assert code == 0, error
    settings.set_theme("plugin:dusk", scope="project")
    with CodingFencedProductReadOnlyPreviewOwner.open(layout) as preview_owner:
        blocked_preview = preview_owner.preview_current_data_resources(
            workspace=workspace
        )
    assert blocked_preview.disposition == "blocked"
    assert blocked_preview.blocking_code == "duplicate_owner_contribution_identity"
    with pytest.raises(ProductCompositionError) as collision:
        _p2_session(workspace, settings, tmp_path / "conflicting-theme-sessions")
    assert collision.value.code == "duplicate_owner_contribution_identity"
    code, _output, error = _p2_cli(workspace, "--disable-plugin", "nightpack")
    assert code == 0, error
    with CodingFencedProductReadOnlyPreviewOwner.open(layout) as preview_owner:
        resolved_preview = preview_owner.preview_current_data_resources(
            workspace=workspace
        )
    assert resolved_preview.disposition == "projected"
    assert ("theme", "dusk", "external_package") in (resolved_preview.catalog_resources)
    session = _p2_session(workspace, settings, tmp_path / "resolved-theme-sessions")
    try:
        assert session.resource_bundle is not None
        selected = select_coding_plugin_theme(
            settings.get_theme(), session.resource_bundle
        )
        assert selected.disposition == "selected"
        assert selected.welcome_theme.resolve("welcome.title")["color"] == "red"
    finally:
        asyncio.run(session.dispose())


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_cached_application_selection_refreshes_external_source_for_new_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout,
        settings,
        workspace=workspace,
        namespace_id="6" * 64,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    first_source = tmp_path / "reviewpack-1-py3-none-any.whl"
    first_source.write_bytes(_data_wheel())
    for args in (
        ("--install-package", str(first_source), "--package-scope", "project"),
        ("--enable-plugin", "reviewpack"),
    ):
        stderr = StringIO()
        assert (
            asyncio.run(
                run_cli(
                    list(args),
                    cwd=workspace,
                    stdin=StringIO(),
                    stdout=StringIO(),
                    stderr=stderr,
                )
            )
            == 0
        ), stderr.getvalue()
    selection = CodingFencedProductApplicationSelection()
    first_manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "first-sessions", cwd=str(workspace), persist=False
        )
    )
    first_factory = selection.factory_for_session(first_manager)
    assert first_factory is not None
    first_runtime = first_factory.create(
        PackageProductRuntimeRequestV1(
            product_id="coding",
            session_id=first_manager.get_header().conversation_id,
            cwd=str(workspace),
        )
    )
    try:
        first_runtime.activate()
        assert first_runtime.selected_external_data_plugin_ids() == ("reviewpack",)
        second_source = tmp_path / "reviewpack-2-py3-none-any.whl"
        second_source.write_bytes(_data_wheel(version="2"))
        stderr = StringIO()
        assert (
            asyncio.run(
                run_cli(
                    [
                        "--update-package",
                        str(second_source),
                        "--package-scope",
                        "project",
                    ],
                    cwd=workspace,
                    stdin=StringIO(),
                    stdout=StringIO(),
                    stderr=stderr,
                )
            )
            == 0
        ), stderr.getvalue()
        second_manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "second-sessions",
                cwd=str(workspace),
                persist=False,
            )
        )
        second_factory = selection.factory_for_session(second_manager)
        assert second_factory is not None
        second_runtime = second_factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding",
                session_id=second_manager.get_header().conversation_id,
                cwd=str(workspace),
            )
        )
        try:
            second_runtime.activate()
            assert second_runtime.selected_external_data_plugin_ids() == ("reviewpack",)
            selected = second_runtime.capture_selected_plugin_manifest_for(
                "reviewpack",
                max_files=16,
                max_total_bytes=1024 * 1024,
            )
            assert selected.manifest.version == "2"
        finally:
            second_runtime.dispose_runtime()
    finally:
        first_runtime.dispose_runtime()
        selection.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_fenced_cli_refuses_external_executable_and_invalid_wheels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout,
        settings,
        workspace=workspace,
        namespace_id="f" * 64,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    failed_operations: list[tuple[str, str]] = []
    for version_id, body, code in (
        (
            "3",
            _data_wheel(version="3", executable_member=True),
            "package_plugin_contribution_rejected",
        ),
        (
            "4",
            _data_wheel(version="4", actions_member=True),
            "package_plugin_contribution_rejected",
        ),
        ("5", _data_wheel(version="5", requires_dist=True), "package_closure_conflict"),
        ("6", b"not a wheel", "package_archive_malformed"),
        (
            "8",
            _data_wheel(version="8", manifest_bytes=b"[" * 1500 + b"0" + b"]" * 1500),
            "package_plugin_contribution_rejected",
        ),
        (
            "9",
            _data_wheel(version="9", managed_actions_reservation=True),
            "package_plugin_contribution_rejected",
        ),
        (
            "10",
            _data_wheel(version="10", skill_size=1024 * 1024 - 1),
            "package_plugin_contribution_rejected",
        ),
    ):
        source = tmp_path / f"reviewpack-{version_id}-py3-none-any.whl"
        source.write_bytes(body)
        stderr = StringIO()
        assert (
            asyncio.run(
                run_cli(
                    ["--install-package", str(source), "--package-scope", "project"],
                    cwd=workspace,
                    stdin=StringIO(),
                    stdout=StringIO(),
                    stderr=stderr,
                )
            )
            == 1
        )
        assert code in stderr.getvalue(), (version_id, stderr.getvalue())
        operation_id = (
            stderr.getvalue().split("(Package operation: ", 1)[1].split(")", 1)[0]
        )
        failed_operations.append((operation_id, code))
    before_explain = tuple(
        sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    )
    explained = explain_coding_fenced_package_operation(layout, failed_operations[0][0])
    assert explained.status == "observed"
    assert explained.failure_code == failed_operations[0][1]
    assert explained.disposition == "rejected"
    assert explained.snapshot_status == "partial_evidence"
    joined = PluginOperationExplanationProjector(
        package_operations=PackageLifecycleJournal(
            resolve_coding_package_epoch_layout(layout).control_root
            / "product-state"
            / "lifecycle.jsonl"
        ),
        management_commands=build_coding_fenced_product_management_cli_ports(
            layout
        ).commands,
        handoffs=PackageRetentionHandoffJournal(
            resolve_coding_package_epoch_layout(layout).control_root
            / "product-state"
            / "handoff.jsonl"
        ),
    ).explain_operation(
        failed_operations[0][0], correlation_id="test:rejected-package-explain"
    )
    assert joined.join_status == "package_only"
    assert joined.management_status == "unknown"
    assert joined.package.failure_code == failed_operations[0][1]
    assert joined.handoff_evidence == "absent"
    assert "package_product_handoff" in joined.evidence_gaps
    assert (
        tuple(sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*")))
        == before_explain
    )
    explained_stdout = StringIO()
    assert (
        asyncio.run(
            run_cli(
                ["--explain-plugin-operation", failed_operations[0][0]],
                cwd=workspace,
                stdin=StringIO(),
                stdout=explained_stdout,
                stderr=StringIO(),
            )
        )
        == 0
    )
    assert json.loads(explained_stdout.getvalue())["handoffEvidence"] == "absent"
    assert (
        tuple(sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*")))
        == before_explain
    )
    target = tmp_path / "reviewpack-real.whl"
    target.write_bytes(_data_wheel(version="7"))
    symlink = tmp_path / "reviewpack-7-py3-none-any.whl"
    symlink.symlink_to(target)
    stderr = StringIO()
    assert (
        asyncio.run(
            run_cli(
                ["--install-package", str(symlink), "--package-scope", "project"],
                cwd=workspace,
                stdin=StringIO(),
                stdout=StringIO(),
                stderr=stderr,
            )
        )
        == 1
    )
    assert "Source changed" in stderr.getvalue()
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=layout.scope_id,
        plugin_id="reviewpack",
    )
    owner = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    try:
        product = owner.runtime_owner.product_owner
        assert (
            product.desired_state.snapshot().installation(key).selection.desired_state
            == "absent"
        )
        lifecycle = PackageLifecycleJournal(product.state_root / "lifecycle.jsonl")
        for operation_id, code in failed_operations:
            status = lifecycle.status(operation_id)
            assert status is not None and status.failure is not None
            assert status.failure.code == code
        management_ids = {
            item.command.mutation.operation_id
            for item in product.management.operations()
            if isinstance(item, PluginManagementOperationEventV1)
        }
        assert not management_ids.intersection(
            operation_id for operation_id, _ in failed_operations
        )
    finally:
        owner.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_fenced_cli_list_preserves_pending_management_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout,
        settings,
        workspace=workspace,
        namespace_id="1" * 64,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    owner = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    try:
        product = owner.runtime_owner.product_owner
        snapshot = product.desired_state.snapshot()
        installation = next(
            item
            for item in snapshot.installations
            if item.installation_key.plugin_id == "coding.base"
        )
        operation = PluginManagementOperationEventV1.accepted(
            journal_revision=len(
                product.management.operation_journal_path.read_bytes().splitlines()
            )
            + 1,
            command=PluginManagementCommandV1(
                action="disable",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="test:pending-b-disable",
                    idempotency_key="test:pending-b-disable",
                    expected_inventory_revision=snapshot.inventory_revision,
                    installation_key=installation.installation_key,
                    desired_state="installed_disabled",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision="test",
                ),
            ),
        )
        path = product.management.operation_journal_path
        path.write_bytes(
            path.read_bytes()
            + (json.dumps(operation.to_dict(), sort_keys=True) + "\n").encode()
        )
        before_operations = path.read_bytes()
        before_desired = product.desired_state.path.read_bytes()
    finally:
        owner.close()
    stdout = StringIO()
    stderr = StringIO()
    assert (
        asyncio.run(
            run_cli(
                ["--list-plugins", "--list-plugins-format", "json"],
                cwd=workspace,
                stdin=StringIO(),
                stdout=stdout,
                stderr=stderr,
            )
        )
        == 0
    ), stderr.getvalue()
    assert path.read_bytes() == before_operations
    assert product.desired_state.path.read_bytes() == before_desired
    [base] = [
        item for item in json.loads(stdout.getvalue()) if item["name"] == "coding.base"
    ]
    assert any(
        item["status"] == "accepted" for item in base["management"]["operations"]
    )
    path.write_bytes(path.read_bytes() + b'{"partial":')
    before_operations = path.read_bytes()
    before_desired = product.desired_state.path.read_bytes()
    stderr = StringIO()
    assert (
        asyncio.run(
            run_cli(
                ["--list-plugins", "--list-plugins-format", "json"],
                cwd=workspace,
                stdin=StringIO(),
                stdout=StringIO(),
                stderr=stderr,
            )
        )
        == 1
    )
    assert path.read_bytes() == before_operations
    assert product.desired_state.path.read_bytes() == before_desired


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_fenced_cli_list_does_not_repair_partial_epoch_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, layout, settings = _p2_workspace(tmp_path, monkeypatch)
    control_root = resolve_coding_package_epoch_layout(layout).control_root

    def tree_snapshot() -> tuple[tuple[str, bytes | None], ...]:
        return tuple(
            sorted(
                (
                    str(path.relative_to(control_root)),
                    path.read_bytes() if path.is_file() else None,
                )
                for path in control_root.rglob("*")
            )
        )

    before_healthy = tree_snapshot()
    healthy_code, _stdout, healthy_stderr = _p2_cli(
        workspace, "--list-plugins", "--list-plugins-format", "json"
    )
    assert healthy_code == 0, healthy_stderr
    assert tree_snapshot() == before_healthy

    epoch_path = control_root / "epoch.jsonl"
    epoch_path.write_bytes(epoch_path.read_bytes() + b'{"partial":')
    before_partial = tree_snapshot()

    code, _stdout, _stderr = _p2_cli(
        workspace, "--list-plugins", "--list-plugins-format", "json"
    )

    assert code == 1
    assert tree_snapshot() == before_partial


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
@pytest.mark.parametrize("repair_mode", ("startup", "operator", "cli", "rpc", "tui"))
def test_external_update_recovers_interrupted_retention_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    repair_mode: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout,
        settings,
        workspace=workspace,
        namespace_id="2" * 64,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    initial = tmp_path / "reviewpack-1-py3-none-any.whl"
    initial.write_bytes(_data_wheel())
    for args in (
        ("--install-package", str(initial), "--package-scope", "project"),
        ("--enable-plugin", "reviewpack"),
    ):
        stderr = StringIO()
        assert (
            asyncio.run(
                run_cli(
                    list(args),
                    cwd=workspace,
                    stdin=StringIO(),
                    stdout=StringIO(),
                    stderr=stderr,
                )
            )
            == 0
        ), stderr.getvalue()
    replacement = tmp_path / "reviewpack-2-py3-none-any.whl"
    replacement.write_bytes(_data_wheel(version="2"))
    captured = admit_coding_external_data_wheel(layout, source=replacement)
    operation_id = "test:interrupted-external-update"
    original_settle = PackageProductRetentionSettlementOwner.settle
    interrupted = False

    def interrupt_once(owner, receipt, *, desired_receipt):  # type: ignore[no-untyped-def]
        nonlocal interrupted
        if receipt.request.operation_id == operation_id and not interrupted:
            interrupted = True
            raise OSError("injected retention settlement interruption")
        return original_settle(owner, receipt, desired_receipt=desired_receipt)

    owner = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    try:
        product = owner.runtime_owner.product_owner
        runtime_id = "interrupted-update-runtime"
        factory = product.factory_for_session(
            session_id=runtime_id, cwd=workspace, runtime_id=runtime_id
        )
        runtime = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id=runtime_id, cwd=str(workspace)
            )
        )
        try:
            runtime.activate()
            monkeypatch.setattr(
                PackageProductRetentionSettlementOwner, "settle", interrupt_once
            )
            with pytest.raises(RuntimeError, match="handoff"):
                runtime.lifecycle.route(
                    PackageProductLifecycleIntentV1(
                        operation_id=operation_id,
                        action="update",
                        source=str(
                            owner.epoch_runtime.control_root
                            / "product-sources"
                            / captured.wheel_filename
                        ),
                        scope="project",
                    ),
                    entrypoint="cli",
                )
            handoff = PackageRetentionHandoffJournal(
                product.state_root / "handoff.jsonl"
            )
            matching = [
                item.receipt
                for item in handoff.records()
                if item.receipt is not None
                and item.receipt.request.operation_id == operation_id
            ]
            assert matching[-1].state == "desired_committed"
            pending_explanation = bind_coding_plugin_operation_explanation_query(
                workspace
            ).explain_plugin_operation(
                PluginOperationExplanationRequestV1(
                    correlation_id="test:pending-update-explain",
                    product_id="coding",
                    scope_id=layout.scope_id,
                    operation_id=operation_id,
                )
            )
            assert pending_explanation.management_action == "update"
            assert pending_explanation.handoff_evidence == "incomplete"
            assert "package_product_handoff" in pending_explanation.evidence_gaps
        finally:
            runtime.dispose_runtime()
    finally:
        owner.close()
    monkeypatch.setattr(
        PackageProductRetentionSettlementOwner, "settle", original_settle
    )
    if repair_mode == "operator":
        handoff_path = product.state_root / "handoff.jsonl"
        pending_handoff = handoff_path.read_bytes()
        with pytest.raises(PackageProductActivationError) as wrong_operation:
            open_coding_package_repair_client(workspace).perform(
                "repair-handoff", f"{operation_id}:other"
            )
        assert wrong_operation.value.code == "package_product_exact_recovery_incomplete"
        assert handoff_path.read_bytes() == pending_handoff
        repaired = open_coding_package_repair_client(workspace).perform(
            "repair-handoff", operation_id
        )
        assert repaired.committed
        assert repaired.phase == "committed"
        assert repaired.failure_code is None
    elif repair_mode == "cli":
        assert (
            package_repair_main(
                ["--workspace", str(workspace), "repair-handoff", operation_id]
            )
            == 0
        )
        assert json.loads(capsys.readouterr().out)["operationId"] == operation_id
    elif repair_mode == "rpc":
        from loushang.coding.package_product_repair_rpc import (
            bind_coding_package_repair_rpc_client,
        )
        from loushang.harness.host.rpc.commands.package_repair import (
            RpcPackageRepairCommands,
        )
        from loushang.harness.host.rpc.output import RpcOutput

        stdout = StringIO()
        commands = RpcPackageRepairCommands(
            get_cwd=lambda: str(workspace),
            bind_client=bind_coding_package_repair_rpc_client,
            output=RpcOutput(stdout),
        )
        asyncio.run(
            commands.repair_plugin_package(
                "test:handoff-rpc",
                {
                    "productId": "coding",
                    "scopeId": layout.scope_id,
                    "action": "repair-handoff",
                    "operationId": operation_id,
                },
            )
        )
        response = json.loads(stdout.getvalue())
        assert response["data"]["operationId"] == operation_id
        assert response["data"]["disposition"] == "committed"
    elif repair_mode == "tui":
        from loushang.coding.package_product_repair_ui import (
            execute_coding_package_repair_ui_command,
        )

        result = execute_coding_package_repair_ui_command(
            workspace,
            f"/plugins repair-package repair-handoff {operation_id}",
        )
        assert result.error_message is None
        assert "new Session required" in (result.status_message or "")
    reopened = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    try:
        product = reopened.runtime_owner.product_owner
        runtime_id = "recovered-update-runtime"
        factory = product.factory_for_session(
            session_id=runtime_id, cwd=workspace, runtime_id=runtime_id
        )
        runtime = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id=runtime_id, cwd=str(workspace)
            )
        )
        try:
            runtime.activate()
            selected = runtime.capture_selected_plugin_manifest_for(
                "reviewpack", max_files=16, max_total_bytes=1024 * 1024
            )
            assert selected.manifest.version == "2"
        finally:
            runtime.dispose_runtime()
        handoff = PackageRetentionHandoffJournal(product.state_root / "handoff.jsonl")
        matching = [
            item.receipt
            for item in handoff.records()
            if item.receipt is not None
            and item.receipt.request.operation_id == operation_id
        ]
        assert matching[-1].state == "settled"
    finally:
        reopened.close()
    before_explain = tuple(
        sorted(
            (str(path.relative_to(tmp_path)), path.read_bytes())
            for path in tmp_path.rglob("*")
            if path.is_file()
        )
    )
    completed_explanation = bind_coding_plugin_operation_explanation_query(
        workspace
    ).explain_plugin_operation(
        PluginOperationExplanationRequestV1(
            correlation_id="test:settled-update-explain",
            product_id="coding",
            scope_id=layout.scope_id,
            operation_id=operation_id,
        )
    )
    assert completed_explanation.management_action == "update"
    assert completed_explanation.management_disposition in {
        "succeeded",
        "restart_required",
    }
    assert completed_explanation.handoff_evidence == "settled"
    assert "package_product_handoff" not in completed_explanation.evidence_gaps
    assert (
        tuple(
            sorted(
                (str(path.relative_to(tmp_path)), path.read_bytes())
                for path in tmp_path.rglob("*")
                if path.is_file()
            )
        )
        == before_explain
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_stale_interrupted_update_cannot_replace_newer_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    layout = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout,
        settings,
        workspace=workspace,
        namespace_id="7" * 64,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    sources = {}
    for release in ("1", "2", "3"):
        source = tmp_path / f"reviewpack-{release}-py3-none-any.whl"
        source.write_bytes(_data_wheel(version=release))
        sources[release] = admit_coding_external_data_wheel(layout, source=source)
    owner = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    product = owner.runtime_owner.product_owner

    def activate(name: str):  # type: ignore[no-untyped-def]
        factory = product.factory_for_session(
            session_id=name, cwd=workspace, runtime_id=name
        )
        runtime = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id=name, cwd=str(workspace)
            )
        )
        runtime.activate()
        return runtime

    def route(runtime, release: str, action: str) -> None:  # type: ignore[no-untyped-def]
        outcome = runtime.lifecycle.route(
            PackageProductLifecycleIntentV1(
                operation_id=f"test:reviewpack-{release}",
                action=action,
                source=str(
                    owner.epoch_runtime.control_root
                    / "product-sources"
                    / sources[release].wheel_filename
                ),
                scope="project",
            ),
            entrypoint="cli",
        )
        assert outcome.record is not None
        assert outcome.record.lifecycle in {"installed", "updated"}

    first = activate("stale-update-first")
    try:
        route(first, "1", "install")
        second = activate("stale-update-second")
        try:
            original_finalize = PackageProductHandoffFinalizer.finalize

            def interrupt(owner, request, *, current):  # type: ignore[no-untyped-def]
                if current.operation_id == "test:reviewpack-2":
                    raise OSError("injected interruption before first handoff")
                return original_finalize(owner, request, current=current)

            with monkeypatch.context() as patch:
                patch.setattr(PackageProductHandoffFinalizer, "finalize", interrupt)
                with pytest.raises(OSError, match="injected interruption"):
                    route(first, "2", "update")
            anchor = product.gc_bindings.update_anchor("test:reviewpack-2")
            assert anchor is not None
            assert anchor.expected_package_revision.plugin_version == "1"
            route(second, "3", "update")
            selected = product.desired_state.snapshot().installation(
                PluginInstallationKeyV1(
                    product_id="coding",
                    installation_scope="workspace",
                    scope_id=layout.scope_id,
                    plugin_id="reviewpack",
                )
            )
            assert selected.selection.package_revision.plugin_version == "3"
            with suppress(RuntimeError):
                first.activate()
            selected_after = product.desired_state.snapshot().installation(
                selected.installation_key
            )
            assert selected_after.selection.package_revision.plugin_version == "3"
            third = activate("stale-update-third")
            try:
                assert (
                    product.desired_state.snapshot()
                    .installation(selected.installation_key)
                    .selection.package_revision.plugin_version
                    == "3"
                )
            finally:
                third.dispose_runtime()
        finally:
            second.dispose_runtime()
    finally:
        first.dispose_runtime()
        owner.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_external_data_skill_survives_disabled_base_product_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, _layout, settings = _p2_workspace(tmp_path, monkeypatch)
    source = _p2_wheel_source(tmp_path, plugin_id="reviewpack", skill_name="review")
    prompt_source = tmp_path / "promptpack-1-py3-none-any.whl"
    prompt_source.write_bytes(
        build_coding_data_prompt_wheel(
            plugin_id="promptpack",
            version="1",
            contribution_id="review-prompt",
            prompt_name="review",
            prompt_document=b"# External review\nCheck the change carefully.\n",
        )
    )
    for args in (
        ("--install-package", str(source), "--package-scope", "project"),
        ("--install-package", str(prompt_source), "--package-scope", "project"),
        ("--enable-plugin", "reviewpack"),
        ("--enable-plugin", "promptpack"),
        ("--disable-plugin", "coding.base"),
    ):
        code, _stdout, stderr = _p2_cli(workspace, *args)
        assert code == 0, stderr
    with CodingFencedProductReadOnlyPreviewOwner.open(
        resolve_coding_plugin_lifecycle_state_layout(workspace)
    ) as preview_owner:
        no_base_preview = preview_owner.preview_current_data_resources(
            workspace=workspace, composition_set_id="coding-standard"
        )
    assert no_base_preview.disposition == "projected"
    assert "coding.base" not in no_base_preview.compiled_plugin_ids
    assert {"reviewpack", "promptpack"} <= set(no_base_preview.compiled_plugin_ids)
    assert ("skill", "review", "external_package") in (
        no_base_preview.catalog_resources
    )
    assert ("prompt", "review", "external_package") in (
        no_base_preview.catalog_resources
    )
    session = _p2_session(workspace, settings, tmp_path / "no-base-sessions")
    try:
        assert session._coding_base_product_compilation is None
        assert session._coding_lsp_plugin_assembly is not None
        assert session.resource_bundle is not None
        external = {
            item.name: item
            for item in session.resource_bundle.skills
            if item.source_kind == "external_package"
        }
        assert "review" in external
        assert "standard" not in external
        assert any(
            item.name == "review" and item.source_kind == "external_package"
            for item in session.resource_bundle.prompts
        )
        loaded = _p2_preflight(session, "review")
        assert len(loaded.loaded_skills) == 1
        assert "# Review v1" in loaded.loaded_skills[0].content
    finally:
        asyncio.run(session.dispose())

    class NoBasePromptAdapter:
        api = "disabled-base-external-prompt-test"

        def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
            return PreparedModelRequest.from_provider_request(
                request,
                payload={
                    "system": request.context.system_prompt,
                    "messages": [
                        serialize_message(message)
                        for message in request.context.messages
                    ],
                    "model": request.model.id,
                },
            )

        async def invoke_prepared_raw(
            self, request: ProviderRequest, prepared: PreparedModelRequest
        ) -> AsyncIterator[dict[str, object]]:
            del request
            prepared.payload_for_transport()
            yield {"type": "response_start", "response_id": "no-base-prompt"}
            yield {"type": "text_delta", "text": "reviewed"}
            yield {"type": "stop_reason", "stop_reason": "stop"}
            yield {"type": "response_done"}

        async def invoke_raw(
            self, request: ProviderRequest
        ) -> AsyncIterator[dict[str, object]]:
            prepared = self.prepare_request(request)
            async for part in self.invoke_prepared_raw(request, prepared):
                yield part

    registry = get_default_api_registry()
    registry.register_api_adapter(
        NoBasePromptAdapter(), source_id=NoBasePromptAdapter.api
    )
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "no-base-prompt-sessions",
            cwd=str(workspace),
            persist=True,
        )
    )
    prompt_session = create_agent_session(
        session_manager=manager,
        model=Model(
            id="no-base-prompt-model",
            name="No Base Prompt Model",
            provider="test",
            endpoint="disabled-base-prompt-test",
            api=NoBasePromptAdapter.api,
            base_url="https://provider.test/v1",
            auth=Auth(kind="none"),
            capabilities=Capabilities(
                input=("text",),
                output=("text",),
                context_window=128000,
                stream=True,
                tool_use=True,
            ),
        ),
        services=create_services(settings_manager=settings),
        composition_set="coding-standard",
    )
    try:
        asyncio.run(prompt_session.prompt("/review Review this change"))
        snapshots = [
            entry.payload
            for entry in manager.get_entries()
            if entry.kind == "model.input.prepared"
        ]
        assert len(snapshots) == 1
        snapshot_id = snapshots[0].snapshot_id
        assert "# External review" in json.dumps(
            manager.rebuild_model_input(snapshot_id).logical_input,
            ensure_ascii=False,
        )
    finally:
        asyncio.run(prompt_session.dispose())
        registry.unregister_api_adapters(NoBasePromptAdapter.api)
    resumed = asyncio.run(SessionManager.load(manager.get_session_file()))
    assert "# External review" in json.dumps(
        resumed.rebuild_model_input(snapshot_id).logical_input,
        ensure_ascii=False,
    )
    code, _stdout, stderr = _p2_cli(workspace, "--disable-plugin", "reviewpack")
    assert code == 0, stderr
    next_session = _p2_session(workspace, settings, tmp_path / "no-base-next-sessions")
    try:
        assert next_session.resource_bundle is not None
        assert not any(
            item.name == "review" and item.source_kind == "external_package"
            for item in next_session.resource_bundle.skills
        )
        assert any(
            item.name == "review" and item.source_kind == "external_package"
            for item in next_session.resource_bundle.prompts
        )
    finally:
        asyncio.run(next_session.dispose())
    code, _stdout, stderr = _p2_cli(workspace, "--disable-plugin", "promptpack")
    assert code == 0, stderr
    with CodingFencedProductReadOnlyPreviewOwner.open(
        resolve_coding_plugin_lifecycle_state_layout(workspace)
    ) as preview_owner:
        native_only_preview = preview_owner.preview_current_data_resources(
            workspace=workspace, composition_set_id="coding-standard"
        )
    assert native_only_preview.disposition == "projected"
    assert native_only_preview.compiled_plugin_ids == ()
    assert not any(
        source == "external_package"
        for _kind, _name, source in native_only_preview.catalog_resources
    )
    code, _stdout, stderr = _p2_cli(
        workspace, "--uninstall-package", "coding.base", "--package-scope", "project"
    )
    assert code == 0, stderr
    with CodingFencedProductReadOnlyPreviewOwner.open(
        resolve_coding_plugin_lifecycle_state_layout(workspace)
    ) as preview_owner:
        removed_base_preview = preview_owner.preview_current_data_resources(
            workspace=workspace, composition_set_id="coding-standard"
        )
    assert removed_base_preview.disposition == "blocked"
    assert removed_base_preview.blocking_code == "product_requested_base_not_installed"


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_base_disabled_external_prompt_conflict_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, _layout, settings = _p2_workspace(tmp_path, monkeypatch)
    for plugin_id in ("promptpack", "auditpack"):
        wheel = tmp_path / f"{plugin_id}-1-py3-none-any.whl"
        wheel.write_bytes(
            build_coding_data_prompt_wheel(
                plugin_id=plugin_id,
                version="1",
                contribution_id="review-prompt",
                prompt_name="review",
                prompt_document=f"# Review by {plugin_id}\n".encode(),
            )
        )
        for args in (
            ("--install-package", str(wheel), "--package-scope", "project"),
            ("--enable-plugin", plugin_id),
        ):
            code, _stdout, stderr = _p2_cli(workspace, *args)
            assert code == 0, stderr
    code, _stdout, stderr = _p2_cli(workspace, "--disable-plugin", "coding.base")
    assert code == 0, stderr
    with CodingFencedProductReadOnlyPreviewOwner.open(
        resolve_coding_plugin_lifecycle_state_layout(workspace)
    ) as preview_owner:
        conflict_preview = preview_owner.preview_current_data_resources(
            workspace=workspace, composition_set_id="coding-standard"
        )
    assert conflict_preview.disposition == "blocked"
    assert conflict_preview.blocking_code == "duplicate_owner_contribution_identity"
    assert conflict_preview.compiled_plugin_ids == ("auditpack", "promptpack")
    assert len(set(conflict_preview.blocking_admission_fingerprints)) == 2
    with pytest.raises(ProductCompositionError) as collision:
        _p2_session(workspace, settings, tmp_path / "no-base-conflict")
    assert collision.value.code == "duplicate_owner_contribution_identity"
    assert len(set(collision.value.admission_fingerprints)) == 2
    assert _p2_list_plugins(workspace)["promptpack"]["desiredState"] == (
        "installed_enabled"
    )
    assert _p2_list_plugins(workspace)["auditpack"]["desiredState"] == (
        "installed_enabled"
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_fenced_management_tui_actions_use_their_own_product_actor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import PromptIntent

    workspace, layout, settings = _p2_workspace(tmp_path, monkeypatch)
    controller = build_coding_ui_controller(
        session=object(), plugin_workspace=workspace
    )
    sdk = open_coding_plugin_management_command_client(workspace)

    disabled = asyncio.run(
        controller.dispatch(PromptIntent(text="/plugins disable coding.base"))
    )
    assert disabled.error_message is None
    assert (disabled.status_message or "").startswith("Plugin disable succeeded: ")
    operation_id = (disabled.status_message or "").split(": ", 1)[1].split(";", 1)[0]
    observed = sdk.operation(operation_id, correlation_id="test:tui-observe")
    assert observed is not None
    mutation = observed["operation"]["command"]["mutation"]
    assert mutation["actorId"] == "coding:tui"
    assert mutation["policyRevision"] == "coding-plugin-management-tui-v1"
    assert (
        sdk.snapshot(correlation_id="test:tui-disabled", plugin_ids=("coding.base",))[
            "installations"
        ][0]["desiredState"]
        == "installed_disabled"
    )
    disabled_session = _p2_session(
        workspace, settings, tmp_path / "tui-disabled-session"
    )
    try:
        assert disabled_session._coding_base_product_compilation is None
    finally:
        asyncio.run(disabled_session.dispose())
    with pytest.raises(PluginDesiredCommandRepairError) as foreign:
        sdk.repair_own_desired_operation(
            operation_id, correlation_id="test:sdk-foreign-tui"
        )
    assert foreign.value.code == "plugin_management_repair_foreign_operation"

    journal = (
        resolve_coding_package_epoch_layout(layout).control_root
        / "product-state"
        / "management-operations.jsonl"
    )
    before = journal.read_bytes()
    terminal = asyncio.run(
        controller.dispatch(PromptIntent(text=f"/plugins repair {operation_id}"))
    )
    unknown = asyncio.run(
        controller.dispatch(PromptIntent(text="/plugins repair tui:unknown"))
    )
    assert "already_terminal" in (terminal.status_message or "")
    assert unknown.status_message == "Plugin operation unknown: tui:unknown"
    assert journal.read_bytes() == before

    enabled = asyncio.run(
        controller.dispatch(PromptIntent(text="/plugins enable coding.base"))
    )
    assert enabled.error_message is None
    assert (
        sdk.snapshot(correlation_id="test:tui-enabled", plugin_ids=("coding.base",))[
            "installations"
        ][0]["desiredState"]
        == "installed_enabled"
    )
    removed = asyncio.run(
        controller.dispatch(PromptIntent(text="/plugins remove coding.base"))
    )
    assert removed.error_message is None
    assert (
        sdk.snapshot(correlation_id="test:tui-removed", plugin_ids=("coding.base",))[
            "installations"
        ][0]["desiredState"]
        == "absent"
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_fenced_management_tui_repairs_its_interrupted_desired_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import PromptIntent

    workspace, _layout, _settings = _p2_workspace(tmp_path, monkeypatch)
    controller = build_coding_ui_controller(
        session=object(), plugin_workspace=workspace
    )
    sdk = open_coding_plugin_management_command_client(workspace)
    original_commit = PluginDesiredStateLedger.commit
    crashed = False

    def commit_then_crash(
        self: PluginDesiredStateLedger, mutation: PluginDesiredStateMutationV1
    ):
        nonlocal crashed
        result = original_commit(self, mutation)
        if mutation.operation_id.startswith("tui-plugin-desired:") and not crashed:
            crashed = True
            raise RuntimeError("simulated TUI crash after Desired commit")
        return result

    monkeypatch.setattr(PluginDesiredStateLedger, "commit", commit_then_crash)
    interrupted = asyncio.run(
        controller.dispatch(PromptIntent(text="/plugins disable coding.base"))
    )
    assert (
        interrupted.error_message
        == "Plugin command failed: plugin_management_unavailable"
    )
    listing = asyncio.run(controller.dispatch(PromptIntent(text="/plugins list")))
    snapshot = sdk.snapshot(
        correlation_id="test:tui:interrupted", plugin_ids=("coding.base",)
    )
    operations = snapshot["installations"][0]["operations"]
    pending = [item for item in operations if item["status"] == "running"]
    assert len(pending) == 1
    operation_id = pending[0]["operationId"]
    assert f"pending: {operation_id}" in (listing.status_message or "")
    assert (
        sdk.snapshot(correlation_id="test:tui:committed", plugin_ids=("coding.base",))[
            "installations"
        ][0]["desiredState"]
        == "installed_disabled"
    )
    repaired = asyncio.run(
        controller.dispatch(PromptIntent(text=f"/plugins repair {operation_id}"))
    )
    assert repaired.error_message is None
    assert f"replayed_pending: {operation_id}" in (repaired.status_message or "")
    assert (
        sdk.operation(operation_id, correlation_id="test:tui:terminal")["operation"][
            "status"
        ]
        == "terminal"
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_fenced_management_command_sdk_uses_exact_desired_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, _layout, _settings = _p2_workspace(tmp_path, monkeypatch)
    client = open_coding_plugin_management_command_client(workspace)
    with pytest.raises(ValueError, match="scope"):
        CodingPluginManagementCommandClientV1(
            workspace=client.workspace,
            layout=replace(client.layout, scope_id="workspace:forged"),
            workspace_identity=client.workspace_identity,
        )
    before = client.snapshot(correlation_id="sdk:before", plugin_ids=("coding.base",))
    revision = before["ownerRevisions"]["desiredState"]
    assert before["installations"][0]["desiredState"] == "installed_enabled"
    disabled = client.submit_desired(
        plugin_id="coding.base",
        action="disable",
        expected_inventory_revision=revision,
        operation_id="sdk:disable:base",
        correlation_id="sdk:disable",
    )
    assert disabled["operation"]["result"]["disposition"] == "succeeded"
    assert (
        client.operation("sdk:disable:base", correlation_id="sdk:observe")["operation"]
        == disabled["operation"]
    )
    assert client.operation("sdk:unknown", correlation_id="sdk:unknown") is None
    repeated = client.submit_desired(
        plugin_id="coding.base",
        action="disable",
        expected_inventory_revision=revision,
        operation_id="sdk:disable:base",
        correlation_id="sdk:disable:retry",
    )
    assert repeated["operation"] == disabled["operation"]
    stale = client.submit_desired(
        plugin_id="coding.base",
        action="enable",
        expected_inventory_revision=revision,
        operation_id="sdk:enable:stale",
        correlation_id="sdk:stale",
    )
    assert stale["operation"]["result"]["errorCode"] == (
        "plugin_inventory_revision_conflict"
    )
    after = client.snapshot(correlation_id="sdk:after", plugin_ids=("coding.base",))
    assert after["installations"][0]["desiredState"] == "installed_disabled"
    enabled = client.submit_desired(
        plugin_id="coding.base",
        action="enable",
        expected_inventory_revision=after["ownerRevisions"]["desiredState"],
        operation_id="sdk:enable:base",
        correlation_id="sdk:enable",
    )
    assert enabled["operation"]["result"]["disposition"] == "succeeded"
    final = client.snapshot(correlation_id="sdk:final", plugin_ids=("coding.base",))
    assert final["installations"][0]["desiredState"] == "installed_enabled"
    removed = client.submit_desired(
        plugin_id="coding.base",
        action="remove",
        expected_inventory_revision=final["ownerRevisions"]["desiredState"],
        operation_id="sdk:remove:base",
        correlation_id="sdk:remove",
    )
    assert removed["operation"]["result"]["disposition"] == "succeeded"
    assert (
        client.snapshot(correlation_id="sdk:removed", plugin_ids=("coding.base",))[
            "installations"
        ][0]["desiredState"]
        == "absent"
    )
    workspace.rename(tmp_path / "workspace-moved")
    workspace.mkdir(mode=0o700)
    with pytest.raises(CodingPluginManagementCommandSdkError) as replaced:
        client.snapshot(correlation_id="sdk:replaced", plugin_ids=("coding.base",))
    assert replaced.value.code == "coding_management_workspace_changed"


def test_management_command_sdk_refuses_unfenced_workspace_without_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    before = tuple(sorted(tmp_path.rglob("*")))
    with pytest.raises(CodingPluginManagementCommandSdkError) as unfenced:
        open_coding_plugin_management_command_client(workspace)
    assert unfenced.value.code == "coding_product_not_fenced"
    assert tuple(sorted(tmp_path.rglob("*"))) == before


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_management_command_sdk_refuses_workspace_replaced_during_owner_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import loushang.coding.plugin_management_command_sdk as command_sdk_module

    workspace, _layout, _settings = _p2_workspace(tmp_path, monkeypatch)
    client = open_coding_plugin_management_command_client(workspace)
    before = client.snapshot(
        correlation_id="test:owner-binding:before", plugin_ids=("coding.base",)
    )
    revision = before["ownerRevisions"]["desiredState"]
    assert before["installations"][0]["desiredState"] == "installed_enabled"
    build_ports = command_sdk_module.build_coding_fenced_product_management_cli_ports

    def replace_after_binding(
        layout: CodingPluginLifecycleStateLayout, **kwargs: object
    ):
        ports = build_ports(layout, **kwargs)
        workspace.rename(tmp_path / "original-workspace")
        workspace.mkdir(mode=0o700)
        return ports

    with monkeypatch.context() as patch:
        patch.setattr(
            command_sdk_module,
            "build_coding_fenced_product_management_cli_ports",
            replace_after_binding,
        )
        with pytest.raises(CodingPluginManagementCommandSdkError) as changed:
            client.submit_desired(
                plugin_id="coding.base",
                action="disable",
                expected_inventory_revision=revision,
                operation_id="sdk:owner-binding:refused",
                correlation_id="test:owner-binding:submit",
            )
    assert changed.value.code == "coding_management_workspace_changed"
    assert tuple(workspace.rglob("*")) == ()
    workspace.rmdir()
    (tmp_path / "original-workspace").rename(workspace)
    after = client.snapshot(
        correlation_id="test:owner-binding:after", plugin_ids=("coding.base",)
    )
    assert after["ownerRevisions"]["desiredState"] == revision
    assert after["installations"][0]["desiredState"] == "installed_enabled"


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_management_command_sdk_refuses_workspace_replaced_after_product_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import loushang.coding.package_product_management_cli as management_cli_module

    workspace, layout, _settings = _p2_workspace(tmp_path, monkeypatch)
    client = open_coding_plugin_management_command_client(workspace)
    before = client.snapshot(
        correlation_id="test:late-swap:before", plugin_ids=("coding.base",)
    )
    revision = before["ownerRevisions"]["desiredState"]
    state_root = (
        resolve_coding_package_epoch_layout(layout).control_root / "product-state"
    )
    names = (
        "desired-state.jsonl",
        "management-operations.jsonl",
        "retirement-intents.jsonl",
        "retirement-sets.jsonl",
    )
    recorded = {
        name: (state_root / name).read_bytes() if (state_root / name).exists() else None
        for name in names
    }
    original_open = management_cli_module._ProductCliOwner.open

    def replace_after_product_open(self: object, *, read_only: bool):
        opened = original_open(self, read_only=read_only)
        if not read_only:
            workspace.rename(tmp_path / "original-workspace")
            workspace.mkdir(mode=0o700)
        return opened

    with monkeypatch.context() as patch:
        patch.setattr(
            management_cli_module._ProductCliOwner,
            "open",
            replace_after_product_open,
        )
        with pytest.raises(CodingPluginManagementCommandSdkError) as changed:
            client.submit_desired(
                plugin_id="coding.base",
                action="disable",
                expected_inventory_revision=revision,
                operation_id="sdk:late-swap:refused",
                correlation_id="test:late-swap:submit",
            )
    assert changed.value.code == "coding_management_workspace_changed"
    assert tuple(workspace.iterdir()) == ()
    assert {
        name: (state_root / name).read_bytes() if (state_root / name).exists() else None
        for name in names
    } == recorded
    workspace.rmdir()
    (tmp_path / "original-workspace").rename(workspace)
    after = client.snapshot(
        correlation_id="test:late-swap:after", plugin_ids=("coding.base",)
    )
    assert after["ownerRevisions"]["desiredState"] == revision
    assert after["installations"][0]["desiredState"] == "installed_enabled"


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
@pytest.mark.parametrize("swap_after_prepare", [1, 2])
def test_management_command_sdk_does_not_recover_pending_after_workspace_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, swap_after_prepare: int
) -> None:
    from loushang.harness.resources.packages.product_epoch_guard import (
        PackageProductPosixFencedRuntimeOwner,
    )

    workspace, layout, _settings = _p2_workspace(tmp_path, monkeypatch)
    owner = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    try:
        product = owner.runtime_owner.product_owner
        snapshot = product.desired_state.snapshot()
        installation = next(
            item
            for item in snapshot.installations
            if item.installation_key.plugin_id == "coding.base"
        )
        operations = product.management.operation_journal_path
        pending = PluginManagementOperationEventV1.accepted(
            journal_revision=len(operations.read_bytes().splitlines()) + 1,
            command=PluginManagementCommandV1(
                action="disable",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="test:pending-workspace-swap",
                    idempotency_key="test:pending-workspace-swap",
                    expected_inventory_revision=snapshot.inventory_revision,
                    installation_key=installation.installation_key,
                    desired_state="installed_disabled",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision="test",
                ),
            ),
        )
        operations.write_bytes(
            operations.read_bytes()
            + (json.dumps(pending.to_dict(), sort_keys=True) + "\n").encode()
            + b'{"partial":'
        )
        desired = product.desired_state.path
        before_operations = operations.read_bytes()
        before_desired = desired.read_bytes()
    finally:
        owner.close()

    original_prepare = PackageProductPosixFencedRuntimeOwner.prepare_product_state_root
    swapped = False
    prepare_calls = 0

    def replace_after_prepare(self: PackageProductPosixFencedRuntimeOwner) -> Path:
        nonlocal swapped, prepare_calls
        root = original_prepare(self)
        prepare_calls += 1
        if prepare_calls == swap_after_prepare:
            swapped = True
            workspace.rename(tmp_path / "original-workspace")
            workspace.mkdir(mode=0o700)
        return root

    client = open_coding_plugin_management_command_client(workspace)
    with monkeypatch.context() as patch:
        patch.setattr(
            PackageProductPosixFencedRuntimeOwner,
            "prepare_product_state_root",
            replace_after_prepare,
        )
        with pytest.raises(CodingPluginManagementCommandSdkError) as changed:
            client.submit_desired(
                plugin_id="coding.base",
                action="disable",
                expected_inventory_revision=snapshot.inventory_revision,
                operation_id="sdk:swap:refused",
                correlation_id="test:swap:submit",
            )
    assert swapped
    assert changed.value.code == "coding_management_workspace_changed"
    assert operations.read_bytes() == before_operations
    assert desired.read_bytes() == before_desired
    workspace.rmdir()
    (tmp_path / "original-workspace").rename(workspace)


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_management_recovery_refuses_workspace_swap_before_gc_tail_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import loushang.harness.plugin_management.package_gc_reservation as gc_module

    workspace, layout, _settings = _p2_workspace(tmp_path, monkeypatch)
    client = open_coding_plugin_management_command_client(workspace)
    revision = client.snapshot(
        correlation_id="test:gc-swap:before", plugin_ids=("coding.base",)
    )["ownerRevisions"]["desiredState"]
    gc_path = (
        resolve_coding_package_epoch_layout(layout).control_root
        / "product-state"
        / "gc-reservations.jsonl"
    )
    before = (gc_path.read_bytes() if gc_path.exists() else b"") + b'{"partial":'
    gc_path.write_bytes(before)
    original_lock = gc_module.journal_file_lock
    swapped = False

    @contextmanager
    def swap_after_gc_lock(path: Path, mode: str, **kwargs: object):
        nonlocal swapped
        with original_lock(path, mode, **kwargs) as locked:
            if not swapped and Path(path) == gc_path and mode == "exclusive":
                swapped = True
                workspace.rename(tmp_path / "original-workspace")
                workspace.mkdir(mode=0o700)
            yield locked

    with monkeypatch.context() as patch:
        patch.setattr(gc_module, "journal_file_lock", swap_after_gc_lock)
        with pytest.raises(CodingPluginManagementCommandSdkError) as changed:
            client.submit_desired(
                plugin_id="coding.base",
                action="disable",
                expected_inventory_revision=revision,
                operation_id="sdk:gc-swap:refused",
                correlation_id="test:gc-swap:submit",
            )
    assert swapped
    assert changed.value.code == "coding_management_workspace_changed"
    assert gc_path.read_bytes() == before
    workspace.rmdir()
    (tmp_path / "original-workspace").rename(workspace)


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
@pytest.mark.parametrize(
    "missing_lock",
    ("gc-reservations.jsonl.lock", "management-operations.jsonl.lock"),
)
def test_management_sdk_recovery_refuses_missing_lock_without_recreating_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing_lock: str
) -> None:
    workspace, layout, _settings = _p2_workspace(tmp_path, monkeypatch)
    client = open_coding_plugin_management_command_client(workspace)
    revision = client.snapshot(
        correlation_id="test:missing-recovery-lock:before", plugin_ids=("coding.base",)
    )["ownerRevisions"]["desiredState"]
    state_root = (
        resolve_coding_package_epoch_layout(layout).control_root / "product-state"
    )
    lock = state_root / missing_lock
    assert lock.is_file()
    lock.unlink()
    before = tuple(sorted(path.name for path in state_root.iterdir()))
    with pytest.raises((OSError, RuntimeError, ValueError)):
        client.submit_desired(
            plugin_id="coding.base",
            action="disable",
            expected_inventory_revision=revision,
            operation_id="sdk:missing-recovery-lock:refused",
            correlation_id="test:missing-recovery-lock:submit",
        )
    assert not lock.exists()
    assert tuple(sorted(path.name for path in state_root.iterdir())) == before


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_management_read_sdk_refuses_replaced_workspace_for_every_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, _layout, _settings = _p2_workspace(tmp_path, monkeypatch)
    client = open_coding_plugin_management_read_client(workspace)
    original = tmp_path / "original-workspace"
    workspace.rename(original)
    workspace.mkdir(mode=0o700)
    before = tuple(workspace.rglob("*"))
    reads = (
        lambda: client.snapshot(
            PluginManagementQueryV1(
                correlation_id="test:replaced:snapshot",
                product_id="coding",
                installation_scope="workspace",
                scope_id=client.scope_id,
            )
        ),
        lambda: client.management_snapshot(correlation_id="test:replaced:management"),
        lambda: client.preview_current(correlation_id="test:replaced:preview"),
        lambda: client.explain_operation(
            "package:missing", correlation_id="test:replaced:explain"
        ),
    )
    for read in reads:
        with pytest.raises(RuntimeError) as changed:
            read()
        assert getattr(changed.value, "code", None) == (
            "coding_management_workspace_changed"
        )
    assert tuple(workspace.rglob("*")) == before


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_management_read_sdk_refuses_workspace_replacement_during_product_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import loushang.coding.plugin_management_read_sdk as read_sdk_module

    workspace, _layout, _settings = _p2_workspace(tmp_path, monkeypatch)
    client = open_coding_plugin_management_read_client(workspace)
    build_binding = read_sdk_module.build_coding_plugin_management_cli_read_binding

    def replace_after_query(
        path: Path,
        settings_manager: object | None,
        *,
        workspace_identity: tuple[int, int] | None = None,
    ):
        binding = build_binding(
            path, settings_manager, workspace_identity=workspace_identity
        )

        class ReplacingBinding:
            scope_id = binding.scope_id

            def query(self, *, correlation_id: str, plugin_ids: tuple[str, ...]):
                result = binding.query(
                    correlation_id=correlation_id, plugin_ids=plugin_ids
                )
                workspace.rename(tmp_path / "original-workspace")
                workspace.mkdir(mode=0o700)
                return result

        return ReplacingBinding()

    monkeypatch.setattr(
        read_sdk_module,
        "build_coding_plugin_management_cli_read_binding",
        replace_after_query,
    )
    with pytest.raises(RuntimeError) as changed:
        client.management_snapshot(correlation_id="test:replacement-during-read")
    assert getattr(changed.value, "code", None) == (
        "coding_management_workspace_changed"
    )
    assert tuple(workspace.rglob("*")) == ()


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_management_read_sdk_snapshot_refuses_workspace_replaced_before_owner_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import loushang.coding.plugin_management_read_sdk as read_sdk_module

    workspace, _layout, _settings = _p2_workspace(tmp_path, monkeypatch)
    client = open_coding_plugin_management_read_client(workspace)
    reads: list[str] = []

    def replace_before_owner_open(
        layout: CodingPluginLifecycleStateLayout, *, workspace_guard=None
    ):
        original = tmp_path / "original-workspace"
        workspace.rename(original)
        workspace.mkdir(mode=0o700)
        if workspace_guard is not None:
            workspace_guard()

        class RestoringQueries:
            def snapshot(self, _query: PluginManagementQueryV1) -> object:
                reads.append("foreign")
                workspace.rmdir()
                original.rename(workspace)
                return object()

        return SimpleNamespace(queries=RestoringQueries())

    monkeypatch.setattr(
        read_sdk_module,
        "build_coding_fenced_product_management_cli_ports",
        replace_before_owner_open,
    )
    with pytest.raises(RuntimeError) as changed:
        client.snapshot(
            PluginManagementQueryV1(
                correlation_id="test:replaced-before-owner-open",
                product_id="coding",
                installation_scope="workspace",
                scope_id=client.scope_id,
            )
        )
    assert getattr(changed.value, "code", None) == (
        "coding_management_workspace_changed"
    )
    assert reads == []
    assert tuple(workspace.rglob("*")) == ()


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_management_read_sdk_management_snapshot_pins_original_workspace_at_bind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import loushang.coding.plugin_management_cli as cli_module

    workspace, _layout, _settings = _p2_workspace(tmp_path, monkeypatch)
    client = open_coding_plugin_management_read_client(workspace)
    normal = client.management_snapshot(correlation_id="test:original-binding")
    assert normal["correlationId"] == "test:original-binding"
    assert normal["projectionVersion"] == 1
    original = tmp_path / "original-workspace"
    capture = cli_module._capture_workspace_identity
    reads: list[str] = []
    swapped = False

    def replace_before_owner_capture(path: Path) -> tuple[int, int] | None:
        nonlocal swapped
        if path == workspace and not swapped:
            swapped = True
            workspace.rename(original)
            workspace.mkdir(mode=0o700)
        return capture(path)

    def restore_after_foreign_binding(profile: object, owner: object):
        class ForeignBinding:
            scope_id = client.scope_id

            def query(self, *, correlation_id: str, plugin_ids: tuple[str, ...]):
                reads.append("foreign")
                workspace.rmdir()
                original.rename(workspace)
                return SimpleNamespace(to_dict=lambda: {})

        return ForeignBinding()

    monkeypatch.setattr(
        cli_module, "_capture_workspace_identity", replace_before_owner_capture
    )
    monkeypatch.setattr(
        cli_module, "bind_plugin_management_cli_read", restore_after_foreign_binding
    )
    with pytest.raises(RuntimeError) as changed:
        client.management_snapshot(correlation_id="test:replaced-before-binding")
    assert getattr(changed.value, "code", None) == (
        "coding_management_workspace_changed"
    )
    assert swapped
    assert reads == []
    assert tuple(workspace.rglob("*")) == ()
    workspace.rmdir()
    original.rename(workspace)


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
@pytest.mark.parametrize("method", ("preview", "explain"))
def test_management_read_sdk_projection_pins_original_workspace_at_bind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: Literal["preview", "explain"],
) -> None:
    import loushang.coding.plugin_management_read_sdk as read_sdk_module

    workspace, _layout, _settings = _p2_workspace(tmp_path, monkeypatch)
    client = open_coding_plugin_management_read_client(workspace)
    correlation_id = f"test:replaced-before-{method}-binding"
    if method == "preview":
        valid = bind_coding_current_preview_query(workspace).preview_current(
            PluginCurrentPreviewRequestV1(
                correlation_id=correlation_id,
                product_id="coding",
                scope_id=client.scope_id,
                composition_set_id="coding-standard",
            )
        )
        binding_name = "bind_coding_current_preview_query"
    else:
        valid = bind_coding_plugin_operation_explanation_query(
            workspace
        ).explain_plugin_operation(
            PluginOperationExplanationRequestV1(
                correlation_id=correlation_id,
                product_id="coding",
                scope_id=client.scope_id,
                operation_id="package:missing",
            )
        )
        binding_name = "bind_coding_plugin_operation_explanation_query"

    def read() -> dict[str, object]:
        if method == "preview":
            return client.preview_current(correlation_id=correlation_id)
        return client.explain_operation(
            "package:missing", correlation_id=correlation_id
        )

    assert read()["correlationId"] == correlation_id
    original = tmp_path / "original-workspace"
    reads: list[str] = []

    class ForeignQuery:
        def _read(self):
            reads.append("foreign")
            workspace.rmdir()
            original.rename(workspace)
            return valid

        def preview_current(self, _request: PluginCurrentPreviewRequestV1):
            return self._read()

        def explain_plugin_operation(
            self, _request: PluginOperationExplanationRequestV1
        ):
            return self._read()

    def replace_before_bind(path: str | Path, *, workspace_guard=None):
        assert Path(path) == workspace
        workspace.rename(original)
        workspace.mkdir(mode=0o700)
        if workspace_guard is not None:
            workspace_guard()
        return ForeignQuery()

    monkeypatch.setattr(read_sdk_module, binding_name, replace_before_bind)
    with pytest.raises(RuntimeError) as changed:
        read()
    assert getattr(changed.value, "code", None) == (
        "coding_management_workspace_changed"
    )
    assert reads == []
    assert tuple(workspace.rglob("*")) == ()
    workspace.rmdir()
    original.rename(workspace)


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_management_read_sdk_preview_refuses_workspace_replaced_after_epoch_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import loushang.coding.package_product_preview as preview_module

    workspace, _layout, _settings = _p2_workspace(tmp_path, monkeypatch)
    client = open_coding_plugin_management_read_client(workspace)
    original = tmp_path / "original-workspace"
    epoch_open = preview_module.PackageProductPosixFencedRuntimeOwner.open
    swapped = False

    def replace_after_epoch_open(cls, **kwargs: object):
        nonlocal swapped
        runtime = epoch_open(**kwargs)
        workspace.rename(original)
        workspace.mkdir(mode=0o700)
        swapped = True
        return runtime

    def forbid_product_source_read(_source_root: Path):
        pytest.fail("Product Source read crossed a replaced workspace")

    monkeypatch.setattr(
        preview_module.PackageProductPosixFencedRuntimeOwner,
        "open",
        classmethod(replace_after_epoch_open),
    )
    monkeypatch.setattr(
        preview_module,
        "inspect_posix_coding_base_product_wheel",
        forbid_product_source_read,
    )
    with pytest.raises(CodingCurrentPreviewError) as changed:
        client.preview_current(correlation_id="test:replaced-after-epoch-open")
    assert changed.value.code == "plugin_preview_owner_unavailable"
    assert swapped
    assert tuple(workspace.rglob("*")) == ()
    workspace.rmdir()
    original.rename(workspace)


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_management_sdk_repairs_only_its_own_interrupted_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, layout, _settings = _p2_workspace(tmp_path, monkeypatch)
    client = open_coding_plugin_management_command_client(workspace)
    before = client.snapshot(
        correlation_id="sdk:repair:before", plugin_ids=("coding.base",)
    )
    revision = before["ownerRevisions"]["desiredState"]
    operation_journal = (
        resolve_coding_package_epoch_layout(layout).control_root
        / "product-state"
        / "management-operations.jsonl"
    )
    journal_before_unknown = operation_journal.read_bytes()
    unknown = client.repair_own_desired_operation(
        "sdk:missing", correlation_id="sdk:unknown"
    )
    assert unknown["disposition"] == "unknown"
    assert unknown["result"] is None
    assert operation_journal.read_bytes() == journal_before_unknown
    original_commit = PluginDesiredStateLedger.commit
    crashed = False

    def commit_then_crash(
        self: PluginDesiredStateLedger, mutation: PluginDesiredStateMutationV1
    ):
        nonlocal crashed
        result = original_commit(self, mutation)
        if mutation.operation_id == "sdk:crash:disable-base" and not crashed:
            crashed = True
            raise RuntimeError("simulated process crash after Desired commit")
        return result

    monkeypatch.setattr(PluginDesiredStateLedger, "commit", commit_then_crash)
    with pytest.raises(RuntimeError, match="simulated process crash"):
        client.submit_desired(
            plugin_id="coding.base",
            action="disable",
            expected_inventory_revision=revision,
            operation_id="sdk:crash:disable-base",
            correlation_id="sdk:crash",
        )
    assert (
        client.operation("sdk:crash:disable-base", correlation_id="sdk:running")[
            "operation"
        ]["status"]
        == "running"
    )
    assert (
        client.snapshot(
            correlation_id="sdk:desired-committed", plugin_ids=("coding.base",)
        )["installations"][0]["desiredState"]
        == "installed_disabled"
    )
    repaired = client.repair_own_desired_operation(
        "sdk:crash:disable-base", correlation_id="sdk:repair"
    )
    assert repaired["disposition"] == "replayed_pending"
    assert repaired["result"]["operation"]["result"]["disposition"] == ("succeeded")
    terminal = client.operation(
        "sdk:crash:disable-base", correlation_id="sdk:terminal"
    )["operation"]
    assert terminal["status"] == "terminal"
    journal_before_terminal = operation_journal.read_bytes()
    again = client.repair_own_desired_operation(
        "sdk:crash:disable-base", correlation_id="sdk:already-terminal"
    )
    assert again["disposition"] == "already_terminal"
    assert again["result"]["operation"] == terminal
    assert operation_journal.read_bytes() == journal_before_terminal
    foreign_revision = client.snapshot(
        correlation_id="sdk:foreign:before", plugin_ids=("coding.base",)
    )["ownerRevisions"]["desiredState"]
    foreign = submit_plugin_desired_command(
        build_coding_fenced_product_management_cli_ports(layout),
        PluginDesiredCommandAuthorityV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=layout.scope_id,
            actor_id="coding:cli",
            policy_revision="coding-plugin-management-cli-v1",
        ),
        PluginDesiredCommandRequestV1(
            correlation_id="sdk:foreign",
            operation_id="cli:foreign-enable",
            plugin_id="coding.base",
            action="enable",
            expected_inventory_revision=foreign_revision,
        ),
    )
    assert foreign.operation.result.disposition == "succeeded"
    with pytest.raises(PluginDesiredCommandRepairError) as refused:
        client.repair_own_desired_operation(
            "cli:foreign-enable", correlation_id="sdk:foreign-repair"
        )
    assert refused.value.code == "plugin_management_repair_foreign_operation"


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_cli_repairs_only_its_own_interrupted_desired_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, layout, _settings = _p2_workspace(tmp_path, monkeypatch)
    client = open_coding_plugin_management_command_client(workspace)
    original_commit = PluginDesiredStateLedger.commit
    crashed_operation: str | None = None

    def commit_then_crash(
        self: PluginDesiredStateLedger, mutation: PluginDesiredStateMutationV1
    ):
        nonlocal crashed_operation
        result = original_commit(self, mutation)
        if (
            mutation.actor_id == "coding:cli"
            and mutation.installation_key.plugin_id == "coding.base"
            and crashed_operation is None
        ):
            crashed_operation = mutation.operation_id
            raise RuntimeError("simulated CLI crash after Desired commit")
        return result

    monkeypatch.setattr(PluginDesiredStateLedger, "commit", commit_then_crash)
    code, output, error = _p2_cli(workspace, "--disable-plugin", "coding.base")
    assert code == 1
    assert output == ""
    assert "simulated CLI crash" in error
    assert crashed_operation is not None
    assert (
        client.operation(crashed_operation, correlation_id="cli:running")["operation"][
            "status"
        ]
        == "running"
    )
    code, output, error = _p2_cli(
        workspace, "--repair-plugin-desired-operation", crashed_operation
    )
    assert code == 0, error
    repaired = json.loads(output)
    assert repaired["disposition"] == "replayed_pending"
    assert repaired["statusBefore"] == "running"
    assert repaired["result"]["operation"]["result"]["disposition"] == ("succeeded")
    assert error == ""
    operation_journal = (
        resolve_coding_package_epoch_layout(layout).control_root
        / "product-state"
        / "management-operations.jsonl"
    )
    journal_before_inert_reads = operation_journal.read_bytes()
    code, output, error = _p2_cli(
        workspace, "--repair-plugin-desired-operation", crashed_operation
    )
    assert code == 0, error
    assert json.loads(output)["disposition"] == "already_terminal"
    code, output, error = _p2_cli(
        workspace, "--repair-plugin-desired-operation", "cli:missing"
    )
    assert code == 1
    assert json.loads(output)["disposition"] == "unknown"
    assert error == ""
    assert operation_journal.read_bytes() == journal_before_inert_reads
    code, output, error = _p2_cli(
        workspace,
        "--repair-plugin-desired-operation",
        crashed_operation,
        "--list-plugins",
    )
    assert code == 2
    assert output == ""
    assert error == "Error: plugin_repair_operation_conflict\n"
    current = client.snapshot(
        correlation_id="cli:foreign:before", plugin_ids=("coding.base",)
    )
    sdk_command = client.submit_desired(
        plugin_id="coding.base",
        action="enable",
        expected_inventory_revision=current["ownerRevisions"]["desiredState"],
        operation_id="sdk:foreign-for-cli",
        correlation_id="sdk:foreign-submit",
    )
    assert sdk_command["operation"]["result"]["disposition"] == "succeeded"
    journal_before_foreign = operation_journal.read_bytes()
    code, output, error = _p2_cli(
        workspace, "--repair-plugin-desired-operation", "sdk:foreign-for-cli"
    )
    assert code == 1
    assert output == ""
    assert error == "Error: plugin_management_repair_foreign_operation\n"
    assert operation_journal.read_bytes() == journal_before_foreign
    with pytest.raises(PluginDesiredCommandRepairError) as refused:
        client.repair_own_desired_operation(
            crashed_operation, correlation_id="sdk:foreign-repair"
        )
    assert refused.value.code == "plugin_management_repair_foreign_operation"


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_rpc_management_snapshot_refuses_unfenced_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "unfenced-workspace"
    workspace.mkdir()
    client = bind_coding_plugin_management_rpc_query(workspace)
    with pytest.raises((OSError, ValueError)):
        client.snapshot(
            PluginManagementQueryV1(
                correlation_id="rpc:unfenced",
                product_id="coding",
                installation_scope="workspace",
                scope_id=client.scope_id,
            )
        )


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_rpc_management_snapshot_refuses_session_workspace_retarget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    foreign_base = tmp_path / "foreign"
    foreign_base.mkdir(mode=0o700)
    shared_home = tmp_path / "home"
    foreign_workspace, foreign_layout, foreign_settings = _p2_workspace(
        foreign_base, monkeypatch, home=shared_home
    )
    workspace, layout, settings = _p2_workspace(tmp_path, monkeypatch, home=shared_home)
    session = _p2_session(workspace, settings, tmp_path / "sessions")

    class CurrentSessionRuntime:
        def get_current_session(self):  # type: ignore[no-untyped-def]
            return session

    output = StringIO()
    session_scope = CodingPluginRpcSessionScope()
    host = RpcHost(
        runtime=CurrentSessionRuntime(),
        stdin=StringIO(),
        stdout=output,
        plugin_management_factory=session_scope.bind_management,
        plugin_preview_factory=session_scope.bind_preview,
        plugin_explanation_factory=session_scope.bind_explanation,
        plugin_desired_factory=session_scope.bind_desired,
        package_repair_factory=session_scope.bind_package_repair,
        on_plugin_session_bound=session_scope.bind_session,
    )

    def request(payload: dict[str, object]) -> dict[str, object]:
        assert asyncio.run(host.submit_input(json.dumps(payload))) == 0
        return json.loads(output.getvalue().splitlines()[-1])

    def snapshot(scope_id: str, request_id: str) -> dict[str, object]:
        return request(
            {
                "id": request_id,
                "type": "plugin_management_snapshot_v1",
                "productId": "coding",
                "scopeId": scope_id,
                "pluginIds": [],
            }
        )

    original = tmp_path / "original-workspace"
    foreign_session = None
    late_host = None
    try:
        assert snapshot(layout.scope_id, "rpc:original")["success"] is True
        workspace.rename(original)
        workspace.symlink_to(foreign_workspace, target_is_directory=True)
        retargeted = bind_coding_plugin_management_rpc_query(workspace)
        assert retargeted.scope_id == foreign_layout.scope_id
        retargeted.snapshot(
            PluginManagementQueryV1(
                correlation_id="rpc:foreign-direct",
                product_id="coding",
                installation_scope="workspace",
                scope_id=foreign_layout.scope_id,
            )
        )
        foreign = snapshot(foreign_layout.scope_id, "rpc:foreign")
        assert foreign["success"] is False
        assert foreign["error"] == "plugin_management_unavailable"
        preview = request(
            {
                "id": "rpc:foreign-preview",
                "type": "preview_current_plugins",
                "productId": "coding",
                "scopeId": foreign_layout.scope_id,
                "compositionSetId": "coding-standard",
            }
        )
        assert preview["success"] is False
        assert preview["errorCode"] == "plugin_preview_unavailable"
        explanation = request(
            {
                "id": "rpc:foreign-explanation",
                "type": "explain_plugin_operation",
                "productId": "coding",
                "scopeId": foreign_layout.scope_id,
                "operationId": "rpc:foreign-explanation",
            }
        )
        assert explanation["success"] is False
        assert explanation["errorCode"] == "plugin_explanation_unavailable"
        foreign_command = open_coding_plugin_management_command_client(
            foreign_workspace
        )
        before = foreign_command.snapshot(correlation_id="rpc:foreign-before")
        command = request(
            {
                "id": "rpc:foreign-command",
                "type": "submit_plugin_desired_v1",
                "productId": "coding",
                "scopeId": foreign_layout.scope_id,
                "pluginId": "coding.base",
                "action": "disable",
                "expectedInventoryRevision": before["ownerRevisions"]["desiredState"],
                "operationId": "rpc:foreign-command",
            }
        )
        assert command["success"] is False
        assert command["errorCode"] == "plugin_management_unavailable"
        assert (
            foreign_command.snapshot(correlation_id="rpc:foreign-after")[
                "ownerRevisions"
            ]
            == before["ownerRevisions"]
        )
        repair = request(
            {
                "id": "rpc:foreign-package-repair",
                "type": "repair_plugin_package_v1",
                "productId": "coding",
                "scopeId": foreign_layout.scope_id,
                "operationId": "rpc:foreign-package-repair",
                "action": "inspect-published",
            }
        )
        assert repair["success"] is False
        assert repair["errorCode"] == "coding_management_workspace_changed"
        late_output = StringIO()
        late_scope = CodingPluginRpcSessionScope()
        late_host = RpcHost(
            runtime=CurrentSessionRuntime(),
            stdin=StringIO(),
            stdout=late_output,
            plugin_management_factory=late_scope.bind_management,
            plugin_preview_factory=late_scope.bind_preview,
            plugin_explanation_factory=late_scope.bind_explanation,
            on_plugin_session_bound=late_scope.bind_session,
        )
        assert (
            asyncio.run(
                late_host.submit_input(
                    json.dumps(
                        {
                            "id": "rpc:late-host",
                            "type": "plugin_management_snapshot_v1",
                            "productId": "coding",
                            "scopeId": foreign_layout.scope_id,
                        }
                    )
                )
            )
            == 0
        )
        late_response = json.loads(late_output.getvalue().splitlines()[-1])
        assert late_response["success"] is False
        assert late_response["error"] == "plugin_management_unavailable"
        for command_type, extra, error_code in (
            (
                "preview_current_plugins",
                {"compositionSetId": "coding-standard"},
                "plugin_preview_unavailable",
            ),
            (
                "explain_plugin_operation",
                {"operationId": "rpc:late-explanation"},
                "plugin_explanation_unavailable",
            ),
        ):
            assert (
                asyncio.run(
                    late_host.submit_input(
                        json.dumps(
                            {
                                "id": f"rpc:late:{command_type}",
                                "type": command_type,
                                "productId": "coding",
                                "scopeId": foreign_layout.scope_id,
                                **extra,
                            }
                        )
                    )
                )
                == 0
            )
            late_response = json.loads(late_output.getvalue().splitlines()[-1])
            assert late_response["success"] is False
            assert late_response["errorCode"] == error_code
        foreign_session = _p2_session(
            foreign_workspace, foreign_settings, foreign_base / "sessions"
        )
        assert host.rebind_session(foreign_session) == 0
        assert (
            snapshot(foreign_layout.scope_id, "rpc:rebound-foreign")["success"] is True
        )
    finally:
        if workspace.is_symlink():
            workspace.unlink()
            original.rename(workspace)
        if late_host is not None:
            asyncio.run(late_host.stop())
        asyncio.run(host.stop())
        asyncio.run(session.dispose())
        if foreign_session is not None:
            asyncio.run(foreign_session.dispose())


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_rpc_desired_command_reaches_fenced_product_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, layout, settings = _p2_workspace(tmp_path, monkeypatch)
    session = _p2_session(workspace, settings, tmp_path / "sessions")

    class CurrentSessionRuntime:
        def get_current_session(self):  # type: ignore[no-untyped-def]
            return session

    client = open_coding_plugin_management_command_client(workspace)
    revision = client.snapshot(
        correlation_id="rpc:before", plugin_ids=("coding.base",)
    )["ownerRevisions"]["desiredState"]
    stdout = StringIO()
    host = RpcHost(
        runtime=CurrentSessionRuntime(),
        stdin=StringIO(),
        stdout=stdout,
        plugin_desired_factory=bind_coding_plugin_desired_rpc_client,
        plugin_management_factory=bind_coding_plugin_management_rpc_query,
    )
    generic_stdout = StringIO()
    payload = {
        "type": "submit_plugin_desired_v1",
        "productId": "coding",
        "scopeId": layout.scope_id,
        "pluginId": "coding.base",
        "action": "disable",
        "expectedInventoryRevision": revision,
        "operationId": "rpc:desired:disable-base",
    }
    try:
        for command in (
            {
                "id": "rpc:snapshot",
                "type": "plugin_management_snapshot_v1",
                "productId": "coding",
                "scopeId": layout.scope_id,
                "pluginIds": ["coding.arch.default"],
            },
            {
                "id": "rpc:snapshot-foreign",
                "type": "plugin_management_snapshot_v1",
                "productId": "coding",
                "scopeId": "workspace:other",
            },
            {**payload, "id": "rpc:wrong-scope", "scopeId": "workspace:other"},
            {**payload, "id": "rpc:disable"},
            {**payload, "id": "rpc:disable-replay"},
            {
                **payload,
                "id": "rpc:stale",
                "action": "enable",
                "operationId": "rpc:desired:stale-enable",
            },
            {
                "id": "rpc:operation",
                "type": "plugin_desired_operation_v1",
                "productId": "coding",
                "scopeId": layout.scope_id,
                "operationId": "rpc:desired:disable-base",
            },
        ):
            assert asyncio.run(host.submit_input(json.dumps(command))) == 0
        generic_host = RpcHost(
            runtime=CurrentSessionRuntime(),
            stdin=StringIO(),
            stdout=generic_stdout,
        )
        try:
            assert (
                asyncio.run(
                    generic_host.submit_input(
                        json.dumps(
                            {
                                **payload,
                                "id": "rpc:generic",
                                "action": "enable",
                                "operationId": "rpc:desired:generic-enable",
                            }
                        )
                    )
                )
                == 0
            )
            assert (
                asyncio.run(
                    generic_host.submit_input(
                        json.dumps(
                            {
                                "id": "rpc:generic-snapshot",
                                "type": "plugin_management_snapshot_v1",
                                "productId": "coding",
                                "scopeId": layout.scope_id,
                            }
                        )
                    )
                )
                == 0
            )
        finally:
            asyncio.run(generic_host.stop())
    finally:
        asyncio.run(host.stop())
        asyncio.run(session.dispose())
    responses = {
        item["id"]: item
        for item in (json.loads(line) for line in stdout.getvalue().splitlines())
        if "id" in item
    }
    assert responses["rpc:wrong-scope"]["errorCode"] == (
        "plugin_management_scope_mismatch"
    )
    assert responses["rpc:snapshot-foreign"]["errorCode"] == (
        "plugin_management_scope_mismatch"
    )
    snapshot = responses["rpc:snapshot"]["data"]
    assert snapshot["correlationId"] == "rpc:snapshot"
    assert snapshot["projectionVersion"] == 1
    assert [
        item["installationKey"]["pluginId"] for item in snapshot["installations"]
    ] == ["coding.arch.default"]
    assert snapshot["installations"][0]["backupRetention"]["status"] in {
        "retained",
        "expiry_pending",
        "expired",
        "unknown",
    }
    assert (
        responses["rpc:disable"]["data"]["operation"]["result"]["disposition"]
        == "succeeded"
    )
    assert (
        responses["rpc:disable-replay"]["data"]["operation"]
        == (responses["rpc:disable"]["data"]["operation"])
    )
    assert (
        responses["rpc:stale"]["data"]["operation"]["result"]["errorCode"]
        == "plugin_inventory_revision_conflict"
    )
    assert (
        responses["rpc:operation"]["data"]["operation"]
        == (responses["rpc:disable"]["data"]["operation"])
    )
    assert [
        item["errorCode"]
        for item in (
            json.loads(line) for line in generic_stdout.getvalue().splitlines()
        )
        if "errorCode" in item
    ] == ["unsupported_command", "unsupported_command"]
    assert (
        client.snapshot(correlation_id="rpc:after", plugin_ids=("coding.base",))[
            "installations"
        ][0]["desiredState"]
        == "installed_disabled"
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_management_commands_share_desired_state_across_cli_tui_sdk_and_rpc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from loushang.coding.ui.product_binding import build_coding_ui_controller
    from loushang.harnesstui.conversation.intents import PromptIntent

    workspace, layout, settings = _p2_workspace(tmp_path, monkeypatch)
    sdk = open_coding_plugin_management_command_client(workspace)

    def state() -> tuple[int, str]:
        snapshot = sdk.snapshot(
            correlation_id="test:cross-entry:state", plugin_ids=("coding.base",)
        )
        return (
            snapshot["ownerRevisions"]["desiredState"],
            snapshot["installations"][0]["desiredState"],
        )

    first_revision, first_state = state()
    assert first_state == "installed_enabled"
    code, _output, error = _p2_cli(workspace, "--disable-plugin", "coding.base")
    assert code == 0, error
    cli_revision, cli_state = state()
    assert cli_revision > first_revision
    assert cli_state == "installed_disabled"

    controller = build_coding_ui_controller(
        session=object(), plugin_workspace=workspace
    )
    ui_result = asyncio.run(
        controller.dispatch(PromptIntent(text="/plugins enable coding.base"))
    )
    assert ui_result.error_message is None
    assert (ui_result.status_message or "").startswith("Plugin enable succeeded: ")
    ui_operation_id = (
        (ui_result.status_message or "").split(": ", 1)[1].split(";", 1)[0]
    )
    ui_revision, ui_state = state()
    assert ui_revision > cli_revision
    assert ui_state == "installed_enabled"
    with pytest.raises(PluginDesiredCommandRepairError) as foreign_ui:
        sdk.repair_own_desired_operation(
            ui_operation_id, correlation_id="test:cross-entry:foreign-ui"
        )
    assert foreign_ui.value.code == "plugin_management_repair_foreign_operation"

    sdk_result = sdk.submit_desired(
        plugin_id="coding.base",
        action="disable",
        expected_inventory_revision=ui_revision,
        operation_id="sdk:cross-entry:disable",
        correlation_id="test:cross-entry:sdk-disable",
    )
    assert sdk_result["operation"]["result"]["disposition"] == "succeeded"
    sdk_revision, sdk_state = state()
    assert sdk_revision > ui_revision
    assert sdk_state == "installed_disabled"

    session = _p2_session(workspace, settings, tmp_path / "rpc-session")

    class CurrentSessionRuntime:
        def get_current_session(self):  # type: ignore[no-untyped-def]
            return session

    stdout = StringIO()
    host = RpcHost(
        runtime=CurrentSessionRuntime(),
        stdin=StringIO(),
        stdout=stdout,
        plugin_desired_factory=bind_coding_plugin_desired_rpc_client,
    )
    try:
        assert (
            asyncio.run(
                host.submit_input(
                    json.dumps(
                        {
                            "id": "rpc:cross-entry:enable",
                            "type": "submit_plugin_desired_v1",
                            "productId": "coding",
                            "scopeId": layout.scope_id,
                            "pluginId": "coding.base",
                            "action": "enable",
                            "expectedInventoryRevision": sdk_revision,
                            "operationId": "rpc:cross-entry:enable",
                        }
                    )
                )
            )
            == 0
        )
    finally:
        asyncio.run(host.stop())
        asyncio.run(session.dispose())
    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    response = next(
        item for item in responses if item.get("id") == "rpc:cross-entry:enable"
    )
    assert response["data"]["operation"]["result"]["disposition"] == "succeeded"
    final_revision, final_state = state()
    assert final_revision > sdk_revision
    assert final_state == "installed_enabled"
    with pytest.raises(PluginDesiredCommandRepairError) as foreign_rpc:
        sdk.repair_own_desired_operation(
            "rpc:cross-entry:enable",
            correlation_id="test:cross-entry:foreign-rpc",
        )
    assert foreign_rpc.value.code == "plugin_management_repair_foreign_operation"
    stale = sdk.submit_desired(
        plugin_id="coding.base",
        action="disable",
        expected_inventory_revision=ui_revision,
        operation_id="sdk:cross-entry:stale",
        correlation_id="test:cross-entry:stale",
    )
    assert stale["operation"]["result"]["errorCode"] == (
        "plugin_inventory_revision_conflict"
    )
    assert state() == (final_revision, final_state)

    fresh = _p2_session(workspace, settings, tmp_path / "fresh-session")
    try:
        assert fresh._coding_base_product_compilation is not None
    finally:
        asyncio.run(fresh.dispose())


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_rpc_repairs_its_interrupted_desired_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, layout, settings = _p2_workspace(tmp_path, monkeypatch)
    session = _p2_session(workspace, settings, tmp_path / "sessions")

    class CurrentSessionRuntime:
        def get_current_session(self):  # type: ignore[no-untyped-def]
            return session

    client = open_coding_plugin_management_command_client(workspace)
    revision = client.snapshot(
        correlation_id="rpc:repair:before", plugin_ids=("coding.base",)
    )["ownerRevisions"]["desiredState"]
    original_commit = PluginDesiredStateLedger.commit
    crashed = False

    def commit_then_crash(
        self: PluginDesiredStateLedger, mutation: PluginDesiredStateMutationV1
    ):
        nonlocal crashed
        result = original_commit(self, mutation)
        if mutation.operation_id == "rpc:crash:disable-base" and not crashed:
            crashed = True
            raise RuntimeError("simulated RPC crash after Desired commit")
        return result

    monkeypatch.setattr(PluginDesiredStateLedger, "commit", commit_then_crash)
    stdout = StringIO()
    host = RpcHost(
        runtime=CurrentSessionRuntime(),
        stdin=StringIO(),
        stdout=stdout,
        plugin_desired_factory=bind_coding_plugin_desired_rpc_client,
    )
    try:
        assert (
            asyncio.run(
                host.submit_input(
                    json.dumps(
                        {
                            "id": "rpc:crash",
                            "type": "submit_plugin_desired_v1",
                            "productId": "coding",
                            "scopeId": layout.scope_id,
                            "pluginId": "coding.base",
                            "action": "disable",
                            "expectedInventoryRevision": revision,
                            "operationId": "rpc:crash:disable-base",
                        }
                    )
                )
            )
            == 0
        )
        assert (
            client.operation("rpc:crash:disable-base", correlation_id="rpc:running")[
                "operation"
            ]["status"]
            == "running"
        )
        assert (
            asyncio.run(
                host.submit_input(
                    json.dumps(
                        {
                            "id": "rpc:wrong-repair",
                            "type": "repair_plugin_desired_v1",
                            "productId": "coding",
                            "scopeId": "workspace:other",
                            "operationId": "rpc:crash:disable-base",
                        }
                    )
                )
            )
            == 0
        )
        assert (
            asyncio.run(
                host.submit_input(
                    json.dumps(
                        {
                            "id": "rpc:repair",
                            "type": "repair_plugin_desired_v1",
                            "productId": "coding",
                            "scopeId": layout.scope_id,
                            "operationId": "rpc:crash:disable-base",
                        }
                    )
                )
            )
            == 0
        )
    finally:
        asyncio.run(host.stop())
        asyncio.run(session.dispose())
    responses = {
        item["id"]: item
        for item in (json.loads(line) for line in stdout.getvalue().splitlines())
        if "id" in item
    }
    assert responses["rpc:crash"]["errorCode"] == "plugin_management_unavailable"
    assert responses["rpc:wrong-repair"]["errorCode"] == (
        "plugin_management_scope_mismatch"
    )
    repaired = responses["rpc:repair"]["data"]
    assert repaired["disposition"] == "replayed_pending"
    assert repaired["statusBefore"] == "running"
    assert repaired["result"]["operation"]["result"]["disposition"] == ("succeeded")
    assert (
        client.snapshot(correlation_id="rpc:repair:after", plugin_ids=("coding.base",))[
            "installations"
        ][0]["desiredState"]
        == "installed_disabled"
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_two_external_data_skills_share_one_product_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, layout, settings = _p2_workspace(tmp_path, monkeypatch)
    for plugin_id, skill_name in (("reviewpack", "review"), ("auditpack", "audit")):
        source = _p2_wheel_source(tmp_path, plugin_id=plugin_id, skill_name=skill_name)
        for args in (
            ("--install-package", str(source), "--package-scope", "project"),
            ("--enable-plugin", plugin_id),
        ):
            code, _stdout, stderr = _p2_cli(workspace, *args)
            assert code == 0, stderr
    session = _p2_session(workspace, settings, tmp_path / "sessions")
    opened = [session]
    try:
        a_before_update = _p2_installation(layout, workspace, "reviewpack")
        b_before_update = _p2_installation(layout, workspace, "auditpack")
        assert session.resource_bundle is not None
        external = {
            item.name: item
            for item in session.resource_bundle.skills
            if item.source_kind == "external_package"
        }
        assert {"standard", "review", "audit"} <= set(external)
        assert all(item.revision_ref is not None for item in external.values())
        inputs = session._capability_composition_inputs
        assert inputs is not None
        assert {"coding.base", "reviewpack", "auditpack"} <= {
            item.plugin_id for item in inputs.product_composition.resource_admissions
        }

        loaded = {}
        for name in ("review", "audit"):
            preflight = _p2_preflight(session, name)
            assert len(preflight.loaded_skills) == 1
            body = preflight.loaded_skills[0]
            assert body.summary.source_kind == "external_package"
            assert body.summary.revision_ref == external[name].revision_ref
            assert body.receipt.content_digest == body.summary.expected_content_digest
            loaded[name] = body
        assert loaded["review"].summary.catalog_generation == (
            loaded["audit"].summary.catalog_generation
        )
        assert "# Review v1" in loaded["review"].content
        assert "# Audit v1" in loaded["audit"].content
        old_consumer = session._skill_catalog_consumer
        assert old_consumer is not None
        old_generation = old_consumer.catalog_generation

        replacement = _p2_wheel_source(
            tmp_path, plugin_id="reviewpack", skill_name="review", version_id="2"
        )
        code, _stdout, stderr = _p2_cli(
            workspace,
            "--update-package",
            str(replacement),
            "--package-scope",
            "project",
        )
        assert code == 0, stderr
        replacement.unlink()
        assert not replacement.exists()
        listing = _p2_list_plugins(workspace)
        assert (
            listing["reviewpack"]["version"],
            listing["reviewpack"]["desiredState"],
        ) == ("2", "installed_enabled")
        assert (
            listing["auditpack"]["version"],
            listing["auditpack"]["desiredState"],
        ) == ("1", "installed_enabled")
        assert _p2_installation(layout, workspace, "auditpack") == b_before_update
        a_before_remove = _p2_installation(layout, workspace, "reviewpack")
        assert a_before_remove.selection.package_revision.plugin_version == "2"
        assert session._skill_catalog_consumer is old_consumer
        assert old_consumer.catalog_generation == old_generation
        assert session.resource_bundle is not None
        old_bundle_skills = {item.name: item for item in session.resource_bundle.skills}
        for name in ("review", "audit"):
            assert old_bundle_skills[name].revision_ref == external[name].revision_ref
            current_summary = old_consumer.get_effective_skill(name)
            assert current_summary is not None
            assert current_summary.revision_ref == loaded[name].summary.revision_ref
        updated = _p2_session(workspace, settings, tmp_path / "updated-sessions")
        opened.append(updated)
        assert updated.resource_bundle is not None
        updated_skills = {item.name: item for item in updated.resource_bundle.skills}
        assert updated_skills["review"].revision_ref != external["review"].revision_ref
        assert updated_skills["audit"].revision_ref == external["audit"].revision_ref
        assert (
            "# Review v2" in _p2_preflight(updated, "review").loaded_skills[0].content
        )
        assert "# Audit v1" in _p2_preflight(updated, "audit").loaded_skills[0].content

        b_before_disable = _p2_installation(layout, workspace, "auditpack")
        code, _stdout, stderr = _p2_cli(workspace, "--disable-plugin", "auditpack")
        assert code == 0, stderr
        assert _p2_installation(layout, workspace, "reviewpack") == a_before_remove
        listing = _p2_list_plugins(workspace)
        assert listing["reviewpack"]["desiredState"] == "installed_enabled"
        assert listing["reviewpack"]["version"] == "2"
        assert listing["auditpack"]["desiredState"] == "installed_disabled"
        review_only = _p2_session(
            workspace, settings, tmp_path / "review-only-sessions"
        )
        opened.append(review_only)
        assert (
            "# Review v2"
            in _p2_preflight(review_only, "review").loaded_skills[0].content
        )
        assert _p2_preflight(review_only, "audit").loaded_skills == ()

        assert _p2_installation(layout, workspace, "reviewpack") == a_before_remove
        code, _stdout, stderr = _p2_cli(
            workspace,
            "--uninstall-package",
            "reviewpack",
            "--package-scope",
            "project",
        )
        assert code == 0, stderr
        listing = _p2_list_plugins(workspace)
        assert listing["reviewpack"]["desiredState"] == "absent"
        assert listing["auditpack"]["desiredState"] == "installed_disabled"
        assert _p2_installation(
            layout, workspace, "auditpack"
        ).selection.package_revision == (b_before_disable.selection.package_revision)
        neither = _p2_session(workspace, settings, tmp_path / "neither-sessions")
        opened.append(neither)
        assert _p2_preflight(neither, "review").loaded_skills == ()
        assert _p2_preflight(neither, "audit").loaded_skills == ()

        code, _stdout, stderr = _p2_cli(workspace, "--enable-plugin", "auditpack")
        assert code == 0, stderr
        audit_only = _p2_session(workspace, settings, tmp_path / "audit-only-sessions")
        opened.append(audit_only)
        assert _p2_preflight(audit_only, "review").loaded_skills == ()
        audit_restored = _p2_preflight(audit_only, "audit").loaded_skills[0]
        assert "# Audit v1" in audit_restored.content
        assert audit_restored.summary.revision_ref == external["audit"].revision_ref

        owner = open_coding_fenced_product_application_owner(
            layout,
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=2,
        )
        try:
            management = owner.runtime_owner.product_owner.management
            intents = PluginRetirementIntentLedger(
                management.retirement_intent_journal_path
            )
            sets = PluginRetirementSetLedger(
                management.retirement_set_journal_path,
                retirement_intents=intents,
            ).snapshot()
            subjects = {
                (
                    item.trigger,
                    item.source_transition.mutation.installation_key.plugin_id,
                ): item
                for item in intents.snapshot().intents
            }
            assert {
                ("update", "reviewpack"),
                ("disable", "auditpack"),
                ("remove", "reviewpack"),
            } <= set(subjects)
            for subject, predecessor in (
                (("update", "reviewpack"), a_before_update),
                (("disable", "auditpack"), b_before_disable),
                (("remove", "reviewpack"), a_before_remove),
            ):
                intent = subjects[subject]
                assert intent.source_transition.mutation.installation_key == (
                    predecessor.installation_key
                )
                assert intent.instance_revision_ref == (
                    predecessor.selection.instance_revision_ref
                )
                assert intent.package_revision == predecessor.selection.package_revision
                settlement = sets.retirement_set(intent.retirement_id)
                assert settlement is not None and settlement.intent == intent
        finally:
            owner.close()
    finally:
        for opened_session in reversed(opened):
            asyncio.run(opened_session.dispose())


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_two_external_data_skills_conflict_without_loading_a_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, layout, settings = _p2_workspace(tmp_path, monkeypatch)
    for plugin_id in ("reviewpack", "auditpack"):
        source = _p2_wheel_source(
            tmp_path,
            plugin_id=plugin_id,
            skill_name="review",
        )
        for args in (
            ("--install-package", str(source), "--package-scope", "project"),
            ("--enable-plugin", plugin_id),
        ):
            code, _stdout, stderr = _p2_cli(workspace, *args)
            assert code == 0, stderr
    with CodingFencedProductReadOnlyPreviewOwner.open(layout) as preview_owner:
        blocked_preview = preview_owner.preview_current_data_resources(
            workspace=workspace, composition_set_id="coding-standard"
        )
    assert blocked_preview.disposition == "blocked"
    assert blocked_preview.blocking_owner == "product_composition"
    assert blocked_preview.blocking_code == "duplicate_owner_contribution_identity"
    assert len(set(blocked_preview.blocking_admission_fingerprints)) == 2
    assert blocked_preview.catalog_resources == ()
    with pytest.raises(ProductCompositionError) as collision:
        _p2_session(workspace, settings, tmp_path / "conflict-sessions")
    assert collision.value.code == "duplicate_owner_contribution_identity"
    assert len(set(collision.value.admission_fingerprints)) == 2
    listing = _p2_list_plugins(workspace)
    assert listing["reviewpack"]["desiredState"] == "installed_enabled"
    assert listing["auditpack"]["desiredState"] == "installed_enabled"
    code, _stdout, stderr = _p2_cli(workspace, "--disable-plugin", "auditpack")
    assert code == 0, stderr
    remaining = _p2_session(workspace, settings, tmp_path / "resolved-sessions")
    try:
        loaded = _p2_preflight(remaining, "review").loaded_skills
        assert len(loaded) == 1
        assert "# Review v1" in loaded[0].content
        owner = open_coding_fenced_product_application_owner(
            layout,
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=2,
        )
        try:
            key = PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=layout.scope_id,
                plugin_id="reviewpack",
            )
            revision = (
                owner.runtime_owner.product_owner.desired_state.snapshot()
                .installation(key)
                .selection.package_revision
            )
            assert revision is not None
            assert revision.package_source_identity.endswith(
                "/reviewpack-1-py3-none-any.whl"
            )
            assert loaded[0].summary.revision_ref is not None
            assert loaded[0].summary.revision_ref.content_digest == (
                revision.package_content_digest
            )
        finally:
            owner.close()
    finally:
        asyncio.run(remaining.dispose())


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_two_external_data_skills_reject_bad_update_without_changing_peer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, layout, settings = _p2_workspace(tmp_path, monkeypatch)
    for plugin_id, skill_name in (("reviewpack", "review"), ("auditpack", "audit")):
        source = _p2_wheel_source(tmp_path, plugin_id=plugin_id, skill_name=skill_name)
        for args in (
            ("--install-package", str(source), "--package-scope", "project"),
            ("--enable-plugin", plugin_id),
        ):
            code, _stdout, stderr = _p2_cli(workspace, *args)
            assert code == 0, stderr
    owner = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    try:
        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=layout.scope_id,
            plugin_id="auditpack",
        )
        before = (
            owner.runtime_owner.product_owner.desired_state.snapshot().installation(key)
        )
    finally:
        owner.close()
    bad = _p2_wheel_source(
        tmp_path,
        plugin_id="reviewpack",
        skill_name="review",
        version_id="2",
        executable_member=True,
    )
    code, _stdout, stderr = _p2_cli(
        workspace,
        "--update-package",
        str(bad),
        "--package-scope",
        "project",
    )
    assert code == 1
    assert "package_plugin_contribution_rejected" in stderr
    owner = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    try:
        after = owner.runtime_owner.product_owner.desired_state.snapshot().installation(
            key
        )
        assert after == before
    finally:
        owner.close()
    listing = _p2_list_plugins(workspace)
    assert listing["reviewpack"]["version"] == "1"
    assert listing["auditpack"]["version"] == "1"
    session = _p2_session(workspace, settings, tmp_path / "after-bad-update")
    try:
        assert (
            "# Review v1" in _p2_preflight(session, "review").loaded_skills[0].content
        )
        assert "# Audit v1" in _p2_preflight(session, "audit").loaded_skills[0].content
    finally:
        asyncio.run(session.dispose())


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_interrupted_a_update_cannot_overwrite_b_disable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, layout, settings = _p2_workspace(tmp_path, monkeypatch)
    for plugin_id, skill_name in (("reviewpack", "review"), ("auditpack", "audit")):
        source = _p2_wheel_source(tmp_path, plugin_id=plugin_id, skill_name=skill_name)
        for args in (
            ("--install-package", str(source), "--package-scope", "project"),
            ("--enable-plugin", plugin_id),
        ):
            code, _stdout, stderr = _p2_cli(workspace, *args)
            assert code == 0, stderr
    replacement = _p2_wheel_source(
        tmp_path, plugin_id="reviewpack", skill_name="review", version_id="2"
    )
    source_record = admit_coding_external_data_wheel(layout, source=replacement)
    owner = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    product = owner.runtime_owner.product_owner
    runtime_id = "interrupted-a-update"
    factory = product.factory_for_session(
        session_id=runtime_id, cwd=workspace, runtime_id=runtime_id
    )
    runtime = factory.create(
        PackageProductRuntimeRequestV1(
            product_id="coding", session_id=runtime_id, cwd=str(workspace)
        )
    )
    try:
        runtime.activate()
        original_finalize = PackageProductHandoffFinalizer.finalize

        def interrupt(owner, request, *, current):  # type: ignore[no-untyped-def]
            if current.operation_id == "test:interrupted-a-update":
                raise OSError("injected interruption before first handoff")
            return original_finalize(owner, request, current=current)

        with monkeypatch.context() as patch:
            patch.setattr(PackageProductHandoffFinalizer, "finalize", interrupt)
            with pytest.raises(OSError, match="injected interruption"):
                runtime.lifecycle.route(
                    PackageProductLifecycleIntentV1(
                        operation_id="test:interrupted-a-update",
                        action="update",
                        source=str(
                            owner.epoch_runtime.control_root
                            / "product-sources"
                            / source_record.wheel_filename
                        ),
                        scope="project",
                    ),
                    entrypoint="cli",
                )
        anchor = product.gc_bindings.update_anchor("test:interrupted-a-update")
        assert anchor is not None
        assert anchor.expected_package_revision.plugin_version == "1"
        snapshot = product.desired_state.snapshot()
        b_key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=layout.scope_id,
            plugin_id="auditpack",
        )
        disabled = product.management.submit(
            PluginManagementCommandV1(
                action="disable",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="test:disable-b-during-a-update",
                    idempotency_key="test:disable-b-during-a-update",
                    expected_inventory_revision=snapshot.inventory_revision,
                    installation_key=b_key,
                    desired_state="installed_disabled",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision="test",
                ),
            )
        )
        assert disabled.result is not None
        assert disabled.result.disposition == "succeeded"
        disabled_revision = product.desired_state.snapshot().inventory_revision
        with suppress(RuntimeError):
            runtime.activate()
        settled = product.desired_state.snapshot()
        a_key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=layout.scope_id,
            plugin_id="reviewpack",
        )
        assert (
            settled.installation(a_key).selection.package_revision.plugin_version == "1"
        )
        assert (
            settled.installation(b_key).selection.desired_state == "installed_disabled"
        )
        assert settled.installation(b_key).selection.package_revision == (
            snapshot.installation(b_key).selection.package_revision
        )
    finally:
        runtime.dispose_runtime()
        owner.close()
    session = _p2_session(workspace, settings, tmp_path / "after-interruption")
    try:
        assert (
            "# Review v1" in _p2_preflight(session, "review").loaded_skills[0].content
        )
        assert _p2_preflight(session, "audit").loaded_skills == ()
    finally:
        asyncio.run(session.dispose())
    handoff = PackageRetentionHandoffJournal(product.state_root / "handoff.jsonl")
    matching = [
        item.receipt
        for item in handoff.records()
        if item.receipt is not None
        and item.receipt.request.operation_id == "test:interrupted-a-update"
    ]
    assert matching
    recovered = matching[-1]
    assert recovered.state == "aborted"
    assert recovered.desired_receipt is None
    assert recovered.desired_failure is not None
    assert recovered.desired_failure.code == "package_desired_revision_conflict"
    assert recovered.desired_failure.request.expected_inventory_revision == (
        anchor.expected_inventory_revision
    )
    assert recovered.desired_failure.observed_inventory_revision == disabled_revision
    assert recovered.dependency_pin_receipt is not None
    assert recovered.dependency_pin_receipt.state == "aborted"
