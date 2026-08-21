from __future__ import annotations

import json
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
    [binding] = materializer.bind_plugin_packages((_descriptor(root),))

    assert binding.plugin_id == "review-pack"
    assert binding.manifest_digest == _descriptor(root).manifest_digest
    assert binding.revision == binding.manifest_digest

    restored = PackageMaterializer(install_root=tmp_path / "installed")
    assert restored.get_plugin_binding(root) == binding
    lockfile = json.loads(
        (tmp_path / "package-lock.json").read_text(encoding="utf-8")
    )
    assert lockfile["version"] == 2
    assert lockfile["pluginBindings"] == [
        {
            "manifestDigest": binding.manifest_digest,
            "pluginId": "review-pack",
            "revision": binding.revision,
            "revisionKind": "manifest_sha256",
            "source": str(root.resolve()),
            "sourceIdentity": binding.source_identity,
            "sourceKind": "local",
        }
    ]

    _write_manifest(root, name="renamed-pack")
    before = (tmp_path / "package-lock.json").read_bytes()

    with pytest.raises(PluginManifestError) as caught:
        restored.bind_plugin_packages((_descriptor(root),))

    assert caught.value.code == "plugin_identity_changed"
    assert restored.get_plugin_binding(root) == binding
    assert (tmp_path / "package-lock.json").read_bytes() == before


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

    [binding] = materializer.bind_plugin_packages((package,))

    assert binding.revision == "abc123"
    assert binding.revision_kind == "git_commit"
    equivalent = "git+https://github.com/acme/review-pack"
    assert materializer.get_plugin_binding(equivalent) == binding
    restored = PackageMaterializer(install_root=tmp_path / "installed")
    assert restored.get_plugin_binding(equivalent) == binding


def test_plugin_source_rebind_is_explicit_and_persistent(tmp_path: Path) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack")
    materializer = PackageMaterializer(install_root=tmp_path / "installed")
    materializer.bind_plugin_packages((_descriptor(root),))
    _write_manifest(root, name="renamed-pack")

    [rebound] = materializer.rebind_plugin_packages((_descriptor(root),))

    assert rebound.plugin_id == "renamed-pack"
    restored = PackageMaterializer(install_root=tmp_path / "installed")
    assert restored.get_plugin_binding(root) == rebound


def test_same_plugin_identity_can_advance_its_bound_revision(tmp_path: Path) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack", version="1")
    materializer = PackageMaterializer(install_root=tmp_path / "installed")
    [initial] = materializer.bind_plugin_packages((_descriptor(root),))
    _write_manifest(root, name="review-pack", version="2")

    [updated] = materializer.bind_plugin_packages((_descriptor(root),))

    assert updated.plugin_id == initial.plugin_id
    assert updated.manifest_digest != initial.manifest_digest
    assert updated.revision == updated.manifest_digest
    assert materializer.get_plugin_binding(root) == updated


def test_plugin_source_binding_can_be_explicitly_forgotten(tmp_path: Path) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack")
    materializer = PackageMaterializer(install_root=tmp_path / "installed")
    materializer.bind_plugin_packages((_descriptor(root),))

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
        materializer.bind_plugin_packages((_descriptor(root),))
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

    [binding] = materializer.rebind_plugin_packages((_descriptor(root),))

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
        materializer.bind_plugin_packages((_descriptor(root),))

    assert caught.value.code == "plugin_binding_lock_invalid"
    assert materializer.get_lockfile_diagnostics()[0]["message"] == (
        "Package lockfile v2 is missing pluginBindings."
    )


def test_explicit_rebind_rewrites_lock_when_valid_binding_preceded_invalid_entry(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "plugins" / "review", name="review-pack")
    initial = PackageMaterializer(install_root=tmp_path / "installed")
    [binding] = initial.bind_plugin_packages((_descriptor(root),))
    lockfile = tmp_path / "package-lock.json"
    payload = json.loads(lockfile.read_text(encoding="utf-8"))
    payload["pluginBindings"].append({"invalid": True})
    lockfile.write_text(json.dumps(payload), encoding="utf-8")
    materializer = PackageMaterializer(install_root=tmp_path / "installed")

    assert materializer.get_plugin_binding(root) == binding
    [repaired] = materializer.rebind_plugin_packages((_descriptor(root),))

    assert repaired == binding
    restored = PackageMaterializer(install_root=tmp_path / "installed")
    assert restored.get_lockfile_diagnostics() == []
    assert restored.get_plugin_binding(root) == binding


def test_plugin_source_binding_batch_rejects_without_partial_revision_advance(
    tmp_path: Path,
) -> None:
    first = _plugin(tmp_path / "plugins" / "first", name="first-pack", version="1")
    second = _plugin(
        tmp_path / "plugins" / "second", name="second-pack", version="1"
    )
    materializer = PackageMaterializer(install_root=tmp_path / "installed")
    initial = materializer.bind_plugin_packages(
        (_descriptor(first), _descriptor(second))
    )

    _write_manifest(first, name="first-pack", version="2")
    _write_manifest(second, name="renamed-pack", version="2")

    with pytest.raises(PluginManifestError, match="second-pack.*renamed-pack"):
        materializer.bind_plugin_packages(
            (_descriptor(first), _descriptor(second))
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
    binding = materializer.bind_plugin_packages((_descriptor(root),))[0]
    _write_manifest(root, name="renamed-pack")

    [entry] = PackageCatalogBuilder(summary_provider=_summary).collect(
        sources=PackageCatalogSources(
            plugin_sources=((str(root), "project"),)
        ),
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


def _descriptor(root: Path):
    return PluginManifestParser().parse(root)


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
