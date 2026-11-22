"""Cross-check captured legacy lock and Desired-state facts."""

from __future__ import annotations

from collections.abc import Callable, Set
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Generic, Literal, NamedTuple, Protocol, TypeVar

from loushang.harness.package_product._legacy_binding_evidence import (
    LEGACY_BINDING_CAPTURE_MAX_BYTES,
    LegacyLocalBindingEvidence,
    decode_legacy_local_binding_heads,
)
from loushang.harness.package_product._legacy_management_evidence import (
    LEGACY_DESIRED_CAPTURE_MAX_BYTES,
    LegacyManagementCapturePaths,
    classify_management_members,
    decode_legacy_desired_evidence,
    read_settled_management_history,
    require_empty_lock_markers,
    require_service_lock_markers,
)
from loushang.harness.package_product._legacy_runtime import _LegacyFirstSnapshot
from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.plugin_management.records import PluginPackageRevisionRefV1
from loushang.harness.plugin_management.retirement import (
    inspect_removed_installation_epoch,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_legacy_source_wheel import (
    _LegacyWheelValues,
    _reacquire_legacy_local_plugin_wheel,
)
from loushang.harness.resources.plugins.dependencies import PluginDependencyClosureLock

_InstalledState = Literal["installed_disabled", "installed_enabled"]
_BINDING_LOCK = "package-lock.json"
_PACKAGE_LOCK_MARKER = "package-lock.json.lock"
_DESIRED_JOURNAL = "desired-state.jsonl"


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
    def manifest_digest(self) -> str: ...

    @property
    def binding_digest(self) -> str: ...
    @property
    def dependency_lock(self) -> PluginDependencyClosureLock: ...


_BindingT = TypeVar("_BindingT", bound=_BindingHead)
_WheelT = TypeVar("_WheelT")


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


class LegacyInventoryEvidence(NamedTuple):
    first_fence_id: str
    snapshot_receipt_id: str
    inventory: LegacyInventoryFacts[LegacyLocalBindingEvidence]
    desired_journal_digest: str | None


def read_legacy_installation_inventory(
    reader: _LegacyFirstSnapshot,
    *,
    desired_path: Path,
    management_paths: LegacyManagementCapturePaths,
    product_id: str,
    scope_id: str,
    builtin_ids: Set[str],
    inventory_error: type[ValueError],
    lock_error: type[ValueError],
    desired_error: type[ValueError],
    operation_error: type[ValueError],
    instance_error: type[ValueError],
    label: str,
) -> LegacyInventoryEvidence:
    """Join first-fence facts using only immutable snapshot read authority."""
    binding_members = reader.list_members(domain="binding_history")
    if binding_members not in ((), (_BINDING_LOCK,)):
        raise inventory_error(f"{label} legacy binding members are ambiguous")
    if not binding_members and any(
        reader.list_members(domain=domain)
        for domain in ("store_bytes", "enablement_state")
    ):
        raise inventory_error(
            f"{label} legacy state without a binding lock is unsupported"
        )
    bindings: tuple[LegacyLocalBindingEvidence, ...] = ()
    if binding_members:
        lock_raw = reader.read_member(
            domain="binding_history",
            member_name=_BINDING_LOCK,
            maximum_bytes=LEGACY_BINDING_CAPTURE_MAX_BYTES,
        )
        if lock_raw is None:
            raise lock_error(f"{label} legacy Package binding lock is missing")
        bindings = decode_legacy_local_binding_heads(
            lock_raw,
            maximum_bytes=LEGACY_BINDING_CAPTURE_MAX_BYTES,
            error_type=lock_error,
            label=f"{label} legacy",
        )

    desired_members = reader.list_members(domain="desired_state")
    instance_members = reader.list_members(domain="instance_state")
    lock_members = reader.list_members(domain="lock_history")
    desired_snapshot = None
    desired_digest = None
    if binding_members or desired_members or instance_members or lock_members:
        has_binding = bool(binding_members)
        has_operations = classify_management_members(
            desired_members=desired_members,
            instance_members=instance_members,
            lock_members=lock_members,
            has_binding=has_binding,
            allow_retirement=has_binding,
            allow_retired_runtime=has_binding,
            error_type=operation_error,
            label=f"{label} old",
        )
        desired_raw = reader.read_member(
            domain="desired_state",
            member_name=_DESIRED_JOURNAL,
            maximum_bytes=LEGACY_DESIRED_CAPTURE_MAX_BYTES,
        )
        if desired_raw is None:
            raise inventory_error(f"{label} old Desired state is missing")
        desired_snapshot, desired_digest, transitions = decode_legacy_desired_evidence(
            desired_raw,
            path=desired_path,
            product_id=product_id,
            scope_id=scope_id,
            maximum_bytes=LEGACY_DESIRED_CAPTURE_MAX_BYTES,
            error_type=desired_error,
            label=f"{label} legacy",
        )
        if _PACKAGE_LOCK_MARKER in lock_members:
            require_empty_lock_markers(
                reader.read_member,
                (("lock_history", _PACKAGE_LOCK_MARKER),),
                error_type=inventory_error,
                message=f"{label} old Package lock changed",
            )
        if has_operations:
            require_service_lock_markers(
                reader.read_member,
                instance_members,
                error_type=inventory_error,
                message=f"{label} old management lock changed",
            )
            read_settled_management_history(
                reader.read_member,
                paths=management_paths,
                instance_members=instance_members,
                desired_snapshot=desired_snapshot,
                desired_transitions=transitions,
                error_type=inventory_error,
                missing_messages=(
                    f"{label} old management operation journal is missing",
                    f"{label} old retirement journals are missing",
                    f"{label} old Instance runtime evidence is missing",
                ),
                operation_error=operation_error,
                operation_label=f"{label} old",
                instance_error=instance_error,
            )
    if not isinstance(scope_id, str) or not scope_id.startswith("workspace:"):
        raise ValueError(f"{label} legacy workspace scope is invalid")
    inventory = classify_legacy_installations(
        bindings,
        desired_snapshot,
        product_id=product_id,
        scope_id=scope_id,
        builtin_ids=builtin_ids,
        error_type=inventory_error,
        label=f"{label} legacy",
    )
    reader.runtime.assert_current()
    fence = reader.runtime.cutover_result.fence
    if fence is None:
        raise inventory_error(f"{label} legacy first fence is missing")
    return LegacyInventoryEvidence(
        fence.fence_id, fence.request.snapshot_receipt_id, inventory, desired_digest
    )


def _matches_binding(
    package: PluginPackageRevisionRefV1, binding: _BindingHead
) -> bool:
    return (
        package.plugin_id == binding.plugin_id
        and package.package_source_identity == binding.source_identity
        and package.package_content_digest == binding.content_digest
        and package.dependency_lock_digest == binding.dependency_lock.digest
    )


def reacquire_legacy_bound_wheel(
    binding: _BindingHead,
    *,
    legacy_package_root: Path,
    staging_prefix: str,
    result_factory: Callable[[_LegacyWheelValues], _WheelT],
) -> _WheelT:
    """Use disposable staging while the original Source is recaptured."""
    with TemporaryDirectory(prefix=staging_prefix) as staging:
        return _reacquire_legacy_local_plugin_wheel(
            Path(binding.source_identity.removeprefix("local:")),
            legacy_package_root=legacy_package_root,
            staging_parent=Path(staging),
            plugin_id=binding.plugin_id,
            expected_source_identity=binding.source_identity,
            expected_content_digest=binding.content_digest,
            expected_manifest_digest=binding.manifest_digest,
            expected_dependency_lock=binding.dependency_lock,
            result_factory=result_factory,
        )


def reacquire_legacy_inventory_source(
    read_inventory: Callable[[], LegacyInventoryEvidence],
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    legacy_package_root: Path,
    plugin_id: str,
    staging_prefix: str,
    error_type: type[ValueError],
    label: str,
    result_factory: Callable[[_LegacyWheelValues], _WheelT],
) -> tuple[LegacyInventoryEvidence, int, _WheelT]:
    """Rebuild a live Source against the same inventory before and after capture."""
    inventory = read_inventory()
    for position, (binding, _, _) in enumerate(inventory.inventory.active_local):
        if binding.plugin_id == plugin_id:
            break
    else:
        raise error_type(f"{label} legacy Plugin is not an installed local candidate")
    if not binding.source_identity.startswith("local:/"):
        raise error_type(f"{label} legacy local Source changed")
    wheel = reacquire_legacy_bound_wheel(
        binding,
        legacy_package_root=legacy_package_root,
        staging_prefix=staging_prefix,
        result_factory=result_factory,
    )
    epoch_runtime.assert_current()
    if read_inventory() != inventory:
        raise error_type(
            f"{label} legacy Installation snapshot changed during Source reacquisition"
        )
    epoch_runtime.assert_current()
    return inventory, position, wheel


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
