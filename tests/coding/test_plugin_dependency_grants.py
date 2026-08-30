from __future__ import annotations

import json
from pathlib import Path

import pytest

from loushang.coding.plugin_dependency_grants import (
    CoDistributedPluginDependencyGrantResolver,
)
from loushang.harness.resources.packages.materializer import (
    PackageMaterializer,
    plugin_source_identity,
)
from loushang.harness.resources.plugins.dependency_grants import (
    PluginDependencyGrantError,
)
from loushang.harness.resources.plugins.manifest import (
    PluginManifestError,
    PluginManifestParser,
)


def test_coding_grants_only_the_exact_checked_in_lsp_source(tmp_path: Path) -> None:
    expected = _plugin(tmp_path / "expected")
    copied = _plugin(tmp_path / "copied")
    resolver = CoDistributedPluginDependencyGrantResolver(
        coding_lsp_source=expected,
    )

    assert resolver.resolve(
        plugin_id="coding.lsp.default",
        source_identity=plugin_source_identity(expected),
    ) == ("loushang",)
    assert resolver.resolve(
        plugin_id="ordinary",
        source_identity=plugin_source_identity(copied),
    ) == ()

    with pytest.raises(PluginDependencyGrantError) as captured:
        resolver.resolve(
            plugin_id="coding.lsp.default",
            source_identity=plugin_source_identity(copied),
        )

    assert captured.value.code == "coding_lsp_plugin_source_mismatch"

    materializer = PackageMaterializer(
        install_root=tmp_path / "installed",
        co_distributed_dependency_grant_resolver=resolver,
    )
    with pytest.raises(PluginManifestError) as publication:
        materializer.publish_plugin_packages((PluginManifestParser().parse(copied),))
    assert publication.value.code == "coding_lsp_plugin_source_mismatch"


def test_coding_grants_only_the_exact_checked_in_arch_source(tmp_path: Path) -> None:
    lsp = _plugin(tmp_path / "lsp", plugin_id="coding.lsp.default")
    expected = _plugin(tmp_path / "expected", plugin_id="coding.arch.default")
    copied = _plugin(tmp_path / "copied", plugin_id="coding.arch.default")
    resolver = CoDistributedPluginDependencyGrantResolver(
        coding_lsp_source=lsp,
        coding_arch_source=expected,
    )

    assert resolver.resolve(
        plugin_id="coding.arch.default",
        source_identity=plugin_source_identity(expected),
    ) == ("loushang",)
    with pytest.raises(PluginDependencyGrantError) as captured:
        resolver.resolve(
            plugin_id="coding.arch.default",
            source_identity=plugin_source_identity(copied),
        )

    assert captured.value.code == "coding_arch_plugin_source_mismatch"


@pytest.mark.parametrize("source", ["missing", "not-a-directory"])
def test_coding_grant_registry_requires_one_existing_plugin_root(
    tmp_path: Path,
    source: str,
) -> None:
    path = tmp_path / source
    if source == "not-a-directory":
        path.write_text("not a Plugin", encoding="utf-8")

    with pytest.raises(ValueError, match="Plugin root"):
        CoDistributedPluginDependencyGrantResolver(coding_lsp_source=path)


def _plugin(root: Path, *, plugin_id: str = "coding.lsp.default") -> Path:
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps({"name": plugin_id}),
        encoding="utf-8",
    )
    return root
