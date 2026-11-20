"""Durable Product acceptance of one reviewed old local Installation.

Acceptance records the operator's exact review choice. It does not authorize
Source publication, mutate Desired State, or run a Package transaction.
"""

from __future__ import annotations

import json as json
import os as os
from dataclasses import dataclass
from hashlib import sha256 as sha256
from typing import Final, Literal

from loushang.coding.harness.package_product import legacy_local_acceptance as _programs
from loushang.coding.harness.package_product import (
    legacy_local_acceptance as _record_programs,
)
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
)
from loushang.harness.journal import (
    JournalCodecError as JournalCodecError,
)
from loushang.harness.package_product._legacy_local_migration import (
    _LocalAcceptanceProtocol,
)
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1 as PluginInstallationKeyV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes as canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from .epoch_layout import (
    resolve_coding_package_epoch_layout as resolve_coding_package_epoch_layout,
)
from .legacy_classification import (
    classify_coding_legacy_source_configuration as classify_coding_legacy_source_configuration,
)
from .legacy_configured_source import (
    match_coding_legacy_local_skill_configured_source as match_coding_legacy_local_skill_configured_source,
)
from .legacy_installation_inventory import (
    read_coding_legacy_installation_inventory as read_coding_legacy_installation_inventory,
)
from .legacy_review import (
    CodingLegacyLocalAdoptionReviewV1,
)
from .legacy_review import (
    review_coding_legacy_installed_local_source as review_coding_legacy_installed_local_source,
)
from .legacy_snapshot_member import (
    CodingFirstBLegacyStateObserver as CodingFirstBLegacyStateObserver,
)
from .legacy_snapshot_member import (
    read_coding_first_b_snapshot_member as read_coding_first_b_snapshot_member,
)

_MAX_ACCEPTANCE_BYTES = 1024 * 1024
_MAX_DESIRED_BYTES = 32 * 1024 * 1024
_BUILTINS = frozenset({"coding.base", "coding.lsp.default", "coding.arch.default"})


_LEGACY_PROGRAM_VALUES = {
    "value_001": "Coding legacy local acceptance lost its first-B Installation",
    "value_002": "coding-source-configuration.json",
    "value_003": "Coding legacy local acceptance lost its Source configuration",
    "value_004": "Coding legacy local acceptance changed first-B evidence",
    "value_005": "coding.base",
    "value_006": "coding.lsp.default",
    "value_007": "coding.arch.default",
}


_LEGACY_ADOPTION_VALUES = {
    "value_001": "Coding legacy local review ID changed",
    "value_002": "Coding legacy local Product epoch changed",
    "value_003": "Coding legacy local review changed before acceptance",
    "value_004": "coding",
    "value_005": "Coding legacy local Plugin identity is required",
    "value_006": "Coding legacy local acceptance conflicts with current review",
}


_LEGACY_RECORD_VALUES = {
    "value_001": "Coding legacy local acceptance record is invalid",
    "value_002": "Coding legacy local acceptance identity changed",
    "value_003": "Coding legacy local review is required",
    "value_004": "Invalid Coding legacy local acceptance",
    "value_005": "coding_legacy_local_acceptance_invalid",
    "value_006": "Unsupported Coding legacy local acceptance version",
    "value_007": "Unsupported Coding legacy local acceptance type",
}

_LEGACY_RECORD_PROMPT: Final[Literal["prompt"]] = "prompt"
_LEGACY_RECORD_SKILL: Final[Literal["skill"]] = "skill"
_LEGACY_RECORD_THEME: Final[Literal["theme"]] = "theme"


_LEGACY_CHAIN_VALUES = {
    "value_001": "Coding legacy local Resource type differs from accepted route",
    "value_002": "Coding legacy local Resource type is unsupported",
}


class CodingLegacyLocalAcceptanceError(RuntimeError):
    """An operator review choice or its Product receipt is inconsistent."""


@dataclass(frozen=True, slots=True)
class CodingLegacyLocalAcceptanceV1:
    review: CodingLegacyLocalAdoptionReviewV1
    acceptance_id: str
    acceptance_version: int = 1
    resource_kind: Literal["skill", "prompt", "theme"] = "skill"

    def __post_init__(self) -> None:
        return _record_programs.validate_acceptance(self)

    @classmethod
    def create(
        cls,
        review: CodingLegacyLocalAdoptionReviewV1,
        *,
        resource_kind: Literal["skill", "prompt", "theme"] = "skill",
    ) -> CodingLegacyLocalAcceptanceV1:
        return _record_programs.create_acceptance(
            cls, review, resource_kind=resource_kind
        )

    def to_dict(self) -> dict[str, object]:
        record: dict[str, object] = {
            "acceptanceId": self.acceptance_id,
            "acceptanceVersion": self.acceptance_version,
            "review": self.review.to_dict(),
        }
        if self.acceptance_version >= 2:
            record["resourceKind"] = self.resource_kind
        return record

    @classmethod
    def from_dict(cls, value: object) -> CodingLegacyLocalAcceptanceV1:
        return _record_programs.decode_acceptance(cls, value)


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingLegacyLocalAcceptanceV1.to_dict,
    decoder=CodingLegacyLocalAcceptanceV1.from_dict,
)


def accept_coding_legacy_installed_local_review(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    policy_revision: str,
    accepted_review_id: str,
    resource_kind: Literal["skill", "prompt", "theme"] = "skill",
) -> CodingLegacyLocalAcceptanceV1:
    """Accept one exact current review while that Installation is untouched in B."""

    return _programs.accept_local_review(
        lifecycle,
        epoch_runtime,
        plugin_id=plugin_id,
        policy_revision=policy_revision,
        accepted_review_id=accepted_review_id,
        resource_kind=resource_kind,
    )


def reopen_coding_legacy_installed_local_acceptance(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    policy_revision: str,
) -> CodingLegacyLocalAcceptanceV1 | None:
    """Reopen a receipt against frozen first-B evidence without live Source."""

    return _programs.reopen_local_acceptance(
        lifecycle, epoch_runtime, plugin_id=plugin_id, policy_revision=policy_revision
    )


def read_coding_legacy_installed_local_acceptance(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    policy_revision: str,
) -> CodingLegacyLocalAcceptanceV1 | None:
    """Additionally require that the original live Source still matches."""

    return _programs.read_local_acceptance(
        lifecycle, epoch_runtime, plugin_id=plugin_id, policy_revision=policy_revision
    )


def _require_live_resource_kind(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> None:
    # The inspector is imported here to keep Product cutover composition out of
    # the acceptance record codec's module initialization path.
    return _programs.require_live_resource_kind(
        lifecycle, epoch_runtime, plugin_id=plugin_id, resource_kind=resource_kind
    )


def _require_frozen_review(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    review: CodingLegacyLocalAdoptionReviewV1,
    *,
    plugin_id: str,
    policy_revision: str,
) -> None:
    return _programs.require_frozen_review(
        lifecycle,
        epoch_runtime,
        review,
        plugin_id=plugin_id,
        policy_revision=policy_revision,
    )


def _acceptance_protocol(
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
) -> _LocalAcceptanceProtocol[CodingLegacyLocalAcceptanceV1]:
    return _LocalAcceptanceProtocol(
        epoch_runtime,
        _CODEC,
        CodingLegacyLocalAcceptanceError,
        "Coding legacy local",
        _MAX_ACCEPTANCE_BYTES,
        _MAX_DESIRED_BYTES,
    )


__all__ = [
    "CodingLegacyLocalAcceptanceError",
    "CodingLegacyLocalAcceptanceV1",
    "accept_coding_legacy_installed_local_review",
    "read_coding_legacy_installed_local_acceptance",
    "reopen_coding_legacy_installed_local_acceptance",
]
