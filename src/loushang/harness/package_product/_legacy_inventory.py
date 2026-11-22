"""Cross-check captured legacy lock and Desired-state facts."""

from __future__ import annotations

from collections.abc import Set
from typing import Generic, Literal, NamedTuple, Protocol, TypeVar

from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.plugin_management.records import PluginPackageRevisionRefV1
from loushang.harness.plugin_management.retirement import (
    inspect_removed_installation_epoch,
)
from loushang.harness.resources.plugins.dependencies import PluginDependencyClosureLock

_InstalledState = Literal["installed_disabled", "installed_enabled"]


class _BindingHead(Protocol):
    @property
    def plugin_id(self) -> str: ...
    @property
    def source_identity(self) -> str: ...
    @property
    def lockfile_digest(self) -> str: ...
    @property
    def content_digest(self) -> str: ...
    @property
    def dependency_lock(self) -> PluginDependencyClosureLock: ...


_BindingT = TypeVar("_BindingT", bound=_BindingHead)


class LegacyInventoryFacts(NamedTuple, Generic[_BindingT]):
    active_local: tuple[tuple[_BindingT, _InstalledState, str | None], ...]
    builtin_intent: tuple[tuple[str, _InstalledState], ...]
    removed_plugin_ids: tuple[str, ...]
    unselected_source_identities: tuple[str, ...]
    lockfile_digest: str | None


class LegacyRemovedBinding(NamedTuple, Generic[_BindingT]):
    binding: _BindingT
    install_operation_id: str
    remove_operation_id: str
    head_operation_id: str
    head_transition_kind: Literal["install", "update"]


def _matches_binding(
    package: PluginPackageRevisionRefV1, binding: _BindingHead
) -> bool:
    return (
        package.plugin_id == binding.plugin_id
        and package.package_source_identity == binding.source_identity
        and package.package_content_digest == binding.content_digest
        and package.dependency_lock_digest == binding.dependency_lock.digest
    )


def classify_legacy_installations(
    bindings: tuple[_BindingT, ...],
    desired: PluginDesiredStateSnapshotV1 | None,
    *,
    product_id: str,
    scope_id: str,
    builtin_ids: Set[str],
    error_type: type[ValueError],
    label: str,
) -> LegacyInventoryFacts[_BindingT]:
    by_plugin: dict[str, _BindingT] = {}
    source_ids: set[str] = set()
    lock_digests = {item.lockfile_digest for item in bindings}
    for binding in bindings:
        if (
            binding.plugin_id in by_plugin
            or binding.plugin_id in builtin_ids
            or binding.source_identity in source_ids
        ):
            raise error_type(f"{label} binding identity is ambiguous")
        by_plugin[binding.plugin_id] = binding
        source_ids.add(binding.source_identity)
    if len(lock_digests) > 1:
        raise error_type(f"{label} lock snapshot changed")

    active: list[tuple[_BindingT, _InstalledState, str | None]] = []
    builtins: list[tuple[str, _InstalledState]] = []
    removed: list[str] = []
    selected_ids: set[str] = set()
    for state in () if desired is None else desired.installations:
        key = state.installation_key
        selection = state.selection
        if (
            key.product_id != product_id
            or key.installation_scope != "workspace"
            or key.scope_id != scope_id
        ):
            raise error_type(f"{label} Installation scope changed")
        plugin_id = key.plugin_id
        if selection.desired_state == "absent":
            removed.append(plugin_id)
            continue
        package = selection.package_revision
        if package is None or package.plugin_id != plugin_id:
            raise error_type(f"{label} installed revision is missing")
        if plugin_id in builtin_ids:
            if (
                plugin_id in by_plugin
                or package.package_source_identity != f"embedded:{plugin_id}"
            ):
                raise error_type(f"{label} builtin Source is unsupported")
            builtins.append((plugin_id, selection.desired_state))
            continue
        matched = by_plugin.get(plugin_id)
        if matched is None or not _matches_binding(package, matched):
            raise error_type(
                f"{label} installed revision differs from current Source head"
            )
        selected_ids.add(plugin_id)
        active.append((matched, selection.desired_state, package.plugin_version))
    return LegacyInventoryFacts(
        active_local=tuple(sorted(active, key=lambda item: item[0].plugin_id)),
        builtin_intent=tuple(sorted(builtins, key=lambda item: item[0])),
        removed_plugin_ids=tuple(sorted(removed)),
        unselected_source_identities=tuple(
            sorted(
                binding.source_identity
                for plugin_id, binding in by_plugin.items()
                if plugin_id not in selected_ids
            )
        ),
        lockfile_digest=next(iter(lock_digests), None),
    )


def prove_removed_legacy_bindings(
    bindings: tuple[_BindingT, ...],
    transitions: tuple[PluginDesiredStateJournalTransition, ...],
    *,
    unselected_source_identities: tuple[str, ...],
    removed_plugin_ids: tuple[str, ...],
    builtin_ids: Set[str],
    maximum_bindings: int,
    error_type: type[ValueError],
    label: str,
) -> tuple[LegacyRemovedBinding[_BindingT], ...]:
    unselected = set(unselected_source_identities)
    removed_bindings = {
        binding.plugin_id: binding
        for binding in bindings
        if binding.source_identity in unselected
    }
    if (
        not 0 < len(bindings) <= maximum_bindings
        or not removed_bindings
        or unselected
        != {binding.source_identity for binding in removed_bindings.values()}
        or not set(removed_bindings) <= set(removed_plugin_ids)
        or set(removed_plugin_ids) - removed_bindings.keys() - builtin_ids
        or not transitions
    ):
        raise error_type(f"{label} set is unsupported")
    mismatch_message = f"{label} does not match its lock head"
    removed: list[LegacyRemovedBinding[_BindingT]] = []
    for plugin_id, binding in sorted(removed_bindings.items()):
        history = tuple(
            item
            for item in transitions
            if item.mutation.installation_key.plugin_id == plugin_id
        )
        proof = inspect_removed_installation_epoch(
            history,
            error_type=error_type,
            label=label,
            mismatch_message=mismatch_message,
        )
        if not _matches_binding(proof.package_revision, binding):
            raise error_type(mismatch_message)
        removed.append(
            LegacyRemovedBinding(
                binding,
                proof.install.mutation.operation_id,
                proof.removal.mutation.operation_id,
                proof.head.mutation.operation_id,
                proof.head_transition_kind,
            )
        )
    return tuple(removed)
