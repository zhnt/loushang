from __future__ import annotations

import json
import sys
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.coding._plugin_lifecycle import (
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_legacy_lock_evidence import (
    CodingLegacyLockError,
    parse_coding_legacy_local_binding_heads,
    read_coding_legacy_local_binding_heads,
)
from loushang.coding.package_pre_b_snapshot import (
    prepare_and_cutover_coding_package_store_from_legacy,
    prepare_coding_package_cutover_roots,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.resources.packages.materializer import (
    PackageMaterializer,
    _plugin_binding_history_key,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.plugins.dependencies import (
    PluginDependencyClosureLock,
    PluginPythonDistributionLock,
)
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.resources.plugins.types import PluginSourceBinding


def _real_pre_b_lock(tmp_path: Path) -> tuple[bytes, PluginSourceBinding]:
    source = tmp_path / "original-source"
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
        [binding] = materializer.bind_plugin_packages(published)
    finally:
        published[0].revision_handle.close()
    return (old_package / "package-lock.json").read_bytes(), binding


def test_real_v4_local_binding_head_is_only_old_lock_evidence(tmp_path: Path) -> None:
    raw, binding = _real_pre_b_lock(tmp_path)
    [selected] = parse_coding_legacy_local_binding_heads(raw)
    assert selected.source_identity == binding.source_identity
    assert selected.plugin_id == binding.plugin_id
    assert selected.content_digest == binding.content_digest
    assert selected.manifest_digest == binding.manifest_digest
    assert selected.dependency_lock == binding.dependency_lock
    assert selected.lockfile_digest == sha256(raw).hexdigest()
    assert len(selected.binding_digest) == 64


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize("lock_present", [False, True])
def test_first_b_fence_reads_old_binding_only_from_verified_snapshot(
    tmp_path: Path, lock_present: bool
) -> None:
    raw, binding = _real_pre_b_lock(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    if lock_present:
        (lifecycle.package_root / "package-lock.json").write_bytes(raw)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
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
    if lock_present:
        (lifecycle.package_root / "package-lock.json").write_bytes(b"changed old Store")
    owner = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    try:
        if not lock_present:
            with pytest.raises(CodingLegacyLockError, match="lock is missing"):
                read_coding_legacy_local_binding_heads(lifecycle, owner)
            return
        [selected] = read_coding_legacy_local_binding_heads(lifecycle, owner)
        assert selected.source_identity == binding.source_identity
        assert selected.lockfile_digest == sha256(raw).hexdigest()
    finally:
        owner.close()


@pytest.mark.parametrize("mutation", ["old_version", "wrong_head", "duplicate_key"])
def test_legacy_lock_refuses_ambiguous_or_downgraded_evidence(
    tmp_path: Path, mutation: str
) -> None:
    raw, _binding = _real_pre_b_lock(tmp_path)
    if mutation == "duplicate_key":
        raw = raw.replace(b'"version": 4', b'"version": 4, "version": 4', 1)
    else:
        document = json.loads(raw)
        if mutation == "old_version":
            document["version"] = 3
        else:
            document["pluginBindingHeads"][0]["historyKey"] = "0" * 64
        raw = json.dumps(document).encode()
    with pytest.raises(CodingLegacyLockError):
        parse_coding_legacy_local_binding_heads(raw)


def test_legacy_lock_refuses_dependency_bearing_local_head(tmp_path: Path) -> None:
    raw, binding = _real_pre_b_lock(tmp_path)
    document = json.loads(raw)
    entry = document["pluginBindings"][0]
    assert binding.dependency_lock is not None
    lock = PluginDependencyClosureLock(
        package_content_digest=binding.dependency_lock.package_content_digest,
        python_distributions=(PluginPythonDistributionLock("example", "1"),),
    )
    entry["dependencyLock"] = lock.to_dict()
    entry["dependencyLockDigest"] = lock.digest
    document["pluginBindingHeads"][0]["historyKey"] = _plugin_binding_history_key(
        replace(binding, dependency_lock=lock)
    )
    with pytest.raises(
        CodingLegacyLockError, match="dependency closure is unsupported"
    ):
        parse_coding_legacy_local_binding_heads(json.dumps(document).encode())
