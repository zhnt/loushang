"""Coding's concrete legacy Package root geometry for POSIX epoch cutover."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from loushang.coding._plugin_lifecycle import CodingPluginLifecycleStateLayout

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")


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
            not isinstance(root, Path)
            or not root.is_absolute()
            or ".." in root.parts
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


def resolve_coding_package_epoch_layout(
    lifecycle: CodingPluginLifecycleStateLayout,
) -> CodingPackageEpochLayoutV1:
    """Keep the deployed legacy root; place B epochs beside it, not over it."""

    if not isinstance(lifecycle, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding Plugin lifecycle layout is required")
    scope = lifecycle.scope_id.removeprefix("workspace:")
    if (
        len(scope) != 64
        or any(character not in "0123456789abcdef" for character in scope)
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


__all__ = ["CodingPackageEpochLayoutV1", "resolve_coding_package_epoch_layout"]
