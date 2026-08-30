"""Private Product policy for same-distribution first-party Plugins."""

from __future__ import annotations

from pathlib import Path

from loushang.harness.resources.packages.materializer import plugin_source_identity
from loushang.harness.resources.plugins.dependency_grants import (
    PluginDependencyGrantError,
)
from loushang.harness.resources.plugins.distribution_evidence import (
    InstalledPythonDistributionEvidenceResolver,
)

_CODING_LSP_PLUGIN_ID = "coding.lsp.default"
_CODING_ARCH_PLUGIN_ID = "coding.arch.default"
_LOUSHANG_DISTRIBUTION = "loushang"


def coding_lsp_default_plugin_root() -> Path:
    """Return the exact checked-in source granted the reserved Plugin id."""

    return (
        Path(__file__).resolve().parent / "_plugins" / "coding_lsp_default"
    ).resolve(strict=True)


def coding_arch_default_plugin_root() -> Path:
    """Return the exact checked-in source granted the reserved Arch Plugin id."""

    return (
        Path(__file__).resolve().parent / "_plugins" / "coding_arch_default"
    ).resolve(strict=True)


def coding_plugin_distribution_evidence_resolver(
) -> InstalledPythonDistributionEvidenceResolver:
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
        identities: dict[str, tuple[str, str]] = {}
        for plugin_id, (source, error_code) in sources.items():
            path = Path(source).expanduser()
            try:
                resolved = path.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise ValueError("Coding Plugin root does not exist") from exc
            if not resolved.is_dir():
                raise ValueError("Coding Plugin root is invalid")
            identities[plugin_id] = (plugin_source_identity(resolved), error_code)
        self._source_identities = identities

    def resolve(
        self,
        *,
        plugin_id: str,
        source_identity: str,
    ) -> tuple[str, ...]:
        expected = self._source_identities.get(plugin_id)
        if expected is None:
            return ()
        expected_identity, error_code = expected
        if source_identity != expected_identity:
            raise PluginDependencyGrantError(
                "The reserved Coding Plugin id came from a foreign source",
                code=error_code,
            )
        return (_LOUSHANG_DISTRIBUTION,)


__all__ = [
    "CoDistributedPluginDependencyGrantResolver",
    "coding_arch_default_plugin_root",
    "coding_lsp_default_plugin_root",
    "coding_plugin_distribution_evidence_resolver",
]
