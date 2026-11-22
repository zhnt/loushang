"""Coding's concrete legacy Package root geometry for POSIX epoch cutover."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product._legacy_runtime import legacy_product_fence_exists
from loushang.harness.resources.packages.product_pre_b_snapshot import (
    inspect_legacy_product_domain_members,
)

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_LIFECYCLE_JOURNAL_DOMAINS = {
    "desired-state.jsonl": "desired_state",
    "management-operations.jsonl": "desired_state",
    "package-gc-reservations.jsonl": "desired_state",
    "enablement-migration.jsonl": "enablement_state",
    "instance-runtime.jsonl": "instance_state",
    "instance-runtime.security-acceptances.jsonl": "instance_state",
    "owner-generation-evidence.jsonl": "instance_state",
    "package-lifecycle.jsonl": "instance_state",
    "retirement-intents.jsonl": "instance_state",
    "retirement-sets.jsonl": "instance_state",
}
_LIFECYCLE_MEMBER_DOMAINS = {
    **{name: (domain,) for name, domain in _LIFECYCLE_JOURNAL_DOMAINS.items()},
    **{
        f"{name}.lock": (domain,) for name, domain in _LIFECYCLE_JOURNAL_DOMAINS.items()
    },
    "enablement-migration.jsonl.migration.lock": ("enablement_state",),
    "lifecycle-coordination.lock": ("desired_state",),
    "process-startups": ("instance_state",),
    "session-owners": ("instance_state",),
}
_LIFECYCLE_DIRECTORY_MEMBERS = frozenset({"process-startups", "session-owners"})

_PACKAGE_DIRECTORY_MEMBERS = frozenset({"installed", "plugin-revisions"})
_PACKAGE_MEMBER_DOMAINS = {
    **dict.fromkeys(_PACKAGE_DIRECTORY_MEMBERS, ("store_bytes",)),
    "package-lock.json": ("binding_history", "lock_history"),
    "package-lock.json.lock": ("lock_history",),
}


class _FencedRuntimeOpenKwargs(TypedDict):
    authority_root: Path
    control_root: Path
    store_id: str
    epochs_root_name: str


@dataclass(frozen=True, slots=True)
class CodingPackageEpochLayoutV1:
    store_id: str
    authority_root: Path
    legacy_root_name: str
    epochs_root_name: str
    control_root: Path
    snapshot_root: Path

    def __post_init__(self) -> None:
        roots = (self.authority_root, self.control_root, self.snapshot_root)
        if any(
            not isinstance(root, Path) or not root.is_absolute() or ".." in root.parts
            for root in roots
        ):
            raise ValueError("Coding Package epoch roots must be absolute")
        if (
            not isinstance(self.store_id, str)
            or not self.store_id.startswith("package-store:coding:")
            or _SAFE_ID.fullmatch(self.store_id) is None
            or not isinstance(self.legacy_root_name, str)
            or _SAFE_ID.fullmatch(self.legacy_root_name) is None
            or not isinstance(self.epochs_root_name, str)
            or _SAFE_ID.fullmatch(self.epochs_root_name) is None
            or self.legacy_root_name == self.epochs_root_name
        ):
            raise ValueError("Coding Package epoch identity is invalid")
        if any(
            left == right or left in right.parents or right in left.parents
            for index, left in enumerate(roots)
            for right in roots[index + 1 :]
        ):
            raise ValueError("Coding Package epoch authorities overlap")

    def fenced_runtime_open_kwargs(self) -> _FencedRuntimeOpenKwargs:
        """Bind the existing fenced runtime entry points to this layout."""

        return {
            "authority_root": self.authority_root,
            "control_root": self.control_root,
            "store_id": self.store_id,
            "epochs_root_name": self.epochs_root_name,
        }

    @property
    def legacy_root(self) -> Path:
        return self.authority_root / self.legacy_root_name

    @property
    def epochs_root(self) -> Path:
        return self.authority_root / self.epochs_root_name

    def epoch_root(self, namespace_id: str) -> Path:
        if (
            not isinstance(namespace_id, str)
            or len(namespace_id) != 64
            or any(character not in "0123456789abcdef" for character in namespace_id)
        ):
            raise ValueError("Coding Package epoch namespace is invalid")
        return self.epochs_root / namespace_id


@dataclass(frozen=True, slots=True)
class CodingPackagePreBStoreMembersV1:
    """Exact old Package-root members, including its combined lock/binding file."""

    source_root: Path
    store_bytes: tuple[str, ...]
    binding_history: tuple[str, ...]
    lock_history: tuple[str, ...]
    mapping_version: int = 1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_root, Path)
            or not self.source_root.is_absolute()
            or ".." in self.source_root.parts
        ):
            raise ValueError("Coding pre-B Package source root is invalid")
        if self.mapping_version != 1:
            raise ValueError("Unsupported Coding pre-B Package source mapping")
        if self.binding_history not in {(), ("package-lock.json",)}:
            raise ValueError("Coding Package binding history mapping is invalid")
        expected_lock = (
            (*self.binding_history, "package-lock.json.lock")
            if "package-lock.json.lock" in self.lock_history
            else self.binding_history
        )
        if self.lock_history != expected_lock:
            raise ValueError("Coding Package lock history mapping is invalid")
        if (
            self.store_bytes != tuple(sorted(set(self.store_bytes)))
            or not set(self.store_bytes) <= _PACKAGE_DIRECTORY_MEMBERS
        ):
            raise ValueError("Coding Package Store member mapping is invalid")

    def domain_members(self) -> dict[str, tuple[str, ...]]:
        return {
            "store_bytes": self.store_bytes,
            "binding_history": self.binding_history,
            "lock_history": self.lock_history,
        }


@dataclass(frozen=True, slots=True)
class CodingLifecyclePreBMembersV1:
    """Exact deployed Coding lifecycle members partitioned into pre-B domains."""

    source_root: Path
    desired_state: tuple[str, ...]
    enablement_state: tuple[str, ...]
    instance_state: tuple[str, ...]
    mapping_version: int = 1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_root, Path)
            or not self.source_root.is_absolute()
            or ".." in self.source_root.parts
            or self.mapping_version != 1
        ):
            raise ValueError("Coding pre-B lifecycle mapping is invalid")
        domains = self.domain_members()
        if any(
            members != tuple(sorted(set(members)))
            or any(_LIFECYCLE_MEMBER_DOMAINS.get(name) != (domain,) for name in members)
            for domain, members in domains.items()
        ):
            raise ValueError("Coding pre-B lifecycle member mapping is invalid")

    def domain_members(self) -> dict[str, tuple[str, ...]]:
        return {
            "desired_state": self.desired_state,
            "enablement_state": self.enablement_state,
            "instance_state": self.instance_state,
        }


def resolve_coding_lifecycle_pre_b_members(
    lifecycle: CodingPluginLifecycleStateLayout,
) -> CodingLifecyclePreBMembersV1:
    """Account for every old lifecycle-root member or refuse the cutover."""

    resolve_coding_package_epoch_layout(lifecycle)
    root = lifecycle.root
    expected_journals = (
        (lifecycle.desired_state, "desired-state.jsonl"),
        (lifecycle.management_operations, "management-operations.jsonl"),
        (lifecycle.retirement_intents, "retirement-intents.jsonl"),
        (lifecycle.retirement_sets, "retirement-sets.jsonl"),
        (lifecycle.instance_runtime, "instance-runtime.jsonl"),
        (lifecycle.package_lifecycle, "package-lifecycle.jsonl"),
        (lifecycle.owner_generation_evidence, "owner-generation-evidence.jsonl"),
        (lifecycle.enablement_migration, "enablement-migration.jsonl"),
        (lifecycle.package_gc_reservations, "package-gc-reservations.jsonl"),
    )
    if any(path != root / name for path, name in expected_journals):
        raise ValueError("Coding pre-B lifecycle paths are not canonical")
    members = inspect_legacy_product_domain_members(
        root,
        domains_by_member=_LIFECYCLE_MEMBER_DOMAINS,
        directory_members=_LIFECYCLE_DIRECTORY_MEMBERS,
        label="Coding pre-B lifecycle",
    )
    return CodingLifecyclePreBMembersV1(
        source_root=root,
        desired_state=members.get("desired_state", ()),
        enablement_state=members.get("enablement_state", ()),
        instance_state=members.get("instance_state", ()),
    )


def resolve_coding_package_pre_b_store_members(
    lifecycle: CodingPluginLifecycleStateLayout,
) -> CodingPackagePreBStoreMembersV1:
    """Partition the deployed Package root; refuse unaccounted old members."""

    resolve_coding_package_epoch_layout(lifecycle)
    root = lifecycle.package_root
    members = inspect_legacy_product_domain_members(
        root,
        domains_by_member=_PACKAGE_MEMBER_DOMAINS,
        directory_members=_PACKAGE_DIRECTORY_MEMBERS,
        label="Coding pre-B Package",
    )
    return CodingPackagePreBStoreMembersV1(
        source_root=root,
        store_bytes=members.get("store_bytes", ()),
        binding_history=members.get("binding_history", ()),
        lock_history=members.get("lock_history", ()),
    )


def resolve_coding_package_epoch_layout(
    lifecycle: CodingPluginLifecycleStateLayout,
) -> CodingPackageEpochLayoutV1:
    """Keep the deployed legacy root; place B epochs beside it, not over it."""

    if not isinstance(lifecycle, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding Plugin lifecycle layout is required")
    scope = lifecycle.scope_id.removeprefix("workspace:")
    if len(scope) != 64 or any(
        character not in "0123456789abcdef" for character in scope
    ):
        raise ValueError("Coding workspace identity is invalid")
    legacy_root = lifecycle.package_root
    if legacy_root.name not in {scope, "coding-lifecycle"}:
        raise ValueError("Coding legacy Package root is not canonical")
    if legacy_root.parent == lifecycle.root.parent:
        raise ValueError("Coding Package data and state roots overlap")
    return CodingPackageEpochLayoutV1(
        store_id=f"package-store:coding:{scope}",
        authority_root=legacy_root.parent,
        legacy_root_name=legacy_root.name,
        epochs_root_name=f"{legacy_root.name}.epochs",
        control_root=lifecycle.root.parent / f"{lifecycle.root.name}.package-epoch",
        snapshot_root=lifecycle.root.parent / f"{lifecycle.root.name}.pre-b-snapshots",
    )


__all__ = [
    "CodingLifecyclePreBMembersV1",
    "CodingPackageEpochLayoutV1",
    "CodingPackagePreBStoreMembersV1",
    "resolve_coding_package_epoch_layout",
    "resolve_coding_lifecycle_pre_b_members",
    "resolve_coding_package_pre_b_store_members",
]


def coding_fenced_product_exists(layout: CodingPluginLifecycleStateLayout) -> bool:
    """Only an existing fence selects B; malformed existing B fails closed later."""

    return legacy_product_fence_exists(
        resolve_coding_package_epoch_layout(layout).control_root
    )


# Preserve the deployed callable/pickle route after moving its implementation.
coding_fenced_product_exists.__module__ = (
    "loushang.coding.package_product_management_cli"
)
