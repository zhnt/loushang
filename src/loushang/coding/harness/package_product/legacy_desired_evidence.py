"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from loushang.coding.package import legacy_desired_evidence as _binding


def parse_desired_evidence(
    raw: bytes, *, lifecycle: _binding.CodingPluginLifecycleStateLayout
) -> _binding.CodingLegacyDesiredEvidenceV1:
    """Decode only a complete committed journal under the old Coding scope."""

    if not isinstance(raw, bytes) or len(raw) > _binding._MAX_DESIRED_BYTES:
        raise _binding.CodingLegacyDesiredError(
            _binding._LEGACY_EVIDENCE_VALUES["value_001"]
        )
    try:
        text = raw.decode("utf-8")
        if text and not text.endswith("\n"):
            raise ValueError(_binding._LEGACY_EVIDENCE_VALUES["value_003"])
        for line in text.splitlines():
            if line.strip():
                _binding.json.loads(line, object_pairs_hook=_binding._unique_object)
        snapshot, transitions = _binding.decode_plugin_desired_state_capture(
            text,
            path=lifecycle.desired_state,
        )
    except (UnicodeError, ValueError, _binding.PluginLifecycleError) as exc:
        raise _binding.CodingLegacyDesiredError(
            _binding._LEGACY_EVIDENCE_VALUES["value_004"]
        ) from exc
    if any(
        state.installation_key.product_id
        != _binding._LEGACY_EVIDENCE_VALUES["value_005"]
        or state.installation_key.installation_scope != "workspace"
        or state.installation_key.scope_id != lifecycle.scope_id
        for state in snapshot.installations
    ):
        raise _binding.CodingLegacyDesiredError(
            _binding._LEGACY_EVIDENCE_VALUES["value_002"]
        )
    return _binding.CodingLegacyDesiredEvidenceV1(
        snapshot=snapshot,
        journal_digest=_binding.sha256(raw).hexdigest(),
        transitions=transitions,
    )
