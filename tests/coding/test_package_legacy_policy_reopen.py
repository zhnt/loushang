from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.coding._plugin_lifecycle import (
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_legacy_binding_catalog import (
    CodingLegacyLocalBindingCatalog,
)
from loushang.coding.package_legacy_local_wheel import (
    reacquire_coding_legacy_local_plugin_wheel,
)
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.package_product_runtime import (
    open_coding_fenced_product_application_owner,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleIntentV1,
)
from loushang.harness.resources.plugins.dependencies import (
    PluginDependencyClosureLock,
)
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.resources.plugins.revisions import PluginRevisionStore


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product cutover")
@pytest.mark.parametrize("legacy_enabled", [False, True])
def test_expanded_product_policy_reopens_existing_builtin_selections(
    tmp_path: Path, legacy_enabled: bool
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
    original_owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        epoch = original_owner.epoch_runtime
        source_root = epoch.prepare_product_source_root()
        state_root = epoch.prepare_product_state_root()
        store_id = epoch.registry.store_id
        base_revision = (
            original_owner.runtime_owner.product_owner.policy.authority_revision
        )
    finally:
        original_owner.close()
    original_source = tmp_path / "original-source"
    original_source.mkdir(mode=0o700)
    (original_source / "plugin.json").write_text(
        json.dumps({"name": "review-pack", "version": "1"})
    )
    published = PluginRevisionStore(tmp_path / "old-revisions").publish(
        PluginManifestParser().parse(original_source)
    )
    published.revision_handle.close()
    assert published.manifest_digest is not None
    dependency_lock = PluginDependencyClosureLock(published.content_digest, ())
    candidate = reacquire_coding_legacy_local_plugin_wheel(
        original_source,
        legacy_package_root=lifecycle.package_root,
        staging_parent=source_root,
        plugin_id="review-pack",
        expected_source_identity=f"local:{original_source}",
        expected_content_digest=published.content_digest,
        expected_manifest_digest=published.manifest_digest,
        expected_dependency_lock=dependency_lock,
    )
    artifact = source_root / candidate.filename
    artifact.write_bytes(candidate.wheel_bytes)
    artifact.chmod(0o600)
    catalog = CodingLegacyLocalBindingCatalog(
        state_root / "legacy-local-bindings.jsonl",
        source_root=source_root,
        store_id=store_id,
        namespace_id="a" * 64,
        scope_id=lifecycle.scope_id,
        policy_revision="coding-product-package-policy:1",
    )
    catalog.append(
        candidate,
        legacy_source_identity=candidate.original_source_identity,
        legacy_binding_digest=sha256(b"old binding evidence").hexdigest(),
        dependency_lock_digest=dependency_lock.digest,
        approval_id="operator:review-pack",
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        policy = owner.runtime_owner.product_owner.policy
        assert policy.authority_revision != base_revision
        assert {item.plugin_id for item in policy.bindings} == {
            "coding.base",
            "coding.lsp.default",
            "coding.arch.default",
            "review-pack",
        }
        factory = owner.runtime_owner.product_owner.factory_for_session(
            session_id="policy-reopen",
            cwd=workspace,
            runtime_id="policy-reopen",
        )
        binding = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id="policy-reopen", cwd=str(workspace)
            )
        )
        try:
            runtime = binding.activate()
            for plugin_id in (
                "coding.base",
                "coding.lsp.default",
                "coding.arch.default",
            ):
                selected = runtime.capture_selected_plugin_manifest_for(
                    plugin_id, max_files=64, max_total_bytes=1024 * 1024
                )
                assert selected.verified_manifest().name == plugin_id
            installed = binding.lifecycle.route(
                PackageProductLifecycleIntentV1(
                    operation_id="legacy-local-policy-install",
                    action="install",
                    source=str(artifact),
                    scope="project",
                ),
                entrypoint="startup",
            )
            assert installed.handled
            assert installed.record is not None
            assert installed.record.lifecycle == "installed"
        finally:
            binding.dispose_runtime()
        product = owner.runtime_owner.product_owner
        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=product.policy.project_scope_id,
            plugin_id="review-pack",
        )
        snapshot = product.desired_state.snapshot()
        assert (
            snapshot.installation(key).selection.desired_state == "installed_disabled"
        )
        assert (
            product.settled_install_command_id(
                operation_id="legacy-local-policy-install", plugin_id="review-pack"
            )
            is not None
        )
        if legacy_enabled:
            enabled = product.management.submit(
                PluginManagementCommandV1(
                    action="enable",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id="legacy-local-policy-enable",
                        idempotency_key="legacy-local-policy-enable",
                        expected_inventory_revision=snapshot.inventory_revision,
                        installation_key=key,
                        desired_state="installed_enabled",
                        package_revision=None,
                        actor_id=product.actor_id,
                        policy_revision=product.desired_policy_revision,
                    ),
                )
            )
            assert enabled.result is not None
            assert enabled.result.disposition == "succeeded"
    finally:
        owner.close()

    reopened = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        factory = reopened.runtime_owner.product_owner.factory_for_session(
            session_id="legacy-policy-selected-reopen",
            cwd=workspace,
            runtime_id="legacy-policy-selected-reopen",
        )
        binding = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding",
                session_id="legacy-policy-selected-reopen",
                cwd=str(workspace),
            )
        )
        try:
            runtime = binding.activate()
            if legacy_enabled:
                selected = runtime.capture_selected_plugin_manifest_for(
                    "review-pack", max_files=64, max_total_bytes=1024 * 1024
                )
                assert selected.verified_manifest().name == "review-pack"
            else:
                with pytest.raises(
                    PackageProductRuntimeReadError, match="not selected"
                ):
                    runtime.capture_selected_plugin_manifest_for(
                        "review-pack", max_files=64, max_total_bytes=1024 * 1024
                    )
        finally:
            binding.dispose_runtime()
    finally:
        reopened.close()
