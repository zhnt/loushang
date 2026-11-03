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
    CodingLegacyBindingError,
    CodingLegacyLocalBindingCatalog,
    CodingLegacyLocalBindingV1,
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
from loushang.harness.journal import journal_file_lock
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.plugins.dependencies import (
    PluginDependencyClosureLock,
)
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.resources.plugins.revisions import PluginRevisionStore


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product cutover")
@pytest.mark.parametrize("stage_before_publish", [False, True])
def test_product_refuses_unaccepted_legacy_source_binding(
    tmp_path: Path, stage_before_publish: bool
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
    interrupted_stage = source_root / f".{candidate.filename}.staging"
    if stage_before_publish:
        interrupted_stage.write_bytes(b"interrupted publication")
        interrupted_stage.chmod(0o600)
    catalog = CodingLegacyLocalBindingCatalog(
        state_root / "legacy-local-bindings.jsonl",
        source_root=source_root,
        store_id=store_id,
        namespace_id="a" * 64,
        scope_id=lifecycle.scope_id,
        policy_revision="coding-product-package-policy:1",
    )
    publisher = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        assert (
            catalog.publish_candidate(candidate, epoch_runtime=publisher.epoch_runtime)
            == artifact
        )
        assert not interrupted_stage.exists()
        if not stage_before_publish:
            interrupted_stage.write_bytes(b"linked but not cleaned")
            interrupted_stage.chmod(0o600)
        assert (
            catalog.publish_candidate(candidate, epoch_runtime=publisher.epoch_runtime)
            == artifact
        )
        assert not interrupted_stage.exists()
    finally:
        publisher.close()
    legacy_binding_digest = sha256(b"old binding evidence").hexdigest()
    with pytest.raises(CodingLegacyBindingError, match="no acceptance owner"):
        catalog.append(
            candidate,
            legacy_source_identity=candidate.original_source_identity,
            legacy_binding_digest=legacy_binding_digest,
            dependency_lock_digest=dependency_lock.digest,
            approval_id="operator:review-pack",
        )
    assert not catalog.path.exists()

    # A prior or corrupted writer can leave a structurally valid record. Product
    # reopen must still rejoin it to an accepted review before selecting it.
    unaccepted = CodingLegacyLocalBindingV1.create(
        record_revision=1,
        store_id=store_id,
        namespace_id="a" * 64,
        scope_id=lifecycle.scope_id,
        legacy_source_identity=candidate.original_source_identity,
        legacy_binding_digest=legacy_binding_digest,
        dependency_lock_digest=dependency_lock.digest,
        policy_revision="coding-product-package-policy:1",
        approval_id="operator:review-pack",
        candidate=candidate,
    )
    with journal_file_lock(catalog.path, "exclusive"):
        catalog.path.write_bytes(canonical_json_bytes(unaccepted.to_dict()) + b"\n")
        catalog.path.chmod(0o600)
    with pytest.raises(CodingLegacyBindingError, match="no accepted review"):
        open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )
