"""Dark, durable Product policy bindings for reacquired local legacy Sources."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256 as sha256
from typing import Literal

from loushang.foundation.json import _unique_json_object_hook
from loushang.harness.journal import (
    JournalCodecError as JournalCodecError,
)
from loushang.harness.journal import (
    JournalRecordCodec,
)
from loushang.harness.package_product._legacy_inventory import (
    legacy_review_scalar_schema,
)
from loushang.harness.package_product._legacy_local_migration import (
    LegacyLocalBindingRecord,
)
from loushang.harness.package_product._local_source_catalog import (
    _LegacyLocalSourceCatalog,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes as canonical_json_bytes,
)
from loushang.harness.resources.packages.product_legacy_source_wheel import (
    LEGACY_SOURCE_WHEEL_FILENAME,
)

from .legacy_data_trust import trust_class_for_legacy_data_resource
from .legacy_local_acceptance import CodingLegacyLocalAcceptanceV1
from .legacy_local_wheel import CodingLegacyLocalWheelCandidateV1

_MAX_WHEEL_BYTES = 2 * 1024 * 1024
_BUILTIN_PLUGIN_IDS = frozenset(
    {"coding.base", "coding.lsp.default", "coding.arch.default"}
)


class CodingLegacyBindingError(RuntimeError):
    """A durable migrated Source binding cannot be trusted or replayed."""


@dataclass(frozen=True, slots=True)
class CodingLegacyLocalBindingV1(LegacyLocalBindingRecord):
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

    _reserved_plugin_ids = _BUILTIN_PLUGIN_IDS
    _candidate_type = CodingLegacyLocalWheelCandidateV1
    _trust_class_for = staticmethod(trust_class_for_legacy_data_resource)
    _invalid_record = "Invalid Coding legacy binding record"
    _invalid_code = "coding_legacy_binding_invalid"


_BINDING_SCHEMA = legacy_review_scalar_schema(
    CodingLegacyLocalBindingV1, "resource_kind"
)
CodingLegacyLocalBindingV1._binding_schema = _BINDING_SCHEMA
_CODEC = CodingLegacyLocalBindingV1._record_codec()


class CodingLegacyLocalBindingCatalog(
    _LegacyLocalSourceCatalog[
        CodingLegacyLocalBindingV1,
        CodingLegacyLocalWheelCandidateV1,
        CodingLegacyLocalAcceptanceV1,
    ]
):
    """Original legacy authorization; shared Source storage mechanics."""

    _label = "Legacy Product"
    _product_id = "coding"
    _error_factory = staticmethod(CodingLegacyBindingError)
    _candidate_type = CodingLegacyLocalWheelCandidateV1
    _new_binding = staticmethod(CodingLegacyLocalBindingV1.create)
    _max_wheel_bytes = staticmethod(lambda: _MAX_WHEEL_BYTES)
    _wheel_filename_pattern = LEGACY_SOURCE_WHEEL_FILENAME
    _acceptance_type = CodingLegacyLocalAcceptanceV1
    _duplicate_key_hook = staticmethod(
        _unique_json_object_hook(
            lambda: "Legacy Product binding has duplicate JSON keys"
        )
    )

    def _record_codec(self) -> JournalRecordCodec[CodingLegacyLocalBindingV1]:
        return _CODEC


__all__ = [
    "CodingLegacyBindingError",
    "CodingLegacyLocalBindingCatalog",
    "CodingLegacyLocalBindingV1",
]
