"""Strictly classify current pre-B Package binding heads from snapshot bytes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.resources.packages.materializer import (
    _plugin_binding_from_json,
    _plugin_binding_history_key,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_snapshot import (
    PackagePosixEpochSnapshotEvidenceStore,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.plugins.dependencies import (
    PluginDependencyClosureLock,
)
from loushang.harness.resources.plugins.types import PluginSourceBinding

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout

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
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
) -> tuple[CodingLegacyLocalBindingEvidenceV1, ...]:
    """Project only exact first-fence snapshot binding heads for later review."""

    if not isinstance(lifecycle, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding Plugin lifecycle layout is required")
    if not isinstance(epoch_runtime, PackageProductPosixFencedRuntimeOwner):
        raise TypeError("Fenced Product epoch owner is required")
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    epoch_runtime.assert_current()
    fence = epoch_runtime.cutover_result.fence
    if (
        epoch_runtime.registry.store_id != epoch.store_id
        or epoch_runtime.control_root != epoch.control_root
        or fence is None
        or fence.store_id != epoch.store_id
        or fence.epoch != 1
        or fence.request.prior_epoch != 0
    ):
        raise CodingLegacyLockError("Coding legacy Package first fence is unsupported")
    snapshots = PackagePosixEpochSnapshotEvidenceStore(
        epoch.snapshot_root, store_id=epoch.store_id
    )
    receipt_id = fence.request.snapshot_receipt_id
    evidence = snapshots.snapshot(receipt_id)
    if (
        evidence is None
        or evidence.snapshot.receipt_id != receipt_id
        or evidence.snapshot.legacy_root_identity != fence.request.legacy_root_identity
    ):
        raise CodingLegacyLockError("Coding legacy Package snapshot is unavailable")
    raw = snapshots.read_regular_member(
        receipt_id,
        domain="binding_history",
        member_name="package-lock.json",
        maximum_bytes=_MAX_LOCK_BYTES,
    )
    epoch_runtime.assert_current()
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

    if not isinstance(raw, bytes) or not raw or len(raw) > _MAX_LOCK_BYTES:
        raise CodingLegacyLockError("Coding legacy Package lock exceeds budget")
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise CodingLegacyLockError(
            "Coding legacy Package lock is invalid JSON"
        ) from exc
    if (
        type(document) is not dict
        or set(document) != _TOP_LEVEL_KEYS
        or type(document["version"]) is not int
        or document["version"] != 4
        or not isinstance(document["trustedSources"], list)
        or any(type(value) is not str for value in document["trustedSources"])
        or not isinstance(document["packages"], list)
        or not isinstance(document["pluginBindings"], list)
        or not isinstance(document["pluginBindingHeads"], list)
    ):
        raise CodingLegacyLockError("Coding legacy Package lock version is unsupported")
    bindings: dict[str, PluginSourceBinding] = {}
    for value in document["pluginBindings"]:
        if type(value) is not dict or frozenset(value) not in {
            _BINDING_KEYS,
            _BINDING_KEYS | {"dependencyLock", "dependencyLockDigest"},
        }:
            raise CodingLegacyLockError("Coding legacy Plugin binding is malformed")
        binding = _plugin_binding_from_json(value)
        if binding is None:
            raise CodingLegacyLockError("Coding legacy Plugin binding is invalid")
        key = _plugin_binding_history_key(binding)
        if key in bindings:
            raise CodingLegacyLockError("Coding legacy Plugin binding is duplicated")
        bindings[key] = binding
    heads: dict[str, PluginSourceBinding] = {}
    for value in document["pluginBindingHeads"]:
        if type(value) is not dict or set(value) != {
            "sourceIdentity",
            "historyKey",
        }:
            raise CodingLegacyLockError("Coding legacy Plugin head is malformed")
        source = value["sourceIdentity"]
        key = value["historyKey"]
        if type(source) is not str or type(key) is not str:
            raise CodingLegacyLockError("Coding legacy Plugin head is invalid")
        binding = bindings.get(key)
        if binding is None or binding.source_identity != source or source in heads:
            raise CodingLegacyLockError("Coding legacy Plugin head is ambiguous")
        heads[source] = binding
    if {binding.source_identity for binding in bindings.values()} != set(heads):
        raise CodingLegacyLockError("Coding legacy Plugin history lacks a head")

    selected: list[CodingLegacyLocalBindingEvidenceV1] = []
    plugin_ids: set[str] = set()
    lockfile_digest = sha256(raw).hexdigest()
    for source, binding in sorted(heads.items()):
        lock = binding.dependency_lock
        if (
            binding.source_kind != "local"
            or binding.source_identity != f"local:{binding.source}"
            or binding.content_digest is None
            or binding.manifest_digest is None
            or not isinstance(lock, PluginDependencyClosureLock)
            or lock.python_distributions
            or binding.revision_kind != "content_sha256"
            or binding.revision != binding.content_digest
        ):
            raise CodingLegacyLockError(
                "Coding legacy Plugin Source kind or dependency closure is unsupported"
            )
        if binding.plugin_id in plugin_ids:
            raise CodingLegacyLockError("Coding legacy Plugin identity is ambiguous")
        plugin_ids.add(binding.plugin_id)
        selected.append(
            CodingLegacyLocalBindingEvidenceV1(
                source_identity=source,
                plugin_id=binding.plugin_id,
                content_digest=binding.content_digest,
                manifest_digest=binding.manifest_digest,
                dependency_lock=lock,
                binding_digest=_plugin_binding_history_key(binding),
                lockfile_digest=lockfile_digest,
            )
        )
    return tuple(selected)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Coding legacy Package lock has duplicate JSON keys")
        result[key] = value
    return result


__all__ = [
    "CodingLegacyLocalBindingEvidenceV1",
    "CodingLegacyLockError",
    "parse_coding_legacy_local_binding_heads",
    "read_coding_legacy_local_binding_heads",
]
