"""Strictly classify current pre-B Package binding heads from snapshot bytes."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product._legacy_binding_evidence import (
    decode_legacy_local_binding_heads,
)
from loushang.harness.resources.plugins.dependencies import PluginDependencyClosureLock

from .legacy_snapshot_member import (
    CodingFencedEpochRuntime,
    read_coding_first_b_snapshot_member,
)

_MAX_LOCK_BYTES = 2 * 1024 * 1024


class CodingLegacyLockError(ValueError):
    """Old Package lock evidence is ambiguous or unsupported for migration."""


@dataclass(frozen=True, slots=True)
class CodingLegacyLocalBindingEvidenceV1:
    source_identity: str
    plugin_id: str
    content_digest: str
    manifest_digest: str
    dependency_lock: PluginDependencyClosureLock
    binding_digest: str
    lockfile_digest: str


def read_coding_legacy_local_binding_heads(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: CodingFencedEpochRuntime,
) -> tuple[CodingLegacyLocalBindingEvidenceV1, ...]:
    """Project only exact first-fence snapshot binding heads for later review."""

    raw = read_coding_first_b_snapshot_member(
        lifecycle,
        epoch_runtime,
        domain="binding_history",
        member_name="package-lock.json",
        maximum_bytes=_MAX_LOCK_BYTES,
    )
    if raw is None:
        raise CodingLegacyLockError("Coding legacy Package binding lock is missing")
    return parse_coding_legacy_local_binding_heads(raw)


def parse_coding_legacy_local_binding_heads(
    raw: bytes,
) -> tuple[CodingLegacyLocalBindingEvidenceV1, ...]:
    """Accept exact v4 local heads; old Store bytes grant no Source authority.

    This proves only the old lock's internal binding selection. The caller must
    separately authenticate the snapshot, installed/desired state, live Source,
    operator decision, and Product transaction before adoption.
    """

    return tuple(
        CodingLegacyLocalBindingEvidenceV1(*evidence)
        for evidence in decode_legacy_local_binding_heads(
            raw,
            maximum_bytes=_MAX_LOCK_BYTES,
            error_type=CodingLegacyLockError,
            label="Coding legacy",
        )
    )


__all__ = [
    "CodingLegacyLocalBindingEvidenceV1",
    "CodingLegacyLockError",
    "parse_coding_legacy_local_binding_heads",
    "read_coding_legacy_local_binding_heads",
]
