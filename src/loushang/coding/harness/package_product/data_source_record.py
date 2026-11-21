"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.package import external_data_wheel as _binding


def validate_record(self: _binding.CodingExternalDataWheelBindingV1) -> None:
    match = _binding._WHEEL_NAME.fullmatch(self.wheel_filename)
    if (
        type(self.record_revision) is not int
        or self.record_revision < 1
        or not self.store_id
        or _binding._DIGEST.fullmatch(self.namespace_id) is None
        or not self.scope_id
        or not _binding.Path(self.original_source).is_absolute()
        or _binding.os.path.normpath(self.original_source) != self.original_source
        or match is None
        or len(self.wheel_filename) > _binding._MAX_WHEEL_FILENAME
        or self.plugin_id != match["plugin"]
        or self.version != match["version"]
        or _binding._DIGEST.fullmatch(self.artifact_digest) is None
        or _binding._DIGEST.fullmatch(self.record_id) is None
    ):
        raise ValueError(_binding._LIFECYCLE_PROGRAM_VALUES["value_001"])
    if (
        self.record_id
        != _binding.sha256(_binding.canonical_json_bytes(self._identity())).hexdigest()
    ):
        raise ValueError(_binding._LIFECYCLE_PROGRAM_VALUES["value_002"])


def create_record(
    cls: type[_binding.CodingExternalDataWheelBindingV1],
    *,
    record_revision: int,
    store_id: str,
    namespace_id: str,
    scope_id: str,
    original_source: str,
    wheel_filename: str,
    artifact_digest: str,
) -> _binding.CodingExternalDataWheelBindingV1:
    match = _binding._WHEEL_NAME.fullmatch(wheel_filename)
    if match is None:
        raise ValueError(_binding._LIFECYCLE_PROGRAM_VALUES["value_003"])
    fields = {
        "recordRevision": record_revision,
        "storeId": store_id,
        "namespaceId": namespace_id,
        "scopeId": scope_id,
        "originalSource": original_source,
        "wheelFilename": wheel_filename,
        "pluginId": match["plugin"],
        "version": match["version"],
        "artifactDigest": artifact_digest,
    }
    return cls(
        record_revision=record_revision,
        store_id=store_id,
        namespace_id=namespace_id,
        scope_id=scope_id,
        original_source=original_source,
        wheel_filename=wheel_filename,
        plugin_id=match["plugin"],
        version=match["version"],
        artifact_digest=artifact_digest,
        record_id=_binding.sha256(_binding.canonical_json_bytes(fields)).hexdigest(),
    )
