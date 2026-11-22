"""Read exact legacy lock binding heads through the existing Package codec."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import NamedTuple

from loushang.foundation.json import _unique_json_object_hook
from loushang.harness.resources.packages.materializer import (
    _plugin_binding_from_json,
    _plugin_binding_history_key,
)
from loushang.harness.resources.plugins.dependencies import PluginDependencyClosureLock
from loushang.harness.resources.plugins.types import PluginSourceBinding

LEGACY_BINDING_CAPTURE_MAX_BYTES = 2 * 1024 * 1024

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


class LegacyLocalBindingEvidence(NamedTuple):
    source_identity: str
    plugin_id: str
    content_digest: str
    manifest_digest: str
    dependency_lock: PluginDependencyClosureLock
    binding_digest: str
    lockfile_digest: str


def decode_legacy_local_binding_heads(
    raw: bytes, *, maximum_bytes: int, error_type: type[ValueError], label: str
) -> tuple[LegacyLocalBindingEvidence, ...]:
    """Accept exact v4 local heads; old Store bytes grant no Source authority.

    This proves only the old lock's internal binding selection. The caller must
    separately authenticate the snapshot, installed/desired state, live Source,
    operator decision, and Product transaction before adoption.
    """

    if not isinstance(raw, bytes) or not raw or len(raw) > maximum_bytes:
        raise error_type(f"{label} Package lock exceeds budget")
    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_json_object_hook(
                lambda: f"{label} Package lock has duplicate JSON keys"
            ),
        )
    except (UnicodeError, ValueError) as exc:
        raise error_type(f"{label} Package lock is invalid JSON") from exc
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
        raise error_type(f"{label} Package lock version is unsupported")
    bindings: dict[str, PluginSourceBinding] = {}
    for value in document["pluginBindings"]:
        if type(value) is not dict or frozenset(value) not in {
            _BINDING_KEYS,
            _BINDING_KEYS | {"dependencyLock", "dependencyLockDigest"},
        }:
            raise error_type(f"{label} Plugin binding is malformed")
        binding = _plugin_binding_from_json(value)
        if binding is None:
            raise error_type(f"{label} Plugin binding is invalid")
        key = _plugin_binding_history_key(binding)
        if key in bindings:
            raise error_type(f"{label} Plugin binding is duplicated")
        bindings[key] = binding
    heads: dict[str, PluginSourceBinding] = {}
    for value in document["pluginBindingHeads"]:
        if type(value) is not dict or set(value) != {
            "sourceIdentity",
            "historyKey",
        }:
            raise error_type(f"{label} Plugin head is malformed")
        source = value["sourceIdentity"]
        key = value["historyKey"]
        if type(source) is not str or type(key) is not str:
            raise error_type(f"{label} Plugin head is invalid")
        binding = bindings.get(key)
        if binding is None or binding.source_identity != source or source in heads:
            raise error_type(f"{label} Plugin head is ambiguous")
        heads[source] = binding
    if {binding.source_identity for binding in bindings.values()} != set(heads):
        raise error_type(f"{label} Plugin history lacks a head")

    selected: list[LegacyLocalBindingEvidence] = []
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
            raise error_type(
                f"{label} Plugin Source kind or dependency closure is unsupported"
            )
        if binding.plugin_id in plugin_ids:
            raise error_type(f"{label} Plugin identity is ambiguous")
        plugin_ids.add(binding.plugin_id)
        selected.append(
            LegacyLocalBindingEvidence(
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
