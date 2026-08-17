from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from loushang.harness.diagnostics.types import DiagnosticDraft

_EMPTY_METADATA: Mapping[str, object] = MappingProxyType({})


def resource_diagnostic(
    *,
    code: str,
    message: str,
    source_path: Path | None = None,
    resource_id: str | None = None,
    resource_type: str | None = None,
    source_kind: str | None = None,
    metadata: Mapping[str, object] = _EMPTY_METADATA,
) -> DiagnosticDraft:
    """Create a neutral draft carrying resource-specific diagnostic details."""

    details: dict[str, object] = {}
    if resource_id:
        details["resource_id"] = resource_id
    if resource_type:
        details["resource_type"] = resource_type
    if source_kind:
        details["source_kind"] = source_kind
    if metadata:
        details["metadata"] = dict(metadata)
    return DiagnosticDraft(
        code=code,
        message=message,
        source_path=source_path,
        details=details,
    )


__all__ = ["resource_diagnostic"]
