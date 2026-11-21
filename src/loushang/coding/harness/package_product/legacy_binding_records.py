"""Legacy record admission and decoding over original nominal values."""

from __future__ import annotations

from typing import Literal

from loushang.coding.package import legacy_binding_catalog as _binding


def validate_binding(self: _binding.CodingLegacyLocalBindingV1) -> None:
    if type(self.record_revision) is not int or self.record_revision < 1:
        raise ValueError("Legacy Product binding revision is invalid")
    for value, name in (
        (self.store_id, "Store"),
        (self.scope_id, "scope"),
        (self.plugin_id, "Plugin"),
        (self.policy_revision, "policy"),
        (self.approval_id, "approval"),
    ):
        if not isinstance(value, str) or _binding._SAFE_ID.fullmatch(value) is None:
            raise ValueError(f"Legacy Product {name} identity is invalid")
    if self.plugin_id in _binding._BUILTIN_PLUGIN_IDS:
        raise ValueError("Legacy Product binding cannot replace a builtin Plugin")
    for value, name in (
        (self.namespace_id, "namespace"),
        (self.legacy_binding_digest, "old binding"),
        (self.source_content_digest, "Source content"),
        (self.manifest_digest, "manifest"),
        (self.dependency_lock_digest, "dependency lock"),
        (self.artifact_digest, "Wheel artifact"),
        (self.record_id, "record"),
    ):
        if not isinstance(value, str) or _binding._SHA256.fullmatch(value) is None:
            raise ValueError(f"Legacy Product {name} digest is invalid")
    if (
        not isinstance(self.legacy_source_identity, str)
        or not self.legacy_source_identity.startswith("local:")
        or len(self.legacy_source_identity) > 4096
        or _binding._WHEEL_FILENAME.fullmatch(self.wheel_filename) is None
        or type(self.record_version) is not int
        or (self.record_version, self.resource_kind)
        not in {
            (1, _binding._LEGACY_RECORD_SKILL),
            (2, _binding._LEGACY_RECORD_PROMPT),
            (3, _binding._LEGACY_RECORD_THEME),
        }
    ):
        raise ValueError("Legacy Product binding Source shape is invalid")
    prefix = self.wheel_filename.removesuffix("-1-py3-none-any.whl")
    if (
        self.requested_package != f"{prefix.replace('_', '-')}==1"
        or self.plugin_manifest_path != f"{prefix}/plugin.json"
    ):
        raise ValueError("Legacy Product binding Wheel identity is inconsistent")
    binding = self.to_policy_binding(_binding.Path("/"))
    if binding.requested_package != self.requested_package:
        raise ValueError("Legacy Product binding package is invalid")
    if (
        self.record_id
        != _binding.sha256(_binding.canonical_json_bytes(self._identity())).hexdigest()
    ):
        raise ValueError("Legacy Product binding record identity is invalid")


def create_binding(
    cls: type[_binding.CodingLegacyLocalBindingV1],
    *,
    record_revision: int,
    store_id: str,
    namespace_id: str,
    scope_id: str,
    legacy_source_identity: str,
    legacy_binding_digest: str,
    dependency_lock_digest: str,
    policy_revision: str,
    approval_id: str,
    candidate: _binding.CodingLegacyLocalWheelCandidateV1,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> _binding.CodingLegacyLocalBindingV1:
    if not isinstance(candidate, _binding.CodingLegacyLocalWheelCandidateV1):
        raise TypeError("Reacquired legacy Wheel candidate is required")
    if legacy_source_identity != candidate.original_source_identity:
        raise ValueError("Legacy Product original Source identity changed")
    if resource_kind not in {
        _binding._LEGACY_RECORD_SKILL,
        _binding._LEGACY_RECORD_PROMPT,
        _binding._LEGACY_RECORD_THEME,
    }:
        raise ValueError("Unsupported legacy Product Resource type")
    record_version = {
        _binding._LEGACY_RECORD_SKILL: 1,
        _binding._LEGACY_RECORD_PROMPT: 2,
        _binding._LEGACY_RECORD_THEME: 3,
    }[resource_kind]
    values = {
        "recordRevision": record_revision,
        "storeId": store_id,
        "namespaceId": namespace_id,
        "scopeId": scope_id,
        "pluginId": candidate.plugin_id,
        "legacySourceIdentity": legacy_source_identity,
        "legacyBindingDigest": legacy_binding_digest,
        "sourceContentDigest": candidate.source_content_digest,
        "manifestDigest": candidate.manifest_digest,
        "dependencyLockDigest": dependency_lock_digest,
        "wheelFilename": candidate.filename,
        "artifactDigest": candidate.artifact_digest,
        "requestedPackage": candidate.requested_package,
        "pluginManifestPath": candidate.plugin_manifest_path,
        "policyRevision": policy_revision,
        "approvalId": approval_id,
        "recordVersion": record_version,
    }
    if record_version >= 2:
        values["resourceKind"] = resource_kind
    return cls(
        record_revision=record_revision,
        store_id=store_id,
        namespace_id=namespace_id,
        scope_id=scope_id,
        plugin_id=candidate.plugin_id,
        legacy_source_identity=legacy_source_identity,
        legacy_binding_digest=legacy_binding_digest,
        source_content_digest=candidate.source_content_digest,
        manifest_digest=candidate.manifest_digest,
        dependency_lock_digest=dependency_lock_digest,
        wheel_filename=candidate.filename,
        artifact_digest=candidate.artifact_digest,
        requested_package=candidate.requested_package,
        plugin_manifest_path=candidate.plugin_manifest_path,
        policy_revision=policy_revision,
        approval_id=approval_id,
        record_id=_binding.sha256(_binding.canonical_json_bytes(values)).hexdigest(),
        record_version=record_version,
        resource_kind=resource_kind,
    )


def decode_binding(
    cls: type[_binding.CodingLegacyLocalBindingV1], value: object
) -> _binding.CodingLegacyLocalBindingV1:
    expected = _binding._BINDING_SCHEMA.keys
    if type(value) is not dict or set(value) not in (
        expected,
        expected | {"resourceKind"},
    ):
        raise _binding.JournalCodecError(
            _binding._LEGACY_RECORD_VALUES["value_001"],
            code=_binding._LEGACY_RECORD_VALUES["value_002"],
        )
    try:
        if type(value["recordVersion"]) is not int:
            raise ValueError("Unsupported legacy Product binding version")
        if value["recordVersion"] == 1 and "resourceKind" not in value:
            resource_kind: Literal["skill", "prompt", "theme"] = (
                _binding._LEGACY_RECORD_SKILL
            )
        elif (
            value["recordVersion"] == 2
            and value.get("resourceKind") == _binding._LEGACY_RECORD_PROMPT
        ):
            resource_kind = _binding._LEGACY_RECORD_PROMPT
        elif (
            value["recordVersion"] == 3
            and value.get("resourceKind") == _binding._LEGACY_RECORD_THEME
        ):
            resource_kind = _binding._LEGACY_RECORD_THEME
        else:
            raise ValueError("Unsupported legacy Product binding type")
        return cls(
            **_binding._BINDING_SCHEMA.decode(dict, value), resource_kind=resource_kind
        )
    except (TypeError, ValueError) as exc:
        raise _binding.JournalCodecError(
            _binding._LEGACY_RECORD_VALUES["value_001"],
            code=_binding._LEGACY_RECORD_VALUES["value_002"],
        ) from exc


def require_accepted_binding(
    self: _binding.CodingLegacyLocalBindingCatalog,
    record: _binding.CodingLegacyLocalBindingV1,
) -> None:
    if self._acceptance_reader is None:
        raise _binding.CodingLegacyBindingError(
            "Legacy Product binding has no acceptance owner"
        )
    accepted = self._acceptance_reader(record.plugin_id)
    if not isinstance(accepted, _binding.CodingLegacyLocalAcceptanceV1):
        raise _binding.CodingLegacyBindingError(
            "Legacy Product binding has no accepted review"
        )
    review = accepted.review
    prefix = record.wheel_filename.removesuffix("-1-py3-none-any.whl")
    if (
        record.approval_id != accepted.acceptance_id
        or record.resource_kind != accepted.resource_kind
        or record.store_id != review.store_id
        or record.namespace_id != review.namespace_id
        or record.scope_id != review.scope_id
        or record.plugin_id != review.plugin_id
        or record.legacy_source_identity != review.legacy_source_identity
        or record.legacy_binding_digest != review.legacy_binding_digest
        or record.source_content_digest != review.source_content_digest
        or record.manifest_digest != review.manifest_digest
        or record.dependency_lock_digest != review.dependency_lock_digest
        or record.wheel_filename != review.wheel_filename
        or record.artifact_digest != review.wheel_artifact_digest
        or record.requested_package != f"{prefix.replace('_', '-')}==1"
        or record.plugin_manifest_path != f"{prefix}/plugin.json"
        or record.policy_revision != review.policy_revision
    ):
        raise _binding.CodingLegacyBindingError(
            "Legacy Product binding differs from accepted review"
        )
