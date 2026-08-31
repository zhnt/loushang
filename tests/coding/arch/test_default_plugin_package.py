from __future__ import annotations

import importlib.metadata
from pathlib import Path

from loushang.coding.plugin_dependency_grants import (
    coding_arch_default_plugin_root,
    coding_plugin_distribution_evidence_resolver,
)
from loushang.coding.resource_runtime import CodingPackageMaterializer
from loushang.harness.capabilities.component_host import _PROVIDER_HOST_API_PREFIXES
from loushang.harness.resources.plugins.declarations import (
    PluginDeclarationDocumentCodec,
)
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.resources.plugins.python_symbols import (
    load_verified_plugin_python_module,
)


def test_checked_in_arch_plugin_has_exact_provider_and_tool_reservations() -> None:
    root = coding_arch_default_plugin_root()
    package = PluginManifestParser().parse(root)

    assert package.manifest.name == "coding.arch.default"
    assert tuple(
        (item.contribution_id, item.kind, item.owner)
        for item in package.contribution_index.items
    ) == (
        ("coding-arch-default", "capability_provider", "coding.arch"),
        ("coding-arch-tools", "tool_pack", "coding.tools"),
    )
    document = PluginDeclarationDocumentCodec.decode_bytes(
        (root / "declarations" / "tools.json").read_bytes()
    )
    [declaration] = document.declarations
    tool_reservation = package.contribution_index.items[1]
    assert declaration.plugin_id == "coding.arch.default"
    assert declaration.contribution_id == "coding-arch-tools"
    assert declaration.reservation_fingerprint == tool_reservation.fingerprint
    assert (
        declaration.source_descriptor_fingerprint
        == tool_reservation.source_descriptor_fingerprint
    )


def test_checked_in_arch_plugin_publishes_with_product_distribution_evidence(
    tmp_path: Path,
) -> None:
    materializer = CodingPackageMaterializer(
        install_root=tmp_path / "installed",
        plugin_revision_root=tmp_path / "revisions",
    )
    package = PluginManifestParser().parse(coding_arch_default_plugin_root())

    [published] = materializer.publish_plugin_packages((package,))

    [distribution] = published.dependency_lock.python_distributions
    assert distribution.name == "loushang"
    assert distribution.version == importlib.metadata.version("loushang")

    module = load_verified_plugin_python_module(
        revision_handle=published.revision_handle,
        dependency_lock=published.dependency_lock,
        relative_path="definition.py",
        module_name="_test_coding_arch_default_component",
        host_api_prefixes=_PROVIDER_HOST_API_PREFIXES,
        distribution_evidence_resolver=(coding_plugin_distribution_evidence_resolver()),
    )
    assert callable(module.resolve("declare"))
    assert callable(module.resolve("create_provider"))
    assert callable(module.resolve("dispose_provider"))
