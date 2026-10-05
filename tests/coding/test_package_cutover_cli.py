from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal
from unittest.mock import patch

import pytest

from loushang.ai.model import Capabilities, Model
from loushang.coding import package_legacy_removed_adoption as removed_adoption_module
from loushang.coding import package_legacy_source_consumption as source_consumption
from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding._resource_catalog_shadow import (
    CodingResourceCatalogAdmissionError,
)
from loushang.coding.bootstrap import create_agent_session, create_services
from loushang.coding.cli.package_cutover import main as cutover_main
from loushang.coding.control.settings_store import (
    default_global_settings_path,
    default_project_settings_path,
)
from loushang.coding.package_epoch_layout import (
    resolve_coding_lifecycle_pre_b_members,
    resolve_coding_package_epoch_layout,
)
from loushang.coding.package_legacy_binding_catalog import CodingLegacyBindingError
from loushang.coding.package_legacy_builtin_review import (
    CodingLegacyBuiltinOnlyReviewV1,
)
from loushang.coding.package_legacy_lock_evidence import (
    parse_coding_legacy_local_binding_heads,
)
from loushang.coding.package_legacy_removed_adoption import (
    adopt_coding_first_b_removed_local,
)
from loushang.coding.package_legacy_removed_review import (
    CodingLegacyRemovedReviewV1,
    admit_coding_removed_local_snapshot,
    review_coding_first_b_removed_local,
)
from loushang.coding.package_legacy_review import (
    CodingLegacyLocalAdoptionReviewV1,
)
from loushang.coding.package_pre_b_snapshot import (
    prepare_and_cutover_coding_package_store_from_legacy,
    prepare_coding_package_cutover_roots,
)
from loushang.coding.package_product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    _bootstrap_coding_builtin_plugin,
    open_coding_fenced_product_application_owner,
)
from loushang.coding.session_manager import SessionManager
from loushang.coding.ui.plugin_theme import select_coding_plugin_theme
from loushang.foundation.platform_paths import resolve_platform_paths
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management.instance_records import (
    PluginInstanceLeaseFamilyReleaseV1,
    PluginInstanceRetirementCompletionV1,
)
from loushang.harness.plugin_management.instance_runtime import (
    PluginInstanceRuntimeLedger,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.plugin_management.retirement import (
    PluginRetirementIntentLedger,
    PluginRetirementIntentV1,
)
from loushang.harness.plugin_management.retirement_sets import (
    PluginOwnerRetirementOutcomeV1,
    PluginOwnerRetirementPlanV1,
    PluginOwnerRetirementTargetV1,
    PluginRetirementSetLedger,
)
from loushang.harness.plugin_management.security_acceptance import (
    PluginInstanceSecurityRetirementJournal,
)
from loushang.harness.plugin_management.service import PluginManagementService
from loushang.harness.plugin_management.updates import (
    PluginDesiredStateUpdateMutationV1,
    PluginManagementUpdateCommandV2,
    PluginMigrationFenceV1,
)
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.plugin import package, resource
from loushang.tui import LoushangWelcomePanel, RenderConstraints


def _old_installed_local_source(
    tmp_path: Path,
    lifecycle,
    *,
    resource_kind: str = "skill",
    old_enabled: bool = True,
    legacy_manifest_disabled: bool = False,
    theme_document: str | None = None,
) -> tuple[Path, str]:
    prepare_coding_package_cutover_roots(lifecycle)
    source = tmp_path / "old-source"
    source.mkdir()
    locator = (
        "skills/review"
        if resource_kind == "skill"
        else "prompts/review.md"
        if resource_kind == "prompt"
        else "themes/review.json"
    )
    contribution = (
        resource.skill(contribution_id="review-skill", locator=locator)
        if resource_kind == "skill"
        else resource.prompt(contribution_id="review-prompt", locator=locator)
        if resource_kind == "prompt"
        else resource.theme(contribution_id="review-theme", locator=locator)
    )
    compiled = package(id="review-pack", version="1", contributions=(contribution,))
    for artifact in compiled.artifacts:
        target = source / artifact.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(artifact.content)
    if legacy_manifest_disabled:
        manifest_path = source / "plugin.json"
        manifest = json.loads(manifest_path.read_text())
        manifest.pop("manifestVersion")
        manifest.pop("engine")
        manifest["enabled"] = False
        manifest_path.write_text(json.dumps(manifest))
    content = source / (
        "skills/review/SKILL.md"
        if resource_kind == "skill"
        else "prompts/review.md"
        if resource_kind == "prompt"
        else "themes/review.json"
    )
    content.parent.mkdir(parents=True, exist_ok=True)
    content.write_text(
        "---\nname: review\ndescription: review files\n---\n# Review\n"
        if resource_kind == "skill"
        else "# Review\nCheck the change.\n"
        if resource_kind == "prompt"
        else (
            theme_document
            if theme_document is not None
            else json.dumps(
                {"schemaVersion": 1, "tokens": {"welcome.title": {"color": "red"}}}
            )
        )
    )
    old_package = tmp_path / "old-package"
    materializer = PackageMaterializer(install_root=old_package / "installed")
    published = materializer.publish_plugin_packages(
        (PluginManifestParser().parse(source),)
    )
    try:
        materializer.bind_plugin_packages(published)
    finally:
        published[0].revision_handle.close()
    lock_bytes = (old_package / "package-lock.json").read_bytes()
    (lifecycle.package_root / "package-lock.json").write_bytes(lock_bytes)
    [binding] = parse_coding_legacy_local_binding_heads(lock_bytes)
    revision = PluginPackageRevisionRefV1(
        plugin_id=binding.plugin_id,
        plugin_version="1",
        package_content_digest=binding.content_digest,
        dependency_lock_digest=binding.dependency_lock.digest,
        package_source_identity=binding.source_identity,
    )
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=lifecycle.scope_id,
        plugin_id=binding.plugin_id,
    )
    old_desired = tmp_path / "old-desired.jsonl"
    ledger = PluginDesiredStateLedger(old_desired)
    ledger.commit(
        PluginDesiredStateMutationV1(
            operation_id="old-install",
            idempotency_key="old-install",
            expected_inventory_revision=0,
            installation_key=key,
            desired_state="installed_disabled",
            package_revision=revision,
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    if old_enabled:
        ledger.commit(
            PluginDesiredStateMutationV1(
                operation_id="old-enable",
                idempotency_key="old-enable",
                expected_inventory_revision=1,
                installation_key=key,
                desired_state="installed_enabled",
                package_revision=None,
                actor_id="old-operator",
                policy_revision="old-policy:1",
            )
        )
    lifecycle.desired_state.write_bytes(old_desired.read_bytes())
    return source, binding.plugin_id


def _commit_old_update(
    ledger: PluginDesiredStateLedger,
    key: PluginInstallationKeyV1,
    expected: PluginPackageRevisionRefV1,
    staged: PluginPackageRevisionRefV1,
    *,
    operation_id: str,
    desired_state: Literal["installed_disabled", "installed_enabled"] = (
        "installed_disabled"
    ),
) -> None:
    command = PluginManagementUpdateCommandV2(
        operation_id=operation_id,
        idempotency_key=operation_id,
        expected_inventory_revision=ledger.snapshot().inventory_revision,
        installation_key=key,
        expected_package_revision=expected,
        staged_package_revision=staged,
        actor_id="old-operator",
        policy_revision="old-policy:1",
    )
    ledger.commit_update(
        PluginDesiredStateUpdateMutationV1(
            command=command,
            desired_state=desired_state,
            migration_fence=PluginMigrationFenceV1(
                fence_id=operation_id,
                installation_key=key,
                expected_package_revision=expected,
                staged_package_revision=staged,
            ),
        )
    )


def _settle_old_retirement(
    sets: PluginRetirementSetLedger,
    intent: PluginRetirementIntentV1,
    *,
    suffix: str,
    disposition: Literal["succeeded", "terminal_failure"] = "succeeded",
) -> None:
    target = PluginOwnerRetirementTargetV1.create(
        owner_reference=f"owner:{suffix}",
        owner_generation_reference=f"generation:{suffix}",
        retirement_handle=f"retirement:{suffix}",
        contribution_ids=("contribution:review-skill",),
    )
    sets.commit_plan(
        PluginOwnerRetirementPlanV1.create(
            retirement_id=intent.retirement_id,
            owner_closure_reference=f"closure:{suffix}",
            targets=(target,),
        )
    )
    sets.record_outcome(
        PluginOwnerRetirementOutcomeV1(
            retirement_id=intent.retirement_id,
            target_id=target.target_id,
            operation_id=f"old-owner-retire:{suffix}",
            idempotency_key=f"old-owner-retire:{suffix}",
            attempt=1,
            disposition=disposition,
            result_code="owner_retirement_done",
            owner_outcome_reference=f"outcome:{suffix}",
        )
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX first-B review")
@pytest.mark.parametrize(
    ("reinstalled", "retained_store"),
    ((False, False), (True, False), (False, True)),
)
def test_removed_old_local_review_binds_install_and_remove_history(
    tmp_path: Path,
    reinstalled: bool,
    retained_store: bool,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    _source, plugin_id = _old_installed_local_source(
        tmp_path, lifecycle, old_enabled=False
    )
    if retained_store:
        shutil.copytree(
            tmp_path / "old-package" / "plugin-revisions",
            lifecycle.package_root / "plugin-revisions",
        )
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=lifecycle.scope_id,
        plugin_id=plugin_id,
    )
    old_desired = tmp_path / "old-desired-removed.jsonl"
    old_desired.write_bytes(lifecycle.desired_state.read_bytes())
    old_ledger = PluginDesiredStateLedger(old_desired)
    old_ledger.commit(
        PluginDesiredStateMutationV1(
            operation_id="old-remove",
            idempotency_key="old-remove",
            expected_inventory_revision=1,
            installation_key=key,
            desired_state="absent",
            package_revision=None,
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    final_install_id = "old-install"
    final_remove_id = "old-remove"
    if reinstalled:
        [binding] = parse_coding_legacy_local_binding_heads(
            (lifecycle.package_root / "package-lock.json").read_bytes()
        )
        final_install_id = "old-reinstall"
        final_remove_id = "old-remove-again"
        old_ledger.commit(
            PluginDesiredStateMutationV1(
                operation_id=final_install_id,
                idempotency_key=final_install_id,
                expected_inventory_revision=2,
                installation_key=key,
                desired_state="installed_disabled",
                package_revision=PluginPackageRevisionRefV1(
                    plugin_id=plugin_id,
                    plugin_version="1",
                    package_content_digest=binding.content_digest,
                    dependency_lock_digest=binding.dependency_lock.digest,
                    package_source_identity=binding.source_identity,
                ),
                actor_id="old-operator",
                policy_revision="old-policy:1",
            )
        )
        old_ledger.commit(
            PluginDesiredStateMutationV1(
                operation_id=final_remove_id,
                idempotency_key=final_remove_id,
                expected_inventory_revision=3,
                installation_key=key,
                desired_state="absent",
                package_revision=None,
                actor_id="old-operator",
                policy_revision="old-policy:1",
            )
        )
    lifecycle.desired_state.write_bytes(old_desired.read_bytes())
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / "settings.json",
    )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    namespace_id = sha256(
        b"loushang.coding-fresh-product-epoch/v1\0" + epoch.store_id.encode()
    ).hexdigest()
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id=namespace_id,
        minimum_runtime_version=version("loushang"),
        minimum_runtime_protocol_epoch=(CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH),
        snapshot_admission=lambda prepared, snapshot: (
            admit_coding_removed_local_snapshot(lifecycle, prepared, snapshot)
        ),
    )
    assert cutover.attempt.result.disposition == "fenced"
    owner = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
        read_only=True,
    )
    try:
        review = review_coding_first_b_removed_local(
            lifecycle, owner, settings_manager=settings
        )
    finally:
        owner.close()
    assert review.removed_local[0].plugin_id == plugin_id
    assert review.removed_local[0].install_operation_id == final_install_id
    assert review.removed_local[0].remove_operation_id == final_remove_id
    assert review.review_version == 1
    assert review.retained_store_roots == (
        ("plugin-revisions",) if retained_store else ()
    )
    assert CodingLegacyRemovedReviewV1.from_dict(review.to_dict()) == review
    changed = review.to_dict()
    changed["reviewId"] = "0" * 64
    with pytest.raises(ValueError, match="ID changed"):
        CodingLegacyRemovedReviewV1.from_dict(changed)
    receipt = adopt_coding_first_b_removed_local(
        lifecycle,
        settings,
        workspace=workspace,
        accepted_review_id=review.review_id,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    assert receipt.review == review
    assert (
        adopt_coding_first_b_removed_local(
            lifecycle,
            settings,
            workspace=workspace,
            accepted_review_id=review.review_id,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        == receipt
    )
    product = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        states = {
            item.installation_key.plugin_id: item.selection.desired_state
            for item in product.runtime_owner.product_owner.desired_state.snapshot().installations
        }
    finally:
        product.close()
    assert states[plugin_id] == "absent"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize("matching_head", (False, True))
def test_removed_updated_local_review_binds_final_update_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    matching_head: bool,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    _source, plugin_id = _old_installed_local_source(
        tmp_path, lifecycle, old_enabled=False
    )
    [binding] = parse_coding_legacy_local_binding_heads(
        (lifecycle.package_root / "package-lock.json").read_bytes()
    )
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=lifecycle.scope_id,
        plugin_id=plugin_id,
    )
    original = PluginPackageRevisionRefV1(
        plugin_id=plugin_id,
        plugin_version="0",
        package_content_digest="e" * 64,
        dependency_lock_digest="d" * 64,
        package_source_identity=binding.source_identity,
    )
    updated = PluginPackageRevisionRefV1(
        plugin_id=plugin_id,
        plugin_version="1",
        package_content_digest=(binding.content_digest if matching_head else "f" * 64),
        dependency_lock_digest=binding.dependency_lock.digest,
        package_source_identity=binding.source_identity,
    )
    old_path = tmp_path / "old-updated-desired.jsonl"
    old_desired = PluginDesiredStateLedger(old_path)
    old_desired.commit(
        PluginDesiredStateMutationV1(
            operation_id="old-install",
            idempotency_key="old-install",
            expected_inventory_revision=0,
            installation_key=key,
            desired_state="installed_disabled",
            package_revision=original,
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    _commit_old_update(old_desired, key, original, updated, operation_id="old-update")
    old_desired.commit(
        PluginDesiredStateMutationV1(
            operation_id="old-remove",
            idempotency_key="old-remove",
            expected_inventory_revision=2,
            installation_key=key,
            desired_state="absent",
            package_revision=None,
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    lifecycle.desired_state.write_bytes(old_path.read_bytes())
    command_prefix = ("--workspace", str(workspace))
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    result = cutover_main((*command_prefix, "--prepare-legacy-removed-review"))
    if not matching_head:
        assert result == 1
        assert capsys.readouterr().out == ""
        assert not (epoch.control_root / "epoch.jsonl").exists()
        return
    assert result == 0
    review = json.loads(capsys.readouterr().out)
    assert review["reviewVersion"] == 2
    assert review["removedLocal"] == [
        {
            "pluginId": plugin_id,
            "sourceIdentity": binding.source_identity,
            "contentDigest": binding.content_digest,
            "manifestDigest": binding.manifest_digest,
            "dependencyLockDigest": binding.dependency_lock.digest,
            "bindingDigest": binding.binding_digest,
            "installOperationId": "old-install",
            "headOperationId": "old-update",
            "headTransitionKind": "update",
            "removeOperationId": "old-remove",
        }
    ]
    assert CodingLegacyRemovedReviewV1.from_dict(review).to_dict() == review
    changed = json.loads(json.dumps(review))
    changed["removedLocal"][0]["headOperationId"] = "other-update"
    with pytest.raises(ValueError, match="ID changed"):
        CodingLegacyRemovedReviewV1.from_dict(changed)
    missing = json.loads(json.dumps(review))
    del missing["removedLocal"][0]["headTransitionKind"]
    with pytest.raises(ValueError, match="review is invalid"):
        CodingLegacyRemovedReviewV1.from_dict(missing)
    noncanonical = json.loads(json.dumps(review))
    noncanonical["removedLocal"][0]["headOperationId"] = None
    with pytest.raises(ValueError, match="review is invalid"):
        CodingLegacyRemovedReviewV1.from_dict(noncanonical)
    noncanonical = json.loads(json.dumps(review))
    noncanonical["removedLocal"][0]["headTransitionKind"] = None
    with pytest.raises(ValueError, match="review is invalid"):
        CodingLegacyRemovedReviewV1.from_dict(noncanonical)
    assert cutover_main((*command_prefix, "--review-legacy-removed-only")) == 0
    assert json.loads(capsys.readouterr().out) == review
    assert (
        cutover_main(
            (*command_prefix, "--adopt-legacy-removed-review", review["reviewId"])
        )
        == 0
    )
    accepted = json.loads(capsys.readouterr().out)
    assert accepted["disposition"] == "adopted"
    assert cutover_main(command_prefix) == 0
    assert json.loads(capsys.readouterr().out)["disposition"] == "fenced"
    product = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        assert (
            product.runtime_owner.product_owner.desired_state.snapshot()
            .installation(key)
            .selection.desired_state
            == "absent"
        )
    finally:
        product.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize("legacy_key", ("resource_roots", "packages"))
def test_offline_command_refuses_other_pre_b_settings_without_writing(
    tmp_path: Path, legacy_key: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    project_config = workspace / ".loushang"
    project_config.mkdir(mode=0o700)
    (project_config / "settings.json").write_text(
        json.dumps({legacy_key: ["old-entry"]}), encoding="utf-8"
    )
    environ = {**os.environ, "LOUSHANG_HOME": str(tmp_path / "private-home")}

    result = subprocess.run(
        (
            sys.executable,
            "-m",
            "loushang.coding.cli.package_cutover",
            "--workspace",
            str(workspace),
        ),
        env=environ,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 1
    assert "pre-B workspace is unsupported" in result.stderr
    assert not (tmp_path / "private-home").exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize(
    "case",
    (
        "accepted",
        "changed_head",
        "partial_operation",
        "pending_operation",
        "missing_remove_operation",
        "changed_lock",
        "retirement_record",
    ),
)
def test_removed_updated_local_accepts_real_old_management_journal_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    _source, plugin_id = _old_installed_local_source(
        tmp_path, lifecycle, old_enabled=False
    )
    [binding] = parse_coding_legacy_local_binding_heads(
        (lifecycle.package_root / "package-lock.json").read_bytes()
    )
    lifecycle.desired_state.unlink()
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=lifecycle.scope_id,
        plugin_id=plugin_id,
    )
    original = PluginPackageRevisionRefV1(
        plugin_id=plugin_id,
        plugin_version="0",
        package_content_digest="e" * 64,
        dependency_lock_digest="d" * 64,
        package_source_identity=binding.source_identity,
    )
    updated = PluginPackageRevisionRefV1(
        plugin_id=plugin_id,
        plugin_version="1",
        package_content_digest=(
            "f" * 64 if case == "changed_head" else binding.content_digest
        ),
        dependency_lock_digest=binding.dependency_lock.digest,
        package_source_identity=binding.source_identity,
    )
    intents = PluginRetirementIntentLedger(lifecycle.retirement_intents)
    service = PluginManagementService(
        desired_state=PluginDesiredStateLedger(lifecycle.desired_state),
        operation_journal_path=lifecycle.management_operations,
        retirement_intents=intents,
        retirement_sets=PluginRetirementSetLedger(
            lifecycle.retirement_sets, retirement_intents=intents
        ),
    )
    service.submit(
        PluginManagementCommandV1(
            action="install",
            mutation=PluginDesiredStateMutationV1(
                operation_id="old-service-install",
                idempotency_key="old-service-install",
                expected_inventory_revision=0,
                installation_key=key,
                desired_state="installed_disabled",
                package_revision=original,
                actor_id="old-operator",
                policy_revision="old-policy:1",
            ),
        )
    )
    service.submit(
        PluginManagementUpdateCommandV2(
            operation_id="old-service-update",
            idempotency_key="old-service-update",
            expected_inventory_revision=1,
            installation_key=key,
            expected_package_revision=original,
            staged_package_revision=updated,
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    service.submit(
        PluginManagementCommandV1(
            action="remove",
            mutation=PluginDesiredStateMutationV1(
                operation_id="old-service-remove",
                idempotency_key="old-service-remove",
                expected_inventory_revision=2,
                installation_key=key,
                desired_state="absent",
                package_revision=None,
                actor_id="old-operator",
                policy_revision="old-policy:1",
            ),
        )
    )
    members = resolve_coding_lifecycle_pre_b_members(lifecycle).domain_members()
    assert members["desired_state"] == (
        "desired-state.jsonl",
        "desired-state.jsonl.lock",
        "management-operations.jsonl",
        "management-operations.jsonl.lock",
    )
    assert members["instance_state"] == (
        "retirement-intents.jsonl.lock",
        "retirement-sets.jsonl.lock",
    )
    if case == "partial_operation":
        lifecycle.management_operations.write_bytes(
            lifecycle.management_operations.read_bytes().rstrip(b"\n")
        )
    if case == "pending_operation":
        lines = lifecycle.management_operations.read_bytes().splitlines()
        lifecycle.management_operations.write_bytes(b"\n".join(lines[:-1]) + b"\n")
    if case == "missing_remove_operation":
        lines = lifecycle.management_operations.read_bytes().splitlines()
        lifecycle.management_operations.write_bytes(b"\n".join(lines[:-2]) + b"\n")
    if case == "changed_lock":
        lifecycle.management_operations.with_name(
            "management-operations.jsonl.lock"
        ).write_bytes(b"bad")
    if case == "retirement_record":
        lifecycle.retirement_intents.write_text("unexpected\n", encoding="utf-8")
    prefix = ("--workspace", str(workspace))
    result = cutover_main((*prefix, "--prepare-legacy-removed-review"))
    if case != "accepted":
        assert result == 1
        assert capsys.readouterr().out == ""
        assert not (
            resolve_coding_package_epoch_layout(lifecycle).control_root / "epoch.jsonl"
        ).exists()
        return
    assert result == 0
    review = json.loads(capsys.readouterr().out)
    assert review["reviewVersion"] == 2
    assert (
        review["operationJournalDigest"]
        == sha256(lifecycle.management_operations.read_bytes()).hexdigest()
    )
    assert review["removedLocal"][0]["headOperationId"] == "old-service-update"
    assert CodingLegacyRemovedReviewV1.from_dict(review).to_dict() == review
    noncanonical = json.loads(json.dumps(review))
    noncanonical["operationJournalDigest"] = None
    with pytest.raises(ValueError, match="review is invalid"):
        CodingLegacyRemovedReviewV1.from_dict(noncanonical)
    assert (
        cutover_main((*prefix, "--adopt-legacy-removed-review", review["reviewId"]))
        == 0
    )
    assert json.loads(capsys.readouterr().out)["disposition"] == "adopted"
    assert cutover_main(prefix) == 0
    assert json.loads(capsys.readouterr().out)["disposition"] == "fenced"
    product = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        assert (
            product.runtime_owner.product_owner.desired_state.snapshot()
            .installation(key)
            .selection.desired_state
            == "absent"
        )
    finally:
        product.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize(
    "case", ("settled", "second_collecting", "second_failed", "changed_set")
)
def test_removed_enabled_update_requires_each_old_retirement_settled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    _source, plugin_id = _old_installed_local_source(
        tmp_path, lifecycle, old_enabled=False
    )
    [binding] = parse_coding_legacy_local_binding_heads(
        (lifecycle.package_root / "package-lock.json").read_bytes()
    )
    lifecycle.desired_state.unlink()
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=lifecycle.scope_id,
        plugin_id=plugin_id,
    )
    original = PluginPackageRevisionRefV1(
        plugin_id=plugin_id,
        plugin_version="0",
        package_content_digest="e" * 64,
        dependency_lock_digest="d" * 64,
        package_source_identity=binding.source_identity,
    )
    updated = PluginPackageRevisionRefV1(
        plugin_id=plugin_id,
        plugin_version="1",
        package_content_digest=binding.content_digest,
        dependency_lock_digest=binding.dependency_lock.digest,
        package_source_identity=binding.source_identity,
    )
    intents = PluginRetirementIntentLedger(lifecycle.retirement_intents)
    sets = PluginRetirementSetLedger(
        lifecycle.retirement_sets, retirement_intents=intents
    )
    service = PluginManagementService(
        desired_state=PluginDesiredStateLedger(lifecycle.desired_state),
        operation_journal_path=lifecycle.management_operations,
        retirement_intents=intents,
        retirement_sets=sets,
    )
    for revision, action, desired_state, package_revision in (
        (0, "install", "installed_disabled", original),
        (1, "enable", "installed_enabled", None),
    ):
        operation_id = f"old-service-{action}"
        service.submit(
            PluginManagementCommandV1(
                action=action,
                mutation=PluginDesiredStateMutationV1(
                    operation_id=operation_id,
                    idempotency_key=operation_id,
                    expected_inventory_revision=revision,
                    installation_key=key,
                    desired_state=desired_state,
                    package_revision=package_revision,
                    actor_id="old-operator",
                    policy_revision="old-policy:1",
                ),
            )
        )
    updated_event = service.submit(
        PluginManagementUpdateCommandV2(
            operation_id="old-service-enabled-update",
            idempotency_key="old-service-enabled-update",
            expected_inventory_revision=2,
            installation_key=key,
            expected_package_revision=original,
            staged_package_revision=updated,
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    assert updated_event.result is not None
    assert updated_event.result.disposition == "restart_required"
    removed_event = service.submit(
        PluginManagementCommandV1(
            action="remove",
            mutation=PluginDesiredStateMutationV1(
                operation_id="old-service-remove",
                idempotency_key="old-service-remove",
                expected_inventory_revision=3,
                installation_key=key,
                desired_state="absent",
                package_revision=None,
                actor_id="old-operator",
                policy_revision="old-policy:1",
            ),
        )
    )
    assert removed_event.result is not None
    assert removed_event.result.disposition == "succeeded"
    old_intents = intents.snapshot().intents
    assert tuple(item.trigger for item in old_intents) == ("update", "remove")
    _settle_old_retirement(sets, old_intents[0], suffix="update")
    if case in {"settled", "changed_set", "second_failed"}:
        _settle_old_retirement(
            sets,
            old_intents[1],
            suffix="remove",
            disposition="terminal_failure" if case == "second_failed" else "succeeded",
        )
    members = resolve_coding_lifecycle_pre_b_members(lifecycle).domain_members()
    assert members["instance_state"] == (
        "retirement-intents.jsonl",
        "retirement-intents.jsonl.lock",
        "retirement-sets.jsonl",
        "retirement-sets.jsonl.lock",
    )
    if case == "changed_set":
        lifecycle.retirement_sets.write_bytes(b"bad\n")
    prefix = ("--workspace", str(workspace))
    result = cutover_main((*prefix, "--prepare-legacy-removed-review"))
    if case != "settled":
        assert result == 1
        assert capsys.readouterr().out == ""
        assert not (
            resolve_coding_package_epoch_layout(lifecycle).control_root / "epoch.jsonl"
        ).exists()
        return
    assert result == 0
    review = json.loads(capsys.readouterr().out)
    assert review["reviewVersion"] == 2
    assert review["removedLocal"][0]["headOperationId"] == (
        "old-service-enabled-update"
    )
    lifecycle.retirement_intents.write_bytes(b"changed old live intents")
    lifecycle.retirement_sets.write_bytes(b"changed old live sets")
    assert cutover_main((*prefix, "--review-legacy-removed-only")) == 0
    assert json.loads(capsys.readouterr().out) == review
    assert (
        cutover_main((*prefix, "--adopt-legacy-removed-review", review["reviewId"]))
        == 0
    )
    assert json.loads(capsys.readouterr().out)["disposition"] == "adopted"
    assert cutover_main(prefix) == 0
    assert json.loads(capsys.readouterr().out)["disposition"] == "fenced"
    product = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        assert (
            product.runtime_owner.product_owner.desired_state.snapshot()
            .installation(key)
            .selection.desired_state
            == "absent"
        )
    finally:
        product.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_active_current_instance_refuses_legacy_skill_first_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    _source, plugin_id = _old_installed_local_source(
        tmp_path, lifecycle, old_enabled=False
    )
    [binding] = parse_coding_legacy_local_binding_heads(
        (lifecycle.package_root / "package-lock.json").read_bytes()
    )
    lifecycle.desired_state.unlink()
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=lifecycle.scope_id,
        plugin_id=plugin_id,
    )
    revision = PluginPackageRevisionRefV1(
        plugin_id=plugin_id,
        plugin_version="1",
        package_content_digest=binding.content_digest,
        dependency_lock_digest=binding.dependency_lock.digest,
        package_source_identity=binding.source_identity,
    )
    intents = PluginRetirementIntentLedger(lifecycle.retirement_intents)
    sets = PluginRetirementSetLedger(
        lifecycle.retirement_sets, retirement_intents=intents
    )
    desired = PluginDesiredStateLedger(lifecycle.desired_state)
    service = PluginManagementService(
        desired_state=desired,
        operation_journal_path=lifecycle.management_operations,
        retirement_intents=intents,
        retirement_sets=sets,
    )
    for inventory_revision, action, state, package_revision in (
        (0, "install", "installed_disabled", revision),
        (1, "enable", "installed_enabled", None),
    ):
        operation_id = f"old-current-{action}"
        event = service.submit(
            PluginManagementCommandV1(
                action=action,
                mutation=PluginDesiredStateMutationV1(
                    operation_id=operation_id,
                    idempotency_key=operation_id,
                    expected_inventory_revision=inventory_revision,
                    installation_key=key,
                    desired_state=state,
                    package_revision=package_revision,
                    actor_id="old-operator",
                    policy_revision="old-policy:1",
                ),
            )
        )
        assert event.result is not None
        assert event.result.disposition == "succeeded"
    runtime = PluginInstanceRuntimeLedger(
        lifecycle.instance_runtime,
        management_operation_journal_path=lifecycle.management_operations,
        desired_state=desired,
        retirement_intents=intents,
        retirement_sets=sets,
        security_acceptances=PluginInstanceSecurityRetirementJournal.for_instance_runtime(
            lifecycle.instance_runtime
        ),
    )
    active = runtime.activate_current(
        key,
        operation_id="old-current-activate",
        idempotency_key="old-current-activate",
        direct_host_reference="old-host:current",
    )
    assert active.state == "ACTIVE"
    assert active.open_family_ids == (active.activation.direct_host_family.family_id,)
    lifecycle.retirement_intents.write_bytes(b"")
    lifecycle.retirement_sets.write_bytes(b"")

    assert (
        cutover_main(
            (
                "--workspace",
                str(workspace),
                "--prepare-legacy-local-skill-review",
                plugin_id,
            )
        )
        == 1
    )
    assert capsys.readouterr().out == ""
    assert not (
        resolve_coding_package_epoch_layout(lifecycle).control_root / "epoch.jsonl"
    ).exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize(
    "case",
    (
        "settled",
        "collecting",
        "failed",
        "changed_set",
        "retired_runtime",
        "open_runtime",
        "changed_runtime",
        "changed_runtime_lock",
        "security_journal",
        "retained_store",
        "retained_both_store_roots",
        "unsafe_store_link",
    ),
)
def test_removed_enabled_without_update_requires_old_retirement_settled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    _source, plugin_id = _old_installed_local_source(
        tmp_path, lifecycle, old_enabled=False
    )
    old_store_bytes = None
    if case in {"retained_store", "retained_both_store_roots", "unsafe_store_link"}:
        old_revisions = lifecycle.package_root / "plugin-revisions"
        shutil.copytree(tmp_path / "old-package" / "plugin-revisions", old_revisions)
        if case == "retained_both_store_roots":
            old_checkout = lifecycle.package_root / "installed" / "old-checkout"
            old_checkout.mkdir(parents=True, mode=0o700)
            (old_checkout / "README.md").write_text("old checkout bytes\n")
        if case == "unsafe_store_link":
            (old_revisions / "unexpected-link").symlink_to(tmp_path / "old-source")
        else:
            old_store_bytes = tuple(
                sorted(
                    (str(path.relative_to(lifecycle.package_root)), path.read_bytes())
                    for root_name in (
                        ("installed", "plugin-revisions")
                        if case == "retained_both_store_roots"
                        else ("plugin-revisions",)
                    )
                    for path in (lifecycle.package_root / root_name).rglob("*")
                    if path.is_file()
                )
            )
    [binding] = parse_coding_legacy_local_binding_heads(
        (lifecycle.package_root / "package-lock.json").read_bytes()
    )
    lifecycle.desired_state.unlink()
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=lifecycle.scope_id,
        plugin_id=plugin_id,
    )
    revision = PluginPackageRevisionRefV1(
        plugin_id=plugin_id,
        plugin_version="1",
        package_content_digest=binding.content_digest,
        dependency_lock_digest=binding.dependency_lock.digest,
        package_source_identity=binding.source_identity,
    )
    intents = PluginRetirementIntentLedger(lifecycle.retirement_intents)
    sets = PluginRetirementSetLedger(
        lifecycle.retirement_sets, retirement_intents=intents
    )
    desired_ledger = PluginDesiredStateLedger(lifecycle.desired_state)
    service = PluginManagementService(
        desired_state=desired_ledger,
        operation_journal_path=lifecycle.management_operations,
        retirement_intents=intents,
        retirement_sets=sets,
    )
    runtime = None
    activated = None
    for inventory_revision, action, state, package_revision in (
        (0, "install", "installed_disabled", revision),
        (1, "enable", "installed_enabled", None),
        (2, "remove", "absent", None),
    ):
        operation_id = f"old-service-direct-{action}"
        event = service.submit(
            PluginManagementCommandV1(
                action=action,
                mutation=PluginDesiredStateMutationV1(
                    operation_id=operation_id,
                    idempotency_key=operation_id,
                    expected_inventory_revision=inventory_revision,
                    installation_key=key,
                    desired_state=state,
                    package_revision=package_revision,
                    actor_id="old-operator",
                    policy_revision="old-policy:1",
                ),
            )
        )
        assert event.result is not None
        assert event.result.disposition == "succeeded"
        if (
            case
            in {
                "retired_runtime",
                "open_runtime",
                "changed_runtime",
                "changed_runtime_lock",
                "security_journal",
            }
            and action == "enable"
        ):
            runtime = PluginInstanceRuntimeLedger(
                lifecycle.instance_runtime,
                management_operation_journal_path=lifecycle.management_operations,
                desired_state=desired_ledger,
                retirement_intents=intents,
                retirement_sets=sets,
                security_acceptances=(
                    PluginInstanceSecurityRetirementJournal.for_instance_runtime(
                        lifecycle.instance_runtime
                    )
                ),
            )
            activated = runtime.activate_current(
                key,
                operation_id="old-instance-activate",
                idempotency_key="old-instance-activate",
                direct_host_reference="old-host:review",
            )
    [intent] = intents.snapshot().intents
    assert intent.trigger == "remove"
    if case != "collecting":
        _settle_old_retirement(
            sets,
            intent,
            suffix="direct-remove",
            disposition="terminal_failure" if case == "failed" else "succeeded",
        )
    if case == "changed_set":
        lifecycle.retirement_sets.write_bytes(b"bad\n")
    if runtime is not None:
        assert activated is not None
        runtime.begin_drain(intent)
        if case != "open_runtime":
            family = activated.activation.direct_host_family
            runtime.release_family(
                PluginInstanceLeaseFamilyReleaseV1(
                    family_id=family.family_id,
                    operation_id="old-instance-release",
                    idempotency_key="old-instance-release",
                    release_reference="old-host:closed",
                )
            )
            retired = runtime.complete_retirement(
                PluginInstanceRetirementCompletionV1.create(
                    completion_kind="graceful",
                    coordination_id=intent.retirement_id,
                    installation_key=key,
                    instance_revision_ref=activated.instance_revision_ref,
                    operation_id="old-instance-retire",
                    idempotency_key="old-instance-retire",
                    completion_reference="old-instance:retired",
                )
            )
            assert retired.state == "RETIRED"
        assert resolve_coding_lifecycle_pre_b_members(lifecycle).domain_members()[
            "instance_state"
        ] == (
            "instance-runtime.jsonl",
            "instance-runtime.jsonl.lock",
            "instance-runtime.security-acceptances.jsonl.lock",
            "retirement-intents.jsonl",
            "retirement-intents.jsonl.lock",
            "retirement-sets.jsonl",
            "retirement-sets.jsonl.lock",
        )
        if case == "changed_runtime":
            lifecycle.instance_runtime.write_bytes(b"bad\n")
        elif case == "changed_runtime_lock":
            lifecycle.instance_runtime.with_name(
                "instance-runtime.jsonl.lock"
            ).write_bytes(b"bad")
        elif case == "security_journal":
            lifecycle.instance_runtime.with_name(
                "instance-runtime.security-acceptances.jsonl"
            ).write_bytes(b"bad\n")
    prefix = ("--workspace", str(workspace))
    result = cutover_main((*prefix, "--prepare-legacy-removed-review"))
    if case not in {
        "settled",
        "retired_runtime",
        "retained_store",
        "retained_both_store_roots",
    }:
        assert result == 1
        assert capsys.readouterr().out == ""
        assert not (
            resolve_coding_package_epoch_layout(lifecycle).control_root / "epoch.jsonl"
        ).exists()
        return
    assert result == 0
    review = json.loads(capsys.readouterr().out)
    assert review["reviewVersion"] == 2
    assert (
        review["operationJournalDigest"]
        == sha256(lifecycle.management_operations.read_bytes()).hexdigest()
    )
    if case in {"retained_store", "retained_both_store_roots"}:
        assert review["retainedStoreRoots"] == (
            ["installed", "plugin-revisions"]
            if case == "retained_both_store_roots"
            else ["plugin-revisions"]
        )
        assert CodingLegacyRemovedReviewV1.from_dict(review).to_dict() == review
        missing_store = dict(review)
        missing_store.pop("retainedStoreRoots")
        with pytest.raises(ValueError, match="ID changed"):
            CodingLegacyRemovedReviewV1.from_dict(missing_store)
    else:
        assert "retainedStoreRoots" not in review
    assert review["removedLocal"][0]["headTransitionKind"] == "install"
    assert review["removedLocal"][0]["headOperationId"] == "old-service-direct-install"
    assert CodingLegacyRemovedReviewV1.from_dict(review).to_dict() == review
    missing_digest = dict(review)
    missing_digest.pop("operationJournalDigest")
    with pytest.raises(ValueError, match="review is invalid"):
        CodingLegacyRemovedReviewV1.from_dict(missing_digest)
    lifecycle.retirement_intents.write_bytes(b"changed old live intents")
    lifecycle.retirement_sets.write_bytes(b"changed old live sets")
    if case == "retired_runtime":
        lifecycle.instance_runtime.write_bytes(b"changed old live runtime")
    assert cutover_main((*prefix, "--review-legacy-removed-only")) == 0
    assert json.loads(capsys.readouterr().out) == review
    assert (
        cutover_main((*prefix, "--adopt-legacy-removed-review", review["reviewId"]))
        == 0
    )
    assert json.loads(capsys.readouterr().out)["disposition"] == "adopted"
    assert cutover_main(prefix) == 0
    assert json.loads(capsys.readouterr().out)["disposition"] == "fenced"
    product = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        assert (
            product.runtime_owner.product_owner.desired_state.snapshot()
            .installation(key)
            .selection.desired_state
            == "absent"
        )
    finally:
        product.close()
    if old_store_bytes is not None:
        assert (
            tuple(
                sorted(
                    (str(path.relative_to(lifecycle.package_root)), path.read_bytes())
                    for root_name in (
                        ("installed", "plugin-revisions")
                        if case == "retained_both_store_roots"
                        else ("plugin-revisions",)
                    )
                    for path in (lifecycle.package_root / root_name).rglob("*")
                    if path.is_file()
                )
            )
            == old_store_bytes
        )


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize(
    ("resource_kind", "case"),
    (
        ("skill", "accepted"),
        ("prompt", "accepted"),
        ("theme", "accepted"),
        ("skill", "missing_enable_operation"),
        ("skill", "changed_lock"),
        ("skill", "retirement_record"),
    ),
)
def test_active_local_data_accepts_real_old_management_journal_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    resource_kind: str,
    case: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    _source, plugin_id = _old_installed_local_source(
        tmp_path, lifecycle, resource_kind=resource_kind, old_enabled=False
    )
    [binding] = parse_coding_legacy_local_binding_heads(
        (lifecycle.package_root / "package-lock.json").read_bytes()
    )
    lifecycle.desired_state.unlink()
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=lifecycle.scope_id,
        plugin_id=plugin_id,
    )
    original = PluginPackageRevisionRefV1(
        plugin_id=plugin_id,
        plugin_version="0",
        package_content_digest="e" * 64,
        dependency_lock_digest="d" * 64,
        package_source_identity=binding.source_identity,
    )
    updated = PluginPackageRevisionRefV1(
        plugin_id=plugin_id,
        plugin_version="1",
        package_content_digest=binding.content_digest,
        dependency_lock_digest=binding.dependency_lock.digest,
        package_source_identity=binding.source_identity,
    )
    intents = PluginRetirementIntentLedger(lifecycle.retirement_intents)
    service = PluginManagementService(
        desired_state=PluginDesiredStateLedger(lifecycle.desired_state),
        operation_journal_path=lifecycle.management_operations,
        retirement_intents=intents,
        retirement_sets=PluginRetirementSetLedger(
            lifecycle.retirement_sets, retirement_intents=intents
        ),
    )
    service.submit(
        PluginManagementCommandV1(
            action="install",
            mutation=PluginDesiredStateMutationV1(
                operation_id="old-service-install",
                idempotency_key="old-service-install",
                expected_inventory_revision=0,
                installation_key=key,
                desired_state="installed_disabled",
                package_revision=original,
                actor_id="old-operator",
                policy_revision="old-policy:1",
            ),
        )
    )
    service.submit(
        PluginManagementUpdateCommandV2(
            operation_id="old-service-update",
            idempotency_key="old-service-update",
            expected_inventory_revision=1,
            installation_key=key,
            expected_package_revision=original,
            staged_package_revision=updated,
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    service.submit(
        PluginManagementCommandV1(
            action="enable",
            mutation=PluginDesiredStateMutationV1(
                operation_id="old-service-enable",
                idempotency_key="old-service-enable",
                expected_inventory_revision=2,
                installation_key=key,
                desired_state="installed_enabled",
                package_revision=None,
                actor_id="old-operator",
                policy_revision="old-policy:1",
            ),
        )
    )
    members = resolve_coding_lifecycle_pre_b_members(lifecycle).domain_members()
    assert members["desired_state"] == (
        "desired-state.jsonl",
        "desired-state.jsonl.lock",
        "management-operations.jsonl",
        "management-operations.jsonl.lock",
    )
    if case == "missing_enable_operation":
        lines = lifecycle.management_operations.read_bytes().splitlines()
        lifecycle.management_operations.write_bytes(b"\n".join(lines[:-2]) + b"\n")
    if case == "changed_lock":
        lifecycle.management_operations.with_name(
            "management-operations.jsonl.lock"
        ).write_bytes(b"bad")
    if case == "retirement_record":
        lifecycle.retirement_intents.write_text("unexpected\n", encoding="utf-8")
    prefix = ("--workspace", str(workspace))
    prepare = (*prefix, f"--prepare-legacy-local-{resource_kind}-review", plugin_id)
    result = cutover_main(prepare)
    if case != "accepted":
        assert result == 1
        assert capsys.readouterr().out == ""
        assert not (
            resolve_coding_package_epoch_layout(lifecycle).control_root / "epoch.jsonl"
        ).exists()
        return
    assert result == 0
    review = json.loads(capsys.readouterr().out)
    assert review["desiredState"] == "installed_enabled"
    if resource_kind == "skill":
        lifecycle.management_operations.write_bytes(b"changed old live operations")
        assert cutover_main((*prefix, "--review-legacy-local-plugin", plugin_id)) == 0
        assert json.loads(capsys.readouterr().out) == review
    assert (
        cutover_main(
            (
                *prefix,
                f"--adopt-legacy-local-{resource_kind}-review",
                plugin_id,
                review["reviewId"],
            )
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["disposition"] == "adopted"
    assert cutover_main(prefix) == 0
    assert json.loads(capsys.readouterr().out)["disposition"] == "fenced"
    product = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        assert (
            product.runtime_owner.product_owner.desired_state.snapshot()
            .installation(key)
            .selection.desired_state
            == "installed_enabled"
        )
        if resource_kind == "skill":
            manager = asyncio.run(
                SessionManager.new(
                    session_dir=tmp_path / "session", cwd=str(workspace), persist=False
                )
            )
            session = create_agent_session(
                session_manager=manager,
                model=Model(
                    id="old-service-skill",
                    name="Old Service Skill",
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
                        global_settings_path=default_global_settings_path(),
                        project_settings_path=default_project_settings_path(workspace),
                    )
                ),
                composition_set="coding-standard",
                package_product_runtime_factory=product.factory_for_session(manager),
            )
            try:
                assert session.resource_bundle is not None
                assert any(
                    item.name == "review" and item.source_kind == "external_package"
                    for item in session.resource_bundle.skills
                )

                async def load_review() -> str:
                    await session.prepare_model_call_runtime()
                    expanded = await session._preflight_user_input_async(
                        "/skill:review"
                    )
                    assert len(expanded.loaded_skills) == 1
                    return expanded.loaded_skills[0].content

                assert "# Review" in asyncio.run(load_review())
            finally:
                asyncio.run(session.dispose())
    finally:
        product.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize(
    "case",
    (
        "settled",
        "collecting",
        "retiring",
        "empty_plan",
        "failed_outcome",
        "changed_intent",
        "changed_set",
        "retired_runtime",
        "open_runtime",
        "changed_runtime",
        "changed_runtime_lock",
        "security_journal",
    ),
)
def test_active_local_enabled_update_requires_settled_old_retirement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    _source, plugin_id = _old_installed_local_source(
        tmp_path, lifecycle, old_enabled=False
    )
    [binding] = parse_coding_legacy_local_binding_heads(
        (lifecycle.package_root / "package-lock.json").read_bytes()
    )
    lifecycle.desired_state.unlink()
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=lifecycle.scope_id,
        plugin_id=plugin_id,
    )
    original = PluginPackageRevisionRefV1(
        plugin_id=plugin_id,
        plugin_version="0",
        package_content_digest="e" * 64,
        dependency_lock_digest="d" * 64,
        package_source_identity=binding.source_identity,
    )
    updated = PluginPackageRevisionRefV1(
        plugin_id=plugin_id,
        plugin_version="1",
        package_content_digest=binding.content_digest,
        dependency_lock_digest=binding.dependency_lock.digest,
        package_source_identity=binding.source_identity,
    )
    intents = PluginRetirementIntentLedger(lifecycle.retirement_intents)
    sets = PluginRetirementSetLedger(
        lifecycle.retirement_sets, retirement_intents=intents
    )
    desired_ledger = PluginDesiredStateLedger(lifecycle.desired_state)
    service = PluginManagementService(
        desired_state=desired_ledger,
        operation_journal_path=lifecycle.management_operations,
        retirement_intents=intents,
        retirement_sets=sets,
    )
    runtime = None
    activated = None
    for action, state, revision in (
        ("install", "installed_disabled", original),
        ("enable", "installed_enabled", None),
    ):
        operation_id = f"old-service-{action}"
        service.submit(
            PluginManagementCommandV1(
                action=action,
                mutation=PluginDesiredStateMutationV1(
                    operation_id=operation_id,
                    idempotency_key=operation_id,
                    expected_inventory_revision=0 if action == "install" else 1,
                    installation_key=key,
                    desired_state=state,
                    package_revision=revision,
                    actor_id="old-operator",
                    policy_revision="old-policy:1",
                ),
            )
        )
        if (
            case
            in {
                "retired_runtime",
                "open_runtime",
                "changed_runtime",
                "changed_runtime_lock",
                "security_journal",
            }
            and action == "enable"
        ):
            runtime = PluginInstanceRuntimeLedger(
                lifecycle.instance_runtime,
                management_operation_journal_path=lifecycle.management_operations,
                desired_state=desired_ledger,
                retirement_intents=intents,
                retirement_sets=sets,
                security_acceptances=(
                    PluginInstanceSecurityRetirementJournal.for_instance_runtime(
                        lifecycle.instance_runtime
                    )
                ),
            )
            activated = runtime.activate_current(
                key,
                operation_id="old-active-instance-activate",
                idempotency_key="old-active-instance-activate",
                direct_host_reference="old-host:active-review",
            )
    result = service.submit(
        PluginManagementUpdateCommandV2(
            operation_id="old-service-enabled-update",
            idempotency_key="old-service-enabled-update",
            expected_inventory_revision=2,
            installation_key=key,
            expected_package_revision=original,
            staged_package_revision=updated,
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    assert result.result is not None
    assert result.result.disposition == "restart_required"
    [intent] = intents.snapshot().intents
    assert sets.snapshot().sets[0].state == "collecting"
    if case != "collecting":
        target = PluginOwnerRetirementTargetV1.create(
            owner_reference="owner:old-service",
            owner_generation_reference="generation:old-service",
            retirement_handle="retirement:old-service",
            contribution_ids=("contribution:review-skill",),
        )
        plan = PluginOwnerRetirementPlanV1.create(
            retirement_id=intent.retirement_id,
            owner_closure_reference="closure:old-service",
            targets=() if case == "empty_plan" else (target,),
        )
        sets.commit_plan(plan)
        if case not in {"empty_plan", "retiring"}:
            sets.record_outcome(
                PluginOwnerRetirementOutcomeV1(
                    retirement_id=intent.retirement_id,
                    target_id=target.target_id,
                    operation_id="old-owner-retire",
                    idempotency_key="old-owner-retire",
                    attempt=1,
                    disposition=(
                        "terminal_failure" if case == "failed_outcome" else "succeeded"
                    ),
                    result_code="owner_retirement_done",
                    owner_outcome_reference="outcome:old-service",
                )
            )
    if runtime is not None:
        assert activated is not None
        runtime.begin_drain(intent)
        if case != "open_runtime":
            family = activated.activation.direct_host_family
            runtime.release_family(
                PluginInstanceLeaseFamilyReleaseV1(
                    family_id=family.family_id,
                    operation_id="old-active-instance-release",
                    idempotency_key="old-active-instance-release",
                    release_reference="old-host:active-closed",
                )
            )
            retired = runtime.complete_retirement(
                PluginInstanceRetirementCompletionV1.create(
                    completion_kind="graceful",
                    coordination_id=intent.retirement_id,
                    installation_key=key,
                    instance_revision_ref=activated.instance_revision_ref,
                    operation_id="old-active-instance-retire",
                    idempotency_key="old-active-instance-retire",
                    completion_reference="old-active-instance:retired",
                )
            )
            assert retired.state == "RETIRED"
    members = resolve_coding_lifecycle_pre_b_members(lifecycle).domain_members()
    assert members["instance_state"] == (
        (
            "instance-runtime.jsonl",
            "instance-runtime.jsonl.lock",
            "instance-runtime.security-acceptances.jsonl.lock",
        )
        if runtime is not None
        else ()
    ) + (
        "retirement-intents.jsonl",
        "retirement-intents.jsonl.lock",
        "retirement-sets.jsonl",
        "retirement-sets.jsonl.lock",
    )
    if case == "changed_intent":
        lifecycle.retirement_intents.write_bytes(b"bad\n")
    if case == "changed_set":
        lifecycle.retirement_sets.write_bytes(b"bad\n")
    if case == "changed_runtime":
        lifecycle.instance_runtime.write_bytes(b"bad\n")
    elif case == "changed_runtime_lock":
        lifecycle.instance_runtime.with_name("instance-runtime.jsonl.lock").write_bytes(
            b"bad"
        )
    elif case == "security_journal":
        lifecycle.instance_runtime.with_name(
            "instance-runtime.security-acceptances.jsonl"
        ).write_bytes(b"bad\n")
    prefix = ("--workspace", str(workspace))
    result_code = cutover_main(
        (*prefix, "--prepare-legacy-local-skill-review", plugin_id)
    )
    if case not in {"settled", "retired_runtime"}:
        assert result_code == 1
        assert capsys.readouterr().out == ""
        assert not (
            resolve_coding_package_epoch_layout(lifecycle).control_root / "epoch.jsonl"
        ).exists()
        return
    assert result_code == 0
    review = json.loads(capsys.readouterr().out)
    assert review["desiredState"] == "installed_enabled"
    lifecycle.retirement_intents.write_bytes(b"changed old live intents")
    lifecycle.retirement_sets.write_bytes(b"changed old live sets")
    if case == "retired_runtime":
        lifecycle.instance_runtime.write_bytes(b"changed old live runtime")
    assert cutover_main((*prefix, "--review-legacy-local-plugin", plugin_id)) == 0
    assert json.loads(capsys.readouterr().out) == review
    assert (
        cutover_main(
            (
                *prefix,
                "--adopt-legacy-local-skill-review",
                plugin_id,
                review["reviewId"],
            )
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["disposition"] == "adopted"
    assert cutover_main(prefix) == 0
    assert json.loads(capsys.readouterr().out)["disposition"] == "fenced"
    product = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        assert (
            product.runtime_owner.product_owner.desired_state.snapshot()
            .installation(key)
            .selection.desired_state
            == "installed_enabled"
        )
        manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "enabled-update-session",
                cwd=str(workspace),
                persist=False,
            )
        )
        session = create_agent_session(
            session_manager=manager,
            model=Model(
                id="old-service-enabled-update",
                name="Old Service Enabled Update",
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
                    global_settings_path=default_global_settings_path(),
                    project_settings_path=default_project_settings_path(workspace),
                )
            ),
            composition_set="coding-standard",
            package_product_runtime_factory=product.factory_for_session(manager),
        )
        try:

            async def load_review() -> str:
                await session.prepare_model_call_runtime()
                expanded = await session._preflight_user_input_async("/skill:review")
                assert len(expanded.loaded_skills) == 1
                return expanded.loaded_skills[0].content

            assert "# Review" in asyncio.run(load_review())
        finally:
            asyncio.run(session.dispose())
    finally:
        product.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize(
    "removed_mode", ("simple", "updated", "direct", "direct_retired_runtime")
)
def test_mixed_active_and_removed_old_service_updates_replay_into_product(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    removed_mode: Literal["simple", "updated", "direct", "direct_retired_runtime"],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    local = _old_installed_local_skills(tmp_path, lifecycle, count=2)
    active_id, removed_id = local[0][1], local[1][1]
    bindings = {
        item.plugin_id: item
        for item in parse_coding_legacy_local_binding_heads(
            (lifecycle.package_root / "package-lock.json").read_bytes()
        )
    }
    lifecycle.desired_state.unlink()
    intents = PluginRetirementIntentLedger(lifecycle.retirement_intents)
    sets = PluginRetirementSetLedger(
        lifecycle.retirement_sets, retirement_intents=intents
    )
    desired_ledger = PluginDesiredStateLedger(lifecycle.desired_state)
    service = PluginManagementService(
        desired_state=desired_ledger,
        operation_journal_path=lifecycle.management_operations,
        retirement_intents=intents,
        retirement_sets=sets,
    )
    removed_runtime = None
    removed_activated = None
    removed_key = None
    for plugin_id, final_state in (
        (active_id, "installed_enabled"),
        (removed_id, "absent"),
    ):
        binding = bindings[plugin_id]
        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=lifecycle.scope_id,
            plugin_id=plugin_id,
        )
        original = PluginPackageRevisionRefV1(
            plugin_id=plugin_id,
            plugin_version="0",
            package_content_digest="e" * 64,
            dependency_lock_digest="d" * 64,
            package_source_identity=binding.source_identity,
        )
        updated = PluginPackageRevisionRefV1(
            plugin_id=plugin_id,
            plugin_version="1",
            package_content_digest=binding.content_digest,
            dependency_lock_digest=binding.dependency_lock.digest,
            package_source_identity=binding.source_identity,
        )
        retired_head = removed_mode != "simple" and plugin_id == removed_id
        if retired_head and removed_mode in {"direct", "direct_retired_runtime"}:
            original = updated
        actions = (
            (
                ("install", "installed_disabled", original),
                ("enable", "installed_enabled", None),
                ("remove", "absent", None),
            )
            if retired_head
            else (
                ("install", "installed_disabled", original),
                (
                    "enable" if final_state == "installed_enabled" else "remove",
                    final_state,
                    None,
                ),
            )
        )
        for action, state, revision in actions:
            if (not retired_head and action != "install") or (
                retired_head and removed_mode == "updated" and action == "remove"
            ):
                service.submit(
                    PluginManagementUpdateCommandV2(
                        operation_id=f"old-{plugin_id}-update",
                        idempotency_key=f"old-{plugin_id}-update",
                        expected_inventory_revision=desired_ledger.snapshot().inventory_revision,
                        installation_key=key,
                        expected_package_revision=original,
                        staged_package_revision=updated,
                        actor_id="old-operator",
                        policy_revision="old-policy:1",
                    )
                )
            operation_id = f"old-{plugin_id}-{action}"
            service.submit(
                PluginManagementCommandV1(
                    action=action,
                    mutation=PluginDesiredStateMutationV1(
                        operation_id=operation_id,
                        idempotency_key=operation_id,
                        expected_inventory_revision=desired_ledger.snapshot().inventory_revision,
                        installation_key=key,
                        desired_state=state,
                        package_revision=revision,
                        actor_id="old-operator",
                        policy_revision="old-policy:1",
                    ),
                )
            )
            if (
                removed_mode == "direct_retired_runtime"
                and retired_head
                and action == "enable"
            ):
                removed_runtime = PluginInstanceRuntimeLedger(
                    lifecycle.instance_runtime,
                    management_operation_journal_path=lifecycle.management_operations,
                    desired_state=desired_ledger,
                    retirement_intents=intents,
                    retirement_sets=sets,
                    security_acceptances=(
                        PluginInstanceSecurityRetirementJournal.for_instance_runtime(
                            lifecycle.instance_runtime
                        )
                    ),
                )
                removed_activated = removed_runtime.activate_current(
                    key,
                    operation_id="old-mixed-instance-activate",
                    idempotency_key="old-mixed-instance-activate",
                    direct_host_reference="old-host:mixed-review",
                )
                removed_key = key
    if removed_mode != "simple":
        old_intents = intents.snapshot().intents
        assert tuple(item.trigger for item in old_intents) == (
            ("update", "remove") if removed_mode == "updated" else ("remove",)
        )
        for index, intent in enumerate(old_intents):
            _settle_old_retirement(sets, intent, suffix=f"mixed-{index}")
        if removed_runtime is not None:
            assert removed_activated is not None and removed_key is not None
            [intent] = old_intents
            removed_runtime.begin_drain(intent)
            family = removed_activated.activation.direct_host_family
            removed_runtime.release_family(
                PluginInstanceLeaseFamilyReleaseV1(
                    family_id=family.family_id,
                    operation_id="old-mixed-instance-release",
                    idempotency_key="old-mixed-instance-release",
                    release_reference="old-host:mixed-closed",
                )
            )
            retired = removed_runtime.complete_retirement(
                PluginInstanceRetirementCompletionV1.create(
                    completion_kind="graceful",
                    coordination_id=intent.retirement_id,
                    installation_key=removed_key,
                    instance_revision_ref=removed_activated.instance_revision_ref,
                    operation_id="old-mixed-instance-retire",
                    idempotency_key="old-mixed-instance-retire",
                    completion_reference="old-mixed-instance:retired",
                )
            )
            assert retired.state == "RETIRED"
    prefix = ("--workspace", str(workspace))
    assert (
        cutover_main((*prefix, "--prepare-legacy-local-skill-review", active_id)) == 0
    )
    active_review = json.loads(capsys.readouterr().out)
    if removed_runtime is not None:
        lifecycle.instance_runtime.write_bytes(b"changed old live runtime")
    assert cutover_main((*prefix, "--review-legacy-removed-only")) == 0
    removed_review = json.loads(capsys.readouterr().out)
    assert removed_review["reviewVersion"] == 2
    assert removed_review["removedLocal"][0]["headOperationId"] == (
        f"old-{removed_id}-install"
        if removed_mode in {"direct", "direct_retired_runtime"}
        else f"old-{removed_id}-update"
    )
    assert (
        cutover_main(
            (*prefix, "--adopt-legacy-removed-review", removed_review["reviewId"])
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["disposition"] == "adopted"
    assert (
        cutover_main(
            (
                *prefix,
                "--adopt-legacy-local-skill-review",
                active_id,
                active_review["reviewId"],
            )
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["disposition"] == "adopted"
    assert cutover_main(prefix) == 0
    assert json.loads(capsys.readouterr().out)["disposition"] == "fenced"
    product = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        states = {
            item.installation_key.plugin_id: item.selection.desired_state
            for item in product.runtime_owner.product_owner.desired_state.snapshot().installations
        }
        assert states[active_id] == "installed_enabled"
        assert states[removed_id] == "absent"
        manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "mixed-session",
                cwd=str(workspace),
                persist=False,
            )
        )
        session = create_agent_session(
            session_manager=manager,
            model=Model(
                id="mixed-old-service-skills",
                name="Mixed Old Service Skills",
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
                    global_settings_path=default_global_settings_path(),
                    project_settings_path=default_project_settings_path(workspace),
                )
            ),
            composition_set="coding-standard",
            package_product_runtime_factory=product.factory_for_session(manager),
        )
        try:
            assert session.resource_bundle is not None
            names = {item.name for item in session.resource_bundle.skills}
            assert "review-1" in names
            assert "review-2" not in names

            async def load_active() -> str:
                await session.prepare_model_call_runtime()
                expanded = await session._preflight_user_input_async("/skill:review-1")
                assert len(expanded.loaded_skills) == 1
                return expanded.loaded_skills[0].content

            assert "# Review 1" in asyncio.run(load_active())
        finally:
            asyncio.run(session.dispose())
    finally:
        product.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize(
    "case", ("accepted", "missing_arch_operation", "changed_lock", "retirement_record")
)
def test_builtin_only_accepts_real_old_management_journal_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    prepare_coding_package_cutover_roots(lifecycle)
    intents = PluginRetirementIntentLedger(lifecycle.retirement_intents)
    desired_ledger = PluginDesiredStateLedger(lifecycle.desired_state)
    service = PluginManagementService(
        desired_state=desired_ledger,
        operation_journal_path=lifecycle.management_operations,
        retirement_intents=intents,
        retirement_sets=PluginRetirementSetLedger(
            lifecycle.retirement_sets, retirement_intents=intents
        ),
    )
    for plugin_id, remove in (("coding.base", True), ("coding.arch.default", False)):
        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=lifecycle.scope_id,
            plugin_id=plugin_id,
        )
        operation_id = f"old-{plugin_id}-install"
        service.submit(
            PluginManagementCommandV1(
                action="install",
                mutation=PluginDesiredStateMutationV1(
                    operation_id=operation_id,
                    idempotency_key=operation_id,
                    expected_inventory_revision=desired_ledger.snapshot().inventory_revision,
                    installation_key=key,
                    desired_state="installed_disabled",
                    package_revision=PluginPackageRevisionRefV1(
                        plugin_id=plugin_id,
                        plugin_version="1",
                        package_content_digest="1" * 64,
                        dependency_lock_digest="2" * 64,
                        package_source_identity=f"embedded:{plugin_id}",
                    ),
                    actor_id="old-operator",
                    policy_revision="old-policy:1",
                ),
            )
        )
        if remove:
            operation_id = f"old-{plugin_id}-remove"
            service.submit(
                PluginManagementCommandV1(
                    action="remove",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id=operation_id,
                        idempotency_key=operation_id,
                        expected_inventory_revision=desired_ledger.snapshot().inventory_revision,
                        installation_key=key,
                        desired_state="absent",
                        package_revision=None,
                        actor_id="old-operator",
                        policy_revision="old-policy:1",
                    ),
                )
            )
    members = resolve_coding_lifecycle_pre_b_members(lifecycle).domain_members()
    assert members.get("binding_history", ()) == ()
    assert members["desired_state"] == (
        "desired-state.jsonl",
        "desired-state.jsonl.lock",
        "management-operations.jsonl",
        "management-operations.jsonl.lock",
    )
    if case == "missing_arch_operation":
        lines = lifecycle.management_operations.read_bytes().splitlines()
        lifecycle.management_operations.write_bytes(b"\n".join(lines[:-2]) + b"\n")
    if case == "changed_lock":
        lifecycle.desired_state.with_name("desired-state.jsonl.lock").write_bytes(
            b"bad"
        )
    if case == "retirement_record":
        lifecycle.retirement_intents.write_text("unexpected\n", encoding="utf-8")
    prefix = ("--workspace", str(workspace))
    result = cutover_main((*prefix, "--prepare-legacy-builtin-review"))
    if case != "accepted":
        assert result == 1
        assert capsys.readouterr().out == ""
        assert not (
            resolve_coding_package_epoch_layout(lifecycle).control_root / "epoch.jsonl"
        ).exists()
        return
    assert result == 0
    review = json.loads(capsys.readouterr().out)
    assert review["removedBuiltinIds"] == ["coding.base"]
    assert review["builtinIntent"] == [
        {"pluginId": "coding.arch.default", "desiredState": "installed_disabled"}
    ]
    lifecycle.management_operations.write_bytes(b"changed old live operations")
    assert cutover_main((*prefix, "--review-legacy-builtin-only")) == 0
    assert json.loads(capsys.readouterr().out) == review
    assert (
        cutover_main((*prefix, "--adopt-legacy-builtin-review", review["reviewId"]))
        == 0
    )
    assert json.loads(capsys.readouterr().out)["disposition"] == "adopted"
    assert cutover_main(prefix) == 0
    assert json.loads(capsys.readouterr().out)["disposition"] == "fenced"
    product = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        snapshot = product.runtime_owner.product_owner.desired_state.snapshot()
        for plugin_id, state in (
            ("coding.base", "absent"),
            ("coding.arch.default", "installed_disabled"),
        ):
            key = PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=lifecycle.scope_id,
                plugin_id=plugin_id,
            )
            assert snapshot.installation(key).selection.desired_state == state
    finally:
        product.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize("remove_base", (False, True))
def test_removed_old_local_cli_requires_reviewed_adoption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    remove_base: bool,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    _source, plugin_id = _old_installed_local_source(
        tmp_path, lifecycle, old_enabled=False
    )
    old_desired_path = tmp_path / "old-desired-removed.jsonl"
    old_desired_path.write_bytes(lifecycle.desired_state.read_bytes())
    old_desired = PluginDesiredStateLedger(old_desired_path)
    old_desired.commit(
        PluginDesiredStateMutationV1(
            operation_id="old-remove",
            idempotency_key="old-remove",
            expected_inventory_revision=1,
            installation_key=PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=lifecycle.scope_id,
                plugin_id=plugin_id,
            ),
            desired_state="absent",
            package_revision=None,
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    if remove_base:
        old_desired.commit(
            PluginDesiredStateMutationV1(
                operation_id="old-base-remove",
                idempotency_key="old-base-remove",
                expected_inventory_revision=old_desired.snapshot().inventory_revision,
                installation_key=PluginInstallationKeyV1(
                    product_id="coding",
                    installation_scope="workspace",
                    scope_id=lifecycle.scope_id,
                    plugin_id="coding.base",
                ),
                desired_state="absent",
                package_revision=None,
                actor_id="old-operator",
                policy_revision="old-policy:1",
            )
        )
    lifecycle.desired_state.write_bytes(old_desired_path.read_bytes())
    prepare = ("--workspace", str(workspace), "--prepare-legacy-removed-review")
    assert cutover_main(prepare) == 0
    review = json.loads(capsys.readouterr().out)
    assert review["removedLocal"][0]["pluginId"] == plugin_id
    assert review["removedBuiltinIds"] == (["coding.base"] if remove_base else [])
    lifecycle.desired_state.write_bytes(b"changed old live state")
    assert (
        cutover_main(("--workspace", str(workspace), "--review-legacy-removed-only"))
        == 0
    )
    assert json.loads(capsys.readouterr().out) == review
    assert cutover_main(("--workspace", str(workspace))) == 1
    assert "explicit adoption" in capsys.readouterr().err
    assert (
        cutover_main(
            ("--workspace", str(workspace), "--adopt-legacy-removed-review", "0" * 64)
        )
        == 1
    )
    assert capsys.readouterr().out == ""
    with patch(
        "loushang.coding.package_legacy_removed_adoption._preserve_removed",
        side_effect=RuntimeError("interrupted after acceptance"),
    ):
        assert (
            cutover_main(
                (
                    "--workspace",
                    str(workspace),
                    "--adopt-legacy-removed-review",
                    review["reviewId"],
                )
            )
            == 1
        )
    assert capsys.readouterr().out == ""
    assert (
        resolve_coding_package_epoch_layout(lifecycle).control_root
        / "product-state"
        / "legacy-removed-acceptance.jsonl"
    ).exists()
    assert (
        cutover_main(
            (
                "--workspace",
                str(workspace),
                "--adopt-legacy-removed-review",
                review["reviewId"],
            )
        )
        == 0
    )
    adopted = json.loads(capsys.readouterr().out)
    assert adopted["reviewId"] == review["reviewId"]
    assert cutover_main(("--workspace", str(workspace))) == 0
    assert json.loads(capsys.readouterr().out)["disposition"] == "fenced"
    fresh = subprocess.run(
        [
            sys.executable,
            "-m",
            "loushang.coding.cli.package_cutover",
            "--workspace",
            str(workspace),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert fresh.returncode == 0, fresh.stderr
    assert json.loads(fresh.stdout)["disposition"] == "fenced"
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        selected = owner.runtime_owner.product_owner.desired_state.snapshot()
        base = selected.installation(
            PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=lifecycle.scope_id,
                plugin_id="coding.base",
            )
        )
        assert base.selection.desired_state == (
            "absent" if remove_base else "installed_enabled"
        )
    finally:
        owner.close()
    acceptance_path = (
        resolve_coding_package_epoch_layout(lifecycle).control_root
        / "product-state"
        / "legacy-removed-acceptance.jsonl"
    )
    foreign_acceptance = tmp_path / "foreign-removed-acceptance.jsonl"
    foreign_acceptance.write_bytes(acceptance_path.read_bytes())
    acceptance_path.unlink()
    acceptance_path.symlink_to(foreign_acceptance)
    assert cutover_main(("--workspace", str(workspace))) == 1
    assert capsys.readouterr().out == ""


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize(
    "old_history", ["remove_only", "changed_install", "changed_reinstall"]
)
def test_removed_old_local_refuses_unproven_history_before_first_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    old_history: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    _source, plugin_id = _old_installed_local_source(
        tmp_path, lifecycle, old_enabled=False
    )
    [binding] = parse_coding_legacy_local_binding_heads(
        (lifecycle.package_root / "package-lock.json").read_bytes()
    )
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=lifecycle.scope_id,
        plugin_id=plugin_id,
    )
    old_path = tmp_path / "unproven-old-desired.jsonl"
    old_desired = PluginDesiredStateLedger(old_path)
    if old_history != "remove_only":
        old_desired.commit(
            PluginDesiredStateMutationV1(
                operation_id="old-install",
                idempotency_key="old-install",
                expected_inventory_revision=0,
                installation_key=key,
                desired_state="installed_disabled",
                package_revision=PluginPackageRevisionRefV1(
                    plugin_id=plugin_id,
                    plugin_version="1",
                    package_content_digest=(
                        binding.content_digest
                        if old_history == "changed_reinstall"
                        else "f" * 64
                    ),
                    dependency_lock_digest=binding.dependency_lock.digest,
                    package_source_identity=binding.source_identity,
                ),
                actor_id="old-operator",
                policy_revision="old-policy:1",
            )
        )
    old_desired.commit(
        PluginDesiredStateMutationV1(
            operation_id="old-remove",
            idempotency_key="old-remove",
            expected_inventory_revision=(0 if old_history == "remove_only" else 1),
            installation_key=key,
            desired_state="absent",
            package_revision=None,
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    if old_history == "changed_reinstall":
        old_desired.commit(
            PluginDesiredStateMutationV1(
                operation_id="old-reinstall",
                idempotency_key="old-reinstall",
                expected_inventory_revision=2,
                installation_key=key,
                desired_state="installed_disabled",
                package_revision=PluginPackageRevisionRefV1(
                    plugin_id=plugin_id,
                    plugin_version="2",
                    package_content_digest="f" * 64,
                    dependency_lock_digest=binding.dependency_lock.digest,
                    package_source_identity=binding.source_identity,
                ),
                actor_id="old-operator",
                policy_revision="old-policy:1",
            )
        )
        old_desired.commit(
            PluginDesiredStateMutationV1(
                operation_id="old-remove-again",
                idempotency_key="old-remove-again",
                expected_inventory_revision=3,
                installation_key=key,
                desired_state="absent",
                package_revision=None,
                actor_id="old-operator",
                policy_revision="old-policy:1",
            )
        )
    lifecycle.desired_state.write_bytes(old_path.read_bytes())
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    assert (
        cutover_main(("--workspace", str(workspace), "--prepare-legacy-removed-review"))
        == 1
    )
    assert capsys.readouterr().out == ""
    assert not (epoch.control_root / "epoch.jsonl").exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize("updated_second", (False, True))
def test_two_removed_old_locals_replay_after_first_tombstone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    updated_second: bool,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    local = _old_installed_local_skills(tmp_path, lifecycle, count=2)
    old_path = tmp_path / "old-removed-both.jsonl"
    old_path.write_bytes(lifecycle.desired_state.read_bytes())
    old_desired = PluginDesiredStateLedger(old_path)
    for _source, plugin_id in local:
        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=lifecycle.scope_id,
            plugin_id=plugin_id,
        )
        if updated_second and plugin_id == local[1][1]:
            current = (
                old_desired.snapshot().installation(key).selection.package_revision
            )
            assert current is not None
            staged = PluginPackageRevisionRefV1(
                plugin_id=plugin_id,
                plugin_version="2",
                package_content_digest="e" * 64,
                dependency_lock_digest="d" * 64,
                package_source_identity=current.package_source_identity,
            )
            _commit_old_update(
                old_desired,
                key,
                current,
                staged,
                operation_id="old-update-away",
                desired_state="installed_enabled",
            )
            _commit_old_update(
                old_desired,
                key,
                staged,
                current,
                operation_id="old-update-head",
                desired_state="installed_enabled",
            )
        operation_id = f"old-remove-{plugin_id}"
        old_desired.commit(
            PluginDesiredStateMutationV1(
                operation_id=operation_id,
                idempotency_key=operation_id,
                expected_inventory_revision=old_desired.snapshot().inventory_revision,
                installation_key=key,
                desired_state="absent",
                package_revision=None,
                actor_id="old-operator",
                policy_revision="old-policy:1",
            )
        )
    lifecycle.desired_state.write_bytes(old_path.read_bytes())
    assert (
        cutover_main(("--workspace", str(workspace), "--prepare-legacy-removed-review"))
        == 0
    )
    review = json.loads(capsys.readouterr().out)
    assert len(review["removedLocal"]) == 2
    assert review["reviewVersion"] == (2 if updated_second else 1)
    if updated_second:
        assert [item["headTransitionKind"] for item in review["removedLocal"]] == [
            "install",
            "update",
        ]
        assert review["removedLocal"][1]["headOperationId"] == "old-update-head"
    original = removed_adoption_module._preserve_removed
    calls = 0

    def interrupt_second(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("interrupted after first tombstone")
        original(*args, **kwargs)

    with patch.object(
        removed_adoption_module, "_preserve_removed", side_effect=interrupt_second
    ):
        assert (
            cutover_main(
                (
                    "--workspace",
                    str(workspace),
                    "--adopt-legacy-removed-review",
                    review["reviewId"],
                )
            )
            == 1
        )
    assert capsys.readouterr().out == ""
    assert (
        cutover_main(
            (
                "--workspace",
                str(workspace),
                "--adopt-legacy-removed-review",
                review["reviewId"],
            )
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["disposition"] == "adopted"
    product = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        states = product.runtime_owner.product_owner.desired_state.snapshot()
        assert all(
            states.installation(
                PluginInstallationKeyV1(
                    product_id="coding",
                    installation_scope="workspace",
                    scope_id=lifecycle.scope_id,
                    plugin_id=plugin_id,
                )
            ).selection.desired_state
            == "absent"
            for _source, plugin_id in local
        )
    finally:
        product.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize("configured_source", (False, True))
@pytest.mark.parametrize("remove_base", (False, True))
def test_mixed_active_and_removed_old_locals_require_removed_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    configured_source: bool,
    remove_base: bool,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    local = _old_installed_local_skills(tmp_path, lifecycle, count=2)
    active_id = local[0][1]
    removed_id = local[1][1]
    if configured_source:
        project_settings = default_project_settings_path(workspace)
        project_settings.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        project_settings.write_text(
            json.dumps({"plugin_sources": [str(local[0][0])]}), encoding="utf-8"
        )
    old_path = tmp_path / "old-mixed-desired.jsonl"
    old_path.write_bytes(lifecycle.desired_state.read_bytes())
    old_desired = PluginDesiredStateLedger(old_path)
    old_desired.commit(
        PluginDesiredStateMutationV1(
            operation_id="old-mixed-remove",
            idempotency_key="old-mixed-remove",
            expected_inventory_revision=old_desired.snapshot().inventory_revision,
            installation_key=PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=lifecycle.scope_id,
                plugin_id=removed_id,
            ),
            desired_state="absent",
            package_revision=None,
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    if remove_base:
        old_desired.commit(
            PluginDesiredStateMutationV1(
                operation_id="old-mixed-base-remove",
                idempotency_key="old-mixed-base-remove",
                expected_inventory_revision=old_desired.snapshot().inventory_revision,
                installation_key=PluginInstallationKeyV1(
                    product_id="coding",
                    installation_scope="workspace",
                    scope_id=lifecycle.scope_id,
                    plugin_id="coding.base",
                ),
                desired_state="absent",
                package_revision=None,
                actor_id="old-operator",
                policy_revision="old-policy:1",
            )
        )
    lifecycle.desired_state.write_bytes(old_path.read_bytes())
    assert (
        cutover_main(
            (
                "--workspace",
                str(workspace),
                "--prepare-legacy-local-skill-review",
                active_id,
            )
        )
        == 0
    )
    active_review = json.loads(capsys.readouterr().out)
    assert active_review.get("removedBuiltinIds", []) == (
        ["coding.base"] if remove_base else []
    )
    assert (
        cutover_main(("--workspace", str(workspace), "--review-legacy-removed-only"))
        == 0
    )
    removed_review = json.loads(capsys.readouterr().out)
    assert [item["pluginId"] for item in removed_review["removedLocal"]] == [removed_id]
    assert removed_review.get("removedBuiltinIds", []) == (
        ["coding.base"] if remove_base else []
    )
    active_adopt = (
        "--workspace",
        str(workspace),
        "--adopt-legacy-local-skill-review",
        active_id,
        active_review["reviewId"],
    )
    assert cutover_main(active_adopt) == 1
    assert "before active locals" in capsys.readouterr().err
    removed_adopt = (
        "--workspace",
        str(workspace),
        "--adopt-legacy-removed-review",
        removed_review["reviewId"],
    )
    if configured_source:
        with patch(
            "loushang.coding.package_legacy_removed_adoption._preserve_removed",
            side_effect=RuntimeError("interrupted after acceptance"),
        ):
            assert cutover_main(removed_adopt) == 1
        assert capsys.readouterr().out == ""
    else:
        assert cutover_main(removed_adopt) == 0
        assert json.loads(capsys.readouterr().out)["disposition"] == "adopted"
    assert cutover_main(active_adopt) == 0
    assert json.loads(capsys.readouterr().out)["pluginId"] == active_id
    assert cutover_main(("--workspace", str(workspace))) == 0
    assert json.loads(capsys.readouterr().out)["disposition"] == "fenced"
    product = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        product_owner = product.runtime_owner.product_owner
        states = {
            item.installation_key.plugin_id: item.selection.desired_state
            for item in product_owner.desired_state.snapshot().installations
        }
        assert states[removed_id] == "absent"
        assert states[active_id] == "installed_enabled"
        assert states["coding.base"] == (
            "absent" if remove_base else "installed_enabled"
        )
        if remove_base:
            base_events = tuple(
                item
                for item in product_owner.desired_state.transitions()
                if item.mutation.installation_key.plugin_id == "coding.base"
            )
            assert len(base_events) == 1
            assert base_events[0].mutation.operation_id.startswith(
                "coding-legacy-builtin-remove:"
            )
        manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "mixed-session",
                cwd=str(workspace),
                persist=False,
            )
        )
        model = Model(
            id="mixed-legacy-model",
            name="Mixed Legacy Model",
            provider="test",
            endpoint="anthropic-messages",
            capabilities=Capabilities(
                reasoning=True,
                input=("text",),
                context_window=128000,
                max_tokens=4096,
            ),
        )
        session = create_agent_session(
            session_manager=manager,
            model=model,
            services=create_services(
                settings_manager=SettingsManager(
                    global_settings_path=default_global_settings_path(),
                    project_settings_path=default_project_settings_path(workspace),
                )
            ),
            composition_set="coding-standard",
            package_product_runtime_factory=product.factory_for_session(manager),
        )
        try:
            assert (session._coding_base_product_compilation is None) == remove_base
            assert session.resource_bundle is not None
            skill_names = {item.name for item in session.resource_bundle.skills}
            assert "review-1" in skill_names
            assert "review-2" not in skill_names

            async def load_active_skill():
                await session.prepare_model_call_runtime()
                return await session._preflight_user_input_async("/skill:review-1")

            loaded = asyncio.run(load_active_skill())
            assert len(loaded.loaded_skills) == 1
            assert "# Review 1" in loaded.loaded_skills[0].content
        finally:
            asyncio.run(session.dispose())
        if configured_source:
            active_key = PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=lifecycle.scope_id,
                plugin_id=active_id,
            )
            disabled = product_owner.management.submit(
                PluginManagementCommandV1(
                    action="disable",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id="operator-disable-mixed-active",
                        idempotency_key="operator-disable-mixed-active",
                        expected_inventory_revision=(
                            product_owner.desired_state.snapshot().inventory_revision
                        ),
                        installation_key=active_key,
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
        product.close()
    if configured_source:
        assert cutover_main(("--workspace", str(workspace))) == 0
        assert json.loads(capsys.readouterr().out)["disposition"] == "fenced"
        reopened = open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        try:
            snapshot = reopened.runtime_owner.product_owner.desired_state.snapshot()
            assert snapshot.installation(active_key).selection.desired_state == (
                "installed_disabled"
            )
            manager = asyncio.run(
                SessionManager.new(
                    session_dir=tmp_path / "mixed-disabled-session",
                    cwd=str(workspace),
                    persist=False,
                )
            )
            session = create_agent_session(
                session_manager=manager,
                model=model,
                services=create_services(
                    settings_manager=SettingsManager(
                        global_settings_path=default_global_settings_path(),
                        project_settings_path=default_project_settings_path(workspace),
                    )
                ),
                composition_set="coding-standard",
                package_product_runtime_factory=reopened.factory_for_session(manager),
            )
            try:
                assert session.resource_bundle is not None
                skill_names = {item.name for item in session.resource_bundle.skills}
                assert "review-1" not in skill_names
                assert "review-2" not in skill_names
            finally:
                asyncio.run(session.dispose())
        finally:
            reopened.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_mixed_old_local_unproven_removal_refuses_before_first_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    local = _old_installed_local_skills(tmp_path, lifecycle, count=2)
    active_id = local[0][1]
    removed_id = local[1][1]
    bindings = parse_coding_legacy_local_binding_heads(
        (lifecycle.package_root / "package-lock.json").read_bytes()
    )
    active_binding = next(item for item in bindings if item.plugin_id == active_id)
    old_path = tmp_path / "old-unproven-mixed.jsonl"
    old_desired = PluginDesiredStateLedger(old_path)
    for operation_id, plugin_id, desired_state, revision in (
        (
            "old-active-install",
            active_id,
            "installed_disabled",
            PluginPackageRevisionRefV1(
                plugin_id=active_id,
                plugin_version="1",
                package_content_digest=active_binding.content_digest,
                dependency_lock_digest=active_binding.dependency_lock.digest,
                package_source_identity=active_binding.source_identity,
            ),
        ),
        ("old-removed-without-install", removed_id, "absent", None),
    ):
        old_desired.commit(
            PluginDesiredStateMutationV1(
                operation_id=operation_id,
                idempotency_key=operation_id,
                expected_inventory_revision=old_desired.snapshot().inventory_revision,
                installation_key=PluginInstallationKeyV1(
                    product_id="coding",
                    installation_scope="workspace",
                    scope_id=lifecycle.scope_id,
                    plugin_id=plugin_id,
                ),
                desired_state=desired_state,  # type: ignore[arg-type]
                package_revision=revision,
                actor_id="old-operator",
                policy_revision="old-policy:1",
            )
        )
    lifecycle.desired_state.write_bytes(old_path.read_bytes())
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    assert (
        cutover_main(
            (
                "--workspace",
                str(workspace),
                "--prepare-legacy-local-skill-review",
                active_id,
            )
        )
        == 1
    )
    assert capsys.readouterr().out == ""
    assert not (epoch.control_root / "epoch.jsonl").exists()


def _old_installed_local_skills(
    tmp_path: Path,
    lifecycle,
    *,
    duplicate_names: bool = False,
    count: int = 2,
    resource_kinds: tuple[str, ...] | None = None,
) -> tuple[tuple[Path, str], ...]:
    prepare_coding_package_cutover_roots(lifecycle)
    if resource_kinds is not None and (
        len(resource_kinds) != count
        or any(kind not in {"skill", "prompt", "theme"} for kind in resource_kinds)
    ):
        raise ValueError("Old local test Resource types are invalid")
    sources: list[Path] = []
    for index in range(1, count + 1):
        resource_kind = "skill" if resource_kinds is None else resource_kinds[index - 1]
        skill_name = "review-1" if duplicate_names else f"review-{index}"
        source = tmp_path / f"old-source-{index}"
        source.mkdir()
        compiled = package(
            id=f"review-pack-{index}",
            version="1",
            contributions=(
                (
                    resource.skill(
                        contribution_id=f"review-skill-{index}",
                        locator=f"skills/{skill_name}",
                    )
                    if resource_kind == "skill"
                    else resource.prompt(
                        contribution_id=f"review-prompt-{index}",
                        locator=f"prompts/{skill_name}.md",
                    )
                    if resource_kind == "prompt"
                    else resource.theme(
                        contribution_id=f"review-theme-{index}",
                        locator=f"themes/{skill_name}.json",
                    )
                ),
            ),
        )
        for artifact in compiled.artifacts:
            target = source / artifact.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(artifact.content)
        body = source / (
            f"skills/{skill_name}/SKILL.md"
            if resource_kind == "skill"
            else f"prompts/{skill_name}.md"
            if resource_kind == "prompt"
            else f"themes/{skill_name}.json"
        )
        body.parent.mkdir(parents=True, exist_ok=True)
        body.write_text(
            f"---\nname: {skill_name}\ndescription: review files\n---\n# Review {index}\n"
            if resource_kind == "skill"
            else f"# Review {index}\nCheck the change.\n"
            if resource_kind == "prompt"
            else json.dumps(
                {
                    "schemaVersion": 1,
                    "tokens": {"welcome.title": {"color": "red"}},
                }
            )
        )
        sources.append(source)
    old_package = tmp_path / "old-package"
    materializer = PackageMaterializer(install_root=old_package / "installed")
    published = materializer.publish_plugin_packages(
        tuple(PluginManifestParser().parse(source) for source in sources)
    )
    try:
        materializer.bind_plugin_packages(published)
    finally:
        for item in published:
            item.revision_handle.close()
    lock_bytes = (old_package / "package-lock.json").read_bytes()
    (lifecycle.package_root / "package-lock.json").write_bytes(lock_bytes)
    bindings = parse_coding_legacy_local_binding_heads(lock_bytes)
    old_desired = tmp_path / "old-desired.jsonl"
    ledger = PluginDesiredStateLedger(old_desired)
    for binding in bindings:
        revision = PluginPackageRevisionRefV1(
            plugin_id=binding.plugin_id,
            plugin_version="1",
            package_content_digest=binding.content_digest,
            dependency_lock_digest=binding.dependency_lock.digest,
            package_source_identity=binding.source_identity,
        )
        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=lifecycle.scope_id,
            plugin_id=binding.plugin_id,
        )
        for desired_state in ("installed_disabled", "installed_enabled"):
            inventory_revision = ledger.snapshot().inventory_revision
            operation_id = f"old-{binding.plugin_id}-{desired_state}"
            ledger.commit(
                PluginDesiredStateMutationV1(
                    operation_id=operation_id,
                    idempotency_key=operation_id,
                    expected_inventory_revision=inventory_revision,
                    installation_key=key,
                    desired_state=desired_state,
                    package_revision=(
                        revision if desired_state == "installed_disabled" else None
                    ),
                    actor_id="old-operator",
                    policy_revision="old-policy:1",
                )
            )
    lifecycle.desired_state.write_bytes(old_desired.read_bytes())
    by_source = {binding.source_identity: binding.plugin_id for binding in bindings}
    return tuple((source, by_source[f"local:{source.resolve()}"]) for source in sources)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_offline_local_disabled_skill_keeps_old_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    _source, plugin_id = _old_installed_local_source(
        tmp_path, lifecycle, old_enabled=False
    )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        SettingsManager(
            global_settings_path=default_global_settings_path(),
            project_settings_path=default_project_settings_path(workspace),
        ),
        namespace_id=sha256(
            b"loushang.coding-fresh-product-epoch/v1\0" + epoch.store_id.encode()
        ).hexdigest(),
        minimum_runtime_version=version("loushang"),
        minimum_runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    assert (
        cutover_main(
            (
                "--workspace",
                str(workspace),
                "--review-legacy-local-plugin",
                plugin_id,
            )
        )
        == 0
    )
    review = json.loads(capsys.readouterr().out)
    assert review["desiredState"] == "installed_disabled"
    adoption = (
        "--workspace",
        str(workspace),
        "--adopt-legacy-local-skill-review",
        plugin_id,
        review["reviewId"],
    )
    assert cutover_main(adoption) == 0
    adopted = json.loads(capsys.readouterr().out)
    assert adopted["enableOperationId"] is None
    assert cutover_main(adoption) == 0
    assert json.loads(capsys.readouterr().out) == adopted
    assert cutover_main(("--workspace", str(workspace))) == 0
    assert json.loads(capsys.readouterr().out)["disposition"] == "fenced"
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        selected = {
            item.installation_key.plugin_id: item.selection.desired_state
            for item in owner.runtime_owner.product_owner.desired_state.snapshot().installations
        }
        assert selected[plugin_id] == "installed_disabled"
        assert selected["coding.base"] == "installed_enabled"
    finally:
        owner.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_offline_three_local_skills_consume_one_scoped_source_at_a_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    local = _old_installed_local_skills(tmp_path, lifecycle, count=3)
    settings_path = default_project_settings_path(workspace)
    settings_path.parent.mkdir(parents=True, mode=0o700)
    settings_path.write_text(
        json.dumps({"plugin_sources": [str(source) for source, _ in local]}) + "\n",
        encoding="utf-8",
    )
    reviews: list[dict[str, Any]] = []
    for _source, plugin_id in local:
        assert (
            cutover_main(
                (
                    "--workspace",
                    str(workspace),
                    "--prepare-legacy-local-skill-review",
                    plugin_id,
                )
            )
            == 0
        )
        review = json.loads(capsys.readouterr().out)
        assert review["configuredPluginSourceScope"] == "project"
        reviews.append(review)
    for index, (_source, plugin_id) in enumerate(local):
        assert (
            cutover_main(
                (
                    "--workspace",
                    str(workspace),
                    "--adopt-legacy-local-skill-review",
                    plugin_id,
                    reviews[index]["reviewId"],
                )
            )
            == 0
        )
        capsys.readouterr()
        assert json.loads(settings_path.read_text())["plugin_sources"] == [
            str(source) for source, _ in local[index + 1 :]
        ]
        if index == 0:
            shutil.rmtree(local[0][0])
        assert cutover_main(("--workspace", str(workspace))) == (0 if index == 2 else 1)
        capsys.readouterr()
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        selected = {
            item.installation_key.plugin_id: item.selection.desired_state
            for item in owner.runtime_owner.product_owner.desired_state.snapshot().installations
        }
        assert all(selected[plugin_id] == "installed_enabled" for _, plugin_id in local)
    finally:
        owner.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize(
    "disabled_builtin,legacy_manifest_disabled",
    [
        (None, False),
        (("project", "coding.lsp.default"), False),
        (("global", "coding.base"), False),
        (None, True),
    ],
)
def test_offline_local_skill_review_adoption_and_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    disabled_builtin: tuple[str, str] | None,
    legacy_manifest_disabled: bool,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    source, plugin_id = _old_installed_local_source(
        tmp_path, lifecycle, legacy_manifest_disabled=legacy_manifest_disabled
    )
    if disabled_builtin is not None:
        scope, disabled_id = disabled_builtin
        settings_path = (
            default_project_settings_path(workspace)
            if scope == "project"
            else default_global_settings_path()
        )
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        old_settings: dict[str, object] = {"disabled_plugins": [disabled_id]}
        if disabled_id == "coding.lsp.default":
            old_settings["capabilities"] = {"coding.lsp": "always"}
        settings_path.write_text(
            json.dumps(old_settings) + "\n",
            encoding="utf-8",
        )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    prepare = (
        "--workspace",
        str(workspace),
        "--prepare-legacy-local-skill-review",
        plugin_id,
    )
    assert cutover_main(prepare) == 0
    review = json.loads(capsys.readouterr().out)
    assert review["pluginId"] == plugin_id
    assert review["desiredState"] == "installed_enabled"
    if disabled_builtin is not None:
        scope, disabled_id = disabled_builtin
        assert review["disabledPlugins"] == [{"scope": scope, "pluginId": disabled_id}]
        assert (
            CodingLegacyLocalAdoptionReviewV1.from_dict(review).review_id
            == (review["reviewId"])
        )
        with pytest.raises(ValueError, match="identity changed"):
            CodingLegacyLocalAdoptionReviewV1.from_dict(
                {
                    **review,
                    "disabledPlugins": [
                        {"scope": scope, "pluginId": "coding.arch.default"}
                    ],
                }
            )
    else:
        assert "disabledPlugins" not in review
    fence_bytes = (epoch.control_root / "epoch.jsonl").read_bytes()
    assert cutover_main(prepare) == 0
    assert json.loads(capsys.readouterr().out) == review
    assert (epoch.control_root / "epoch.jsonl").read_bytes() == fence_bytes

    bad_adoption = (
        "--workspace",
        str(workspace),
        "--adopt-legacy-local-skill-review",
        plugin_id,
        "0" * 64,
    )
    assert cutover_main(bad_adoption) == 1
    assert capsys.readouterr().out == ""
    adoption = (*bad_adoption[:-1], review["reviewId"])
    with patch(
        "loushang.coding.package_legacy_local_adoption.bind_coding_accepted_legacy_local_source",
        side_effect=RuntimeError("interrupted after acceptance"),
    ):
        assert cutover_main(adoption) == 1
    assert capsys.readouterr().out == ""
    assert (
        len(
            tuple(
                (epoch.control_root / "product-state").glob(
                    "legacy-local-acceptance-*.jsonl"
                )
            )
        )
        == 1
    )
    assert cutover_main(("--workspace", str(workspace))) == 1
    assert capsys.readouterr().out == ""
    with patch(
        "loushang.coding.package_legacy_local_adoption.enable_coding_accepted_legacy_local_data_plugin",
        side_effect=RuntimeError("interrupted after install"),
    ):
        assert cutover_main(adoption) == 1
    assert capsys.readouterr().out == ""
    assert cutover_main(("--workspace", str(workspace))) == 1
    assert capsys.readouterr().out == ""
    assert cutover_main(adoption) == 0
    adopted = json.loads(capsys.readouterr().out)
    assert adopted["disposition"] == "adopted"
    assert adopted["pluginId"] == plugin_id
    assert adopted["enableOperationId"]
    shutil.rmtree(source)
    restarted = subprocess.run(
        (
            sys.executable,
            "-m",
            "loushang.coding.cli.package_cutover",
            *adoption,
        ),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    assert restarted.returncode == 0, restarted.stderr
    assert json.loads(restarted.stdout) == adopted
    assert (epoch.control_root / "epoch.jsonl").read_bytes() == fence_bytes
    before_default = tuple(
        sorted(
            (str(path.relative_to(tmp_path)), path.read_bytes())
            for path in tmp_path.rglob("*")
            if path.is_file()
        )
    )
    assert cutover_main(("--workspace", str(workspace))) == 0
    assert json.loads(capsys.readouterr().out)["disposition"] == "fenced"
    assert (
        tuple(
            sorted(
                (str(path.relative_to(tmp_path)), path.read_bytes())
                for path in tmp_path.rglob("*")
                if path.is_file()
            )
        )
        == before_default
    )
    handoff_path = epoch.control_root / "product-state" / "handoff.jsonl"
    handoff_bytes = handoff_path.read_bytes()
    handoff_path.write_bytes(b"")
    try:
        assert cutover_main(("--workspace", str(workspace))) == 1
        assert capsys.readouterr().out == ""
    finally:
        handoff_path.write_bytes(handoff_bytes)

    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        product = owner.runtime_owner.product_owner
        selected = {
            item.installation_key.plugin_id: item.selection.desired_state
            for item in product.desired_state.snapshot().installations
        }
        assert selected == {
            plugin_id: "installed_enabled",
            "coding.base": (
                "installed_disabled"
                if disabled_builtin is not None and disabled_builtin[1] == "coding.base"
                else "installed_enabled"
            ),
            "coding.lsp.default": (
                "installed_disabled"
                if disabled_builtin is not None
                and disabled_builtin[1] == "coding.lsp.default"
                else "installed_enabled"
            ),
            "coding.arch.default": "installed_enabled",
        }
        if legacy_manifest_disabled:
            selected_runtime = product.factory_for_session(
                session_id="legacy-skill-manifest-check",
                cwd=workspace,
                runtime_id="legacy-skill-manifest-check",
            ).create(
                PackageProductRuntimeRequestV1(
                    product_id="coding",
                    session_id="legacy-skill-manifest-check",
                    cwd=str(workspace),
                )
            )
            try:
                selected_runtime.activate()
                captured = selected_runtime.capture_selected_plugin_manifest_for(
                    plugin_id, max_files=64, max_total_bytes=1024 * 1024
                )
                assert captured.verified_manifest().enabled is False
            finally:
                selected_runtime.dispose_runtime()
        if disabled_builtin is not None or legacy_manifest_disabled:
            manager = asyncio.run(
                SessionManager.new(
                    session_dir=tmp_path / "mixed-legacy-session",
                    cwd=str(workspace),
                    persist=False,
                )
            )
            model = Model(
                id="mixed-legacy-skill-model",
                name="Mixed Legacy Skill Model",
                provider="test",
                endpoint="anthropic-messages",
                capabilities=Capabilities(
                    reasoning=True,
                    input=("text",),
                    context_window=128000,
                    max_tokens=4096,
                ),
            )
            session = create_agent_session(
                session_manager=manager,
                model=model,
                services=create_services(
                    settings_manager=SettingsManager(
                        global_settings_path=default_global_settings_path(),
                        project_settings_path=default_project_settings_path(workspace),
                    )
                ),
                composition_set="coding-standard",
                package_product_runtime_factory=owner.factory_for_session(manager),
            )
            try:
                assert session.resource_bundle is not None
                assert any(
                    item.name == "review" and item.source_kind == "external_package"
                    for item in session.resource_bundle.skills
                )

                async def load_review():
                    await session.prepare_model_call_runtime()
                    return await session._preflight_user_input_async("/skill:review")

                loaded = asyncio.run(load_review())
                assert len(loaded.loaded_skills) == 1
                assert "# Review" in loaded.loaded_skills[0].content
                if disabled_builtin == ("project", "coding.lsp.default"):
                    capability_snapshot = session._capability_graph_runtime.snapshot
                    assert capability_snapshot is not None
                    assert "coding.lsp" not in {
                        node.capability_id for node in capability_snapshot.nodes
                    }
                    assert {"document_outline", "inspect_symbol"}.isdisjoint(
                        session.get_active_tool_names()
                    )
            finally:
                asyncio.run(session.dispose())
            if disabled_builtin == ("project", "coding.lsp.default"):
                lsp_key = PluginInstallationKeyV1(
                    product_id="coding",
                    installation_scope="workspace",
                    scope_id=lifecycle.scope_id,
                    plugin_id="coding.lsp.default",
                )
                enabled = product.management.submit(
                    PluginManagementCommandV1(
                        action="enable",
                        mutation=PluginDesiredStateMutationV1(
                            operation_id="operator-enable-lsp-after-mixed-migration",
                            idempotency_key="operator-enable-lsp-after-mixed-migration",
                            expected_inventory_revision=(
                                product.desired_state.snapshot().inventory_revision
                            ),
                            installation_key=lsp_key,
                            desired_state="installed_enabled",
                            package_revision=None,
                            actor_id="operator",
                            policy_revision=product.desired_policy_revision,
                        ),
                    )
                )
                assert enabled.result is not None
                assert enabled.result.disposition == "succeeded"
                second_manager = asyncio.run(
                    SessionManager.new(
                        session_dir=tmp_path / "mixed-legacy-lsp-session",
                        cwd=str(workspace),
                        persist=False,
                    )
                )
                second_session = create_agent_session(
                    session_manager=second_manager,
                    model=model,
                    services=create_services(
                        settings_manager=SettingsManager(
                            global_settings_path=default_global_settings_path(),
                            project_settings_path=default_project_settings_path(
                                workspace
                            ),
                        )
                    ),
                    composition_set="coding-standard",
                    package_product_runtime_factory=owner.factory_for_session(
                        second_manager
                    ),
                )
                try:
                    asyncio.run(second_session.prepare_model_call_runtime())
                    capability_snapshot = (
                        second_session._capability_graph_runtime.snapshot
                    )
                    assert capability_snapshot is not None
                    assert "coding.lsp" in {
                        node.capability_id for node in capability_snapshot.nodes
                    }
                    assert {"document_outline", "inspect_symbol"} <= set(
                        second_session.get_active_tool_names()
                    )
                    assert second_session.resource_bundle is not None
                    assert any(
                        item.name == "review" and item.source_kind == "external_package"
                        for item in second_session.resource_bundle.skills
                    )
                finally:
                    asyncio.run(second_session.dispose())
        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=lifecycle.scope_id,
            plugin_id=plugin_id,
        )
        disabled = product.management.submit(
            PluginManagementCommandV1(
                action="disable",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator-disabled-after-adoption",
                    idempotency_key="operator-disabled-after-adoption",
                    expected_inventory_revision=(
                        product.desired_state.snapshot().inventory_revision
                    ),
                    installation_key=key,
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
    assert cutover_main(adoption) == 1
    assert capsys.readouterr().out == ""
    assert cutover_main(("--workspace", str(workspace))) == 0
    assert json.loads(capsys.readouterr().out)["disposition"] == "fenced"
    reopened = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        assert (
            reopened.runtime_owner.product_owner.desired_state.snapshot()
            .installation(key)
            .selection.desired_state
            == "installed_disabled"
        )
    finally:
        reopened.close()
    project_settings = default_project_settings_path(workspace)
    prior_settings = (
        project_settings.read_bytes() if project_settings.exists() else None
    )
    project_settings.parent.mkdir(parents=True, exist_ok=True)
    project_settings.write_text(
        json.dumps({"plugin_sources": [str(tmp_path / "new-old-source")]}) + "\n",
        encoding="utf-8",
    )
    assert cutover_main(("--workspace", str(workspace))) == 1
    if prior_settings is None:
        project_settings.unlink()
    else:
        project_settings.write_bytes(prior_settings)
    assert cutover_main(("--workspace", str(workspace))) == 0


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize(
    ("old_builtin_state", "scoped_disable"),
    (
        ("installed_disabled", False),
        ("installed_enabled", False),
        ("absent", False),
        ("installed_enabled", True),
    ),
)
def test_builtin_only_cli_review_is_frozen_and_does_not_claim_adoption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    old_builtin_state: str,
    scoped_disable: bool,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    prepare_coding_package_cutover_roots(lifecycle)
    project_settings = default_project_settings_path(workspace)
    if scoped_disable:
        project_settings.parent.mkdir(mode=0o700, exist_ok=True)
        project_settings.write_text(
            json.dumps({"disabled_plugins": ["coding.arch.default"]}) + "\n",
            encoding="utf-8",
        )
    old_path = tmp_path / "old-builtin.jsonl"
    old_desired = PluginDesiredStateLedger(old_path)
    old_desired.commit(
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
            desired_state=(
                "installed_disabled"
                if old_builtin_state == "installed_enabled"
                else old_builtin_state  # type: ignore[arg-type]
            ),
            package_revision=(
                None
                if old_builtin_state == "absent"
                else PluginPackageRevisionRefV1(
                    plugin_id="coding.arch.default",
                    plugin_version="1",
                    package_content_digest="1" * 64,
                    dependency_lock_digest="2" * 64,
                    package_source_identity="embedded:coding.arch.default",
                )
            ),
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    if old_builtin_state == "installed_enabled":
        old_desired.commit(
            PluginDesiredStateMutationV1(
                operation_id="old-arch-enable",
                idempotency_key="old-arch-enable",
                expected_inventory_revision=1,
                installation_key=PluginInstallationKeyV1(
                    product_id="coding",
                    installation_scope="workspace",
                    scope_id=lifecycle.scope_id,
                    plugin_id="coding.arch.default",
                ),
                desired_state="installed_enabled",
                package_revision=None,
                actor_id="old-operator",
                policy_revision="old-policy:1",
            )
        )
    lifecycle.desired_state.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    lifecycle.desired_state.write_bytes(old_path.read_bytes())
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    prepare = ("--workspace", str(workspace), "--prepare-legacy-builtin-review")
    assert cutover_main(prepare) == 0
    review = json.loads(capsys.readouterr().out)
    assert review["removedBuiltinIds"] == (
        ["coding.arch.default"] if old_builtin_state == "absent" else []
    )
    assert review["builtinIntent"] == (
        []
        if old_builtin_state == "absent"
        else [{"pluginId": "coding.arch.default", "desiredState": old_builtin_state}]
    )
    assert review["disabledPlugins"] == (
        [{"scope": "project", "pluginId": "coding.arch.default"}]
        if scoped_disable
        else []
    )
    with pytest.raises(ValueError, match="identity changed"):
        CodingLegacyBuiltinOnlyReviewV1.from_dict(
            {**review, "removedBuiltinIds": ["coding.lsp.default"]}
        )
    assert not (epoch.control_root / "product-state" / "desired-state.jsonl").exists()
    lifecycle.desired_state.write_bytes(b"changed old live state")
    assert (
        cutover_main(("--workspace", str(workspace), "--review-legacy-builtin-only"))
        == 0
    )
    assert json.loads(capsys.readouterr().out) == review
    assert cutover_main(("--workspace", str(workspace))) == 1
    refused = capsys.readouterr()
    assert refused.out == ""
    assert "pre-B workspace is unsupported" in refused.err
    wrong = ("--workspace", str(workspace), "--adopt-legacy-builtin-review", "0" * 64)
    assert cutover_main(wrong) == 1
    assert capsys.readouterr().out == ""
    adoption = (
        "--workspace",
        str(workspace),
        "--adopt-legacy-builtin-review",
        review["reviewId"],
    )
    with patch(
        "loushang.coding.package_legacy_builtin_adoption.open_coding_fenced_product_application_owner",
        side_effect=RuntimeError("interrupted after acceptance"),
    ):
        assert cutover_main(adoption) == 1
    assert capsys.readouterr().out == ""
    assert (
        epoch.control_root / "product-state" / "legacy-builtin-acceptance.jsonl"
    ).exists()
    if old_builtin_state == "installed_disabled":

        def fail_after_base(
            owner: object, plugin_id: str, *, enable: bool = True
        ) -> bool:
            if plugin_id == "coding.lsp.default":
                raise RuntimeError("interrupted after base Product commit")
            return _bootstrap_coding_builtin_plugin(
                owner,
                plugin_id,
                enable=enable,  # type: ignore[arg-type]
            )

        with patch(
            "loushang.coding.package_legacy_builtin_adoption._bootstrap_coding_builtin_plugin",
            side_effect=fail_after_base,
        ):
            assert cutover_main(adoption) == 1
        assert capsys.readouterr().out == ""
    assert cutover_main(adoption) == 0
    assert json.loads(capsys.readouterr().out)["disposition"] == "adopted"
    if scoped_disable:
        project_settings.write_text('{"disabled_plugins": []}\n', encoding="utf-8")
    assert cutover_main(("--workspace", str(workspace))) == 0
    assert json.loads(capsys.readouterr().out)["disposition"] == "fenced"
    restarted = subprocess.run(
        (
            sys.executable,
            "-m",
            "loushang.coding.cli.package_cutover",
            "--workspace",
            str(workspace),
        ),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    assert restarted.returncode == 0, restarted.stderr
    assert json.loads(restarted.stdout)["disposition"] == "fenced"
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        product = owner.runtime_owner.product_owner
        states = {
            item.installation_key.plugin_id: item.selection.desired_state
            for item in product.desired_state.snapshot().installations
        }
        assert states["coding.base"] == "installed_enabled"
        assert states["coding.arch.default"] == (
            "installed_disabled" if scoped_disable else old_builtin_state
        )
        if old_builtin_state == "absent":
            key = PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=lifecycle.scope_id,
                plugin_id="coding.arch.default",
            )
            history = tuple(
                item
                for item in product.desired_state.transitions()
                if item.mutation.installation_key == key
            )
            assert len(history) == 1
            assert history[0].mutation.operation_id.startswith(
                "coding-legacy-builtin-remove:"
            )
        manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "builtin-only-session",
                cwd=str(workspace),
                persist=False,
            )
        )
        session = create_agent_session(
            session_manager=manager,
            model=Model(
                id="builtin-only-selection",
                name="Builtin Only Selection",
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
                    global_settings_path=default_global_settings_path(),
                    project_settings_path=default_project_settings_path(workspace),
                )
            ),
            composition_set="coding-architecture",
            package_product_runtime_factory=owner.factory_for_session(manager),
        )
        try:
            assert session._coding_base_product_compilation is not None
            assembly = session._coding_capability_plugin_assembly
            if old_builtin_state == "installed_enabled" and not scoped_disable:
                assert assembly is not None
                assert assembly.tool_owner_for("coding.arch.default") is not None
            else:
                assert (
                    assembly is None
                    or assembly.tool_owner_for("coding.arch.default") is None
                )
        finally:
            asyncio.run(session.dispose())
    finally:
        owner.close()
    if old_builtin_state == "absent":
        owner = open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        try:
            product = owner.runtime_owner.product_owner
            base_key = PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=lifecycle.scope_id,
                plugin_id="coding.base",
            )
            disabled = product.management.submit(
                PluginManagementCommandV1(
                    action="disable",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id="operator-disabled-base-after-builtin-adoption",
                        idempotency_key="operator-disabled-base-after-builtin-adoption",
                        expected_inventory_revision=(
                            product.desired_state.snapshot().inventory_revision
                        ),
                        installation_key=base_key,
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
        assert cutover_main(("--workspace", str(workspace))) == 0
        assert json.loads(capsys.readouterr().out)["disposition"] == "fenced"
        owner = open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        try:
            assert (
                owner.runtime_owner.product_owner.desired_state.snapshot()
                .installation(base_key)
                .selection.desired_state
                == "installed_disabled"
            )
        finally:
            owner.close()
        acceptance_path = (
            epoch.control_root / "product-state" / "legacy-builtin-acceptance.jsonl"
        )
        foreign_acceptance = tmp_path / "foreign-builtin-acceptance.jsonl"
        foreign_acceptance.write_bytes(acceptance_path.read_bytes())
        acceptance_path.unlink()
        acceptance_path.symlink_to(foreign_acceptance)
        assert cutover_main(("--workspace", str(workspace))) == 1
        assert capsys.readouterr().out == ""


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize("removed_plugin_id", ("foreign.plugin",))
def test_builtin_only_cli_refuses_unsupported_old_removal_before_first_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    removed_plugin_id: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    prepare_coding_package_cutover_roots(lifecycle)
    old_path = tmp_path / "old-foreign.jsonl"
    old_desired = PluginDesiredStateLedger(old_path)
    old_desired.commit(
        PluginDesiredStateMutationV1(
            operation_id="old-foreign-remove",
            idempotency_key="old-foreign-remove",
            expected_inventory_revision=0,
            installation_key=PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=lifecycle.scope_id,
                plugin_id=removed_plugin_id,
            ),
            desired_state="absent",
            package_revision=None,
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    lifecycle.desired_state.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    lifecycle.desired_state.write_bytes(old_path.read_bytes())
    assert (
        cutover_main(("--workspace", str(workspace), "--prepare-legacy-builtin-review"))
        == 1
    )
    assert capsys.readouterr().out == ""
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    assert not (epoch.control_root / "epoch.jsonl").exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_builtin_only_cli_preserves_removed_base_as_product_tombstone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    prepare_coding_package_cutover_roots(lifecycle)
    old_path = tmp_path / "old-base-removed.jsonl"
    old_desired = PluginDesiredStateLedger(old_path)
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=lifecycle.scope_id,
        plugin_id="coding.base",
    )
    old_desired.commit(
        PluginDesiredStateMutationV1(
            operation_id="old-base-remove",
            idempotency_key="old-base-remove",
            expected_inventory_revision=0,
            installation_key=key,
            desired_state="absent",
            package_revision=None,
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    lifecycle.desired_state.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    lifecycle.desired_state.write_bytes(old_path.read_bytes())
    assert (
        cutover_main(("--workspace", str(workspace), "--prepare-legacy-builtin-review"))
        == 0
    )
    review = json.loads(capsys.readouterr().out)
    assert review["removedBuiltinIds"] == ["coding.base"]
    assert cutover_main(("--workspace", str(workspace))) == 1
    assert capsys.readouterr().out == ""
    assert (
        cutover_main(
            (
                "--workspace",
                str(workspace),
                "--adopt-legacy-builtin-review",
                review["reviewId"],
            )
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["disposition"] == "adopted"
    assert cutover_main(("--workspace", str(workspace))) == 0
    assert json.loads(capsys.readouterr().out)["disposition"] == "fenced"
    reopened = subprocess.run(
        (
            sys.executable,
            "-m",
            "loushang.coding.cli.package_cutover",
            "--workspace",
            str(workspace),
        ),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    assert reopened.returncode == 0, reopened.stderr
    assert json.loads(reopened.stdout)["disposition"] == "fenced"
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        state = owner.runtime_owner.product_owner.desired_state.snapshot().installation(
            key
        )
        assert state.selection.desired_state == "absent"
        manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "base-removed-session",
                cwd=str(workspace),
                persist=False,
            )
        )
        session = create_agent_session(
            session_manager=manager,
            model=Model(
                id="base-removed-selection",
                name="Base Removed Selection",
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
                    global_settings_path=default_global_settings_path(),
                    project_settings_path=default_project_settings_path(workspace),
                )
            ),
            composition_set="coding-architecture",
            package_product_runtime_factory=owner.factory_for_session(manager),
        )
        try:
            assert session._coding_base_product_compilation is None
            assert session._coding_capability_plugin_assembly is not None
        finally:
            asyncio.run(session.dispose())
    finally:
        owner.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize(
    ("old_builtin_id", "old_builtin_state"),
    (
        ("coding.arch.default", "installed_disabled"),
        ("coding.arch.default", "absent"),
        ("coding.base", "absent"),
    ),
)
def test_offline_local_skill_cli_preserves_reviewed_old_builtin_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    old_builtin_id: str,
    old_builtin_state: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    _source, plugin_id = _old_installed_local_source(tmp_path, lifecycle)
    old_desired_path = tmp_path / "old-desired.jsonl"
    old_desired = PluginDesiredStateLedger(old_desired_path)
    old_desired.commit(
        PluginDesiredStateMutationV1(
            operation_id="old-builtin-intent",
            idempotency_key="old-builtin-intent",
            expected_inventory_revision=old_desired.snapshot().inventory_revision,
            installation_key=PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=lifecycle.scope_id,
                plugin_id=old_builtin_id,
            ),
            desired_state=old_builtin_state,  # type: ignore[arg-type]
            package_revision=(
                None
                if old_builtin_state == "absent"
                else PluginPackageRevisionRefV1(
                    plugin_id=old_builtin_id,
                    plugin_version="1",
                    package_content_digest="1" * 64,
                    dependency_lock_digest="2" * 64,
                    package_source_identity=f"embedded:{old_builtin_id}",
                )
            ),
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    lifecycle.desired_state.write_bytes(old_desired_path.read_bytes())
    prepare = (
        "--workspace",
        str(workspace),
        "--prepare-legacy-local-skill-review",
        plugin_id,
    )
    assert cutover_main(prepare) == 0
    review = json.loads(capsys.readouterr().out)
    if old_builtin_state == "absent":
        assert review["removedBuiltinIds"] == [old_builtin_id]
        assert "builtinIntent" not in review
        with pytest.raises(ValueError, match="identity changed"):
            CodingLegacyLocalAdoptionReviewV1.from_dict(
                {**review, "removedBuiltinIds": ["coding.lsp.default"]}
            )
    else:
        assert review["builtinIntent"] == [
            {"pluginId": old_builtin_id, "desiredState": "installed_disabled"}
        ]
    assert (
        cutover_main(
            (
                "--workspace",
                str(workspace),
                "--adopt-legacy-local-skill-review",
                plugin_id,
                review["reviewId"],
            )
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["disposition"] == "adopted"
    restarted = subprocess.run(
        (
            sys.executable,
            "-m",
            "loushang.coding.cli.package_cutover",
            "--workspace",
            str(workspace),
        ),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    assert restarted.returncode == 0, restarted.stderr
    assert json.loads(restarted.stdout)["disposition"] == "fenced"
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        selected = {
            item.installation_key.plugin_id: item.selection.desired_state
            for item in owner.runtime_owner.product_owner.desired_state.snapshot().installations
        }
        assert selected[plugin_id] == "installed_enabled"
        assert selected[old_builtin_id] == old_builtin_state
        if old_builtin_id != "coding.base":
            assert selected["coding.base"] == "installed_enabled"
        manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "migrated-arch-session",
                cwd=str(workspace),
                persist=False,
            )
        )
        session = create_agent_session(
            session_manager=manager,
            model=Model(
                id="migrated-arch-selection",
                name="Migrated Arch Selection",
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
                    global_settings_path=default_global_settings_path(),
                    project_settings_path=default_project_settings_path(workspace),
                )
            ),
            composition_set="coding-architecture",
            package_product_runtime_factory=owner.factory_for_session(manager),
        )
        try:
            assert (session._coding_base_product_compilation is None) == (
                old_builtin_id == "coding.base"
            )
            assert session.resource_bundle is not None
            assert any(
                item.name == "review" and item.source_kind == "external_package"
                for item in session.resource_bundle.skills
            )
            assembly = session._coding_capability_plugin_assembly
            if old_builtin_id == "coding.arch.default":
                assert (
                    assembly is None
                    or assembly.tool_owner_for("coding.arch.default") is None
                )
            else:
                assert assembly is not None
        finally:
            asyncio.run(session.dispose())
    finally:
        owner.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize(
    ("base_enabled", "arch_recorded"),
    ((True, False), (False, False), (False, True)),
)
def test_product_session_distinguishes_unseen_and_removed_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    base_enabled: bool,
    arch_recorded: bool,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=default_global_settings_path(),
        project_settings_path=default_project_settings_path(workspace),
    )
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="c" * 64,
        minimum_runtime_version=version("loushang"),
        minimum_runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    assert cutover.attempt.result.disposition == "fenced"
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        _bootstrap_coding_builtin_plugin(owner, "coding.base", enable=base_enabled)
        _bootstrap_coding_builtin_plugin(owner, "coding.lsp.default")
        if arch_recorded:
            product = owner.runtime_owner.product_owner
            removed = product.management.submit(
                PluginManagementCommandV1(
                    action="remove",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id="remove-unseen-arch",
                        idempotency_key="remove-unseen-arch",
                        expected_inventory_revision=(
                            product.desired_state.snapshot().inventory_revision
                        ),
                        installation_key=PluginInstallationKeyV1(
                            product_id="coding",
                            installation_scope="workspace",
                            scope_id=lifecycle.scope_id,
                            plugin_id="coding.arch.default",
                        ),
                        desired_state="absent",
                        package_revision=None,
                        actor_id="operator",
                        policy_revision=product.desired_policy_revision,
                    ),
                )
            )
            assert removed.result is not None
            assert removed.result.disposition == "succeeded"
        manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "unseen-capability-session",
                cwd=str(workspace),
                persist=False,
            )
        )

        def start_session():
            return create_agent_session(
                session_manager=manager,
                model=Model(
                    id="unseen-capability",
                    name="Unseen Capability",
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
                composition_set="coding-architecture",
                package_product_runtime_factory=owner.factory_for_session(manager),
            )

        if arch_recorded:
            session = start_session()
            try:
                assert session._coding_base_product_compilation is None
                assembly = session._coding_capability_plugin_assembly
                assert (
                    assembly is None
                    or assembly.tool_owner_for("coding.arch.default") is None
                )
            finally:
                asyncio.run(session.dispose())
        else:
            with pytest.raises(CodingResourceCatalogAdmissionError) as refused:
                start_session()
            assert refused.value.reasons == (
                "product_requested_capability_not_installed",
            )
    finally:
        owner.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_two_old_skills_share_one_reviewed_builtin_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    local = _old_installed_local_skills(tmp_path, lifecycle)
    old_desired_path = tmp_path / "old-desired.jsonl"
    old_desired = PluginDesiredStateLedger(old_desired_path)
    old_desired.commit(
        PluginDesiredStateMutationV1(
            operation_id="old-arch-remove",
            idempotency_key="old-arch-remove",
            expected_inventory_revision=old_desired.snapshot().inventory_revision,
            installation_key=PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=lifecycle.scope_id,
                plugin_id="coding.arch.default",
            ),
            desired_state="absent",
            package_revision=None,
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    lifecycle.desired_state.write_bytes(old_desired_path.read_bytes())
    reviews: list[dict[str, Any]] = []
    for _source, plugin_id in local:
        assert (
            cutover_main(
                (
                    "--workspace",
                    str(workspace),
                    "--prepare-legacy-local-skill-review",
                    plugin_id,
                )
            )
            == 0
        )
        review = json.loads(capsys.readouterr().out)
        assert review["removedBuiltinIds"] == ["coding.arch.default"]
        reviews.append(review)
    assert reviews[0]["reviewId"] != reviews[1]["reviewId"]
    adoptions = tuple(
        (
            "--workspace",
            str(workspace),
            "--adopt-legacy-local-skill-review",
            plugin_id,
            review["reviewId"],
        )
        for (_source, plugin_id), review in zip(local, reviews, strict=True)
    )
    assert cutover_main(adoptions[0]) == 0
    capsys.readouterr()
    assert cutover_main(("--workspace", str(workspace))) == 1
    capsys.readouterr()
    assert cutover_main(adoptions[1]) == 0
    capsys.readouterr()
    assert cutover_main(("--workspace", str(workspace))) == 0
    assert json.loads(capsys.readouterr().out)["disposition"] == "fenced"
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        product = owner.runtime_owner.product_owner
        arch_events = tuple(
            item
            for item in product.desired_state.transitions()
            if item.mutation.installation_key.plugin_id == "coding.arch.default"
        )
        assert len(arch_events) == 1
        assert arch_events[0].committed_state.selection.desired_state == "absent"
        selected = {
            item.installation_key.plugin_id: item.selection.desired_state
            for item in product.desired_state.snapshot().installations
        }
        assert all(selected[plugin_id] == "installed_enabled" for _, plugin_id in local)
    finally:
        owner.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize("scope", ("project", "global"))
def test_offline_local_skill_consumes_matching_configured_source_and_replays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    scope: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    source, plugin_id = _old_installed_local_source(tmp_path, lifecycle)
    settings_path = (
        default_project_settings_path(workspace)
        if scope == "project"
        else default_global_settings_path()
    )
    settings_path.parent.mkdir(parents=True, mode=0o700)
    old_settings = {"plugin_sources": [str(source)], "quiet_startup": True}
    settings_path.write_text(json.dumps(old_settings) + "\n", encoding="utf-8")
    prepare = (
        "--workspace",
        str(workspace),
        "--prepare-legacy-local-skill-review",
        plugin_id,
    )
    assert cutover_main(prepare) == 0
    review = json.loads(capsys.readouterr().out)
    assert review["configuredPluginSourceScope"] == scope
    assert (
        CodingLegacyLocalAdoptionReviewV1.from_dict(review).review_id
        == review["reviewId"]
    )
    with pytest.raises(ValueError, match="identity changed"):
        CodingLegacyLocalAdoptionReviewV1.from_dict(
            {
                **review,
                "configuredPluginSourceScope": (
                    "global" if scope == "project" else "project"
                ),
            }
        )
    assert json.loads(settings_path.read_text()) == old_settings
    adoption = (
        "--workspace",
        str(workspace),
        "--adopt-legacy-local-skill-review",
        plugin_id,
        review["reviewId"],
    )
    assert cutover_main((*adoption[:-1], "0" * 64)) == 1
    assert json.loads(settings_path.read_text()) == old_settings
    capsys.readouterr()
    settings_path.write_text(
        json.dumps({"plugin_sources": [str(source)], "quiet_startup": False}) + "\n",
        encoding="utf-8",
    )
    assert cutover_main(adoption) == 1
    assert json.loads(settings_path.read_text())["plugin_sources"] == [str(source)]
    settings_path.write_text(json.dumps(old_settings) + "\n", encoding="utf-8")
    capsys.readouterr()

    original_receipt_bytes = source_consumption._receipt_bytes

    def interrupt_before_settled(identity: dict[str, object], phase: str) -> bytes:
        if phase == "settled":
            raise RuntimeError("interrupted after configured Source removal")
        return original_receipt_bytes(identity, phase)

    with patch.object(
        source_consumption, "_receipt_bytes", side_effect=interrupt_before_settled
    ):
        assert cutover_main(adoption) == 1
    assert json.loads(settings_path.read_text()) == {
        "plugin_sources": [],
        "quiet_startup": True,
    }
    assert cutover_main(("--workspace", str(workspace))) == 1
    assert cutover_main(adoption) == 0
    assert json.loads(capsys.readouterr().out)["disposition"] == "adopted"
    assert cutover_main(("--workspace", str(workspace))) == 0
    assert json.loads(capsys.readouterr().out)["disposition"] == "fenced"
    assert json.loads(settings_path.read_text()) == {
        "plugin_sources": [],
        "quiet_startup": True,
    }

    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "configured-source-session",
                cwd=str(workspace),
                persist=False,
            )
        )
        model = Model(
            id="configured-source-model",
            name="Configured Source Model",
            provider="test",
            endpoint="anthropic-messages",
            capabilities=Capabilities(
                reasoning=True,
                input=("text",),
                context_window=128000,
                max_tokens=4096,
            ),
        )
        session = create_agent_session(
            session_manager=manager,
            model=model,
            services=create_services(
                settings_manager=SettingsManager(
                    global_settings_path=default_global_settings_path(),
                    project_settings_path=default_project_settings_path(workspace),
                )
            ),
            composition_set="coding-standard",
            package_product_runtime_factory=owner.factory_for_session(manager),
        )
        try:
            assert session.resource_bundle is not None
            assert any(
                item.name == "review" and item.source_kind == "external_package"
                for item in session.resource_bundle.skills
            )

            async def load_review():
                await session.prepare_model_call_runtime()
                return await session._preflight_user_input_async("/skill:review")

            loaded = asyncio.run(load_review())
            assert len(loaded.loaded_skills) == 1
            assert "# Review" in loaded.loaded_skills[0].content
        finally:
            asyncio.run(session.dispose())
    finally:
        owner.close()
    settings_path.write_text(json.dumps(old_settings) + "\n", encoding="utf-8")
    assert cutover_main(("--workspace", str(workspace))) == 1
    assert json.loads(settings_path.read_text()) == old_settings
    settings_path.write_text(
        json.dumps({"plugin_sources": [], "quiet_startup": True}) + "\n",
        encoding="utf-8",
    )
    assert cutover_main(("--workspace", str(workspace))) == 0
    receipt = next(
        (
            resolve_coding_package_epoch_layout(lifecycle).control_root
            / "product-state"
        ).glob("legacy-local-source-consumption-*.json")
    )
    receipt_bytes = receipt.read_bytes()
    receipt.write_bytes(b"{}\n")
    try:
        assert cutover_main(("--workspace", str(workspace))) == 1
    finally:
        receipt.write_bytes(receipt_bytes)
    assert cutover_main(("--workspace", str(workspace))) == 0


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize("extra", ("different", "second", "package_roots"))
def test_offline_local_skill_refuses_other_configured_sources_before_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    source, plugin_id = _old_installed_local_source(tmp_path, lifecycle)
    settings_path = default_project_settings_path(workspace)
    settings_path.parent.mkdir(mode=0o700)
    settings: dict[str, object] = {"plugin_sources": [str(source)]}
    if extra == "different":
        settings["plugin_sources"] = [str(tmp_path / "other-source")]
    elif extra == "second":
        settings["plugin_sources"] = [str(source), str(tmp_path / "other-source")]
    else:
        settings["package_roots"] = [str(tmp_path / "old-packages")]
    settings_path.write_text(json.dumps(settings) + "\n", encoding="utf-8")
    epoch = resolve_coding_package_epoch_layout(lifecycle)

    assert (
        cutover_main(
            (
                "--workspace",
                str(workspace),
                "--prepare-legacy-local-skill-review",
                plugin_id,
            )
        )
        == 1
    )
    assert capsys.readouterr().out == ""
    assert not (epoch.control_root / "epoch.jsonl").exists()
    assert json.loads(settings_path.read_text()) == settings


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize("configured_layout", ("none", "split", "same_scope", "mixed"))
def test_offline_two_local_skills_require_both_explicit_adoptions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    configured_layout: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    local = _old_installed_local_skills(tmp_path, lifecycle)
    settings_paths = (
        default_global_settings_path(),
        default_project_settings_path(workspace),
    )
    configured_paths: dict[Path, list[str]] = {}
    if configured_layout == "split":
        configured_paths = {
            settings_paths[0]: [str(local[0][0])],
            settings_paths[1]: [str(local[1][0])],
        }
    elif configured_layout == "same_scope":
        configured_paths = {
            settings_paths[1]: [str(source) for source, _plugin_id in local]
        }
    elif configured_layout == "mixed":
        configured_paths = {settings_paths[1]: [str(local[0][0])]}
    for path, sources in configured_paths.items():
        path.parent.mkdir(parents=True, mode=0o700)
        path.write_text(
            json.dumps({"plugin_sources": sources, "quiet_startup": True}) + "\n",
            encoding="utf-8",
        )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    reviews: list[dict[str, Any]] = []
    for _source, plugin_id in local:
        assert (
            cutover_main(
                (
                    "--workspace",
                    str(workspace),
                    "--prepare-legacy-local-skill-review",
                    plugin_id,
                )
            )
            == 0
        )
        review = json.loads(capsys.readouterr().out)
        assert review["pluginId"] == plugin_id
        expected_scope = {
            "none": (None, None),
            "split": ("global", "project"),
            "same_scope": ("project", "project"),
            "mixed": ("project", None),
        }[configured_layout][len(reviews)]
        assert review.get("configuredPluginSourceScope") == expected_scope
        reviews.append(review)
    assert (epoch.control_root / "epoch.jsonl").exists()
    assert reviews[0]["legacyStateDigest"] == reviews[1]["legacyStateDigest"]
    assert reviews[0]["reviewId"] != reviews[1]["reviewId"]

    first_adoption = (
        "--workspace",
        str(workspace),
        "--adopt-legacy-local-skill-review",
        local[0][1],
        reviews[0]["reviewId"],
    )
    second_adoption = (
        "--workspace",
        str(workspace),
        "--adopt-legacy-local-skill-review",
        local[1][1],
        reviews[1]["reviewId"],
    )
    assert cutover_main(first_adoption) == 0
    capsys.readouterr()
    assert cutover_main(("--workspace", str(workspace))) == 1
    if configured_layout == "split":
        assert json.loads(settings_paths[0].read_text())["plugin_sources"] == []
    if configured_layout in ("split", "same_scope", "mixed"):
        remaining = (
            [str(local[1][0])] if configured_layout in ("split", "same_scope") else []
        )
        assert json.loads(settings_paths[1].read_text())["plugin_sources"] == remaining
        settings_paths[1].write_text(
            json.dumps(
                {
                    "plugin_sources": [str(tmp_path / "uninstalled-source")],
                    "quiet_startup": True,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        assert cutover_main(second_adoption) == 1
        assert json.loads(settings_paths[1].read_text())["plugin_sources"] == [
            str(tmp_path / "uninstalled-source")
        ]
        settings_paths[1].write_text(
            json.dumps({"plugin_sources": remaining, "quiet_startup": True}) + "\n",
            encoding="utf-8",
        )
    if configured_layout == "same_scope":
        settings_paths[1].write_text(
            json.dumps({"plugin_sources": [], "quiet_startup": True}) + "\n",
            encoding="utf-8",
        )
        assert cutover_main(second_adoption) == 1
        settings_paths[1].write_text(
            json.dumps(
                {
                    "plugin_sources": [str(local[1][0])],
                    "quiet_startup": True,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        first_receipt = source_consumption._receipt_path(
            epoch.control_root / "product-state", local[0][1]
        )
        first_receipt_bytes = first_receipt.read_bytes()
        first_receipt.write_bytes(b"{}\n")
        assert cutover_main(second_adoption) == 1
        first_receipt.write_bytes(first_receipt_bytes)
    shutil.rmtree(local[0][0])
    between = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        product = between.runtime_owner.product_owner
        lsp_key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=lifecycle.scope_id,
            plugin_id="coding.lsp.default",
        )
        disabled = product.management.submit(
            PluginManagementCommandV1(
                action="disable",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator-disabled-lsp-between-old-skills",
                    idempotency_key="operator-disabled-lsp-between-old-skills",
                    expected_inventory_revision=(
                        product.desired_state.snapshot().inventory_revision
                    ),
                    installation_key=lsp_key,
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
        between.close()
    if configured_layout == "same_scope":
        original_receipt_bytes = source_consumption._receipt_bytes

        def interrupt_second_settlement(
            identity: dict[str, object], phase: str
        ) -> bytes:
            if phase == "settled" and identity["sourcePath"] == str(local[1][0]):
                raise RuntimeError("interrupted after second Source removal")
            return original_receipt_bytes(identity, phase)

        with patch.object(
            source_consumption,
            "_receipt_bytes",
            side_effect=interrupt_second_settlement,
        ):
            assert cutover_main(second_adoption) == 1
        assert json.loads(settings_paths[1].read_text())["plugin_sources"] == []
        assert cutover_main(("--workspace", str(workspace))) == 1
    assert cutover_main(second_adoption) == 0
    capsys.readouterr()
    if configured_paths:
        assert all(
            json.loads(path.read_text())["plugin_sources"] == []
            for path in configured_paths
        )
    assert cutover_main(("--workspace", str(workspace))) == 0
    assert json.loads(capsys.readouterr().out)["disposition"] == "fenced"

    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        selected = {
            item.installation_key.plugin_id: item.selection.desired_state
            for item in owner.runtime_owner.product_owner.desired_state.snapshot().installations
        }
        assert all(selected[plugin_id] == "installed_enabled" for _, plugin_id in local)
        assert selected["coding.lsp.default"] == "installed_disabled"
        manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "two-old-skills-session",
                cwd=str(workspace),
                persist=False,
            )
        )
        model = Model(
            id="two-old-skills-model",
            name="Two Old Skills Model",
            provider="test",
            endpoint="anthropic-messages",
            capabilities=Capabilities(
                reasoning=True,
                input=("text",),
                context_window=128000,
                max_tokens=4096,
            ),
        )
        session = create_agent_session(
            session_manager=manager,
            model=model,
            services=create_services(
                settings_manager=SettingsManager(
                    global_settings_path=default_global_settings_path(),
                    project_settings_path=default_project_settings_path(workspace),
                )
            ),
            composition_set="coding-standard",
            package_product_runtime_factory=owner.factory_for_session(manager),
        )
        try:
            assert session.resource_bundle is not None
            assert {"review-1", "review-2"} <= {
                item.name for item in session.resource_bundle.skills
            }
            for index in (1, 2):

                async def load_review(name: str):
                    await session.prepare_model_call_runtime()
                    return await session._preflight_user_input_async(f"/skill:{name}")

                loaded = asyncio.run(load_review(f"review-{index}"))
                assert len(loaded.loaded_skills) == 1
                assert f"# Review {index}" in loaded.loaded_skills[0].content
        finally:
            asyncio.run(session.dispose())
    finally:
        owner.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize(
    ("adoption_order", "duplicate_names", "configured_prompt"),
    (
        ((0, 1), False, False),
        ((1, 0), False, False),
        ((0, 1), True, False),
        ((0, 1), False, True),
    ),
)
def test_offline_skill_and_prompt_require_separate_typed_adoptions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    adoption_order: tuple[int, int],
    duplicate_names: bool,
    configured_prompt: bool,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    local = _old_installed_local_skills(
        tmp_path,
        lifecycle,
        resource_kinds=("skill", "prompt"),
        duplicate_names=duplicate_names,
    )
    if configured_prompt:
        settings_path = default_project_settings_path(workspace)
        settings_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        settings_path.write_text(
            json.dumps({"plugin_sources": [str(local[1][0])], "quiet_startup": True})
            + "\n",
            encoding="utf-8",
        )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    wrong_type = (
        "--workspace",
        str(workspace),
        "--prepare-legacy-local-skill-review",
        local[1][1],
    )
    assert cutover_main(wrong_type) == 1
    assert not (epoch.control_root / "epoch.jsonl").exists()
    capsys.readouterr()
    reviews: list[dict[str, object]] = []
    for index, (_source, plugin_id) in enumerate(local):
        kind = "skill" if index == 0 else "prompt"
        assert (
            cutover_main(
                (
                    "--workspace",
                    str(workspace),
                    f"--prepare-legacy-local-{kind}-review",
                    plugin_id,
                )
            )
            == 0
        )
        reviews.append(json.loads(capsys.readouterr().out))
    assert reviews[0]["legacyStateDigest"] == reviews[1]["legacyStateDigest"]
    assert cutover_main(("--workspace", str(workspace))) == 1
    capsys.readouterr()
    wrong_adoption = (
        "--workspace",
        str(workspace),
        "--adopt-legacy-local-skill-review",
        local[1][1],
        str(reviews[1]["reviewId"]),
    )
    assert cutover_main(wrong_adoption) == 1
    capsys.readouterr()
    for position, index in enumerate(adoption_order):
        source, plugin_id = local[index]
        kind = "skill" if index == 0 else "prompt"
        assert (
            cutover_main(
                (
                    "--workspace",
                    str(workspace),
                    f"--adopt-legacy-local-{kind}-review",
                    plugin_id,
                    str(reviews[index]["reviewId"]),
                )
            )
            == 0
        )
        capsys.readouterr()
        shutil.rmtree(source)
        assert cutover_main(("--workspace", str(workspace))) == (
            1 if position == 0 else 0
        )
        capsys.readouterr()
    if configured_prompt:
        assert json.loads(settings_path.read_text()) == {
            "plugin_sources": [],
            "quiet_startup": True,
        }
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "mixed-old-data-session",
                cwd=str(workspace),
                persist=False,
            )
        )
        session = create_agent_session(
            session_manager=manager,
            model=Model(
                id="mixed-old-data-model",
                name="Mixed Old Data Model",
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
                    global_settings_path=default_global_settings_path(),
                    project_settings_path=default_project_settings_path(workspace),
                )
            ),
            composition_set="coding-standard",
            package_product_runtime_factory=owner.factory_for_session(manager),
        )
        try:
            assert session.resource_bundle is not None
            assert any(
                item.name == "review-1" and item.source_kind == "external_package"
                for item in session.resource_bundle.skills
            )
            assert any(
                item.name == ("review-1" if duplicate_names else "review-2")
                and item.source_kind == "external_package"
                for item in session.resource_bundle.prompts
            )
        finally:
            asyncio.run(session.dispose())
    finally:
        owner.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_offline_two_old_prompts_require_both_explicit_adoptions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    local = _old_installed_local_skills(
        tmp_path, lifecycle, resource_kinds=("prompt", "prompt")
    )
    reviews: list[dict[str, object]] = []
    for _source, plugin_id in local:
        assert (
            cutover_main(
                (
                    "--workspace",
                    str(workspace),
                    "--prepare-legacy-local-prompt-review",
                    plugin_id,
                )
            )
            == 0
        )
        reviews.append(json.loads(capsys.readouterr().out))
    assert reviews[0]["legacyStateDigest"] == reviews[1]["legacyStateDigest"]
    assert cutover_main(("--workspace", str(workspace))) == 1
    capsys.readouterr()
    for index, (source, plugin_id) in enumerate(local):
        assert (
            cutover_main(
                (
                    "--workspace",
                    str(workspace),
                    "--adopt-legacy-local-prompt-review",
                    plugin_id,
                    str(reviews[index]["reviewId"]),
                )
            )
            == 0
        )
        capsys.readouterr()
        shutil.rmtree(source)
        assert cutover_main(("--workspace", str(workspace))) == (1 if index == 0 else 0)
        capsys.readouterr()

    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "two-old-prompts-session",
                cwd=str(workspace),
                persist=False,
            )
        )
        session = create_agent_session(
            session_manager=manager,
            model=Model(
                id="two-old-prompts-model",
                name="Two Old Prompts Model",
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
                    global_settings_path=default_global_settings_path(),
                    project_settings_path=default_project_settings_path(workspace),
                )
            ),
            composition_set="coding-standard",
            package_product_runtime_factory=owner.factory_for_session(manager),
        )
        try:
            assert session.resource_bundle is not None
            assert {"review-1", "review-2"} <= {
                item.name
                for item in session.resource_bundle.prompts
                if item.source_kind == "external_package"
            }

            async def expand_prompt(name: str) -> str:
                await session.prepare_model_call_runtime()
                expanded = await session._preflight_user_input_async(f"/{name} change")
                return expanded.text

            for index in (1, 2):
                assert f"# Review {index}" in asyncio.run(
                    expand_prompt(f"review-{index}")
                )
        finally:
            asyncio.run(session.dispose())
    finally:
        owner.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_offline_duplicate_old_prompts_refuse_before_first_fence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    local = _old_installed_local_skills(
        tmp_path,
        lifecycle,
        resource_kinds=("prompt", "prompt"),
        duplicate_names=True,
    )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    assert (
        cutover_main(
            (
                "--workspace",
                str(workspace),
                "--prepare-legacy-local-prompt-review",
                local[0][1],
            )
        )
        == 1
    )
    assert not (epoch.control_root / "epoch.jsonl").exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize("legacy_manifest_disabled", [False, True])
def test_offline_old_disabled_prompt_follows_product_desired_state_after_adoption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    legacy_manifest_disabled: bool,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    source, plugin_id = _old_installed_local_source(
        tmp_path,
        lifecycle,
        resource_kind="prompt",
        old_enabled=False,
        legacy_manifest_disabled=legacy_manifest_disabled,
    )
    prefix = ("--workspace", str(workspace))
    assert (
        cutover_main((*prefix, "--prepare-legacy-local-prompt-review", plugin_id)) == 0
    )
    review = json.loads(capsys.readouterr().out)
    assert review["desiredState"] == "installed_disabled"
    assert (
        cutover_main(
            (
                *prefix,
                "--adopt-legacy-local-prompt-review",
                plugin_id,
                review["reviewId"],
            )
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["enableOperationId"] is None
    shutil.rmtree(source)
    assert cutover_main(prefix) == 0
    capsys.readouterr()
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        product = owner.runtime_owner.product_owner
        snapshot = product.desired_state.snapshot()
        selected = next(
            item
            for item in snapshot.installations
            if item.installation_key.plugin_id == plugin_id
        )
        assert selected.selection.desired_state == "installed_disabled"
        first = product.factory_for_session(
            session_id="old-disabled-prompt",
            cwd=workspace,
            runtime_id="old-disabled-prompt",
        ).create(
            PackageProductRuntimeRequestV1(
                product_id="coding",
                session_id="old-disabled-prompt",
                cwd=str(workspace),
            )
        )
        try:
            first.activate()
            assert plugin_id not in first.selected_external_data_plugin_ids()
        finally:
            first.dispose_runtime()
        enabled = product.management.submit(
            PluginManagementCommandV1(
                action="enable",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator:enable-migrated-prompt",
                    idempotency_key="operator:enable-migrated-prompt",
                    expected_inventory_revision=snapshot.inventory_revision,
                    installation_key=selected.installation_key,
                    desired_state="installed_enabled",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision=product.desired_policy_revision,
                ),
            )
        )
        assert enabled.result is not None
        assert enabled.result.disposition == "succeeded"
        if legacy_manifest_disabled:
            selected_runtime = product.factory_for_session(
                session_id="legacy-manifest-check",
                cwd=workspace,
                runtime_id="legacy-manifest-check",
            ).create(
                PackageProductRuntimeRequestV1(
                    product_id="coding",
                    session_id="legacy-manifest-check",
                    cwd=str(workspace),
                )
            )
            try:
                selected_runtime.activate()
                assert plugin_id in selected_runtime.selected_external_data_plugin_ids()
                captured = selected_runtime.capture_selected_plugin_manifest_for(
                    plugin_id, max_files=64, max_total_bytes=1024 * 1024
                )
                assert captured.verified_manifest().enabled is False
            finally:
                selected_runtime.dispose_runtime()
        manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "reenabled-old-prompt-session",
                cwd=str(workspace),
                persist=False,
            )
        )
        session = create_agent_session(
            session_manager=manager,
            model=Model(
                id="reenabled-old-prompt-model",
                name="Reenabled Old Prompt Model",
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
                    global_settings_path=default_global_settings_path(),
                    project_settings_path=default_project_settings_path(workspace),
                )
            ),
            composition_set="coding-standard",
            package_product_runtime_factory=owner.factory_for_session(manager),
        )
        try:
            assert session.resource_bundle is not None
            assert any(
                item.name == "review" and item.source_kind == "external_package"
                for item in session.resource_bundle.prompts
            )

            async def expand_prompt() -> str:
                await session.prepare_model_call_runtime()
                expanded = await session._preflight_user_input_async("/review change")
                return expanded.text

            assert "# Review" in asyncio.run(expand_prompt())
        finally:
            asyncio.run(session.dispose())
    finally:
        owner.close()
    assert cutover_main(prefix) == 0
    capsys.readouterr()
    reopened = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        second = reopened.runtime_owner.product_owner.factory_for_session(
            session_id="reenabled-old-prompt-reopen",
            cwd=workspace,
            runtime_id="reenabled-old-prompt-reopen",
        ).create(
            PackageProductRuntimeRequestV1(
                product_id="coding",
                session_id="reenabled-old-prompt-reopen",
                cwd=str(workspace),
            )
        )
        try:
            second.activate()
            assert plugin_id in second.selected_external_data_plugin_ids()
        finally:
            second.dispose_runtime()
    finally:
        reopened.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize("configured_source", (False, True))
def test_offline_old_theme_requires_typed_adoption_and_reaches_visible_product(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    configured_source: bool,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    source, plugin_id = _old_installed_local_source(
        tmp_path, lifecycle, resource_kind="theme"
    )
    settings_path = default_project_settings_path(workspace)
    if configured_source:
        settings_path.parent.mkdir(mode=0o700)
        settings_path.write_text(
            json.dumps({"plugin_sources": [str(source)]}) + "\n", encoding="utf-8"
        )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    prefix = ("--workspace", str(workspace))
    assert (
        cutover_main((*prefix, "--prepare-legacy-local-prompt-review", plugin_id)) == 1
    )
    assert not (epoch.control_root / "epoch.jsonl").exists()
    capsys.readouterr()
    assert (
        cutover_main((*prefix, "--prepare-legacy-local-theme-review", plugin_id)) == 0
    )
    review = json.loads(capsys.readouterr().out)
    assert review.get("configuredPluginSourceScope") == (
        "project" if configured_source else None
    )
    assert (
        cutover_main(
            (
                *prefix,
                "--adopt-legacy-local-prompt-review",
                plugin_id,
                review["reviewId"],
            )
        )
        == 1
    )
    capsys.readouterr()
    adoption = (
        *prefix,
        "--adopt-legacy-local-theme-review",
        plugin_id,
        review["reviewId"],
    )
    assert cutover_main(adoption) == 0
    accepted = json.loads(capsys.readouterr().out)
    if configured_source:
        assert (
            json.loads(settings_path.read_text(encoding="utf-8"))["plugin_sources"]
            == []
        )
    shutil.rmtree(source)
    assert cutover_main(adoption) == 0
    assert json.loads(capsys.readouterr().out) == accepted
    assert cutover_main(prefix) == 0
    capsys.readouterr()

    settings = SettingsManager(
        global_settings_path=default_global_settings_path(),
        project_settings_path=default_project_settings_path(workspace),
    )
    settings.set_theme("plugin:review", scope="project")
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "old-theme-session",
                cwd=str(workspace),
                persist=False,
            )
        )
        session = create_agent_session(
            session_manager=manager,
            model=Model(
                id="old-theme-model",
                name="Old Theme Model",
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
            package_product_runtime_factory=owner.factory_for_session(manager),
        )
        try:
            assert session.resource_bundle is not None
            assert any(
                item.name == "review" and item.source_kind == "external_package"
                for item in session.resource_bundle.themes
            )
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
        finally:
            asyncio.run(session.dispose())
    finally:
        owner.close()

    disabled_owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        product = disabled_owner.runtime_owner.product_owner
        snapshot = product.desired_state.snapshot()
        selected = next(
            item
            for item in snapshot.installations
            if item.installation_key.plugin_id == plugin_id
        )
        disabled = product.management.submit(
            PluginManagementCommandV1(
                action="disable",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator:disable-old-theme",
                    idempotency_key="operator:disable-old-theme",
                    expected_inventory_revision=snapshot.inventory_revision,
                    installation_key=selected.installation_key,
                    desired_state="installed_disabled",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision="operator:theme",
                ),
            )
        )
        assert disabled.result is not None
        assert disabled.result.disposition == "succeeded"
        manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "disabled-old-theme-session",
                cwd=str(workspace),
                persist=False,
            )
        )
        session = create_agent_session(
            session_manager=manager,
            model=Model(
                id="disabled-old-theme-model",
                name="Disabled Old Theme Model",
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
            package_product_runtime_factory=disabled_owner.factory_for_session(manager),
        )
        try:
            assert session.resource_bundle is not None
            selection = select_coding_plugin_theme(
                settings.get_theme(), session.resource_bundle
            )
            assert selection.disposition == "unavailable"
            assert selection.welcome_theme.resolve("welcome.title")["color"] == "cyan"
        finally:
            asyncio.run(session.dispose())
    finally:
        disabled_owner.close()
    bound_wheel = epoch.control_root / "product-sources" / review["wheelFilename"]
    bound_wheel.write_bytes(b"changed")
    with pytest.raises(CodingLegacyBindingError, match="changed on disk"):
        open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize(
    "refusal", ("invalid_document", "duplicate_names", "foreign_configured_source")
)
def test_offline_old_theme_refuses_invalid_set_before_first_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    refusal: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    if refusal == "invalid_document":
        _source, plugin_id = _old_installed_local_source(
            tmp_path,
            lifecycle,
            resource_kind="theme",
            theme_document=json.dumps(
                {"schemaVersion": 1, "tokens": {"welcome.title": {"color": "bogus"}}}
            ),
        )
    elif refusal == "duplicate_names":
        local = _old_installed_local_skills(
            tmp_path,
            lifecycle,
            resource_kinds=("theme", "theme"),
            duplicate_names=True,
        )
        plugin_id = local[0][1]
    else:
        _source, plugin_id = _old_installed_local_source(
            tmp_path, lifecycle, resource_kind="theme"
        )
        settings_path = default_project_settings_path(workspace)
        settings_path.parent.mkdir(mode=0o700)
        settings_path.write_text(
            json.dumps({"plugin_sources": [str(tmp_path / "foreign-theme-source")]})
            + "\n",
            encoding="utf-8",
        )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    assert (
        cutover_main(
            (
                "--workspace",
                str(workspace),
                "--prepare-legacy-local-theme-review",
                plugin_id,
            )
        )
        == 1
    )
    assert not (epoch.control_root / "epoch.jsonl").exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize("legacy_manifest_disabled", [False, True])
def test_offline_old_disabled_theme_follows_product_desired_state_after_adoption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    legacy_manifest_disabled: bool,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    source, plugin_id = _old_installed_local_source(
        tmp_path,
        lifecycle,
        resource_kind="theme",
        old_enabled=False,
        legacy_manifest_disabled=legacy_manifest_disabled,
    )
    prefix = ("--workspace", str(workspace))
    assert (
        cutover_main((*prefix, "--prepare-legacy-local-theme-review", plugin_id)) == 0
    )
    review = json.loads(capsys.readouterr().out)
    assert review["desiredState"] == "installed_disabled"
    adoption = (
        *prefix,
        "--adopt-legacy-local-theme-review",
        plugin_id,
        review["reviewId"],
    )
    assert cutover_main(adoption) == 0
    assert json.loads(capsys.readouterr().out)["enableOperationId"] is None
    shutil.rmtree(source)
    assert cutover_main(adoption) == 0
    capsys.readouterr()
    assert cutover_main(prefix) == 0
    capsys.readouterr()
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        product = owner.runtime_owner.product_owner
        selected = next(
            item
            for item in product.desired_state.snapshot().installations
            if item.installation_key.plugin_id == plugin_id
        )
        assert selected.selection.desired_state == "installed_disabled"
        runtime = product.factory_for_session(
            session_id="old-disabled-theme",
            cwd=workspace,
            runtime_id="old-disabled-theme",
        ).create(
            PackageProductRuntimeRequestV1(
                product_id="coding",
                session_id="old-disabled-theme",
                cwd=str(workspace),
            )
        )
        try:
            runtime.activate()
            assert plugin_id not in runtime.selected_external_data_plugin_ids()
        finally:
            runtime.dispose_runtime()
        snapshot = product.desired_state.snapshot()
        enabled = product.management.submit(
            PluginManagementCommandV1(
                action="enable",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator:enable-migrated-theme",
                    idempotency_key="operator:enable-migrated-theme",
                    expected_inventory_revision=snapshot.inventory_revision,
                    installation_key=selected.installation_key,
                    desired_state="installed_enabled",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision=product.desired_policy_revision,
                ),
            )
        )
        assert enabled.result is not None
        assert enabled.result.disposition == "succeeded"
        settings = SettingsManager(
            global_settings_path=default_global_settings_path(),
            project_settings_path=default_project_settings_path(workspace),
        )
        settings.set_theme("plugin:review", scope="project")
        manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "reenabled-old-theme-session",
                cwd=str(workspace),
                persist=False,
            )
        )
        session = create_agent_session(
            session_manager=manager,
            model=Model(
                id="reenabled-old-theme-model",
                name="Reenabled Old Theme Model",
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
            package_product_runtime_factory=owner.factory_for_session(manager),
        )
        try:
            assert session.resource_bundle is not None
            choice = select_coding_plugin_theme(
                settings.get_theme(), session.resource_bundle
            )
            assert choice.disposition == "selected"
            assert "\x1b[1;31m Loushang " in "\n".join(
                line.text
                for line in LoushangWelcomePanel(theme=choice.welcome_theme)
                .render(RenderConstraints(width=42, max_height=15))
                .lines
            )
        finally:
            asyncio.run(session.dispose())
    finally:
        owner.close()
    assert cutover_main(prefix) == 0
    capsys.readouterr()
    reopened = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        runtime = reopened.runtime_owner.product_owner.factory_for_session(
            session_id="reenabled-old-theme-reopen",
            cwd=workspace,
            runtime_id="reenabled-old-theme-reopen",
        ).create(
            PackageProductRuntimeRequestV1(
                product_id="coding",
                session_id="reenabled-old-theme-reopen",
                cwd=str(workspace),
            )
        )
        try:
            runtime.activate()
            assert plugin_id in runtime.selected_external_data_plugin_ids()
            if legacy_manifest_disabled:
                captured = runtime.capture_selected_plugin_manifest_for(
                    plugin_id, max_files=64, max_total_bytes=1024 * 1024
                )
                assert captured.verified_manifest().enabled is False
        finally:
            runtime.dispose_runtime()
    finally:
        reopened.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_offline_skill_and_theme_settle_separately_in_one_product_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    local = _old_installed_local_skills(
        tmp_path, lifecycle, resource_kinds=("skill", "theme")
    )
    prefix = ("--workspace", str(workspace))
    reviews: list[dict[str, object]] = []
    for index, (_source, plugin_id) in enumerate(local):
        kind = "skill" if index == 0 else "theme"
        assert (
            cutover_main((*prefix, f"--prepare-legacy-local-{kind}-review", plugin_id))
            == 0
        )
        reviews.append(json.loads(capsys.readouterr().out))
    for index, (source, plugin_id) in enumerate(local):
        kind = "skill" if index == 0 else "theme"
        assert (
            cutover_main(
                (
                    *prefix,
                    f"--adopt-legacy-local-{kind}-review",
                    plugin_id,
                    str(reviews[index]["reviewId"]),
                )
            )
            == 0
        )
        capsys.readouterr()
        shutil.rmtree(source)
        assert cutover_main(prefix) == (1 if index == 0 else 0)
        capsys.readouterr()

    settings = SettingsManager(
        global_settings_path=default_global_settings_path(),
        project_settings_path=default_project_settings_path(workspace),
    )
    settings.set_theme("plugin:review-2", scope="project")
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "mixed-skill-theme-session",
                cwd=str(workspace),
                persist=False,
            )
        )
        session = create_agent_session(
            session_manager=manager,
            model=Model(
                id="mixed-skill-theme-model",
                name="Mixed Skill Theme Model",
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
            package_product_runtime_factory=owner.factory_for_session(manager),
        )
        try:
            assert session.resource_bundle is not None
            assert "review-1" in {item.name for item in session.resource_bundle.skills}
            assert "review-2" in {item.name for item in session.resource_bundle.themes}
            selection = select_coding_plugin_theme(
                settings.get_theme(), session.resource_bundle
            )
            assert selection.disposition == "selected"
            assert selection.welcome_theme.resolve("welcome.title")["color"] == "red"
        finally:
            asyncio.run(session.dispose())
    finally:
        owner.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize(
    "refusal", ("changed_source", "configured_source", "duplicate_names")
)
def test_offline_two_local_skills_validate_every_source_before_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    refusal: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    local = _old_installed_local_skills(
        tmp_path, lifecycle, duplicate_names=refusal == "duplicate_names"
    )
    if refusal == "changed_source":
        (local[1][0] / "skills/review-2/SKILL.md").write_text("changed\n")
    elif refusal == "configured_source":
        settings_path = default_project_settings_path(workspace)
        settings_path.parent.mkdir(mode=0o700)
        settings_path.write_text(
            json.dumps(
                {
                    "plugin_sources": [
                        str(local[0][0]),
                        str(tmp_path / "uninstalled-source"),
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    lock_before = (lifecycle.package_root / "package-lock.json").read_bytes()
    desired_before = lifecycle.desired_state.read_bytes()

    assert (
        cutover_main(
            (
                "--workspace",
                str(workspace),
                "--prepare-legacy-local-skill-review",
                local[0][1],
            )
        )
        == 1
    )
    assert capsys.readouterr().out == ""
    assert not (epoch.control_root / "epoch.jsonl").exists()
    assert (lifecycle.package_root / "package-lock.json").read_bytes() == lock_before
    assert lifecycle.desired_state.read_bytes() == desired_before


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_offline_local_skill_prepare_refuses_prompt_before_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    _source, plugin_id = _old_installed_local_source(
        tmp_path, lifecycle, resource_kind="prompt"
    )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    assert (
        cutover_main(
            (
                "--workspace",
                str(workspace),
                "--prepare-legacy-local-skill-review",
                plugin_id,
            )
        )
        == 1
    )
    assert "cutover refused" in capsys.readouterr().err
    assert not (epoch.control_root / "epoch.jsonl").exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_local_skill_adoption_refuses_prompt_on_preexisting_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    _source, plugin_id = _old_installed_local_source(
        tmp_path, lifecycle, resource_kind="prompt"
    )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    namespace_id = sha256(
        b"loushang.coding-fresh-product-epoch/v1\0" + epoch.store_id.encode()
    ).hexdigest()
    prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        SettingsManager(
            global_settings_path=default_global_settings_path(),
            project_settings_path=default_project_settings_path(workspace),
        ),
        namespace_id=namespace_id,
        minimum_runtime_version=version("loushang"),
        minimum_runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    assert (
        cutover_main(
            (
                "--workspace",
                str(workspace),
                "--prepare-legacy-local-skill-review",
                plugin_id,
            )
        )
        == 1
    )
    assert capsys.readouterr().out == ""
    assert (
        cutover_main(
            ("--workspace", str(workspace), "--review-legacy-local-plugin", plugin_id)
        )
        == 0
    )
    review = json.loads(capsys.readouterr().out)
    assert (
        cutover_main(
            (
                "--workspace",
                str(workspace),
                "--adopt-legacy-local-skill-review",
                plugin_id,
                review["reviewId"],
            )
        )
        == 1
    )
    assert capsys.readouterr().out == ""
    assert not tuple(
        (epoch.control_root / "product-state").glob("legacy-local-acceptance-*.jsonl")
    )


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_local_review_requires_existing_product_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    assert (
        cutover_main(
            (
                "--workspace",
                str(workspace),
                "--review-legacy-local-plugin",
                "review-pack",
            )
        )
        == 1
    )
    assert "cutover refused" in capsys.readouterr().err
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    assert not (epoch.control_root / "epoch.jsonl").exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_offline_command_fences_persistent_workspace_and_replays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    environ = {**os.environ, "LOUSHANG_HOME": str(tmp_path / "private-home")}
    command = (
        sys.executable,
        "-m",
        "loushang.coding.cli.package_cutover",
        "--workspace",
        str(workspace),
    )

    first = subprocess.run(
        command,
        env=environ,
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    assert first.returncode == 0, first.stderr
    result = json.loads(first.stdout)
    assert result["disposition"] == "fenced"
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(
        workspace, platform_paths=resolve_platform_paths(environ=environ)
    )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    assert result["storeId"] == epoch.store_id
    assert len(result["namespaceId"]) == 64
    fence_bytes = (epoch.control_root / "epoch.jsonl").read_bytes()

    second = subprocess.run(
        command,
        env=environ,
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout) == result
    assert (epoch.control_root / "epoch.jsonl").read_bytes() == fence_bytes

    monkeypatch.setenv("LOUSHANG_HOME", environ["LOUSHANG_HOME"])
    with patch("loushang.coding.cli.package_cutover.version", return_value="9.0.0"):
        assert cutover_main(("--workspace", str(workspace))) == 0
    assert json.loads(capsys.readouterr().out) == result
    assert (epoch.control_root / "epoch.jsonl").read_bytes() == fence_bytes

    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        selected = owner.runtime_owner.product_owner.desired_state.snapshot()
        assert {
            item.installation_key.plugin_id
            for item in selected.installations
            if item.selection.desired_state == "installed_enabled"
        } == {"coding.base", "coding.lsp.default", "coding.arch.default"}
    finally:
        owner.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_offline_command_refuses_legacy_disabled_setting_before_fence(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    project_config = workspace / ".loushang"
    project_config.mkdir(mode=0o700)
    (project_config / "settings.json").write_text(
        json.dumps({"disabled_plugins": ["coding.base"]}), encoding="utf-8"
    )
    environ = {**os.environ, "LOUSHANG_HOME": str(tmp_path / "private-home")}

    result = subprocess.run(
        (
            sys.executable,
            "-m",
            "loushang.coding.cli.package_cutover",
            "--workspace",
            str(workspace),
        ),
        env=environ,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 1
    assert "pre-B workspace is unsupported" in result.stderr
    assert not (tmp_path / "private-home").exists()
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(
        workspace, platform_paths=resolve_platform_paths(environ=environ)
    )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    assert not (epoch.control_root / "epoch.jsonl").exists()
    (project_config / "settings.json").write_text(
        json.dumps(
            {
                "disabled_plugins": ["coding.base"],
                "plugin_sources": ["/old/plugins"],
            }
        ),
        encoding="utf-8",
    )
    configured = subprocess.run(
        (
            sys.executable,
            "-m",
            "loushang.coding.cli.package_cutover",
            "--workspace",
            str(workspace),
            "--prepare-legacy-disabled-review",
        ),
        env=environ,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert configured.returncode == 1
    assert "configured Sources" in configured.stderr
    assert not (epoch.control_root / "epoch.jsonl").exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize(
    ("legacy_root", "legacy_member"),
    (("lifecycle", "desired-state.jsonl"), ("package", "package-lock.json")),
)
def test_offline_command_refuses_pre_b_state_without_writing(
    tmp_path: Path, legacy_root: str, legacy_member: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    environ = {**os.environ, "LOUSHANG_HOME": str(tmp_path / "private-home")}
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(
        workspace, platform_paths=resolve_platform_paths(environ=environ)
    )
    root = lifecycle.root if legacy_root == "lifecycle" else lifecycle.package_root
    root.mkdir(mode=0o700, parents=True)
    (root / legacy_member).write_bytes(b"")
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}

    result = subprocess.run(
        (
            sys.executable,
            "-m",
            "loushang.coding.cli.package_cutover",
            "--workspace",
            str(workspace),
        ),
        env=environ,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 1
    assert "pre-B workspace is unsupported" in result.stderr
    assert {path.relative_to(tmp_path) for path in tmp_path.rglob("*")} == before


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_disabled_only_review_command_reads_frozen_first_b_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    project_config = workspace / ".loushang"
    project_config.mkdir(mode=0o700)
    project_settings = project_config / "settings.json"
    project_settings.write_text(
        json.dumps({"disabled_plugins": ["coding.base"]}), encoding="utf-8"
    )
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    command = ("--workspace", str(workspace), "--review-legacy-disabled-only")
    assert cutover_main(command) == 1
    assert capsys.readouterr().out == ""
    assert (
        cutover_main(
            ("--workspace", str(workspace), "--prepare-legacy-disabled-review")
        )
        == 0
    )
    prepared = json.loads(capsys.readouterr().out)
    assert prepared["reviewId"]
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    assert (epoch.control_root / "epoch.jsonl").exists()
    project_settings.write_text('{"disabled_plugins": []}', encoding="utf-8")
    before = tuple(
        sorted(
            (str(path.relative_to(tmp_path)), path.read_bytes())
            for path in tmp_path.rglob("*")
            if path.is_file()
        )
    )
    assert cutover_main(command) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["disabledPlugins"] == [{"scope": "project", "pluginId": "coding.base"}]
    assert first["reviewId"]
    assert str(tmp_path) not in json.dumps(first)
    assert cutover_main(command) == 0
    assert json.loads(capsys.readouterr().out) == first
    after = tuple(
        sorted(
            (str(path.relative_to(tmp_path)), path.read_bytes())
            for path in tmp_path.rglob("*")
            if path.is_file()
        )
    )
    assert after == before
    bad_adoption = (
        "--workspace",
        str(workspace),
        "--adopt-legacy-disabled-review",
        "0" * 64,
    )
    assert cutover_main(bad_adoption) == 1
    assert capsys.readouterr().out == ""
    adoption = (
        "--workspace",
        str(workspace),
        "--adopt-legacy-disabled-review",
        first["reviewId"],
    )
    with patch(
        "loushang.coding.package_product_runtime.open_coding_fenced_product_application_owner",
        side_effect=RuntimeError("interrupted after acceptance"),
    ):
        assert cutover_main(adoption) == 1
    assert capsys.readouterr().out == ""
    state_root = epoch.control_root / "product-state"
    assert (state_root / "legacy-disabled-acceptance.jsonl").exists()
    assert cutover_main(adoption) == 0
    accepted = json.loads(capsys.readouterr().out)
    assert accepted["disposition"] == "adopted"
    assert accepted["reviewId"] == first["reviewId"]
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        selected = owner.runtime_owner.product_owner.desired_state.snapshot()
        assert {
            item.installation_key.plugin_id: item.selection.desired_state
            for item in selected.installations
        } == {
            "coding.base": "installed_disabled",
            "coding.lsp.default": "installed_enabled",
            "coding.arch.default": "installed_enabled",
        }
    finally:
        owner.close()
    assert cutover_main(adoption) == 0
    assert json.loads(capsys.readouterr().out) == accepted
    project_settings.write_text(
        '{"disabled_plugins":["coding.arch.default"]}', encoding="utf-8"
    )
    assert cutover_main(("--workspace", str(workspace))) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["disposition"] == "fenced"
    reopened = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        product = reopened.runtime_owner.product_owner
        assert {
            item.installation_key.plugin_id: item.selection.desired_state
            for item in product.desired_state.snapshot().installations
        } == {
            "coding.base": "installed_disabled",
            "coding.lsp.default": "installed_enabled",
            "coding.arch.default": "installed_enabled",
        }
        factory = product.factory_for_session(
            session_id="migrated-disabled-reopen",
            cwd=workspace,
            runtime_id="migrated-disabled-reopen",
        )
        binding = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding",
                session_id="migrated-disabled-reopen",
                cwd=str(workspace),
            )
        )
        try:
            runtime = binding.activate()
            with pytest.raises(PackageProductRuntimeReadError, match="not selected"):
                runtime.capture_selected_plugin_manifest_for(
                    "coding.base", max_files=64, max_total_bytes=1024 * 1024
                )
            for plugin_id in ("coding.lsp.default", "coding.arch.default"):
                selected_manifest = runtime.capture_selected_plugin_manifest_for(
                    plugin_id, max_files=64, max_total_bytes=1024 * 1024
                )
                assert selected_manifest.verified_manifest().name == plugin_id
        finally:
            binding.dispose_runtime()
    finally:
        reopened.close()
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=False
        )
    )
    session = create_agent_session(
        session_manager=manager,
        model=Model(
            id="migrated-disabled-base",
            name="Migrated Disabled Base",
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
                global_settings_path=default_global_settings_path(),
                project_settings_path=default_project_settings_path(workspace),
            )
        ),
        composition_set="coding-standard",
    )
    try:
        assert session.package_product_lifecycle_mode == "enforced"
        assert session._coding_base_product_compilation is None
        assert session._coding_lsp_plugin_assembly is not None
    finally:
        asyncio.run(session.dispose())
    arch_manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "arch-sessions", cwd=str(workspace), persist=False
        )
    )
    arch_session = create_agent_session(
        session_manager=arch_manager,
        model=Model(
            id="migrated-disabled-base-arch",
            name="Migrated Disabled Base Arch",
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
                global_settings_path=default_global_settings_path(),
                project_settings_path=default_project_settings_path(workspace),
            )
        ),
        composition_set="coding-architecture",
    )
    try:
        assert arch_session._coding_base_product_compilation is None
        assert arch_session._coding_capability_plugin_assembly is not None
        assert (
            arch_session._coding_capability_plugin_assembly.tool_owner_for(
                "coding.arch.default"
            )
            is not None
        )
    finally:
        asyncio.run(arch_session.dispose())


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_cutover_backup_status_reads_exact_snapshot_owner_without_expiry_claim(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    environ = {**os.environ, "LOUSHANG_HOME": str(tmp_path / "private-home")}
    command = (
        sys.executable,
        "-m",
        "loushang.coding.cli.package_cutover",
        "--workspace",
        str(workspace),
    )
    initial = subprocess.run(
        command, env=environ, capture_output=True, text=True, check=False, timeout=90
    )
    assert initial.returncode == 0, initial.stderr
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(
        workspace, platform_paths=resolve_platform_paths(environ=environ)
    )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    fence_before = (epoch.control_root / "epoch.jsonl").read_bytes()
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        desired_path = owner.runtime_owner.product_owner.desired_state.path
        desired_before = desired_path.read_bytes()
    finally:
        owner.close()

    status = subprocess.run(
        (*command, "--backup-status"),
        env=environ,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert status.returncode == 0, status.stderr
    verified = json.loads(status.stdout)
    assert verified["backupKind"] == "pre_b_workspace_snapshot"
    assert verified["status"] == "retained"
    assert verified["expiryStatus"] == "unknown"
    assert verified["snapshotReceiptId"]
    assert str(workspace) not in status.stdout
    assert str(epoch.snapshot_root) not in status.stdout
    assert (epoch.control_root / "epoch.jsonl").read_bytes() == fence_before
    assert desired_path.read_bytes() == desired_before

    evidence_file = epoch.snapshot_root / (
        verified["snapshotReceiptId"] + ".evidence.json"
    )
    evidence_file.rename(evidence_file.with_suffix(".unavailable"))
    missing = subprocess.run(
        (*command, "--backup-status"),
        env=environ,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert missing.returncode == 0, missing.stderr
    unknown = json.loads(missing.stdout)
    assert unknown["status"] == "unknown"
    assert unknown["reason"] == "snapshot_evidence_missing"
    assert unknown["entryCount"] is None
    assert (epoch.control_root / "epoch.jsonl").read_bytes() == fence_before
    assert desired_path.read_bytes() == desired_before

    evidence_file.with_suffix(".unavailable").rename(evidence_file)
    evidence_before = evidence_file.read_bytes()
    evidence_file.write_bytes(b"{}\n")
    corrupted = subprocess.run(
        (*command, "--backup-status"),
        env=environ,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert corrupted.returncode == 1
    assert corrupted.stdout == ""
    assert (epoch.control_root / "epoch.jsonl").read_bytes() == fence_before
    assert desired_path.read_bytes() == desired_before

    evidence_file.write_bytes(evidence_before)
    epoch_journal = epoch.control_root / "epoch.jsonl"
    partial = fence_before + b'{"unfinished":'
    epoch_journal.write_bytes(partial)
    lock_path = epoch.control_root / "epoch.jsonl.lock"
    lock_path.unlink(missing_ok=True)
    control_before = tuple(sorted(path.name for path in epoch.control_root.iterdir()))
    refused = subprocess.run(
        (*command, "--backup-status"),
        env=environ,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert refused.returncode == 1
    assert refused.stdout == ""
    assert epoch_journal.read_bytes() == partial
    assert (
        tuple(sorted(path.name for path in epoch.control_root.iterdir()))
        == control_before
    )
