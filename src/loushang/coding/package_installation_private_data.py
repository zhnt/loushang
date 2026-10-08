"""Exact Installation-owned private root for Coding Product Arch Sessions.

Existing Session-owned caches retain their Session lifetime. Only a selected,
active Product runtime may prepare this new Installation subtree.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    windows_listdir_at,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    inspect_windows_product_private_directory_identity,
    prepare_windows_product_private_directory_chain,
)

from ._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    _prepare_private_tree,
)
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_legacy_windows_receipt import (
    CodingWindowsPrivateReceiptError,
    read_windows_private_receipt,
    write_windows_private_receipt,
)

_ARCH_PLUGIN_ID = "coding.arch.default"
_WINDOWS_ROOT_RECEIPT_MAX_BYTES = 4096
_WINDOWS_GENERATION_SUFFIX = re.compile(
    r"([0-9]{8})\.(?:intent\.)?json(?:\.stage)?\Z"
)

if TYPE_CHECKING:
    from .package_private_data_deletion_journal import (
        CodingArchPrivateDataDeletionEventV1,
    )


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
    layout: CodingPluginLifecycleStateLayout,
    key: PluginInstallationKeyV1,
) -> Path:
    """Map only the exact Coding Arch Installation to its private subtree."""

    if (
        not isinstance(layout, CodingPluginLifecycleStateLayout)
        or not isinstance(key, PluginInstallationKeyV1)
        or key.product_id != "coding"
        or key.installation_scope != "workspace"
        or key.scope_id != layout.scope_id
        or key.plugin_id != _ARCH_PLUGIN_ID
    ):
        raise ValueError("Coding Arch private-data Installation key changed")
    installation_id = sha256(
        b"loushang.coding-installation-private-data/v1\0"
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
        b"loushang.coding-installation-private-session/v1\0"
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
        or runtime.session_id != session_id
        or not isinstance(session_id, str)
        or not session_id
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
        # The selected Product runtime rechecks the same epoch after the
        # directory handles have been opened and before Arch receives a path.
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
    package_root_identity = inspect_windows_product_private_directory_identity(
        layout.package_root
    )
    generation = _windows_arch_current_root_generation(
        key, installation_root, state_root, package_root_identity, recover_stage=True
    )
    intent = _windows_arch_generation_intent_payload(
        key,
        installation_root,
        package_root_identity,
        generation.number,
        generation.predecessor_receipt_id,
    )
    if generation.intent is None:
        try:
            installation_root.lstat()
        except FileNotFoundError:
            pass
        else:
            raise ValueError("Coding Arch private-data root is unclaimed")
        _write_or_match_windows_root_receipt(generation.intent_path, intent)
    if generation.receipt is None:
        prepare_windows_product_private_directory_chain(
            layout.package_root,
            "installation-private-data",
            installation_root.name,
        )
        if any(installation_root.iterdir()):
            raise ValueError("Unbound Coding Arch private-data root is not empty")
    parent_identity = inspect_windows_product_private_directory_identity(
        installation_root.parent
    )
    identity = inspect_windows_product_private_directory_identity(installation_root)
    receipt = _windows_arch_generation_receipt_payload(
        key,
        installation_root,
        parent_identity,
        identity,
        generation.number,
        generation.predecessor_receipt_id,
    )
    if generation.receipt is not None and generation.receipt != receipt:
        raise ValueError("Coding Arch private-data Installation root changed")
    if generation.receipt is None:
        _write_or_match_windows_root_receipt(generation.receipt_path, receipt)
    return identity


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
    package_root_identity = inspect_windows_product_private_directory_identity(
        layout.package_root
    )
    generation = _windows_arch_current_root_generation(
        key, installation_root, state_root, package_root_identity
    )
    if generation.intent is None and generation.receipt is None:
        try:
            installation_root.lstat()
        except FileNotFoundError:
            return None
        raise ValueError("Coding Arch private-data root is unclaimed")
    if generation.receipt is None:
        raise ValueError("Coding Arch private-data root receipt is incomplete")
    parent_identity = inspect_windows_product_private_directory_identity(
        installation_root.parent
    )
    try:
        identity = inspect_windows_product_private_directory_identity(installation_root)
    except FileNotFoundError as exc:
        raise ValueError("Coding Arch private-data Installation root changed") from exc
    if generation.receipt != _windows_arch_generation_receipt_payload(
        key,
        installation_root,
        parent_identity,
        identity,
        generation.number,
        generation.predecessor_receipt_id,
    ):
        raise ValueError("Coding Arch private-data Installation root changed")
    return identity


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
    if state_root != resolve_coding_package_epoch_layout(layout).control_root / "product-state":
        raise ValueError("Coding Arch restore Product state root changed")
    package_identity = inspect_windows_product_private_directory_identity(
        layout.package_root
    )
    generation = _windows_arch_current_root_generation(
        key, root, state_root, package_identity, recover_stage=True
    )
    if (
        generation.number < 2
        or generation.predecessor_receipt_id != deletion_receipt_id
        or generation.receipt is not None
    ):
        raise ValueError("Coding Arch restore root generation changed")
    try:
        root.lstat()
    except FileNotFoundError:
        pass
    else:
        raise ValueError("Coding Arch restore root is already present")
    payload = _windows_arch_generation_intent_payload(
        key, root, package_identity, generation.number, deletion_receipt_id
    )
    _write_or_match_windows_root_receipt(generation.intent_path, payload)
    return generation.number


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
    if state_root != resolve_coding_package_epoch_layout(layout).control_root / "product-state":
        raise ValueError("Coding Arch restore Product state root changed")
    package_identity = inspect_windows_product_private_directory_identity(
        layout.package_root
    )
    generation = _windows_arch_current_root_generation(
        key, root, state_root, package_identity, recover_stage=True
    )
    if (
        generation.number != generation_number
        or generation.predecessor_receipt_id != deletion_receipt_id
        or generation.intent is None
        or (generation.identity is not None and generation.identity != expected_identity)
    ):
        raise ValueError("Coding Arch restore root generation changed")
    parent_identity = inspect_windows_product_private_directory_identity(root.parent)
    identity = inspect_windows_product_private_directory_identity(root)
    if identity != expected_identity:
        raise ValueError("Coding Arch restored root identity changed")
    payload = _windows_arch_generation_receipt_payload(
        key, root, parent_identity, identity, generation_number, deletion_receipt_id
    )
    _write_or_match_windows_root_receipt(generation.receipt_path, payload)
    return identity


def _windows_arch_root_receipt_paths(
    installation_root: Path, state_root: Path
) -> tuple[Path, Path]:
    basename = "arch-private-root-" + installation_root.name
    return state_root / (basename + ".intent.json"), state_root / (basename + ".json")


def _windows_arch_generation_paths(
    installation_root: Path, state_root: Path, number: int
) -> tuple[Path, Path]:
    if number == 1:
        return _windows_arch_root_receipt_paths(installation_root, state_root)
    if number < 2 or number > 4097:
        raise ValueError("Coding Arch private-data root generation is invalid")
    basename = f"arch-private-root-{installation_root.name}.generation-{number:08d}"
    return state_root / (basename + ".intent.json"), state_root / (basename + ".json")


def _windows_arch_current_root_generation(
    key: PluginInstallationKeyV1,
    installation_root: Path,
    state_root: Path,
    package_root_identity: tuple[int, int],
    *,
    recover_stage: bool = False,
    allow_pending: bool = False,
) -> _WindowsArchRootGeneration:
    events = _windows_arch_root_deletion_events(state_root)
    if (
        not allow_pending
        and events
        and events[-1].phase != "completed"
        and events[-1].plan.installation_key == key
    ):
        raise ValueError("Coding Arch private-data deletion is unfinished")
    completed = tuple(
        event
        for event in events
        if event.phase == "completed"
        and event.plan.installation_key == key
        and event.target.root_identity is not None
    )
    predecessor: str | None = None
    path_digest = sha256(os.fsencode(str(installation_root))).hexdigest()
    for number, event in enumerate(completed, start=1):
        target_identity = event.target.root_identity
        generation = _read_windows_arch_root_generation(
            key,
            installation_root,
            state_root,
            package_root_identity,
            number,
            predecessor,
            recover_stage=False,
        )
        if (
            generation.identity is None
            or target_identity is None
            or generation.identity != target_identity[:2]
            or event.target.root_path_digest != path_digest
            or event.receipt is None
            or event.receipt.disposition != "deleted"
        ):
            raise ValueError("Coding Arch private-data root retirement changed")
        predecessor = event.receipt.receipt_id
    _require_no_future_windows_root_generations(
        state_root, installation_root, len(completed) + 1
    )
    return _read_windows_arch_root_generation(
        key,
        installation_root,
        state_root,
        package_root_identity,
        len(completed) + 1,
        predecessor,
        recover_stage=recover_stage,
    )


def _windows_arch_root_deletion_events(
    state_root: Path,
) -> tuple[CodingArchPrivateDataDeletionEventV1, ...]:
    # The local import avoids a module cycle: the deletion journal also checks
    # the Installation root receipt before it can record a rename.
    from .package_private_data_windows_deletion_journal import (
        CodingWindowsArchPrivateDataDeletionTransaction,
    )

    with WindowsPrivateDirectoryAcl() as acl:
        descriptor = open_windows_directory(state_root, read_control=True)
        try:
            acl.validate(descriptor)
            transaction = CodingWindowsArchPrivateDataDeletionTransaction(
                state_root, descriptor
            )
            try:
                events = transaction.events()
            finally:
                transaction._close()
            acl.validate(descriptor)
            return events
        finally:
            os.close(descriptor)


def _require_no_future_windows_root_generations(
    state_root: Path, installation_root: Path, current_number: int
) -> None:
    with WindowsPrivateDirectoryAcl() as acl:
        descriptor = open_windows_directory(state_root, read_control=True)
        try:
            acl.validate(descriptor)
            _validate_windows_root_generation_names(
                windows_listdir_at(descriptor), installation_root, current_number
            )
            acl.validate(descriptor)
        finally:
            os.close(descriptor)


def _validate_windows_root_generation_names(
    names: tuple[str, ...], installation_root: Path, current_number: int
) -> None:
    prefix = f"arch-private-root-{installation_root.name}.generation-"
    for name in names:
        if not name.startswith(prefix):
            continue
        match = _WINDOWS_GENERATION_SUFFIX.fullmatch(name[len(prefix) :])
        if match is None or not 2 <= int(match.group(1)) <= current_number:
            raise ValueError("Coding Arch private-data root generation is unexpected")


def _read_windows_arch_root_generation(
    key: PluginInstallationKeyV1,
    installation_root: Path,
    state_root: Path,
    package_root_identity: tuple[int, int],
    number: int,
    predecessor_receipt_id: str | None,
    *,
    recover_stage: bool,
) -> _WindowsArchRootGeneration:
    intent_path, receipt_path = _windows_arch_generation_paths(
        installation_root, state_root, number
    )
    intent = read_windows_private_receipt(
        intent_path,
        maximum_bytes=_WINDOWS_ROOT_RECEIPT_MAX_BYTES,
        allow_unpublished_stage=recover_stage,
    )
    receipt = read_windows_private_receipt(
        receipt_path,
        maximum_bytes=_WINDOWS_ROOT_RECEIPT_MAX_BYTES,
        allow_unpublished_stage=recover_stage,
    )
    if intent is not None and intent != _windows_arch_generation_intent_payload(
        key,
        installation_root,
        package_root_identity,
        number,
        predecessor_receipt_id,
    ):
        raise ValueError("Coding Arch private-data root intent changed")
    if intent is None and receipt is not None:
        raise ValueError("Coding Arch private-data root receipt has no intent")
    identity: tuple[int, int] | None = None
    if receipt is not None:
        try:
            document = json.loads(receipt.decode("utf-8"))
            raw_identity = document["rootIdentity"]
        except (KeyError, TypeError, UnicodeError, ValueError) as exc:
            raise ValueError("Coding Arch private-data root receipt is invalid") from exc
        if (
            type(raw_identity) is not list
            or len(raw_identity) != 2
            or any(type(value) is not int or value < 0 for value in raw_identity)
        ):
            raise ValueError("Coding Arch private-data root identity is invalid")
        identity = (raw_identity[0], raw_identity[1])
        parent_identity = inspect_windows_product_private_directory_identity(
            installation_root.parent
        )
        if receipt != _windows_arch_generation_receipt_payload(
            key,
            installation_root,
            parent_identity,
            identity,
            number,
            predecessor_receipt_id,
        ):
            raise ValueError("Coding Arch private-data root receipt changed")
    return _WindowsArchRootGeneration(
        number,
        predecessor_receipt_id,
        intent_path,
        receipt_path,
        intent,
        receipt,
        identity,
    )


def _windows_arch_generation_intent_payload(
    key: PluginInstallationKeyV1,
    installation_root: Path,
    package_root_identity: tuple[int, int],
    number: int,
    predecessor_receipt_id: str | None,
) -> bytes:
    if number == 1:
        if predecessor_receipt_id is not None:
            raise ValueError("Initial Coding Arch root has a predecessor")
        return _windows_arch_root_intent_payload(
            key, installation_root, package_root_identity
        )
    if predecessor_receipt_id is None:
        raise ValueError("Successor Coding Arch root has no deletion receipt")
    return canonical_json_bytes(
        {
            "bindingVersion": 3,
            "generation": number,
            "installationKey": key.to_dict(),
            "packageRootIdentity": list(package_root_identity),
            "predecessorReceiptId": predecessor_receipt_id,
            "rootName": installation_root.name,
        }
    )


def _windows_arch_generation_receipt_payload(
    key: PluginInstallationKeyV1,
    installation_root: Path,
    parent_identity: tuple[int, int],
    identity: tuple[int, int],
    number: int,
    predecessor_receipt_id: str | None,
) -> bytes:
    if number == 1:
        if predecessor_receipt_id is not None:
            raise ValueError("Initial Coding Arch root has a predecessor")
        return _windows_arch_root_receipt_payload(
            key, installation_root, parent_identity, identity
        )
    if predecessor_receipt_id is None:
        raise ValueError("Successor Coding Arch root has no deletion receipt")
    return canonical_json_bytes(
        {
            "bindingVersion": 3,
            "generation": number,
            "installationKey": key.to_dict(),
            "parentIdentity": list(parent_identity),
            "predecessorReceiptId": predecessor_receipt_id,
            "rootIdentity": list(identity),
            "rootName": installation_root.name,
        }
    )


def _windows_arch_root_intent_payload(
    key: PluginInstallationKeyV1,
    installation_root: Path,
    package_root_identity: tuple[int, int],
) -> bytes:
    return canonical_json_bytes(
        {
            "bindingVersion": 1,
            "installationKey": key.to_dict(),
            "packageRootIdentity": list(package_root_identity),
            "rootName": installation_root.name,
        }
    )


def _windows_arch_root_receipt_payload(
    key: PluginInstallationKeyV1,
    installation_root: Path,
    parent_identity: tuple[int, int],
    identity: tuple[int, int],
) -> bytes:
    return canonical_json_bytes(
        {
            "bindingVersion": 2,
            "installationKey": key.to_dict(),
            "parentIdentity": list(parent_identity),
            "rootIdentity": list(identity),
            "rootName": installation_root.name,
        }
    )


def _write_or_match_windows_root_receipt(path: Path, payload: bytes) -> None:
    try:
        write_windows_private_receipt(path, payload)
    except (CodingWindowsPrivateReceiptError, FileExistsError):
        if (
            read_windows_private_receipt(
                path, maximum_bytes=_WINDOWS_ROOT_RECEIPT_MAX_BYTES
            )
            != payload
        ):
            raise
    if (
        read_windows_private_receipt(
            path, maximum_bytes=_WINDOWS_ROOT_RECEIPT_MAX_BYTES
        )
        != payload
    ):
        raise ValueError("Coding Arch private-data root receipt changed")


__all__ = [
    "coding_arch_installation_private_data_root",
    "coding_arch_session_private_data_root",
    "inspect_coding_windows_arch_installation_root",
    "prepare_coding_product_arch_private_data_root",
]
