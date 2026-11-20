"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from loushang.coding.package import legacy_source_evidence as _binding


def parse_source_evidence(
    raw: bytes,
    *,
    global_settings_path: _binding.Path,
    project_settings_path: _binding.Path,
) -> _binding.CodingLegacySourceEvidenceV1:
    """Validate the exact settings paths and source patches frozen at cutover."""

    if (
        not isinstance(raw, bytes)
        or not raw
        or len(raw) > _binding._MAX_PROJECTION_BYTES
    ):
        raise _binding.CodingLegacySourceEvidenceError(
            _binding._LEGACY_EVIDENCE_VALUES["value_001"]
        )
    for path in (global_settings_path, project_settings_path):
        if (
            not isinstance(path, _binding.Path)
            or not path.is_absolute()
            or ".." in path.parts
        ):
            raise _binding.CodingLegacySourceEvidenceError(
                _binding._LEGACY_EVIDENCE_VALUES["value_003"]
            )
    if global_settings_path == project_settings_path:
        raise _binding.CodingLegacySourceEvidenceError(
            _binding._LEGACY_EVIDENCE_VALUES["value_002"]
        )
    try:
        projection = _binding.json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_binding._unique_object,
            parse_constant=_binding._reject_non_json_constant,
        )
        classification = _binding.classify_coding_legacy_source_configuration(
            projection
        )
        if type(projection) is not dict:
            raise ValueError(_binding._LEGACY_EVIDENCE_VALUES["value_004"])
        scopes = projection["scopes"]
        if scopes["global"]["settingsPath"] != str(global_settings_path) or scopes[
            "project"
        ]["settingsPath"] != str(project_settings_path):
            raise ValueError(_binding._LEGACY_EVIDENCE_VALUES["value_005"])
        canonical = _binding.json.dumps(
            projection,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if raw != canonical:
            raise ValueError(_binding._LEGACY_EVIDENCE_VALUES["value_006"])
    except (UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise _binding.CodingLegacySourceEvidenceError(
            _binding._LEGACY_EVIDENCE_VALUES["value_007"]
        ) from exc
    return _binding.CodingLegacySourceEvidenceV1(
        projection_bytes=raw,
        classification=classification,
        projection_digest=_binding.sha256(raw).hexdigest(),
    )
