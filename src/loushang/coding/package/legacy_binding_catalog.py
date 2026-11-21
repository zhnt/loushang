"""Dark, durable Product policy bindings for reacquired local legacy Sources."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from hashlib import sha256 as sha256
from pathlib import Path
from typing import Final, Literal

from loushang.coding.harness.package_product import (
    legacy_binding_records as _record_programs,
)
from loushang.foundation.json import _unique_json_object_hook
from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    FunctionalJournalRecordCodec,
    JournalLoadPolicy,
    JournalRecordCodec,
)
from loushang.harness.journal import (
    JournalCodecError as JournalCodecError,
)
from loushang.harness.package_product._local_source_catalog import (
    _LegacyLocalSourceCatalog,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes as canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
    PackageProductLocalWheelPolicy,
)

from .legacy_data_trust import trust_class_for_legacy_data_resource
from .legacy_local_acceptance import CodingLegacyLocalAcceptanceV1
from .legacy_local_wheel import CodingLegacyLocalWheelCandidateV1

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_WHEEL_FILENAME = re.compile(r"loushang_legacy_[0-9a-f]{24}-1-py3-none-any\.whl\Z")
_MAX_WHEEL_BYTES = 2 * 1024 * 1024
_BUILTIN_PLUGIN_IDS = frozenset(
    {"coding.base", "coding.lsp.default", "coding.arch.default"}
)


_LEGACY_RECORD_VALUES = {
    "value_001": "Invalid Coding legacy binding record",
    "value_002": "coding_legacy_binding_invalid",
}

_LEGACY_RECORD_PROMPT: Final[Literal["prompt"]] = "prompt"
_LEGACY_RECORD_SKILL: Final[Literal["skill"]] = "skill"
_LEGACY_RECORD_THEME: Final[Literal["theme"]] = "theme"


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
        return _record_programs.validate_binding(self)

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
        return _record_programs.create_binding(
            cls,
            record_revision=record_revision,
            store_id=store_id,
            namespace_id=namespace_id,
            scope_id=scope_id,
            legacy_source_identity=legacy_source_identity,
            legacy_binding_digest=legacy_binding_digest,
            dependency_lock_digest=dependency_lock_digest,
            policy_revision=policy_revision,
            approval_id=approval_id,
            candidate=candidate,
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
        return _record_programs.decode_binding(cls, value)

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
        return _record_programs.require_accepted_binding(self, record)

    def _record_codec(self) -> JournalRecordCodec[CodingLegacyLocalBindingV1]:
        return _CODEC


__all__ = [
    "CodingLegacyBindingError",
    "CodingLegacyLocalBindingCatalog",
    "CodingLegacyLocalBindingV1",
]
