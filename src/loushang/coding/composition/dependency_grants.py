"""Private Product policy for same-distribution first-party Plugins."""

from __future__ import annotations

from pathlib import Path

from loushang.coding import _plugins as _coding_plugin_sources
from loushang.coding.harness.plugin_management.dependency_grants import (
    collect_source_identities,
    resolve_exact_source_grant,
)
from loushang.harness.resources.packages.plugin_lifecycle._exact_product_source import (
    resolve_installed_product_root,
)
from loushang.harness.resources.plugins.distribution_evidence import (
    InstalledPythonDistributionEvidenceResolver,
)

_CODING_LSP_PLUGIN_ID = "coding.lsp.default"
_CODING_ARCH_PLUGIN_ID = "coding.arch.default"
_LOUSHANG_DISTRIBUTION = "loushang"
_SOURCE_LABEL = "Coding Plugin"


_CODING_PRODUCT_SOURCE_LOCATIONS = {
    _CODING_LSP_PLUGIN_ID: ("coding_lsp_default",),
    _CODING_ARCH_PLUGIN_ID: ("coding_arch_default",),
}


def coding_capability_plugin_source_location(
    plugin_id: str,
) -> tuple[str, tuple[str, ...]]:
    """Return the asset owner's file and relative location as one closed fact."""
    return _coding_plugin_sources.__file__, _CODING_PRODUCT_SOURCE_LOCATIONS[plugin_id]


def coding_lsp_default_plugin_root() -> Path:
    """Return the exact checked-in source granted the reserved Plugin id."""
    return resolve_installed_product_root(
        *coding_capability_plugin_source_location(_CODING_LSP_PLUGIN_ID)
    )


def coding_arch_default_plugin_root() -> Path:
    """Return the exact checked-in source granted the reserved Arch Plugin id."""
    return resolve_installed_product_root(
        *coding_capability_plugin_source_location(_CODING_ARCH_PLUGIN_ID)
    )


def coding_plugin_distribution_evidence_resolver() -> (
    InstalledPythonDistributionEvidenceResolver
):
    """Create Coding's explicit evidence policy for its own editable checkout."""

    return InstalledPythonDistributionEvidenceResolver(allow_editable=True)


class CoDistributedPluginDependencyGrantResolver:
    """Recognize only Coding's exact checked-in executable Plugin sources."""

    def __init__(
        self,
        *,
        coding_lsp_source: str | Path,
        coding_arch_source: str | Path | None = None,
    ) -> None:
        sources = {
            _CODING_LSP_PLUGIN_ID: (
                coding_lsp_source,
                "coding_lsp_plugin_source_mismatch",
            ),
        }
        if coding_arch_source is not None:
            sources[_CODING_ARCH_PLUGIN_ID] = (
                coding_arch_source,
                "coding_arch_plugin_source_mismatch",
            )
        self._source_identities = collect_source_identities(
            sources, source_label=_SOURCE_LABEL
        )

    def resolve(
        self,
        *,
        plugin_id: str,
        source_identity: str,
    ) -> tuple[str, ...]:
        return resolve_exact_source_grant(
            self._source_identities,
            plugin_id=plugin_id,
            source_identity=source_identity,
            distribution=_LOUSHANG_DISTRIBUTION,
            source_label=_SOURCE_LABEL,
        )


__all__ = [
    "CoDistributedPluginDependencyGrantResolver",
    "coding_arch_default_plugin_root",
    "coding_lsp_default_plugin_root",
    "coding_plugin_distribution_evidence_resolver",
]
