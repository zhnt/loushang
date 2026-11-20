"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from loushang.coding.package import legacy_lock_evidence as _binding


def parse_binding_heads(
    raw: bytes,
) -> tuple[_binding.CodingLegacyLocalBindingEvidenceV1, ...]:
    """Accept exact v4 local heads; old Store bytes grant no Source authority.

    This proves only the old lock's internal binding selection. The caller must
    separately authenticate the snapshot, installed/desired state, live Source,
    operator decision, and Product transaction before adoption.
    """

    if not isinstance(raw, bytes) or not raw or len(raw) > _binding._MAX_LOCK_BYTES:
        raise _binding.CodingLegacyLockError(
            _binding._LEGACY_EVIDENCE_VALUES["value_001"]
        )
    try:
        document = _binding.json.loads(
            raw.decode("utf-8"), object_pairs_hook=_binding._unique_object
        )
    except (UnicodeError, _binding.json.JSONDecodeError, ValueError) as exc:
        raise _binding.CodingLegacyLockError(
            _binding._LEGACY_EVIDENCE_VALUES["value_004"]
        ) from exc
    if (
        type(document) is not dict
        or set(document) != _binding._TOP_LEVEL_KEYS
        or type(document["version"]) is not int
        or document["version"] != 4
        or not isinstance(document["trustedSources"], list)
        or any(type(value) is not str for value in document["trustedSources"])
        or not isinstance(document["packages"], list)
        or not isinstance(document["pluginBindings"], list)
        or not isinstance(document["pluginBindingHeads"], list)
    ):
        raise _binding.CodingLegacyLockError(
            _binding._LEGACY_EVIDENCE_VALUES["value_002"]
        )
    bindings: dict[str, _binding.PluginSourceBinding] = {}
    for value in document["pluginBindings"]:
        if type(value) is not dict or frozenset(value) not in {
            _binding._BINDING_KEYS,
            _binding._BINDING_KEYS | {"dependencyLock", "dependencyLockDigest"},
        }:
            raise _binding.CodingLegacyLockError(
                _binding._LEGACY_EVIDENCE_VALUES["value_005"]
            )
        binding = _binding._plugin_binding_from_json(value)
        if binding is None:
            raise _binding.CodingLegacyLockError(
                _binding._LEGACY_EVIDENCE_VALUES["value_006"]
            )
        key = _binding._plugin_binding_history_key(binding)
        if key in bindings:
            raise _binding.CodingLegacyLockError(
                _binding._LEGACY_EVIDENCE_VALUES["value_007"]
            )
        bindings[key] = binding
    heads: dict[str, _binding.PluginSourceBinding] = {}
    for value in document["pluginBindingHeads"]:
        if type(value) is not dict or set(value) != {
            "sourceIdentity",
            "historyKey",
        }:
            raise _binding.CodingLegacyLockError(
                _binding._LEGACY_EVIDENCE_VALUES["value_008"]
            )
        source = value["sourceIdentity"]
        key = value["historyKey"]
        if type(source) is not str or type(key) is not str:
            raise _binding.CodingLegacyLockError(
                _binding._LEGACY_EVIDENCE_VALUES["value_009"]
            )
        binding = bindings.get(key)
        if binding is None or binding.source_identity != source or source in heads:
            raise _binding.CodingLegacyLockError(
                _binding._LEGACY_EVIDENCE_VALUES["value_010"]
            )
        heads[source] = binding
    if {binding.source_identity for binding in bindings.values()} != set(heads):
        raise _binding.CodingLegacyLockError(
            _binding._LEGACY_EVIDENCE_VALUES["value_003"]
        )

    selected: list[_binding.CodingLegacyLocalBindingEvidenceV1] = []
    plugin_ids: set[str] = set()
    lockfile_digest = _binding.sha256(raw).hexdigest()
    for source, binding in sorted(heads.items()):
        lock = binding.dependency_lock
        if (
            binding.source_kind != "local"
            or binding.source_identity != f"local:{binding.source}"
            or binding.content_digest is None
            or binding.manifest_digest is None
            or not isinstance(lock, _binding.PluginDependencyClosureLock)
            or lock.python_distributions
            or binding.revision_kind != "content_sha256"
            or binding.revision != binding.content_digest
        ):
            raise _binding.CodingLegacyLockError(
                _binding._LEGACY_EVIDENCE_VALUES["value_011"]
            )
        if binding.plugin_id in plugin_ids:
            raise _binding.CodingLegacyLockError(
                _binding._LEGACY_EVIDENCE_VALUES["value_012"]
            )
        plugin_ids.add(binding.plugin_id)
        selected.append(
            _binding.CodingLegacyLocalBindingEvidenceV1(
                source_identity=source,
                plugin_id=binding.plugin_id,
                content_digest=binding.content_digest,
                manifest_digest=binding.manifest_digest,
                dependency_lock=lock,
                binding_digest=_binding._plugin_binding_history_key(binding),
                lockfile_digest=lockfile_digest,
            )
        )
    return tuple(selected)
