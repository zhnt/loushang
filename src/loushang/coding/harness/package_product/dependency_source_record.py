"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.package import external_dependency_wheel as _binding


def validate_record(self: _binding.CodingExternalDependencyWheelBindingV1) -> None:
    project_name, version = _binding._wheel_identity(self.wheel_filename)
    if (
        type(self.record_revision) is not int
        or self.record_revision < 1
        or not isinstance(self.store_id, str)
        or not self.store_id
        or not isinstance(self.namespace_id, str)
        or _binding._DIGEST.fullmatch(self.namespace_id) is None
        or not isinstance(self.scope_id, str)
        or not self.scope_id
        or not isinstance(self.original_source, str)
        or not _binding.Path(self.original_source).is_absolute()
        or _binding.os.path.normpath(self.original_source) != self.original_source
        or self.project_name != project_name
        or self.version != version
        or not isinstance(self.artifact_digest, str)
        or _binding._DIGEST.fullmatch(self.artifact_digest) is None
        or not isinstance(self.record_id, str)
        or _binding._DIGEST.fullmatch(self.record_id) is None
    ):
        raise ValueError(_binding._LIFECYCLE_PROGRAM_VALUES["value_001"])
    if (
        self.record_id
        != _binding.sha256(_binding.canonical_json_bytes(self._identity())).hexdigest()
    ):
        raise ValueError(_binding._LIFECYCLE_PROGRAM_VALUES["value_002"])


def create_record(
    cls: type[_binding.CodingExternalDependencyWheelBindingV1],
    *,
    record_revision: int,
    store_id: str,
    namespace_id: str,
    scope_id: str,
    original_source: str,
    wheel_filename: str,
    artifact_digest: str,
) -> _binding.CodingExternalDependencyWheelBindingV1:
    project_name, version = _binding._wheel_identity(wheel_filename)
    fields = {
        "recordRevision": record_revision,
        "storeId": store_id,
        "namespaceId": namespace_id,
        "scopeId": scope_id,
        "originalSource": original_source,
        "wheelFilename": wheel_filename,
        "projectName": project_name,
        "version": version,
        "artifactDigest": artifact_digest,
    }
    return cls(
        record_revision=record_revision,
        store_id=store_id,
        namespace_id=namespace_id,
        scope_id=scope_id,
        original_source=original_source,
        wheel_filename=wheel_filename,
        project_name=project_name,
        version=version,
        artifact_digest=artifact_digest,
        record_id=_binding.sha256(_binding.canonical_json_bytes(fields)).hexdigest(),
    )


def wheel_identity(filename: str) -> tuple[str, str]:
    if (
        not isinstance(filename, str)
        or len(filename) > _binding._MAX_WHEEL_FILENAME
        or _binding._WHEEL_FILENAME.fullmatch(filename) is None
    ):
        raise ValueError(_binding._LIFECYCLE_PROGRAM_VALUES["wheel_filename_invalid"])
    try:
        project_name, version, _build, _tags = _binding.parse_wheel_filename(filename)
    except _binding.InvalidWheelFilename as exc:
        raise ValueError(
            _binding._LIFECYCLE_PROGRAM_VALUES["wheel_filename_invalid"]
        ) from exc
    return (project_name, str(version))
