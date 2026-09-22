from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.registry import ManagedMuxCreationInspectionV1

from .test_managed_registry import intent
from .test_managed_registry import namespace as namespace
from .test_managed_registry import registry as registry


def snapshot(root):
    return {str(path.relative_to(root)): (path.lstat().st_mode, path.lstat().st_ino,
                                         path.lstat().st_mtime_ns,
                                         path.read_bytes() if path.is_file() else None)
            for path in (root, *sorted(root.rglob("*")))}


def test_exact_creation_inspection_is_readonly_before_service_and_after_name_reuse(registry, tmp_path):
    first = intent()
    registry.reserve_mux(first)
    original = snapshot(tmp_path)
    assert registry.inspect_mux_creation("f" * 32) is None
    result = registry.inspect_mux_creation(first.operation_id)
    assert result == ManagedMuxCreationInspectionV1(first, True, None)
    with pytest.raises(FrozenInstanceError):
        result.active = False
    assert snapshot(tmp_path) == original
    with registry._database.transaction(write=True) as connection:
        connection.execute("INSERT INTO mux_authorities VALUES (?, ?, ?, ?, ?, ?)",
                           (first.operation_id, "c" * 32, "c" * 32, "d" * 64, "c" * 32, "old-mux"))
        connection.execute("DELETE FROM muxes WHERE operation_id=?", (first.operation_id,))
    second = intent(operation="e" * 32)
    registry.reserve_mux(second)
    original = snapshot(tmp_path)
    old = registry.inspect_mux_creation(first.operation_id)
    assert old.reservation == first and not old.active
    assert old.created.operation_id == first.operation_id and old.created.mux_space_id == "old-mux"
    assert registry.inspect_mux_creation(second.operation_id) == ManagedMuxCreationInspectionV1(second, True, None)
    assert snapshot(tmp_path) == original
    assert "authority" not in repr(old)


@pytest.mark.parametrize("column,value", [("origin_instance_id", "e" * 32), ("created_instance_id", "d" * 32),
                                          ("mux_space_id", "invalid id")])
def test_inspection_rejects_corrupt_creation_without_writes(registry, tmp_path, column, value):
    first = intent()
    registry.reserve_mux(first)
    with registry._database.transaction(write=True) as connection:
        connection.execute("INSERT INTO mux_authorities VALUES (?, ?, ?, ?, ?, ?)",
                           (first.operation_id, "c" * 32, "c" * 32, "d" * 64, "c" * 32, "mux"))
        connection.execute(f"UPDATE mux_authorities SET {column}=?", (value,))
    original = snapshot(tmp_path)
    with pytest.raises(ManagedStorageError, match="invalid_record"):
        registry.inspect_mux_creation(first.operation_id)
    assert snapshot(tmp_path) == original


@pytest.mark.parametrize("present", [False, True])
def test_final_deadline_applies_to_empty_and_present_results(registry, tmp_path, monkeypatch, present):
    from loushang.apphost.managed import registry as module

    first = intent()
    if present:
        registry.reserve_mux(first)
    original = snapshot(tmp_path)
    checked = []

    def expired(deadline):
        checked.append(deadline)
        raise ManagedStorageError("unavailable")

    monkeypatch.setattr(module, "_check_deadline", expired)
    with pytest.raises(ManagedStorageError, match="unavailable"):
        registry.inspect_mux_creation(first.operation_id)
    assert checked == [None] and snapshot(tmp_path) == original
