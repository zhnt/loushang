from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.coding.package_legacy_desired_evidence import (
    CodingLegacyDesiredEvidenceV1,
)
from loushang.coding.package_legacy_installation_inventory import (
    CodingLegacyInventoryError,
    classify_coding_legacy_installations,
)
from loushang.coding.package_legacy_lock_evidence import (
    parse_coding_legacy_local_binding_heads,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.plugins.manifest import PluginManifestParser

_SCOPE = "workspace:" + "a" * 64


def _real_binding(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "plugin.json").write_text(
        json.dumps({"name": "review-pack", "version": "1"})
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
    [binding] = parse_coding_legacy_local_binding_heads(
        (old_package / "package-lock.json").read_bytes()
    )
    return binding


def _desired(
    tmp_path: Path,
    package: PluginPackageRevisionRefV1,
    *,
    final_state: str,
) -> CodingLegacyDesiredEvidenceV1:
    path = tmp_path / "old-desired.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=_SCOPE,
        plugin_id=package.plugin_id,
    )
    ledger = PluginDesiredStateLedger(path)
    ledger.commit(
        PluginDesiredStateMutationV1(
            operation_id="old-install",
            idempotency_key="old-install",
            expected_inventory_revision=0,
            installation_key=key,
            desired_state="installed_disabled",
            package_revision=package,
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    if final_state != "installed_disabled":
        ledger.commit(
            PluginDesiredStateMutationV1(
                operation_id="old-final-state",
                idempotency_key="old-final-state",
                expected_inventory_revision=1,
                installation_key=key,
                desired_state=final_state,  # type: ignore[arg-type]
                package_revision=None,
                actor_id="old-operator",
                policy_revision="old-policy:1",
            )
        )
    return CodingLegacyDesiredEvidenceV1(
        snapshot=ledger.snapshot(), journal_digest=sha256(path.read_bytes()).hexdigest()
    )


@pytest.mark.parametrize("state", ["installed_disabled", "installed_enabled"])
def test_inventory_requires_exact_old_installed_head(
    tmp_path: Path, state: str
) -> None:
    binding = _real_binding(tmp_path)
    package = PluginPackageRevisionRefV1(
        plugin_id=binding.plugin_id,
        plugin_version="1",
        package_content_digest=binding.content_digest,
        dependency_lock_digest=binding.dependency_lock.digest,
        package_source_identity=binding.source_identity,
    )
    desired = _desired(tmp_path, package, final_state=state)
    inventory = classify_coding_legacy_installations(
        (binding,), desired, scope_id=_SCOPE
    )
    assert len(inventory.active_local) == 1
    assert inventory.active_local[0].desired_state == state
    assert inventory.active_local[0].binding == binding
    assert inventory.removed_plugin_ids == ()
    assert inventory.unselected_source_identities == ()

    changed = _desired(
        tmp_path / "changed",
        replace(package, package_content_digest="f" * 64),
        final_state="installed_disabled",
    )
    with pytest.raises(CodingLegacyInventoryError, match="differs"):
        classify_coding_legacy_installations((binding,), changed, scope_id=_SCOPE)


def test_inventory_keeps_removed_and_unselected_sources_out_of_adoption(
    tmp_path: Path,
) -> None:
    binding = _real_binding(tmp_path)
    package = PluginPackageRevisionRefV1(
        plugin_id=binding.plugin_id,
        plugin_version="1",
        package_content_digest=binding.content_digest,
        dependency_lock_digest=binding.dependency_lock.digest,
        package_source_identity=binding.source_identity,
    )
    missing = classify_coding_legacy_installations((binding,), None, scope_id=_SCOPE)
    assert missing.active_local == ()
    assert missing.unselected_source_identities == (binding.source_identity,)

    removed = classify_coding_legacy_installations(
        (binding,), _desired(tmp_path, package, final_state="absent"), scope_id=_SCOPE
    )
    assert removed.active_local == ()
    assert removed.removed_plugin_ids == (binding.plugin_id,)
    assert removed.unselected_source_identities == (binding.source_identity,)


def test_inventory_tracks_builtin_intent_without_local_binding(tmp_path: Path) -> None:
    package = PluginPackageRevisionRefV1(
        plugin_id="coding.base",
        plugin_version="1",
        package_content_digest="1" * 64,
        dependency_lock_digest="2" * 64,
        package_source_identity="embedded:coding.base",
    )
    inventory = classify_coding_legacy_installations(
        (),
        _desired(tmp_path, package, final_state="installed_disabled"),
        scope_id=_SCOPE,
    )
    assert inventory.active_local == ()
    assert [
        (item.plugin_id, item.desired_state) for item in inventory.builtin_intent
    ] == [("coding.base", "installed_disabled")]
