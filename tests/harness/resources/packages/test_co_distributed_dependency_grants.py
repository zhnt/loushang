from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from loushang.harness.resources.packages.materializer import (
    PackageMaterializer,
    plugin_source_identity,
)
from loushang.harness.resources.plugins.dependencies import (
    PluginPythonDistributionLock,
)
from loushang.harness.resources.plugins.distribution_evidence import (
    InstalledPythonDistributionEvidence,
    InstalledPythonDistributionEvidenceError,
)
from loushang.harness.resources.plugins.manifest import (
    PluginManifestError,
    PluginManifestParser,
)


@dataclass
class _GrantResolver:
    plugin_id: str
    source_identity: str
    calls: list[tuple[str, str]]

    def resolve(
        self,
        *,
        plugin_id: str,
        source_identity: str,
    ) -> tuple[str, ...]:
        self.calls.append((plugin_id, source_identity))
        if (plugin_id, source_identity) == (
            self.plugin_id,
            self.source_identity,
        ):
            return ("loushang",)
        return ()


class _EvidenceResolver:
    def __init__(self, manifest_path: Path, *, version: str = "0.1.0") -> None:
        self.manifest_path = manifest_path.resolve()
        self.version = version
        self.calls: list[tuple[str, tuple[Path, ...]]] = []

    def resolve(
        self,
        distribution: str,
        *,
        expected_version: str | None = None,
        required_paths: tuple[Path, ...] = (),
    ) -> InstalledPythonDistributionEvidence:
        assert expected_version is None
        paths = tuple(path.resolve() for path in required_paths)
        self.calls.append((distribution, paths))
        if distribution != "loushang":
            raise AssertionError("unexpected distribution grant")
        if paths != (self.manifest_path,):
            raise InstalledPythonDistributionEvidenceError(
                "Plugin source is outside the installed distribution",
                code="plugin_dependency_distribution_source_mismatch",
            )
        return InstalledPythonDistributionEvidence(
            distribution=PluginPythonDistributionLock(
                name="loushang",
                version=self.version,
            ),
            install_mode="record",
            top_level_packages=("loushang",),
            _recorded_paths=(self.manifest_path,),
        )


def test_product_grant_is_unioned_into_the_canonical_dependency_lock(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "coding-lsp", name="coding.lsp.default")
    calls: list[tuple[str, str]] = []
    grant_resolver = _GrantResolver(
        plugin_id="coding.lsp.default",
        source_identity=plugin_source_identity(root),
        calls=calls,
    )
    evidence_resolver = _EvidenceResolver(root / "plugin.json")
    materializer = PackageMaterializer(
        install_root=tmp_path / "installed",
        co_distributed_dependency_grant_resolver=grant_resolver,
        installed_distribution_evidence_resolver=evidence_resolver,
    )

    [published] = materializer.publish_plugin_packages(
        (PluginManifestParser().parse(root),)
    )
    [binding] = materializer.bind_plugin_packages((published,))

    assert published.dependency_lock.python_distributions == (
        PluginPythonDistributionLock(name="loushang", version="0.1.0"),
    )
    assert binding.dependency_lock == published.dependency_lock
    assert calls == [
        ("coding.lsp.default", plugin_source_identity(root)),
        ("coding.lsp.default", plugin_source_identity(root)),
    ]
    assert evidence_resolver.calls == [
        ("loushang", ((root / "plugin.json").resolve(),)),
        ("loushang", ((root / "plugin.json").resolve(),)),
    ]


def test_binding_recomputes_product_grants_and_rejects_version_drift(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "coding-lsp", name="coding.lsp.default")
    evidence_resolver = _EvidenceResolver(root / "plugin.json")
    materializer = PackageMaterializer(
        install_root=tmp_path / "installed",
        co_distributed_dependency_grant_resolver=_GrantResolver(
            plugin_id="coding.lsp.default",
            source_identity=plugin_source_identity(root),
            calls=[],
        ),
        installed_distribution_evidence_resolver=evidence_resolver,
    )
    [published] = materializer.publish_plugin_packages(
        (PluginManifestParser().parse(root),)
    )
    evidence_resolver.version = "0.2.0"

    with pytest.raises(PluginManifestError) as captured:
        materializer.bind_plugin_packages((published,))

    assert captured.value.code == "plugin_dependency_closure_changed"


def test_canonical_lock_rejects_a_grant_conflicting_with_the_plugin_tree(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "coding-lsp", name="coding.lsp.default")
    dist_info = root / "loushang-9.9.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Name: loushang\nVersion: 9.9.0\n",
        encoding="utf-8",
    )
    materializer = PackageMaterializer(
        install_root=tmp_path / "installed",
        co_distributed_dependency_grant_resolver=_GrantResolver(
            plugin_id="coding.lsp.default",
            source_identity=plugin_source_identity(root),
            calls=[],
        ),
        installed_distribution_evidence_resolver=_EvidenceResolver(
            root / "plugin.json",
            version="0.1.0",
        ),
    )

    with pytest.raises(PluginManifestError) as captured:
        materializer.publish_plugin_packages((PluginManifestParser().parse(root),))

    assert captured.value.code == "invalid_plugin_dependency_closure"


def test_granted_distribution_evidence_failure_preserves_its_stable_code(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "coding-lsp", name="coding.lsp.default")

    class _MissingEvidence:
        def resolve(self, *args: object, **kwargs: object) -> object:
            del args, kwargs
            raise InstalledPythonDistributionEvidenceError(
                "A locked Plugin dependency is unavailable",
                code="plugin_dependency_distribution_unavailable",
            )

    materializer = PackageMaterializer(
        install_root=tmp_path / "installed",
        co_distributed_dependency_grant_resolver=_GrantResolver(
            plugin_id="coding.lsp.default",
            source_identity=plugin_source_identity(root),
            calls=[],
        ),
        installed_distribution_evidence_resolver=_MissingEvidence(),
    )

    with pytest.raises(PluginManifestError) as captured:
        materializer.publish_plugin_packages((PluginManifestParser().parse(root),))

    assert captured.value.code == "plugin_dependency_distribution_unavailable"


def test_ordinary_plugin_keeps_the_materialized_root_only_lock(
    tmp_path: Path,
) -> None:
    coding_root = _plugin(tmp_path / "coding-lsp", name="coding.lsp.default")
    ordinary_root = _plugin(tmp_path / "ordinary", name="ordinary")
    evidence_resolver = _EvidenceResolver(coding_root / "plugin.json")
    materializer = PackageMaterializer(
        install_root=tmp_path / "installed",
        co_distributed_dependency_grant_resolver=_GrantResolver(
            plugin_id="coding.lsp.default",
            source_identity=plugin_source_identity(coding_root),
            calls=[],
        ),
        installed_distribution_evidence_resolver=evidence_resolver,
    )

    [published] = materializer.publish_plugin_packages(
        (PluginManifestParser().parse(ordinary_root),)
    )

    assert published.dependency_lock.python_distributions == ()
    assert evidence_resolver.calls == []


def _plugin(root: Path, *, name: str) -> Path:
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps({"name": name, "version": "1"}),
        encoding="utf-8",
    )
    return root
