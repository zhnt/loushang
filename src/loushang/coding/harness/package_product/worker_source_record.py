"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.package import external_worker_wheel as _binding


def validate_record(self: _binding.CodingExternalWorkerWheelBindingV1) -> None:
    if (
        not isinstance(self.store_id, str)
        or not isinstance(self.namespace_id, str)
        or not isinstance(self.scope_id, str)
        or not isinstance(self.original_source, str)
        or not isinstance(self.wheel_filename, str)
        or not isinstance(self.plugin_id, str)
        or not isinstance(self.version, str)
        or not isinstance(self.artifact_digest, str)
        or not isinstance(self.record_id, str)
    ):
        raise ValueError(_binding._LIFECYCLE_PROGRAM_VALUES["value_001"])
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
        or not isinstance(self.admission, _binding.PackageProductLocalWorkerAdmissionV1)
        or self.admission.native_platform
        != (
            "windows-amd64"
            if match is not None and match["tag"] == "win_amd64"
            else "linux-x86_64"
        )
        or _binding._DIGEST.fullmatch(self.record_id) is None
    ):
        raise ValueError(_binding._LIFECYCLE_PROGRAM_VALUES["value_002"])
    if (
        self.record_id
        != _binding.sha256(_binding.canonical_json_bytes(self._identity())).hexdigest()
    ):
        raise ValueError(_binding._LIFECYCLE_PROGRAM_VALUES["value_003"])


def create_record(
    cls: type[_binding.CodingExternalWorkerWheelBindingV1],
    *,
    record_revision: int,
    store_id: str,
    namespace_id: str,
    scope_id: str,
    original_source: str,
    wheel_filename: str,
    artifact_digest: str,
    admission: _binding.PackageProductLocalWorkerAdmissionV1,
) -> _binding.CodingExternalWorkerWheelBindingV1:
    match = _binding._WHEEL_NAME.fullmatch(wheel_filename)
    if match is None:
        raise ValueError(_binding._LIFECYCLE_PROGRAM_VALUES["value_004"])
    fields = {
        "admission": {
            "contributionId": admission.contribution_id,
            "nativePlatform": admission.native_platform,
            "ownerId": admission.owner_id,
        },
        "artifactDigest": artifact_digest,
        "namespaceId": namespace_id,
        "originalSource": original_source,
        "pluginId": match["plugin"],
        "recordRevision": record_revision,
        "scopeId": scope_id,
        "storeId": store_id,
        "version": match["version"],
        "wheelFilename": wheel_filename,
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
        admission=admission,
        record_id=_binding.sha256(_binding.canonical_json_bytes(fields)).hexdigest(),
    )


def encode_record(
    self: _binding.CodingExternalWorkerWheelBindingV1,
) -> dict[str, object]:
    return {
        "admission": {
            "contributionId": self.admission.contribution_id,
            "nativePlatform": self.admission.native_platform,
            "ownerId": self.admission.owner_id,
        },
        "artifactDigest": self.artifact_digest,
        "namespaceId": self.namespace_id,
        "originalSource": self.original_source,
        "pluginId": self.plugin_id,
        "recordId": self.record_id,
        "recordRevision": self.record_revision,
        "scopeId": self.scope_id,
        "storeId": self.store_id,
        "version": self.version,
        "wheelFilename": self.wheel_filename,
    }


def decode_record(
    cls: type[_binding.CodingExternalWorkerWheelBindingV1], value: object
) -> _binding.CodingExternalWorkerWheelBindingV1:
    keys = {
        "admission",
        "artifactDigest",
        "namespaceId",
        "originalSource",
        "pluginId",
        "recordId",
        "recordRevision",
        "scopeId",
        "storeId",
        "version",
        "wheelFilename",
    }
    if type(value) is not dict or set(value) != keys:
        raise ValueError(_binding._LIFECYCLE_PROGRAM_VALUES["value_005"])
    admission = value["admission"]
    if type(admission) is not dict or set(admission) != {
        "contributionId",
        "nativePlatform",
        "ownerId",
    }:
        raise ValueError(_binding._LIFECYCLE_PROGRAM_VALUES["value_006"])
    return cls(
        record_revision=value["recordRevision"],
        store_id=value["storeId"],
        namespace_id=value["namespaceId"],
        scope_id=value["scopeId"],
        original_source=value["originalSource"],
        wheel_filename=value["wheelFilename"],
        plugin_id=value["pluginId"],
        version=value["version"],
        artifact_digest=value["artifactDigest"],
        admission=_binding.PackageProductLocalWorkerAdmissionV1(
            contribution_id=admission["contributionId"],
            owner_id=admission["ownerId"],
            native_platform=admission["nativePlatform"],
        ),
        record_id=value["recordId"],
    )
