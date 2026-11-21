"""Strictly classify current pre-B Package binding heads from snapshot bytes."""

from __future__ import annotations

import json as json
from dataclasses import dataclass
from hashlib import sha256 as sha256

from loushang.coding.harness.package_product import legacy_binding_evidence as _programs
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.foundation.json import _unique_json_object_hook
from loushang.harness.resources.packages.materializer import (
    _plugin_binding_from_json as _plugin_binding_from_json,
)
from loushang.harness.resources.packages.materializer import (
    _plugin_binding_history_key as _plugin_binding_history_key,
)
from loushang.harness.resources.plugins.dependencies import (
    PluginDependencyClosureLock,
)
from loushang.harness.resources.plugins.types import (
    PluginSourceBinding as PluginSourceBinding,
)

from .legacy_snapshot_member import (
    CodingFencedEpochRuntime,
    read_coding_first_b_snapshot_member,
)

_MAX_LOCK_BYTES = 2 * 1024 * 1024
_TOP_LEVEL_KEYS = frozenset(
    {"version", "trustedSources", "packages", "pluginBindings", "pluginBindingHeads"}
)
_BINDING_KEYS = frozenset(
    {
        "source",
        "sourceIdentity",
        "sourceKind",
        "pluginId",
        "manifestDigest",
        "contentDigest",
        "revision",
        "revisionKind",
    }
)


_LEGACY_EVIDENCE_VALUES = {
    "value_001": "Coding legacy Package lock exceeds budget",
    "value_002": "Coding legacy Package lock version is unsupported",
    "value_003": "Coding legacy Plugin history lacks a head",
    "value_004": "Coding legacy Package lock is invalid JSON",
    "value_005": "Coding legacy Plugin binding is malformed",
    "value_006": "Coding legacy Plugin binding is invalid",
    "value_007": "Coding legacy Plugin binding is duplicated",
    "value_008": "Coding legacy Plugin head is malformed",
    "value_009": "Coding legacy Plugin head is invalid",
    "value_010": "Coding legacy Plugin head is ambiguous",
    "value_011": "Coding legacy Plugin Source kind or dependency closure is unsupported",
    "value_012": "Coding legacy Plugin identity is ambiguous",
}


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

    return _programs.parse_binding_heads(raw)


_unique_object = _unique_json_object_hook(
    lambda: "Coding legacy Package lock has duplicate JSON keys",
)


__all__ = [
    "CodingLegacyLocalBindingEvidenceV1",
    "CodingLegacyLockError",
    "parse_coding_legacy_local_binding_heads",
    "read_coding_legacy_local_binding_heads",
]
