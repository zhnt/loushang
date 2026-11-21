"""Resolve exact source grants through the original Package source identity."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from loushang.harness.resources.packages.materializer import plugin_source_identity
from loushang.harness.resources.plugins.dependency_grants import (
    PluginDependencyGrantError,
)


def collect_source_identities(
    sources: Mapping[str, tuple[str | Path, str]], *, source_label: str
) -> dict[str, tuple[str, str]]:
    """Observe the declared roots in their original order before issuing grants."""
    identities: dict[str, tuple[str, str]] = {}
    for plugin_id, (source, error_code) in sources.items():
        path = Path(source).expanduser()
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise ValueError(f"{source_label} root does not exist") from error
        if not resolved.is_dir():
            raise ValueError(f"{source_label} root is invalid")
        identities[plugin_id] = (plugin_source_identity(resolved), error_code)
    return identities


def resolve_exact_source_grant(
    identities: Mapping[str, tuple[str, str]],
    *,
    plugin_id: str,
    source_identity: str,
    distribution: str,
    source_label: str,
) -> tuple[str, ...]:
    """Grant the Product-declared distribution for the exact original source."""
    expected = identities.get(plugin_id)
    if expected is None:
        return ()
    expected_identity, error_code = expected
    if source_identity != expected_identity:
        raise PluginDependencyGrantError(
            f"The reserved {source_label} id came from a foreign source",
            code=error_code,
        )
    return (distribution,)
