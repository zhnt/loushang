"""Join old lock heads to old desired intent without granting adoption."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product._legacy_binding_evidence import (
    LegacyLocalBindingEvidence,
)
from loushang.harness.package_product._legacy_inventory import (
    LegacyInventoryFacts,
    classify_legacy_installations,
    prove_removed_legacy_bindings,
    read_legacy_installation_inventory,
)

from .legacy_desired_evidence import (
    CodingLegacyDesiredError,
    CodingLegacyDesiredEvidenceV1,
)
from .legacy_desired_evidence import (
    read_coding_legacy_desired_evidence as read_coding_legacy_desired_evidence,
)
from .legacy_instance_evidence import (
    CodingLegacyInstanceEvidenceError,
    _management_capture_paths,
)
from .legacy_instance_evidence import (
    parse_coding_legacy_retired_instance_capture as parse_coding_legacy_retired_instance_capture,
)
from .legacy_lock_evidence import (
    CodingLegacyLocalBindingEvidenceV1,
    CodingLegacyLockError,
)
from .legacy_lock_evidence import (
    read_coding_legacy_local_binding_heads as read_coding_legacy_local_binding_heads,
)
from .legacy_operation_evidence import (
    CodingLegacyOperationEvidenceError,
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
    _snapshot_reader,
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

    if not isinstance(lifecycle, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding Plugin lifecycle layout is required")
    if not isinstance(epoch_runtime, CodingFencedEpochRuntime):
        raise TypeError("Fenced Product epoch owner is required")
    epoch_runtime.assert_current()
    evidence = read_legacy_installation_inventory(
        _snapshot_reader(lifecycle, epoch_runtime),
        desired_path=lifecycle.desired_state,
        management_paths=_management_capture_paths(lifecycle),
        product_id="coding",
        scope_id=lifecycle.scope_id,
        builtin_ids=_BUILTINS,
        inventory_error=CodingLegacyInventoryError,
        lock_error=CodingLegacyLockError,
        desired_error=CodingLegacyDesiredError,
        operation_error=CodingLegacyOperationEvidenceError,
        instance_error=CodingLegacyInstanceEvidenceError,
        label="Coding",
    )
    return CodingLegacyInstallationInventoryEvidenceV1(
        first_fence_id=evidence.first_fence_id,
        snapshot_receipt_id=evidence.snapshot_receipt_id,
        inventory=_project_inventory_facts(
            evidence.inventory, desired_journal_digest=evidence.desired_journal_digest
        ),
    )


def classify_coding_legacy_installations(
    bindings: tuple[CodingLegacyLocalBindingEvidenceV1, ...],
    desired: CodingLegacyDesiredEvidenceV1 | None,
    *,
    scope_id: str,
) -> CodingLegacyInstallationInventoryV1:
    """List only exact installed local heads; preserve negative user intent."""

    if type(bindings) is not tuple or any(
        not isinstance(item, CodingLegacyLocalBindingEvidenceV1) for item in bindings
    ):
        raise TypeError("Coding legacy local bindings are required")
    if desired is not None and not isinstance(desired, CodingLegacyDesiredEvidenceV1):
        raise TypeError("Coding legacy desired evidence is invalid")
    if not isinstance(scope_id, str) or not scope_id.startswith("workspace:"):
        raise ValueError("Coding legacy workspace scope is invalid")
    facts = classify_legacy_installations(
        bindings,
        None if desired is None else desired.snapshot,
        product_id="coding",
        scope_id=scope_id,
        builtin_ids=_BUILTINS,
        error_type=CodingLegacyInventoryError,
        label="Coding legacy",
    )
    return _project_inventory_facts(
        facts,
        desired_journal_digest=None if desired is None else desired.journal_digest,
    )


def _project_inventory_facts(
    facts: (
        LegacyInventoryFacts[CodingLegacyLocalBindingEvidenceV1]
        | LegacyInventoryFacts[LegacyLocalBindingEvidence]
    ),
    *,
    desired_journal_digest: str | None,
) -> CodingLegacyInstallationInventoryV1:
    return CodingLegacyInstallationInventoryV1(
        active_local=tuple(
            CodingLegacyLocalInstallationV1(
                binding
                if isinstance(binding, CodingLegacyLocalBindingEvidenceV1)
                else CodingLegacyLocalBindingEvidenceV1(*binding),
                state,
                version,
            )
            for binding, state, version in facts.active_local
        ),
        builtin_intent=tuple(
            CodingLegacyBuiltinIntentV1(*item) for item in facts.builtin_intent
        ),
        removed_plugin_ids=facts.removed_plugin_ids,
        unselected_source_identities=facts.unselected_source_identities,
        desired_journal_digest=desired_journal_digest,
        lockfile_digest=facts.lockfile_digest,
    )


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

    if not isinstance(desired, CodingLegacyDesiredEvidenceV1):
        raise TypeError("Coding legacy Desired evidence is required")
    inventory = classify_coding_legacy_installations(
        bindings, desired, scope_id=scope_id
    )
    return tuple(
        CodingLegacyRemovedLocalInstallationV1(*item)
        for item in prove_removed_legacy_bindings(
            bindings,
            desired.transitions,
            unselected_source_identities=inventory.unselected_source_identities,
            removed_plugin_ids=inventory.removed_plugin_ids,
            builtin_ids=_BUILTINS,
            maximum_bindings=16,
            error_type=CodingLegacyInventoryError,
            label="Coding old local removal",
        )
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
