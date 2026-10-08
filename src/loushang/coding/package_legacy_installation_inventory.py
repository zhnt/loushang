"""Join old lock heads to old desired intent without granting adoption."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from loushang.harness.plugin_management.records import (
    PluginDesiredStateTransitionV1,
)
from loushang.harness.plugin_management.updates import (
    PluginDesiredStateUpdateTransitionV2,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_legacy_desired_evidence import (
    CodingLegacyDesiredEvidenceV1,
    read_coding_legacy_desired_evidence,
)
from .package_legacy_instance_evidence import (
    parse_coding_legacy_retired_instance_capture,
)
from .package_legacy_lock_evidence import (
    CodingLegacyLocalBindingEvidenceV1,
    read_coding_legacy_local_binding_heads,
)
from .package_legacy_operation_evidence import (
    CodingLegacyRetirementCaptureV1,
    classify_coding_legacy_management_members,
    parse_coding_legacy_operation_evidence,
)
from .package_legacy_snapshot_member import (
    CodingFencedEpochRuntime,
    CodingLegacyEvidenceDomain,
    CodingLegacyInventoryDomain,
    list_coding_first_b_snapshot_domain_members,
    read_coding_first_b_snapshot_member,
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
    binding_members = list_coding_first_b_snapshot_domain_members(
        lifecycle, epoch_runtime, domain="binding_history"
    )
    if binding_members not in ((), ("package-lock.json",)):
        raise CodingLegacyInventoryError("Coding legacy binding members are ambiguous")
    unbound_state_domains: tuple[CodingLegacyInventoryDomain, ...] = (
        "store_bytes",
        "enablement_state",
    )
    if binding_members == () and any(
        list_coding_first_b_snapshot_domain_members(
            lifecycle, epoch_runtime, domain=domain
        )
        for domain in unbound_state_domains
    ):
        raise CodingLegacyInventoryError(
            "Coding legacy state without a binding lock is unsupported"
        )
    bindings = (
        read_coding_legacy_local_binding_heads(lifecycle, epoch_runtime)
        if binding_members
        else ()
    )
    desired_members = list_coding_first_b_snapshot_domain_members(
        lifecycle, epoch_runtime, domain="desired_state"
    )
    instance_members = list_coding_first_b_snapshot_domain_members(
        lifecycle, epoch_runtime, domain="instance_state"
    )
    lock_members = list_coding_first_b_snapshot_domain_members(
        lifecycle, epoch_runtime, domain="lock_history"
    )
    desired: CodingLegacyDesiredEvidenceV1 | None
    if (
        not binding_members
        and not desired_members
        and not instance_members
        and not lock_members
    ):
        desired = None
    else:
        has_operations = classify_coding_legacy_management_members(
            desired_members=desired_members,
            instance_members=instance_members,
            lock_members=lock_members,
            has_binding=bool(binding_members),
            allow_retirement=bool(binding_members),
            allow_retired_runtime=bool(binding_members),
        )
        desired = read_coding_legacy_desired_evidence(lifecycle, epoch_runtime)
        if desired is None:
            raise CodingLegacyInventoryError("Coding old Desired state is missing")
        if "package-lock.json.lock" in lock_members and (
            read_coding_first_b_snapshot_member(
                lifecycle,
                epoch_runtime,
                domain="lock_history",
                member_name="package-lock.json.lock",
                maximum_bytes=8,
            )
            != b"\0"
        ):
            raise CodingLegacyInventoryError("Coding old Package lock changed")
        if has_operations:
            service_locks: tuple[tuple[CodingLegacyEvidenceDomain, str], ...] = (
                ("desired_state", "desired-state.jsonl.lock"),
                ("desired_state", "management-operations.jsonl.lock"),
                ("instance_state", "retirement-intents.jsonl.lock"),
                ("instance_state", "retirement-sets.jsonl.lock"),
            )
            if "instance-runtime.jsonl" in instance_members:
                service_locks += (
                    ("instance_state", "instance-runtime.jsonl.lock"),
                    (
                        "instance_state",
                        "instance-runtime.security-acceptances.jsonl.lock",
                    ),
                )
            for domain, name in service_locks:
                if (
                    read_coding_first_b_snapshot_member(
                        lifecycle,
                        epoch_runtime,
                        domain=domain,
                        member_name=name,
                        maximum_bytes=8,
                    )
                    != b"\0"
                ):
                    raise CodingLegacyInventoryError(
                        "Coding old management lock changed"
                    )
            operations_raw = read_coding_first_b_snapshot_member(
                lifecycle,
                epoch_runtime,
                domain="desired_state",
                member_name="management-operations.jsonl",
                maximum_bytes=2 * 1024 * 1024,
            )
            if operations_raw is None:
                raise CodingLegacyInventoryError(
                    "Coding old management operation journal is missing"
                )
            retirements = None
            if "retirement-intents.jsonl" in instance_members:
                intents_raw = read_coding_first_b_snapshot_member(
                    lifecycle,
                    epoch_runtime,
                    domain="instance_state",
                    member_name="retirement-intents.jsonl",
                    maximum_bytes=2 * 1024 * 1024,
                )
                sets_raw = read_coding_first_b_snapshot_member(
                    lifecycle,
                    epoch_runtime,
                    domain="instance_state",
                    member_name="retirement-sets.jsonl",
                    maximum_bytes=2 * 1024 * 1024,
                )
                if intents_raw is None or sets_raw is None:
                    raise CodingLegacyInventoryError(
                        "Coding old retirement journals are missing"
                    )
                retirements = CodingLegacyRetirementCaptureV1(
                    intents_raw=intents_raw,
                    sets_raw=sets_raw,
                    intents_path=lifecycle.retirement_intents,
                    sets_path=lifecycle.retirement_sets,
                )
            parse_coding_legacy_operation_evidence(
                operations_raw,
                desired=desired,
                path=lifecycle.management_operations,
                retirements=retirements,
            )
            if "instance-runtime.jsonl" in instance_members:
                runtime_raw = read_coding_first_b_snapshot_member(
                    lifecycle,
                    epoch_runtime,
                    domain="instance_state",
                    member_name="instance-runtime.jsonl",
                    maximum_bytes=2 * 1024 * 1024,
                )
                if runtime_raw is None or retirements is None:
                    raise CodingLegacyInventoryError(
                        "Coding old Instance runtime evidence is missing"
                    )
                parse_coding_legacy_retired_instance_capture(
                    runtime_raw,
                    intents_raw=retirements.intents_raw,
                    sets_raw=retirements.sets_raw,
                    desired=desired,
                    lifecycle=lifecycle,
                )
    inventory = classify_coding_legacy_installations(
        bindings, desired, scope_id=lifecycle.scope_id
    )
    epoch_runtime.assert_current()
    fence = epoch_runtime.cutover_result.fence
    if fence is None:
        raise CodingLegacyInventoryError("Coding legacy first fence is missing")
    return CodingLegacyInstallationInventoryEvidenceV1(
        first_fence_id=fence.fence_id,
        snapshot_receipt_id=fence.request.snapshot_receipt_id,
        inventory=inventory,
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
    by_plugin: dict[str, CodingLegacyLocalBindingEvidenceV1] = {}
    source_ids: set[str] = set()
    lock_digests = {item.lockfile_digest for item in bindings}
    for binding in bindings:
        if (
            binding.plugin_id in by_plugin
            or binding.plugin_id in _BUILTINS
            or binding.source_identity in source_ids
        ):
            raise CodingLegacyInventoryError(
                "Coding legacy binding identity is ambiguous"
            )
        by_plugin[binding.plugin_id] = binding
        source_ids.add(binding.source_identity)
    if len(lock_digests) > 1:
        raise CodingLegacyInventoryError("Coding legacy lock snapshot changed")

    active: list[CodingLegacyLocalInstallationV1] = []
    builtins: list[CodingLegacyBuiltinIntentV1] = []
    removed: list[str] = []
    selected_ids: set[str] = set()
    states = () if desired is None else desired.snapshot.installations
    for state in states:
        key = state.installation_key
        selection = state.selection
        if (
            key.product_id != "coding"
            or key.installation_scope != "workspace"
            or key.scope_id != scope_id
        ):
            raise CodingLegacyInventoryError("Coding legacy Installation scope changed")
        plugin_id = key.plugin_id
        if selection.desired_state == "absent":
            removed.append(plugin_id)
            continue
        package = selection.package_revision
        if package is None or package.plugin_id != plugin_id:
            raise CodingLegacyInventoryError(
                "Coding legacy installed revision is missing"
            )
        if plugin_id in _BUILTINS:
            if plugin_id in by_plugin or package.package_source_identity != (
                f"embedded:{plugin_id}"
            ):
                raise CodingLegacyInventoryError(
                    "Coding legacy builtin Source is unsupported"
                )
            builtins.append(
                CodingLegacyBuiltinIntentV1(plugin_id, selection.desired_state)
            )
            continue
        matched = by_plugin.get(plugin_id)
        if (
            matched is None
            or package.package_source_identity != matched.source_identity
            or package.package_content_digest != matched.content_digest
            or package.dependency_lock_digest != matched.dependency_lock.digest
        ):
            raise CodingLegacyInventoryError(
                "Coding legacy installed revision differs from current Source head"
            )
        selected_ids.add(plugin_id)
        active.append(
            CodingLegacyLocalInstallationV1(
                binding=matched,
                desired_state=selection.desired_state,
                plugin_version=package.plugin_version,
            )
        )
    return CodingLegacyInstallationInventoryV1(
        active_local=tuple(sorted(active, key=lambda item: item.binding.plugin_id)),
        builtin_intent=tuple(sorted(builtins, key=lambda item: item.plugin_id)),
        removed_plugin_ids=tuple(sorted(removed)),
        unselected_source_identities=tuple(
            sorted(
                binding.source_identity
                for plugin_id, binding in by_plugin.items()
                if plugin_id not in selected_ids
            )
        ),
        desired_journal_digest=None if desired is None else desired.journal_digest,
        lockfile_digest=next(iter(lock_digests), None),
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
    by_plugin = {binding.plugin_id: binding for binding in bindings}
    removed_bindings = {
        plugin_id: binding
        for plugin_id, binding in by_plugin.items()
        if binding.source_identity in inventory.unselected_source_identities
    }
    if (
        not 0 < len(bindings) <= 16
        or not removed_bindings
        or set(inventory.unselected_source_identities)
        != {binding.source_identity for binding in removed_bindings.values()}
        or not set(removed_bindings) <= set(inventory.removed_plugin_ids)
        or any(
            plugin_id not in removed_bindings
            and plugin_id
            not in {"coding.base", "coding.lsp.default", "coding.arch.default"}
            for plugin_id in inventory.removed_plugin_ids
        )
        or not desired.transitions
    ):
        raise CodingLegacyInventoryError("Coding old local removal set is unsupported")
    removed: list[CodingLegacyRemovedLocalInstallationV1] = []
    for plugin_id, binding in sorted(removed_bindings.items()):
        history = tuple(
            item
            for item in desired.transitions
            if item.mutation.installation_key.plugin_id == plugin_id
        )
        if len(history) < 2 or any(
            not isinstance(
                item,
                (PluginDesiredStateTransitionV1, PluginDesiredStateUpdateTransitionV2),
            )
            for item in history
        ):
            raise CodingLegacyInventoryError(
                "Coding old local removal history is incomplete"
            )
        last = history[-1]
        installs = tuple(
            item
            for item in history[:-1]
            if item.transition_kind == "install"
            and isinstance(item, PluginDesiredStateTransitionV1)
        )
        if not installs:
            raise CodingLegacyInventoryError(
                "Coding old local removal has no final install epoch"
            )
        head_install = installs[-1]
        head_index = history.index(head_install)
        installed = head_install.committed_state.selection.package_revision
        if (
            head_install.previous_state.selection.desired_state != "absent"
            or head_install.committed_state.selection.desired_state
            not in {"installed_disabled", "installed_enabled"}
            or installed is None
            or not isinstance(last, PluginDesiredStateTransitionV1)
            or last.transition_kind != "remove"
            or last.committed_state.selection.desired_state != "absent"
        ):
            raise CodingLegacyInventoryError(
                "Coding old local removal does not match its lock head"
            )
        head: PluginDesiredStateTransitionV1 | PluginDesiredStateUpdateTransitionV2 = (
            head_install
        )
        for item in history[head_index + 1 : -1]:
            if item.previous_state.selection.package_revision != installed:
                raise CodingLegacyInventoryError(
                    "Coding old local removal revision chain changed"
                )
            if isinstance(item, PluginDesiredStateUpdateTransitionV2):
                installed = item.committed_state.selection.package_revision
                head = item
            elif (
                isinstance(item, PluginDesiredStateTransitionV1)
                and item.transition_kind in {"enable", "disable"}
                and item.committed_state.selection.package_revision == installed
            ):
                continue
            else:
                raise CodingLegacyInventoryError(
                    "Coding old local removal history is unsupported"
                )
        if (
            installed is None
            or installed.plugin_id != plugin_id
            or installed.package_source_identity != binding.source_identity
            or installed.package_content_digest != binding.content_digest
            or installed.dependency_lock_digest != binding.dependency_lock.digest
            or last.previous_state.selection.package_revision != installed
        ):
            raise CodingLegacyInventoryError(
                "Coding old local removal does not match its lock head"
            )
        removed.append(
            CodingLegacyRemovedLocalInstallationV1(
                binding=binding,
                install_operation_id=head_install.mutation.operation_id,
                remove_operation_id=last.mutation.operation_id,
                head_operation_id=head.mutation.operation_id,
                head_transition_kind=(
                    "update"
                    if isinstance(head, PluginDesiredStateUpdateTransitionV2)
                    else "install"
                ),
            )
        )
    return tuple(removed)


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
