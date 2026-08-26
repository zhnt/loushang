"""Private Product policy for same-distribution first-party Plugins."""

from __future__ import annotations

from pathlib import Path

from loushang.harness.resources.packages.materializer import plugin_source_identity
from loushang.harness.resources.plugins.dependency_grants import (
    PluginDependencyGrantError,
)

_CODING_LSP_PLUGIN_ID = "coding.lsp.default"
_LOUSHANG_DISTRIBUTION = "loushang"


class CoDistributedPluginDependencyGrantResolver:
    """Recognize only Coding's exact checked-in LSP Plugin source."""

    def __init__(self, *, coding_lsp_source: str | Path) -> None:
        source = Path(coding_lsp_source).expanduser()
        try:
            resolved = source.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("Coding LSP Plugin root does not exist") from exc
        if not resolved.is_dir():
            raise ValueError("Coding LSP Plugin root is invalid")
        self._coding_lsp_source_identity = plugin_source_identity(resolved)

    def resolve(
        self,
        *,
        plugin_id: str,
        source_identity: str,
    ) -> tuple[str, ...]:
        if plugin_id != _CODING_LSP_PLUGIN_ID:
            return ()
        if source_identity != self._coding_lsp_source_identity:
            raise PluginDependencyGrantError(
                "The reserved Coding LSP Plugin id came from a foreign source",
                code="coding_lsp_plugin_source_mismatch",
            )
        return (_LOUSHANG_DISTRIBUTION,)


__all__ = ["CoDistributedPluginDependencyGrantResolver"]
