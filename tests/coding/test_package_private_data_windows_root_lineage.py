"""Portable lineage checks for native Windows Arch private roots."""

from __future__ import annotations

import os
import stat
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.package_installation_private_data as root_module
from loushang.coding.package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionEventV1,
)
from loushang.coding.package_private_data_deletion_preview import (
    CodingArchPrivateDataTargetSnapshotV1,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionPlanV1,
    PluginPrivateDataDeletionReceiptV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1


def _completed_deletion(
    key: PluginInstallationKeyV1,
    root: Path,
    identity: tuple[int, int],
    *,
    revision: int,
) -> CodingArchPrivateDataDeletionEventV1:
    target = CodingArchPrivateDataTargetSnapshotV1(
        root_path_digest=sha256(os.fsencode(str(root))).hexdigest(),
        root_identity=(*identity, stat.S_IFDIR | 0o700, 0, 1),
        members=(),
    )
    plan = PluginPrivateDataDeletionPlanV1(
        key, "coding.arch.private-data:windows-v1", target.target_id
    )
    confirmation = PluginPrivateDataDeletionConfirmationV1(
        plan_fingerprint=plan.fingerprint,
        confirmation_id=f"root-generation:{revision}",
    )
    receipt = PluginPrivateDataDeletionReceiptV1(
        installation_key=key,
        owner_id=plan.owner_id,
        target_id=plan.target_id,
        plan_fingerprint=plan.fingerprint,
        confirmation_id=confirmation.confirmation_id,
        receipt_id=f"deletion-receipt:{revision}",
        disposition="deleted",
    )
    return CodingArchPrivateDataDeletionEventV1(
        revision, "completed", plan, confirmation, target, receipt
    )


def test_windows_arch_root_generations_follow_completed_deletions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace:" + "a" * 64,
        plugin_id="coding.arch.default",
    )
    root = tmp_path / "installation-private-data" / ("b" * 64)
    state_root = tmp_path / "product-state"
    package_identity = (1, 2)
    parent_identity = (3, 4)
    first_identity = (5, 6)
    second_identity = (7, 8)
    records: dict[Path, bytes] = {}
    events: tuple[CodingArchPrivateDataDeletionEventV1, ...] = ()
    monkeypatch.setattr(
        root_module, "read_windows_private_receipt", lambda path, **_kwargs: records.get(path)
    )
    monkeypatch.setattr(
        root_module,
        "inspect_windows_product_private_directory_identity",
        lambda _path: parent_identity,
    )
    monkeypatch.setattr(
        root_module, "_windows_arch_root_deletion_events", lambda _path: events
    )
    monkeypatch.setattr(
        root_module,
        "_require_no_future_windows_root_generations",
        lambda _state, _root, _number: None,
    )
    first_intent, first_receipt = root_module._windows_arch_generation_paths(
        root, state_root, 1
    )
    records[first_intent] = root_module._windows_arch_generation_intent_payload(
        key, root, package_identity, 1, None
    )
    records[first_receipt] = root_module._windows_arch_generation_receipt_payload(
        key, root, parent_identity, first_identity, 1, None
    )
    current = root_module._windows_arch_current_root_generation(
        key, root, state_root, package_identity
    )
    assert (current.number, current.identity) == (1, first_identity)

    first_deletion = _completed_deletion(key, root, first_identity, revision=3)
    assert first_deletion.receipt is not None
    events = (first_deletion,)
    current = root_module._windows_arch_current_root_generation(
        key, root, state_root, package_identity
    )
    assert (current.number, current.identity) == (2, None)
    assert current.predecessor_receipt_id == first_deletion.receipt.receipt_id

    second_intent, second_receipt = root_module._windows_arch_generation_paths(
        root, state_root, 2
    )
    records[second_intent] = root_module._windows_arch_generation_intent_payload(
        key, root, package_identity, 2, current.predecessor_receipt_id
    )
    records[second_receipt] = root_module._windows_arch_generation_receipt_payload(
        key,
        root,
        parent_identity,
        second_identity,
        2,
        current.predecessor_receipt_id,
    )
    current = root_module._windows_arch_current_root_generation(
        key, root, state_root, package_identity
    )
    assert (current.number, current.identity) == (2, second_identity)

    second_deletion = _completed_deletion(key, root, second_identity, revision=6)
    assert second_deletion.receipt is not None
    events = (first_deletion, second_deletion)
    current = root_module._windows_arch_current_root_generation(
        key, root, state_root, package_identity
    )
    assert (current.number, current.identity) == (3, None)
    assert current.predecessor_receipt_id == second_deletion.receipt.receipt_id

    events = (_completed_deletion(key, root, (99, 100), revision=3),)
    with pytest.raises(ValueError, match="retirement changed"):
        root_module._windows_arch_current_root_generation(
            key, root, state_root, package_identity
        )
    events = (first_deletion,)
    records[second_intent] = root_module._windows_arch_generation_intent_payload(
        key, root, package_identity, 2, "wrong-predecessor"
    )
    with pytest.raises(ValueError, match="root intent changed"):
        root_module._windows_arch_current_root_generation(
            key, root, state_root, package_identity
        )
    events = (
        first_deletion,
        replace(second_deletion, revision=4, phase="started", receipt=None),
    )
    with pytest.raises(ValueError, match="deletion is unfinished"):
        root_module._windows_arch_current_root_generation(
            key, root, state_root, package_identity
        )


def test_windows_arch_root_rebinds_only_after_completed_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace:" + "a" * 64,
        plugin_id="coding.arch.default",
    )
    package_root = tmp_path / "packages"
    root = package_root / "installation-private-data" / ("b" * 64)
    state_root = tmp_path / "product-state"
    package_identity = (1, 2)
    parent_identity = (3, 4)
    records: dict[Path, bytes] = {}
    first_intent, first_receipt = root_module._windows_arch_generation_paths(
        root, state_root, 1
    )
    records[first_intent] = root_module._windows_arch_generation_intent_payload(
        key, root, package_identity, 1, None
    )
    records[first_receipt] = root_module._windows_arch_generation_receipt_payload(
        key, root, parent_identity, (5, 6), 1, None
    )
    deletion = _completed_deletion(key, root, (5, 6), revision=3)
    monkeypatch.setattr(
        root_module, "coding_arch_installation_private_data_root", lambda _layout, _key: root
    )
    monkeypatch.setattr(
        root_module, "_windows_arch_root_deletion_events", lambda _path: (deletion,)
    )
    monkeypatch.setattr(
        root_module,
        "_require_no_future_windows_root_generations",
        lambda _state, _root, _number: None,
    )
    monkeypatch.setattr(
        root_module, "read_windows_private_receipt", lambda path, **_kwargs: records.get(path)
    )
    monkeypatch.setattr(
        root_module, "write_windows_private_receipt", lambda path, payload: records.setdefault(path, payload)
    )
    monkeypatch.setattr(
        root_module,
        "prepare_windows_product_private_directory_chain",
        lambda _package_root, *_parts: root.mkdir(parents=True, exist_ok=True),
    )

    def identity(path: Path) -> tuple[int, int]:
        if path == package_root:
            return package_identity
        if path == root.parent:
            return parent_identity
        metadata = path.stat()
        return metadata.st_dev, metadata.st_ino

    monkeypatch.setattr(
        root_module, "inspect_windows_product_private_directory_identity", identity
    )
    layout = SimpleNamespace(package_root=package_root)
    rebound = root_module._bind_windows_arch_installation_root(
        layout, key, state_root=state_root  # type: ignore[arg-type]
    )
    second_intent, second_receipt = root_module._windows_arch_generation_paths(
        root, state_root, 2
    )
    assert second_intent in records and second_receipt in records
    assert root_module._bind_windows_arch_installation_root(
        layout, key, state_root=state_root  # type: ignore[arg-type]
    ) == rebound
    root.rename(root.with_name("moved-root"))
    root.mkdir()
    with pytest.raises(ValueError, match="Installation root changed"):
        root_module._bind_windows_arch_installation_root(
            layout, key, state_root=state_root  # type: ignore[arg-type]
        )


def test_windows_restore_publishes_only_the_retired_successor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace:" + "a" * 64,
        plugin_id="coding.arch.default",
    )
    package_root = tmp_path / "packages"
    parent = package_root / "installation-private-data"
    parent.mkdir(parents=True)
    root = parent / ("b" * 64)
    state_root = tmp_path / "product-state"
    state_root.mkdir()
    layout = SimpleNamespace(package_root=package_root)
    records: dict[Path, bytes] = {}
    package_identity, parent_identity, first_identity = (1, 2), (3, 4), (5, 6)
    first_intent, first_receipt = root_module._windows_arch_generation_paths(
        root, state_root, 1
    )
    records[first_intent] = root_module._windows_arch_generation_intent_payload(
        key, root, package_identity, 1, None
    )
    records[first_receipt] = root_module._windows_arch_generation_receipt_payload(
        key, root, parent_identity, first_identity, 1, None
    )
    deletion = _completed_deletion(key, root, first_identity, revision=3)
    assert deletion.receipt is not None
    monkeypatch.setattr(
        root_module, "coding_arch_installation_private_data_root", lambda _layout, _key: root
    )
    monkeypatch.setattr(
        root_module,
        "resolve_coding_package_epoch_layout",
        lambda _layout: SimpleNamespace(control_root=tmp_path),
    )
    monkeypatch.setattr(
        root_module, "_windows_arch_root_deletion_events", lambda _path: (deletion,)
    )
    monkeypatch.setattr(
        root_module,
        "_require_no_future_windows_root_generations",
        lambda _state, _root, _number: None,
    )
    monkeypatch.setattr(
        root_module, "read_windows_private_receipt", lambda path, **_kwargs: records.get(path)
    )

    def write_receipt(path: Path, payload: bytes) -> None:
        if path in records and records[path] != payload:
            raise FileExistsError(path)
        records[path] = payload

    monkeypatch.setattr(root_module, "write_windows_private_receipt", write_receipt)

    def identity(path: Path) -> tuple[int, int]:
        if path == package_root:
            return package_identity
        if path == parent:
            return parent_identity
        metadata = path.stat()
        return metadata.st_dev, metadata.st_ino

    monkeypatch.setattr(
        root_module, "inspect_windows_product_private_directory_identity", identity
    )
    receipt_id = deletion.receipt.receipt_id
    with pytest.raises(ValueError, match="generation changed"):
        root_module._prepare_windows_arch_restore_generation_intent(
            layout, key, state_root=state_root, deletion_receipt_id="wrong"
        )  # type: ignore[arg-type]
    number = root_module._prepare_windows_arch_restore_generation_intent(
        layout, key, state_root=state_root, deletion_receipt_id=receipt_id
    )  # type: ignore[arg-type]
    assert number == 2
    assert root_module._prepare_windows_arch_restore_generation_intent(
        layout, key, state_root=state_root, deletion_receipt_id=receipt_id
    ) == 2  # type: ignore[arg-type]
    root.mkdir()
    root_identity = identity(root)
    with pytest.raises(ValueError, match="identity changed"):
        root_module._publish_windows_arch_restored_root_receipt(
            layout,
            key,
            state_root=state_root,
            generation_number=number,
            deletion_receipt_id=receipt_id,
            expected_identity=(99, 100),
        )  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="already present"):
        root_module._prepare_windows_arch_restore_generation_intent(
            layout, key, state_root=state_root, deletion_receipt_id=receipt_id
        )  # type: ignore[arg-type]
    assert root_module._publish_windows_arch_restored_root_receipt(
        layout,
        key,
        state_root=state_root,
        generation_number=number,
        deletion_receipt_id=receipt_id,
        expected_identity=root_identity,
    ) == root_identity  # type: ignore[arg-type]
    assert root_module._publish_windows_arch_restored_root_receipt(
        layout,
        key,
        state_root=state_root,
        generation_number=number,
        deletion_receipt_id=receipt_id,
        expected_identity=root_identity,
    ) == root_identity  # type: ignore[arg-type]


def test_windows_arch_root_refuses_future_generation_members(tmp_path: Path) -> None:
    root = tmp_path / ("b" * 64)
    prefix = f"arch-private-root-{root.name}.generation-"
    root_module._validate_windows_root_generation_names(
        (prefix + "00000002.intent.json", prefix + "00000002.json"), root, 2
    )
    with pytest.raises(ValueError, match="generation is unexpected"):
        root_module._validate_windows_root_generation_names(
            (prefix + "00000003.intent.json",), root, 2
        )
    with pytest.raises(ValueError, match="generation is unexpected"):
        root_module._validate_windows_root_generation_names(
            (prefix + "00000002.evil.json",), root, 2
        )
