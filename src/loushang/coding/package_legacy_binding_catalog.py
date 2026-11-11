"""Dark, durable Product policy bindings for reacquired local legacy Sources."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from hashlib import sha256
from pathlib import Path
from typing import Literal

from loushang.foundation.json import _unique_json_object_hook
from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalLoadPolicy,
    JournalRecordCodec,
)
from loushang.harness.package_product._local_source_catalog import (
    _LegacyLocalSourceCatalog,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
    PackageProductLocalWheelPolicy,
)

from .package_legacy_data_trust import trust_class_for_legacy_data_resource
from .package_legacy_local_acceptance import CodingLegacyLocalAcceptanceV1
from .package_legacy_local_wheel import CodingLegacyLocalWheelCandidateV1

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_WHEEL_FILENAME = re.compile(r"loushang_legacy_[0-9a-f]{24}-1-py3-none-any\.whl\Z")
_MAX_WHEEL_BYTES = 2 * 1024 * 1024
_BUILTIN_PLUGIN_IDS = frozenset(
    {"coding.base", "coding.lsp.default", "coding.arch.default"}
)


class CodingLegacyBindingError(RuntimeError):
    """A durable migrated Source binding cannot be trusted or replayed."""


@dataclass(frozen=True, slots=True)
class CodingLegacyLocalBindingV1:
    record_revision: int
    store_id: str
    namespace_id: str
    scope_id: str
    plugin_id: str
    legacy_source_identity: str
    legacy_binding_digest: str
    source_content_digest: str
    manifest_digest: str
    dependency_lock_digest: str
    wheel_filename: str
    artifact_digest: str
    requested_package: str
    plugin_manifest_path: str
    policy_revision: str
    approval_id: str
    record_id: str
    record_version: int = 1
    resource_kind: Literal["skill", "prompt", "theme"] = "skill"

    def __post_init__(self) -> None:
        if type(self.record_revision) is not int or self.record_revision < 1:
            raise ValueError("Legacy Product binding revision is invalid")
        for value, name in (
            (self.store_id, "Store"),
            (self.scope_id, "scope"),
            (self.plugin_id, "Plugin"),
            (self.policy_revision, "policy"),
            (self.approval_id, "approval"),
        ):
            if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
                raise ValueError(f"Legacy Product {name} identity is invalid")
        if self.plugin_id in _BUILTIN_PLUGIN_IDS:
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
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise ValueError(f"Legacy Product {name} digest is invalid")
        if (
            not isinstance(self.legacy_source_identity, str)
            or not self.legacy_source_identity.startswith("local:")
            or len(self.legacy_source_identity) > 4096
            or _WHEEL_FILENAME.fullmatch(self.wheel_filename) is None
            or type(self.record_version) is not int
            or (self.record_version, self.resource_kind)
            not in {(1, "skill"), (2, "prompt"), (3, "theme")}
        ):
            raise ValueError("Legacy Product binding Source shape is invalid")
        prefix = self.wheel_filename.removesuffix("-1-py3-none-any.whl")
        if (
            self.requested_package != f"{prefix.replace('_', '-')}==1"
            or self.plugin_manifest_path != f"{prefix}/plugin.json"
        ):
            raise ValueError("Legacy Product binding Wheel identity is inconsistent")
        binding = self.to_policy_binding(Path("/"))
        if binding.requested_package != self.requested_package:
            raise ValueError("Legacy Product binding package is invalid")
        if self.record_id != sha256(canonical_json_bytes(self._identity())).hexdigest():
            raise ValueError("Legacy Product binding record identity is invalid")

    @classmethod
    def create(
        cls,
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
        candidate: CodingLegacyLocalWheelCandidateV1,
        resource_kind: Literal["skill", "prompt", "theme"] = "skill",
    ) -> CodingLegacyLocalBindingV1:
        if not isinstance(candidate, CodingLegacyLocalWheelCandidateV1):
            raise TypeError("Reacquired legacy Wheel candidate is required")
        if legacy_source_identity != candidate.original_source_identity:
            raise ValueError("Legacy Product original Source identity changed")
        if resource_kind not in {"skill", "prompt", "theme"}:
            raise ValueError("Unsupported legacy Product Resource type")
        record_version = {"skill": 1, "prompt": 2, "theme": 3}[resource_kind]
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
            record_id=sha256(canonical_json_bytes(values)).hexdigest(),
            record_version=record_version,
            resource_kind=resource_kind,
        )

    def _identity(self) -> dict[str, object]:
        return {
            key: value for key, value in self.to_dict().items() if key != "recordId"
        }

    def to_dict(self) -> dict[str, object]:
        record = _BINDING_SCHEMA.encode(self)
        if self.record_version >= 2:
            record["resourceKind"] = self.resource_kind
        return record

    @classmethod
    def from_dict(cls, value: object) -> CodingLegacyLocalBindingV1:
        expected = _BINDING_SCHEMA.keys
        if type(value) is not dict or set(value) not in (
            expected,
            expected | {"resourceKind"},
        ):
            raise JournalCodecError(
                "Invalid Coding legacy binding record",
                code="coding_legacy_binding_invalid",
            )
        try:
            if type(value["recordVersion"]) is not int:
                raise ValueError("Unsupported legacy Product binding version")
            if value["recordVersion"] == 1 and "resourceKind" not in value:
                resource_kind: Literal["skill", "prompt", "theme"] = "skill"
            elif value["recordVersion"] == 2 and value.get("resourceKind") == "prompt":
                resource_kind = "prompt"
            elif value["recordVersion"] == 3 and value.get("resourceKind") == "theme":
                resource_kind = "theme"
            else:
                raise ValueError("Unsupported legacy Product binding type")
            return cls(
                **_BINDING_SCHEMA.decode(dict, value), resource_kind=resource_kind
            )
        except (TypeError, ValueError) as exc:
            raise JournalCodecError(
                "Invalid Coding legacy binding record",
                code="coding_legacy_binding_invalid",
            ) from exc

    def to_policy_binding(self, source_root: Path) -> PackageProductLocalWheelBindingV1:
        return PackageProductLocalWheelBindingV1(
            source_identity=str(source_root / self.wheel_filename),
            requested_package=self.requested_package,
            plugin_id=self.plugin_id,
            artifact_digest=self.artifact_digest,
            plugin_manifest_path=self.plugin_manifest_path,
            source_trust_class=trust_class_for_legacy_data_resource(self.resource_kind),
        )


_BINDING_SCHEMA = RecordSchema(
    lambda value: value,
    tuple(
        RecordField(item.name)
        for item in fields(CodingLegacyLocalBindingV1)
        if item.name != "resource_kind"
    ),
)


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingLegacyLocalBindingV1.to_dict,
    decoder=CodingLegacyLocalBindingV1.from_dict,
)


class CodingLegacyLocalBindingCatalog(
    _LegacyLocalSourceCatalog[
        CodingLegacyLocalBindingV1, CodingLegacyLocalWheelCandidateV1
    ]
):
    """Original legacy authorization; shared Source storage mechanics."""

    _label = "Legacy Product"
    _product_id = "coding"
    _error_factory = staticmethod(CodingLegacyBindingError)
    _candidate_type = CodingLegacyLocalWheelCandidateV1
    _new_binding = staticmethod(CodingLegacyLocalBindingV1.create)
    _max_wheel_bytes = staticmethod(lambda: _MAX_WHEEL_BYTES)
    _wheel_filename_pattern = _WHEEL_FILENAME
    _duplicate_key_hook = staticmethod(
        _unique_json_object_hook(
            lambda: "Legacy Product binding has duplicate JSON keys"
        )
    )

    def __init__(
        self,
        path: Path,
        *,
        source_root: Path,
        store_id: str,
        namespace_id: str,
        scope_id: str,
        policy_revision: str,
        acceptance_reader: Callable[[str], CodingLegacyLocalAcceptanceV1 | None]
        | None = None,
    ) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError("Legacy binding catalog path is invalid")
        self.path = path
        self.source_root = source_root
        self.store_id = store_id
        self.namespace_id = namespace_id
        self.scope_id = scope_id
        self.policy_revision = policy_revision
        self._acceptance_reader = acceptance_reader
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    def publish_candidate(
        self,
        candidate: CodingLegacyLocalWheelCandidateV1,
        *,
        epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    ) -> Path:
        """Stage verified inert bytes atomically under the exact B Source root."""
        return super().publish_candidate(candidate, epoch_runtime=epoch_runtime)

    def append(
        self,
        candidate: CodingLegacyLocalWheelCandidateV1,
        *,
        legacy_source_identity: str,
        legacy_binding_digest: str,
        dependency_lock_digest: str,
        approval_id: str,
        resource_kind: Literal["skill", "prompt", "theme"] = "skill",
    ) -> CodingLegacyLocalBindingV1:
        return super().append(
            candidate,
            legacy_source_identity=legacy_source_identity,
            legacy_binding_digest=legacy_binding_digest,
            dependency_lock_digest=dependency_lock_digest,
            approval_id=approval_id,
            resource_kind=resource_kind,
        )

    def records(self) -> tuple[CodingLegacyLocalBindingV1, ...]:
        return super().records()

    def read_records(self) -> tuple[CodingLegacyLocalBindingV1, ...]:
        """Observe policy bindings without creating or repairing owner state."""
        return super().read_records()

    def extend_policy(
        self, base: PackageProductLocalWheelPolicy
    ) -> PackageProductLocalWheelPolicy:
        return super().extend_policy(base)

    def read_extend_policy(
        self, base: PackageProductLocalWheelPolicy
    ) -> PackageProductLocalWheelPolicy:
        """Build the same policy from strict, non-repairing Source evidence."""
        return super().read_extend_policy(base)

    def _require_accepted_binding(self, record: CodingLegacyLocalBindingV1) -> None:
        if self._acceptance_reader is None:
            raise CodingLegacyBindingError(
                "Legacy Product binding has no acceptance owner"
            )
        accepted = self._acceptance_reader(record.plugin_id)
        if not isinstance(accepted, CodingLegacyLocalAcceptanceV1):
            raise CodingLegacyBindingError(
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
            raise CodingLegacyBindingError(
                "Legacy Product binding differs from accepted review"
            )

    def _record_codec(self) -> JournalRecordCodec[CodingLegacyLocalBindingV1]:
        return _CODEC


__all__ = [
    "CodingLegacyBindingError",
    "CodingLegacyLocalBindingCatalog",
    "CodingLegacyLocalBindingV1",
]
