"""Join old lock heads to old desired intent without granting adoption."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from loushang.coding.harness.package_product import legacy_inventory as _programs
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.plugin_management.retirement import (
    inspect_removed_installation_epoch as inspect_removed_installation_epoch,
)

from .legacy_desired_evidence import (
    CodingLegacyDesiredEvidenceV1,
)
from .legacy_desired_evidence import (
    read_coding_legacy_desired_evidence as read_coding_legacy_desired_evidence,
)
from .legacy_instance_evidence import (
    parse_coding_legacy_retired_instance_capture as parse_coding_legacy_retired_instance_capture,
)
from .legacy_lock_evidence import (
    CodingLegacyLocalBindingEvidenceV1,
)
from .legacy_lock_evidence import (
    read_coding_legacy_local_binding_heads as read_coding_legacy_local_binding_heads,
)
from .legacy_operation_evidence import (
    CodingLegacyRetirementCaptureV1 as CodingLegacyRetirementCaptureV1,
)
from .legacy_operation_evidence import (
    classify_coding_legacy_management_members as classify_coding_legacy_management_members,
)
from .legacy_operation_evidence import (
    parse_coding_legacy_operation_evidence as parse_coding_legacy_operation_evidence,
)
from .legacy_snapshot_member import (
    CodingFencedEpochRuntime,
)
from .legacy_snapshot_member import (
    CodingLegacyEvidenceDomain as CodingLegacyEvidenceDomain,
)
from .legacy_snapshot_member import (
    CodingLegacyInventoryDomain as CodingLegacyInventoryDomain,
)
from .legacy_snapshot_member import (
    list_coding_first_b_snapshot_domain_members as list_coding_first_b_snapshot_domain_members,
)
from .legacy_snapshot_member import (
    read_coding_first_b_snapshot_member as read_coding_first_b_snapshot_member,
)

_BUILTINS = frozenset({"coding.base", "coding.lsp.default", "coding.arch.default"})
CodingLegacyInstalledState = Literal["installed_disabled", "installed_enabled"]


_LEGACY_PROGRAM_VALUES = {
    "value_001": "Coding Plugin lifecycle layout is required",
    "value_002": "Fenced Product epoch owner is required",
    "value_003": "Coding legacy binding members are ambiguous",
    "value_004": "Coding legacy state without a binding lock is unsupported",
    "value_005": "Coding legacy first fence is missing",
    "value_006": "package-lock.json",
    "value_007": "Coding old Desired state is missing",
    "value_008": "package-lock.json.lock",
    "value_009": "Coding old Package lock changed",
    "value_010": "instance-runtime.jsonl",
    "value_011": "retirement-intents.jsonl",
    "value_016": "management-operations.jsonl",
    "value_017": "Coding old management operation journal is missing",
    "value_020": "Coding old management lock changed",
    "value_021": "retirement-sets.jsonl",
    "value_022": "Coding old retirement journals are missing",
    "value_023": "Coding old Instance runtime evidence is missing",
    "value_024": "Coding legacy local bindings are required",
    "value_025": "Coding legacy desired evidence is invalid",
    "value_026": "Coding legacy workspace scope is invalid",
    "value_027": "Coding legacy lock snapshot changed",
    "value_028": "Coding legacy binding identity is ambiguous",
    "value_029": "coding",
    "value_030": "Coding legacy Installation scope changed",
    "value_031": "Coding legacy installed revision is missing",
    "value_032": "Coding legacy installed revision differs from current Source head",
    "value_033": "Coding legacy builtin Source is unsupported",
    "value_034": "Coding legacy Desired evidence is required",
    "value_035": "Coding old local removal set is unsupported",
    "value_036": "Coding old local removal",
    "value_037": "Coding old local removal does not match its lock head",
    "value_038": "coding.base",
    "value_039": "coding.lsp.default",
    "value_040": "coding.arch.default",
}


class CodingLegacyInventoryError(ValueError):
    """Old lock and desired authorities cannot be reconciled exactly."""


@dataclass(frozen=True, slots=True)
class CodingLegacyLocalInstallationV1:
    binding: CodingLegacyLocalBindingEvidenceV1
    desired_state: CodingLegacyInstalledState
    plugin_version: str | None


@dataclass(frozen=True, slots=True)
class CodingLegacyRemovedLocalInstallationV1:
    """One old local head with an exact final install/update/remove epoch."""

    binding: CodingLegacyLocalBindingEvidenceV1
    install_operation_id: str
    remove_operation_id: str
    head_operation_id: str
    head_transition_kind: Literal["install", "update"]


@dataclass(frozen=True, slots=True)
class CodingLegacyBuiltinIntentV1:
    plugin_id: str
    desired_state: CodingLegacyInstalledState


@dataclass(frozen=True, slots=True)
class CodingLegacyInstallationInventoryV1:
    """Classification only; a later owner must authorize every transition."""

    active_local: tuple[CodingLegacyLocalInstallationV1, ...]
    builtin_intent: tuple[CodingLegacyBuiltinIntentV1, ...]
    removed_plugin_ids: tuple[str, ...]
    unselected_source_identities: tuple[str, ...]
    desired_journal_digest: str | None
    lockfile_digest: str | None


@dataclass(frozen=True, slots=True)
class CodingLegacyInstallationInventoryEvidenceV1:
    """One first-B fence and snapshot binding for a read-only inventory."""

    first_fence_id: str
    snapshot_receipt_id: str
    inventory: CodingLegacyInstallationInventoryV1


def read_coding_legacy_installation_inventory(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: CodingFencedEpochRuntime,
) -> CodingLegacyInstallationInventoryEvidenceV1:
    """Join authenticated old lock and desired state under the current B fence."""

    return _programs.read_inventory(lifecycle, epoch_runtime)


def classify_coding_legacy_installations(
    bindings: tuple[CodingLegacyLocalBindingEvidenceV1, ...],
    desired: CodingLegacyDesiredEvidenceV1 | None,
    *,
    scope_id: str,
) -> CodingLegacyInstallationInventoryV1:
    """List only exact installed local heads; preserve negative user intent."""

    return _programs.classify_installations(bindings, desired, scope_id=scope_id)


def classify_coding_legacy_removed_local_installations(
    bindings: tuple[CodingLegacyLocalBindingEvidenceV1, ...],
    desired: CodingLegacyDesiredEvidenceV1,
    *,
    scope_id: str,
) -> tuple[CodingLegacyRemovedLocalInstallationV1, ...]:
    """Prove each absent old local head was installed from this lock, then removed.

    A final absent row alone cannot prove that a lock head ever belonged to
    the Installation. The decoded journal has already verified the whole
    history; this check binds the lock head to the last install or update in
    the final installation epoch and its eventual removal.
    """

    return _programs.classify_removed_installations(
        bindings, desired, scope_id=scope_id
    )


__all__ = [
    "CodingLegacyBuiltinIntentV1",
    "CodingLegacyInstallationInventoryV1",
    "CodingLegacyInstallationInventoryEvidenceV1",
    "CodingLegacyInventoryError",
    "CodingLegacyLocalInstallationV1",
    "CodingLegacyRemovedLocalInstallationV1",
    "classify_coding_legacy_installations",
    "classify_coding_legacy_removed_local_installations",
    "read_coding_legacy_installation_inventory",
]
