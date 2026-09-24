"""Join old lock heads to old desired intent without granting adoption."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .package_legacy_desired_evidence import CodingLegacyDesiredEvidenceV1
from .package_legacy_lock_evidence import CodingLegacyLocalBindingEvidenceV1

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


__all__ = [
    "CodingLegacyBuiltinIntentV1",
    "CodingLegacyInstallationInventoryV1",
    "CodingLegacyInventoryError",
    "CodingLegacyLocalInstallationV1",
    "classify_coding_legacy_installations",
]
