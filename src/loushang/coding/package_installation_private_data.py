"""Exact Installation-owned private root for Coding Product Arch Sessions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.plugin_management._installation_root_windows import (
    _DeletionRecords,
    _WindowsInstallationRootLineage,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    prepare_windows_product_private_directory_chain,
)

from . import package_legacy_windows_receipt as _receipts
from ._plugin_lifecycle import CodingPluginLifecycleStateLayout, _prepare_private_tree
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_legacy_windows_receipt import CodingWindowsPrivateReceiptError

_ARCH_PLUGIN_ID = "coding.arch.default"

_WINDOWS_ROOT_RECEIPT_MAX_BYTES = 4096


@dataclass(frozen=True, slots=True)
class _WindowsArchRootGeneration:
    number: int
    predecessor_receipt_id: str | None
    intent_path: Path
    receipt_path: Path
    intent: bytes | None
    receipt: bytes | None
    identity: tuple[int, int] | None


def coding_arch_installation_private_data_root(
    layout: CodingPluginLifecycleStateLayout, key: PluginInstallationKeyV1
) -> Path:
    """Map only the exact Coding Arch Installation to its private subtree."""
    if (
        not isinstance(layout, CodingPluginLifecycleStateLayout)
        or not isinstance(key, PluginInstallationKeyV1)
        or key.product_id != "coding"
        or (key.installation_scope != "workspace")
        or (key.scope_id != layout.scope_id)
        or (key.plugin_id != _ARCH_PLUGIN_ID)
    ):
        raise ValueError("Coding Arch private-data Installation key changed")
    installation_id = sha256(
        b"loushang.coding-installation-private-data/v1\x00"
        + canonical_json_bytes(key.to_dict())
    ).hexdigest()
    return layout.package_root / "installation-private-data" / installation_id


def coding_arch_session_private_data_root(
    layout: CodingPluginLifecycleStateLayout,
    key: PluginInstallationKeyV1,
    *,
    session_id: str,
) -> Path:
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Coding Arch private-data Session identity is invalid")
    session_id_digest = sha256(
        b"loushang.coding-installation-private-session/v1\x00"
        + session_id.encode("utf-8")
    ).hexdigest()
    return (
        coding_arch_installation_private_data_root(layout, key)
        / "sessions"
        / session_id_digest
    )


def prepare_coding_product_arch_private_data_root(
    layout: CodingPluginLifecycleStateLayout,
    runtime: PackageProductRuntimeBindingV1,
    *,
    session_id: str,
) -> Path:
    """Prepare a private per-Session cache beneath the exact Installation."""
    if (
        not isinstance(layout, CodingPluginLifecycleStateLayout)
        or not isinstance(runtime, PackageProductRuntimeBindingV1)
        or runtime.product_id != "coding"
        or (runtime.session_id != session_id)
        or (not isinstance(session_id, str))
        or (not session_id)
    ):
        raise ValueError("Coding Arch private-data Product session changed")
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=layout.scope_id,
        plugin_id=_ARCH_PLUGIN_ID,
    )
    selected = runtime.capture_plugin_desired_selection_for(_ARCH_PLUGIN_ID)
    if (
        selected.installation_key != key
        or selected.desired_state != "installed_enabled"
    ):
        raise ValueError("Coding Arch private-data Installation is not selected")
    selected_root = runtime.capture_selected_plugin_manifest_for(
        _ARCH_PLUGIN_ID, max_files=64, max_total_bytes=1024 * 1024
    )
    source = Path(selected_root.snapshot.package_revision.package_source_identity)
    epoch = resolve_coding_package_epoch_layout(layout)
    if (
        selected_root.snapshot.installation_key != key
        or source.parent != epoch.control_root / "product-sources"
    ):
        raise ValueError("Coding Arch private-data Product authority changed")
    root = coding_arch_session_private_data_root(layout, key, session_id=session_id)
    if os.name == "nt":
        installation_root = coding_arch_installation_private_data_root(layout, key)
        bound_identity = _bind_windows_arch_installation_root(
            layout, key, state_root=epoch.control_root / "product-state"
        )
        prepare_windows_product_private_directory_chain(
            installation_root,
            *root.relative_to(installation_root).parts,
            inherit_leaf=True,
        )
        if (
            _bind_windows_arch_installation_root(
                layout, key, state_root=epoch.control_root / "product-state"
            )
            != bound_identity
        ):
            raise ValueError("Coding Arch private-data Installation root changed")
        runtime.capture_selected_plugin_manifest_for(
            _ARCH_PLUGIN_ID, max_files=64, max_total_bytes=1024 * 1024
        )
    else:
        _prepare_private_tree(root, private_base=layout.private_data_base, label="data")
    return root


def _bind_windows_arch_installation_root(
    layout: CodingPluginLifecycleStateLayout,
    key: PluginInstallationKeyV1,
    *,
    state_root: Path,
) -> tuple[int, int]:
    """Bind the current Installation root generation to Product state."""
    installation_root = coding_arch_installation_private_data_root(layout, key)
    return _windows_root_lineage().bind(
        key, installation_root, state_root=state_root, package_root=layout.package_root
    )


def inspect_coding_windows_arch_installation_root(
    layout: CodingPluginLifecycleStateLayout,
    key: PluginInstallationKeyV1,
    *,
    state_root: Path,
) -> tuple[int, int] | None:
    """Read one bound Windows Installation root without creating or repairing it."""
    installation_root = coding_arch_installation_private_data_root(layout, key)
    if (
        state_root
        != resolve_coding_package_epoch_layout(layout).control_root / "product-state"
    ):
        raise ValueError("Coding Arch private-data Product state root changed")
    return _windows_root_lineage().inspect(
        key, installation_root, state_root=state_root, package_root=layout.package_root
    )


def _prepare_windows_arch_restore_generation_intent(
    layout: CodingPluginLifecycleStateLayout,
    key: PluginInstallationKeyV1,
    *,
    state_root: Path,
    deletion_receipt_id: str,
) -> int:
    """Claim only the successor root retired by an exact deletion receipt.

    The restore owner calls this while holding offline Product authority, after
    its start event and before publishing any restored directory bytes.
    """
    root = coding_arch_installation_private_data_root(layout, key)
    if (
        state_root
        != resolve_coding_package_epoch_layout(layout).control_root / "product-state"
    ):
        raise ValueError("Coding Arch restore Product state root changed")
    return _windows_root_lineage().prepare_restore_intent(
        key,
        root,
        state_root=state_root,
        package_root=layout.package_root,
        deletion_receipt_id=deletion_receipt_id,
    )


def _publish_windows_arch_restored_root_receipt(
    layout: CodingPluginLifecycleStateLayout,
    key: PluginInstallationKeyV1,
    *,
    state_root: Path,
    generation_number: int,
    deletion_receipt_id: str,
    expected_identity: tuple[int, int],
) -> tuple[int, int]:
    """Bind a separately verified restored tree to the retired generation."""
    root = coding_arch_installation_private_data_root(layout, key)
    if (
        state_root
        != resolve_coding_package_epoch_layout(layout).control_root / "product-state"
    ):
        raise ValueError("Coding Arch restore Product state root changed")
    return _windows_root_lineage().publish_restored_receipt(
        key,
        root,
        state_root=state_root,
        package_root=layout.package_root,
        generation_number=generation_number,
        deletion_receipt_id=deletion_receipt_id,
        expected_identity=expected_identity,
    )


def _windows_arch_generation_paths(
    installation_root: Path, state_root: Path, number: int
) -> tuple[Path, Path]:
    return _windows_root_lineage().generation_paths(
        installation_root, state_root, number
    )


def _windows_arch_current_root_generation(
    key: PluginInstallationKeyV1,
    installation_root: Path,
    state_root: Path,
    package_root_identity: tuple[int, int],
    *,
    recover_stage: bool = False,
    allow_pending: bool = False,
) -> _WindowsArchRootGeneration:
    return _windows_root_lineage().current_generation(
        key,
        installation_root,
        state_root,
        package_root_identity,
        recover_stage=recover_stage,
        allow_pending=allow_pending,
    )


def _validate_windows_root_generation_names(
    names: tuple[str, ...], installation_root: Path, current_number: int
) -> None:
    return _windows_root_lineage().validate_generation_names(
        names, installation_root, current_number
    )


def _windows_arch_generation_intent_payload(
    key: PluginInstallationKeyV1,
    installation_root: Path,
    package_root_identity: tuple[int, int],
    number: int,
    predecessor_receipt_id: str | None,
) -> bytes:
    return _windows_root_lineage().generation_intent_payload(
        key, installation_root, package_root_identity, number, predecessor_receipt_id
    )


def _windows_arch_generation_receipt_payload(
    key: PluginInstallationKeyV1,
    installation_root: Path,
    parent_identity: tuple[int, int],
    identity: tuple[int, int],
    number: int,
    predecessor_receipt_id: str | None,
) -> bytes:
    return _windows_root_lineage().generation_receipt_payload(
        key,
        installation_root,
        parent_identity,
        identity,
        number,
        predecessor_receipt_id,
    )


__all__ = [
    "coding_arch_installation_private_data_root",
    "coding_arch_session_private_data_root",
    "inspect_coding_windows_arch_installation_root",
    "prepare_coding_product_arch_private_data_root",
]


def _windows_deletion_records_type() -> type[_DeletionRecords]:
    # Preserve the original lazy import before directory admission.
    from .package_private_data_windows_deletion_journal import (
        CodingWindowsArchPrivateDataDeletionTransaction,
    )

    return CodingWindowsArchPrivateDataDeletionTransaction


def _windows_root_lineage() -> _WindowsInstallationRootLineage[
    _WindowsArchRootGeneration
]:
    return _WindowsInstallationRootLineage(
        label="Coding Arch",
        receipt_prefix="arch-private-root-",
        maximum_receipt_bytes=_WINDOWS_ROOT_RECEIPT_MAX_BYTES,
        maximum_write_bytes=4 * 1024 * 1024,
        receipt_io=lambda: _receipts._receipt_io,
        receipt_error_type=lambda: CodingWindowsPrivateReceiptError,
        deletion_type=_windows_deletion_records_type,
        generation_type=lambda: _WindowsArchRootGeneration,
    )
