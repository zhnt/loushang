from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.policy import PolicyDecision
from loushang.harness.resources.packages.catalog import (
    PackageCatalogBuilder,
    PackageCatalogSources,
)
from loushang.harness.resources.packages.materializer import (
    PackageMaterializationRecord,
    PackageMaterializer,
)
from loushang.harness.resources.packages.roots import resolve_package_resource_roots
from loushang.harness.resources.plugins.dependencies import (
    lock_plugin_dependency_closure,
)
from loushang.harness.resources.plugins.manifest import (
    PluginManifestError,
    PluginManifestParser,
)
from loushang.harness.resources.plugins.types import PluginSource
from loushang.harness.resources.types import PackageResourceSummary


def test_plugin_source_binding_survives_restart_and_rejects_implicit_rename(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack")
    materializer = PackageMaterializer(install_root=tmp_path / "installed")
    [binding] = materializer.bind_plugin_packages(
        (_published_descriptor(materializer, root),)
    )

    assert binding.plugin_id == "review-pack"
    assert binding.manifest_digest == _descriptor(root).manifest_digest
    assert binding.content_digest is not None
    assert binding.revision == binding.content_digest
    assert binding.dependency_lock is not None

    restored = PackageMaterializer(install_root=tmp_path / "installed")
    assert restored.get_plugin_binding(root) == binding
    lockfile = json.loads((tmp_path / "package-lock.json").read_text(encoding="utf-8"))
    assert lockfile["version"] == 4
    assert lockfile["pluginBindings"] == [
        {
            "contentDigest": binding.content_digest,
            "dependencyLock": binding.dependency_lock.to_dict(),
            "dependencyLockDigest": binding.dependency_lock.digest,
            "manifestDigest": binding.manifest_digest,
            "pluginId": "review-pack",
            "revision": binding.revision,
            "revisionKind": "content_sha256",
            "source": str(root.resolve()),
            "sourceIdentity": binding.source_identity,
            "sourceKind": "local",
        }
    ]
    assert lockfile["pluginBindingHeads"] == [
        {
            "historyKey": lockfile["pluginBindingHeads"][0]["historyKey"],
            "sourceIdentity": binding.source_identity,
        }
    ]
    assert len(lockfile["pluginBindingHeads"][0]["historyKey"]) == 64

    _write_manifest(root, name="renamed-pack")
    before = (tmp_path / "package-lock.json").read_bytes()

    with pytest.raises(PluginManifestError) as caught:
        restored.bind_plugin_packages((_published_descriptor(restored, root),))

    assert caught.value.code == "plugin_identity_changed"
    assert restored.get_plugin_binding(root) == binding
    assert (tmp_path / "package-lock.json").read_bytes() == before


def test_stale_materializers_merge_disjoint_plugin_bindings_without_lost_update(
    tmp_path: Path,
) -> None:
    first_root = _plugin(tmp_path / "plugins" / "first", name="first-pack")
    second_root = _plugin(tmp_path / "plugins" / "second", name="second-pack")
    install_root = tmp_path / "installed"
    first = PackageMaterializer(install_root=install_root)
    second = PackageMaterializer(install_root=install_root)
    first_package = _published_descriptor(first, first_root)
    second_package = _published_descriptor(second, second_root)

    [first_binding] = first.bind_plugin_packages((first_package,))
    [second_binding] = second.bind_plugin_packages((second_package,))

    restored = PackageMaterializer(install_root=install_root)
    assert restored.get_plugin_binding(first_root) == first_binding
    assert restored.get_plugin_binding(second_root) == second_binding
    reopened_first = restored.reopen_plugin_package(first_binding)
    reopened_second = restored.reopen_plugin_package(second_binding)
    try:
        assert reopened_first.manifest.name == "first-pack"
        assert reopened_second.manifest.name == "second-pack"
    finally:
        reopened_second.revision_handle.close()
        reopened_first.revision_handle.close()
        second_package.revision_handle.close()
        first_package.revision_handle.close()


def test_stale_materializer_rejects_conflicting_same_binding_update(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack", version="1")
    install_root = tmp_path / "installed"
    initial = PackageMaterializer(install_root=install_root)
    initial_package = _published_descriptor(initial, root)
    initial.bind_plugin_packages((initial_package,))
    initial_package.revision_handle.close()
    first = PackageMaterializer(install_root=install_root)
    second = PackageMaterializer(install_root=install_root)

    _write_manifest(root, name="review-pack", version="2")
    first_package = _published_descriptor(first, root)
    _write_manifest(root, name="review-pack", version="3")
    second_package = _published_descriptor(second, root)
    first.bind_plugin_packages((first_package,))

    with pytest.raises(PluginManifestError) as caught:
        second.bind_plugin_packages((second_package,))

    assert caught.value.code == "package_lockfile_concurrent_update"
    restored = PackageMaterializer(install_root=install_root)
    assert restored.get_plugin_binding(root).content_digest == (
        first_package.content_digest
    )
    second_package.revision_handle.close()
    first_package.revision_handle.close()


def test_reopen_plugin_package_closes_revision_handle_on_binding_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack")
    materializer = PackageMaterializer(install_root=tmp_path / "installed")
    published = _published_descriptor(materializer, root)
    [binding] = materializer.bind_plugin_packages((published,))
    published.revision_handle.close()
    payload = json.loads(materializer.lockfile_path.read_text(encoding="utf-8"))
    payload["pluginBindings"][0]["manifestDigest"] = "0" * 64
    materializer.lockfile_path.write_text(json.dumps(payload), encoding="utf-8")
    restored = PackageMaterializer(install_root=tmp_path / "installed")
    replay_binding = restored.get_plugin_binding_by_identity(binding.source_identity)
    assert replay_binding is not None
    captured = []
    original_reopen = restored._plugin_revision_store.reopen

    def capture_reopen(*args, **kwargs):
        revision = original_reopen(*args, **kwargs)
        captured.append(revision.revision_handle)
        return revision

    monkeypatch.setattr(restored._plugin_revision_store, "reopen", capture_reopen)

    with pytest.raises(PluginManifestError) as caught:
        restored.reopen_plugin_package(replay_binding)

    assert caught.value.code == "invalid_plugin_source_binding"
    assert len(captured) == 1
    assert captured[0].closed is True


def test_reopen_plugin_package_rejects_dependency_lock_content_mismatch(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack")
    materializer = PackageMaterializer(install_root=tmp_path / "installed")
    published = _published_descriptor(materializer, root)
    materializer.bind_plugin_packages((published,))
    published.revision_handle.close()
    payload = json.loads(materializer.lockfile_path.read_text(encoding="utf-8"))
    binding = payload["pluginBindings"][0]
    dependency_lock = binding["dependencyLock"]
    dependency_lock["packageContentDigest"] = "f" * 64
    binding["dependencyLockDigest"] = lock_plugin_dependency_closure(
        package_content_digest="f" * 64,
        installed_distributions=(),
    ).digest
    materializer.lockfile_path.write_text(json.dumps(payload), encoding="utf-8")

    restored = PackageMaterializer(install_root=tmp_path / "installed")

    assert restored.get_plugin_binding(root) is None
    assert restored.get_lockfile_diagnostics()[0]["code"] == (
        "package_lockfile_invalid_plugin_binding"
    )


def test_remote_plugin_binding_uses_materialized_revision_and_normalized_source(
    tmp_path: Path,
) -> None:
    source = "https://github.com/acme/review-pack.git"

    def backend(
        record: PackageMaterializationRecord,
    ) -> PackageMaterializationRecord:
        record.target_path.mkdir(parents=True)
        _write_manifest(record.target_path, name="review-pack")
        return record.with_lifecycle("installed").with_git_state(
            resolved_commit="abc123",
            installed_commit="abc123",
        )

    materializer = PackageMaterializer(
        install_root=tmp_path / "installed",
        backend=backend,
        security_policy=_AllowPolicy(),
    )
    record = materializer.materialize_remote_source_sync(source)
    package = PluginManifestParser().parse(
        record.target_path,
        source=PluginSource(
            path=record.target_path,
            url=source,
            kind="remote",
        ),
    )

    [published] = materializer.publish_plugin_packages((package,))
    [binding] = materializer.bind_plugin_packages((published,))

    assert published.dependency_lock is not None
    assert published.dependency_lock.package_content_digest == published.content_digest
    assert published.dependency_lock.python_distributions == ()
    assert binding.dependency_lock == published.dependency_lock
    assert binding.revision == "abc123"
    assert binding.revision_kind == "git_commit"
    assert binding.content_digest == published.content_digest
    equivalent = "git+https://github.com/acme/review-pack"
    assert materializer.get_plugin_binding(equivalent) == binding
    restored = PackageMaterializer(install_root=tmp_path / "installed")
    assert restored.get_plugin_binding(equivalent) == binding


def test_plugin_binding_rejects_unpublished_mutable_descriptor(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack")
    materializer = PackageMaterializer(install_root=tmp_path / "installed")

    with pytest.raises(PluginManifestError) as caught:
        materializer.bind_plugin_packages((_descriptor(root),))

    assert caught.value.code == "unpublished_plugin_package"
    assert materializer.get_plugin_binding(root) is None
    assert materializer.lockfile_path.exists() is False


def test_plugin_binding_revalidates_dependency_closure_from_published_tree(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack")
    _write_python_dist(root, name="review-dependency", version="1.2.3")
    materializer = PackageMaterializer(install_root=tmp_path / "installed")
    [published] = materializer.publish_plugin_packages((_descriptor(root),))
    assert published.content_digest is not None
    fabricated = replace(
        published,
        dependency_lock=lock_plugin_dependency_closure(
            package_content_digest=published.content_digest,
            installed_distributions=(),
        ),
    )

    with pytest.raises(PluginManifestError) as caught:
        materializer.bind_plugin_packages((fabricated,))

    assert caught.value.code == "plugin_dependency_closure_changed"
    assert materializer.get_plugin_binding(root) is None


def test_v4_plugin_binding_rejects_removed_dependency_lock_on_restart(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack")
    materializer = PackageMaterializer(install_root=tmp_path / "installed")
    materializer.bind_plugin_packages((_published_descriptor(materializer, root),))
    lockfile = materializer.lockfile_path
    payload = json.loads(lockfile.read_text(encoding="utf-8"))
    [binding] = payload["pluginBindings"]
    binding.pop("dependencyLock")
    binding.pop("dependencyLockDigest")
    lockfile.write_text(json.dumps(payload), encoding="utf-8")

    restored = PackageMaterializer(install_root=tmp_path / "installed")

    assert restored.get_plugin_binding(root) is None
    assert restored.get_lockfile_diagnostics()[0]["code"] == (
        "package_lockfile_invalid_plugin_binding_head"
    )
    with pytest.raises(PluginManifestError) as caught:
        restored.bind_plugin_packages((_published_descriptor(restored, root),))
    assert caught.value.code == "plugin_binding_lock_invalid"


def test_v2_plugin_binding_requires_verified_upgrade_to_v3(tmp_path: Path) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack")
    descriptor = _descriptor(root)
    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text(
        json.dumps(
            {
                "version": 2,
                "packages": [],
                "pluginBindings": [
                    {
                        "source": str(root.resolve()),
                        "sourceIdentity": f"local:{root.resolve()}",
                        "sourceKind": "local",
                        "pluginId": "review-pack",
                        "manifestDigest": descriptor.manifest_digest,
                        "contentDigest": None,
                        "revision": descriptor.manifest_digest,
                        "revisionKind": "manifest_sha256",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    materializer = PackageMaterializer(install_root=tmp_path / "installed")

    legacy = materializer.get_plugin_binding(root)
    assert legacy is not None
    assert legacy.dependency_lock is None

    [upgraded] = materializer.bind_plugin_packages(
        (_published_descriptor(materializer, root),)
    )

    assert upgraded.dependency_lock is not None
    assert upgraded.content_digest is not None
    assert json.loads(lockfile.read_text(encoding="utf-8"))["version"] == 4
    restored = PackageMaterializer(install_root=tmp_path / "installed")
    assert restored.get_plugin_binding(root) == upgraded


def test_v2_plugin_binding_migrates_with_explicit_head_until_verified(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack")
    descriptor = _descriptor(root)
    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text(
        json.dumps(
            {
                "version": 2,
                "packages": [],
                "pluginBindings": [
                    {
                        "source": str(root.resolve()),
                        "sourceIdentity": f"local:{root.resolve()}",
                        "sourceKind": "local",
                        "pluginId": "review-pack",
                        "manifestDigest": descriptor.manifest_digest,
                        "contentDigest": None,
                        "revision": descriptor.manifest_digest,
                        "revisionKind": "manifest_sha256",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    materializer = PackageMaterializer(install_root=tmp_path / "installed")

    materializer.prepare_remote_source("https://github.com/acme/other-pack.git")

    payload = json.loads(lockfile.read_text(encoding="utf-8"))
    assert payload["version"] == 4
    assert payload["pluginBindingHeads"][0]["sourceIdentity"] == (
        f"local:{root.resolve()}"
    )
    restored = PackageMaterializer(install_root=tmp_path / "installed")
    assert restored.get_plugin_binding(root) == materializer.get_plugin_binding(root)


def test_python_plugin_binding_locks_complete_installed_distribution_closure(
    tmp_path: Path,
) -> None:
    source = "pypi:acme-review-pack==1.2.3"

    def backend(
        record: PackageMaterializationRecord,
    ) -> PackageMaterializationRecord:
        record.target_path.mkdir(parents=True)
        _write_manifest(record.target_path, name="review-pack")
        _write_python_dist(
            record.target_path,
            name="acme-review-pack",
            version="1.2.3",
        )
        _write_python_dist(
            record.target_path,
            name="Transitive_Dep",
            version="4.5.6",
        )
        return record.with_lifecycle("installed").with_python_state(
            installer="uv",
            resolved_name="acme-review-pack",
            resolved_version="1.2.3",
            installed_distributions=(
                "transitive-dep==4.5.6",
                "acme-review-pack==1.2.3",
            ),
        )

    materializer = PackageMaterializer(
        install_root=tmp_path / "installed",
        python_backend=backend,
        security_policy=_AllowPolicy(),
    )
    record = materializer.materialize_remote_source_sync(source)
    package = PluginManifestParser().parse(
        record.target_path,
        source=PluginSource(
            path=record.target_path,
            url=source,
            kind="remote",
        ),
    )

    [published] = materializer.publish_plugin_packages((package,))
    [binding] = materializer.bind_plugin_packages((published,))

    assert published.dependency_lock is not None
    assert [
        (item.name, item.version)
        for item in published.dependency_lock.python_distributions
    ] == [
        ("acme-review-pack", "1.2.3"),
        ("transitive-dep", "4.5.6"),
    ]
    assert binding.dependency_lock == published.dependency_lock
    restored = PackageMaterializer(install_root=tmp_path / "installed")
    assert restored.get_plugin_binding(source) == binding


def test_python_plugin_publication_rejects_missing_distribution_closure(
    tmp_path: Path,
) -> None:
    source = "pypi:acme-review-pack==1.2.3"

    def backend(
        record: PackageMaterializationRecord,
    ) -> PackageMaterializationRecord:
        record.target_path.mkdir(parents=True)
        _write_manifest(record.target_path, name="review-pack")
        return record.with_lifecycle("installed").with_python_state(
            installer="uv",
            resolved_name="acme-review-pack",
            resolved_version="1.2.3",
            installed_distributions=(),
        )

    materializer = PackageMaterializer(
        install_root=tmp_path / "installed",
        python_backend=backend,
        security_policy=_AllowPolicy(),
    )
    record = materializer.materialize_remote_source_sync(source)
    package = PluginManifestParser().parse(
        record.target_path,
        source=PluginSource(
            path=record.target_path,
            url=source,
            kind="remote",
        ),
    )

    with pytest.raises(PluginManifestError) as caught:
        materializer.publish_plugin_packages((package,))

    assert caught.value.code == "plugin_dependency_closure_incomplete"


def test_python_plugin_publication_rejects_distribution_record_tree_drift(
    tmp_path: Path,
) -> None:
    source = "pypi:acme-review-pack==1.2.3"

    def backend(
        record: PackageMaterializationRecord,
    ) -> PackageMaterializationRecord:
        record.target_path.mkdir(parents=True)
        _write_manifest(record.target_path, name="review-pack")
        _write_python_dist(
            record.target_path,
            name="acme-review-pack",
            version="1.2.3",
        )
        return record.with_lifecycle("installed").with_python_state(
            installer="uv",
            resolved_name="acme-review-pack",
            resolved_version="1.2.3",
            installed_distributions=(
                "acme-review-pack==1.2.3",
                "missing-transitive==4.5.6",
            ),
        )

    materializer = PackageMaterializer(
        install_root=tmp_path / "installed",
        python_backend=backend,
        security_policy=_AllowPolicy(),
    )
    record = materializer.materialize_remote_source_sync(source)
    package = PluginManifestParser().parse(
        record.target_path,
        source=PluginSource(
            path=record.target_path,
            url=source,
            kind="remote",
        ),
    )

    with pytest.raises(PluginManifestError) as caught:
        materializer.publish_plugin_packages((package,))

    assert caught.value.code == "plugin_dependency_closure_changed"


def test_plugin_source_rebind_is_explicit_and_persistent(tmp_path: Path) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack")
    materializer = PackageMaterializer(install_root=tmp_path / "installed")
    materializer.bind_plugin_packages((_published_descriptor(materializer, root),))
    _write_manifest(root, name="renamed-pack")

    [rebound] = materializer.rebind_plugin_packages(
        (_published_descriptor(materializer, root),)
    )

    assert rebound.plugin_id == "renamed-pack"
    restored = PackageMaterializer(install_root=tmp_path / "installed")
    assert restored.get_plugin_binding(root) == rebound


def test_same_plugin_identity_can_advance_its_bound_revision(tmp_path: Path) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack", version="1")
    materializer = PackageMaterializer(install_root=tmp_path / "installed")
    [initial] = materializer.bind_plugin_packages(
        (_published_descriptor(materializer, root),)
    )
    _write_manifest(root, name="review-pack", version="2")

    [updated] = materializer.bind_plugin_packages(
        (_published_descriptor(materializer, root),)
    )

    assert updated.plugin_id == initial.plugin_id
    assert updated.manifest_digest != initial.manifest_digest
    assert updated.revision == updated.content_digest
    assert materializer.get_plugin_binding(root) == updated

    restored = PackageMaterializer(install_root=tmp_path / "installed")
    exact_initial = restored.get_plugin_binding_by_revision(
        initial.source_identity,
        content_digest=initial.content_digest or "",
        dependency_lock_digest=initial.dependency_lock.digest
        if initial.dependency_lock is not None
        else "",
    )
    exact_updated = restored.get_plugin_binding_by_revision(
        updated.source_identity,
        content_digest=updated.content_digest or "",
        dependency_lock_digest=updated.dependency_lock.digest
        if updated.dependency_lock is not None
        else "",
    )

    assert exact_initial == initial
    assert exact_updated == updated
    reopened_initial = restored.reopen_plugin_package(initial)
    reopened_updated = restored.reopen_plugin_package(updated)
    try:
        assert reopened_initial.manifest.version == "1"
        assert reopened_updated.manifest.version == "2"
    finally:
        reopened_updated.revision_handle.close()
        reopened_initial.revision_handle.close()


def test_plugin_source_binding_can_be_explicitly_forgotten(tmp_path: Path) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack")
    materializer = PackageMaterializer(install_root=tmp_path / "installed")
    materializer.bind_plugin_packages((_published_descriptor(materializer, root),))

    materializer.forget_plugin_binding(root)

    assert materializer.get_plugin_binding(root) is None
    restored = PackageMaterializer(install_root=tmp_path / "installed")
    assert restored.get_plugin_binding(root) is None


def test_plugin_source_binding_rejects_noncanonical_lockfile_identity(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack")
    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text(
        json.dumps(
            {
                "version": 2,
                "packages": [],
                "pluginBindings": [
                    {
                        "source": str(root),
                        "sourceIdentity": "local:/spoofed/path",
                        "sourceKind": "local",
                        "pluginId": "review-pack",
                        "manifestDigest": _descriptor(root).manifest_digest,
                        "revision": _descriptor(root).manifest_digest,
                        "revisionKind": "manifest_sha256",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    materializer = PackageMaterializer(install_root=tmp_path / "installed")

    assert materializer.get_plugin_binding(root) is None
    assert materializer.get_lockfile_diagnostics() == [
        {
            "code": "package_lockfile_invalid_plugin_binding",
            "message": "Package lockfile contains an invalid Plugin source binding.",
            "path": str(lockfile),
        }
    ]
    with pytest.raises(PluginManifestError) as caught:
        materializer.bind_plugin_packages((_published_descriptor(materializer, root),))
    assert caught.value.code == "plugin_binding_lock_invalid"


def test_explicit_rebind_repairs_invalid_plugin_binding_lock_section(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack")
    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text(
        json.dumps(
            {
                "version": 2,
                "packages": [],
                "pluginBindings": "invalid",
            }
        ),
        encoding="utf-8",
    )
    materializer = PackageMaterializer(install_root=tmp_path / "installed")

    [binding] = materializer.rebind_plugin_packages(
        (_published_descriptor(materializer, root),)
    )

    assert binding.plugin_id == "review-pack"
    restored = PackageMaterializer(install_root=tmp_path / "installed")
    assert restored.get_lockfile_diagnostics() == []
    assert restored.get_plugin_binding(root) == binding


def test_version_two_lockfile_cannot_silently_omit_plugin_bindings(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack")
    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text(
        json.dumps({"version": 2, "packages": []}),
        encoding="utf-8",
    )
    materializer = PackageMaterializer(install_root=tmp_path / "installed")

    with pytest.raises(PluginManifestError) as caught:
        materializer.bind_plugin_packages((_published_descriptor(materializer, root),))

    assert caught.value.code == "plugin_binding_lock_invalid"
    assert materializer.get_lockfile_diagnostics()[0]["message"] == (
        "Package lockfile v2 is missing pluginBindings."
    )


def test_explicit_rebind_rewrites_lock_when_valid_binding_preceded_invalid_entry(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack")
    initial = PackageMaterializer(install_root=tmp_path / "installed")
    [binding] = initial.bind_plugin_packages((_published_descriptor(initial, root),))
    lockfile = tmp_path / "package-lock.json"
    payload = json.loads(lockfile.read_text(encoding="utf-8"))
    payload["pluginBindings"].append({"invalid": True})
    lockfile.write_text(json.dumps(payload), encoding="utf-8")
    materializer = PackageMaterializer(install_root=tmp_path / "installed")

    assert materializer.get_plugin_binding(root) == binding
    [repaired] = materializer.rebind_plugin_packages(
        (_published_descriptor(materializer, root),)
    )

    assert repaired == binding
    restored = PackageMaterializer(install_root=tmp_path / "installed")
    assert restored.get_lockfile_diagnostics() == []
    assert restored.get_plugin_binding(root) == binding


def test_plugin_source_binding_batch_rejects_without_partial_revision_advance(
    tmp_path: Path,
) -> None:
    first = _plugin(tmp_path / "plugins" / "first", name="first-pack", version="1")
    second = _plugin(tmp_path / "plugins" / "second", name="second-pack", version="1")
    materializer = PackageMaterializer(install_root=tmp_path / "installed")
    initial = materializer.bind_plugin_packages(
        materializer.publish_plugin_packages((_descriptor(first), _descriptor(second)))
    )

    _write_manifest(first, name="first-pack", version="2")
    _write_manifest(second, name="renamed-pack", version="2")

    with pytest.raises(PluginManifestError, match="second-pack.*renamed-pack"):
        materializer.bind_plugin_packages(
            materializer.publish_plugin_packages(
                (_descriptor(first), _descriptor(second))
            )
        )

    assert materializer.get_plugin_binding(first) == initial[0]
    assert materializer.get_plugin_binding(second) == initial[1]


def test_root_resolution_rejects_restart_rename_before_disabled_policy_can_be_bypassed(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack")
    install_root = tmp_path / "installed"
    materializer = PackageMaterializer(install_root=install_root)

    resolved = resolve_package_resource_roots(
        package_roots=(),
        plugin_sources=(str(root),),
        package_sources=(),
        materializer=materializer,
        disabled_plugins=("review-pack",),
    )

    assert resolved.roots == ()
    _write_manifest(root, name="renamed-pack")
    diagnostics = DiagnosticsService()

    with pytest.raises(PluginManifestError) as caught:
        resolve_package_resource_roots(
            package_roots=(),
            plugin_sources=(str(root),),
            package_sources=(),
            materializer=PackageMaterializer(install_root=install_root),
            disabled_plugins=("review-pack",),
            diagnostics_service=diagnostics,
            session_id="session-1",
        )

    assert caught.value.code == "plugin_identity_changed"
    [record] = diagnostics.get_last_diagnostics()
    assert record.code == "plugin_identity_changed"
    assert record.details["plugin_source"] == str(root)


def test_catalog_reports_persisted_identity_drift_without_rebinding(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack")
    materializer = PackageMaterializer(install_root=tmp_path / "installed")
    binding = materializer.bind_plugin_packages(
        (_published_descriptor(materializer, root),)
    )[0]
    _write_manifest(root, name="renamed-pack")

    [entry] = PackageCatalogBuilder(summary_provider=_summary).collect(
        sources=PackageCatalogSources(plugin_sources=((str(root), "project"),)),
        cwd=tmp_path,
        materializer=materializer,
    )

    assert entry.name == "renamed-pack"
    assert entry.version == "1"
    assert entry.enabled is False
    assert entry.manifest_diagnostics[0]["code"] == "plugin_identity_changed"
    assert materializer.get_plugin_binding(root) == binding


def _plugin(
    root: Path,
    *,
    name: str,
    version: str = "1",
) -> Path:
    root.mkdir(parents=True)
    _write_manifest(root, name=name, version=version)
    return root


def _write_manifest(root: Path, *, name: str, version: str = "1") -> None:
    (root / "plugin.json").write_text(
        json.dumps({"name": name, "version": version}),
        encoding="utf-8",
    )


def _write_python_dist(target: Path, *, name: str, version: str) -> None:
    dist_info_name = f"{name.replace('-', '_')}-{version}.dist-info"
    dist_info = target / dist_info_name
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(
        f"Name: {name}\nVersion: {version}\n",
        encoding="utf-8",
    )


def _descriptor(root: Path):
    return PluginManifestParser().parse(root)


def _published_descriptor(
    materializer: PackageMaterializer,
    root: Path,
):
    return materializer.publish_plugin_packages((_descriptor(root),))[0]


def _summary(
    package_root: Path,
    cwd: Path,
    package_source: object | None,
) -> PackageResourceSummary:
    del cwd, package_source
    return PackageResourceSummary(source_root=package_root, prompt_count=1)


class _AllowPolicy:
    def evaluate_package_source(self, source: str | Path) -> PolicyDecision:
        del source
        return PolicyDecision.allow()
