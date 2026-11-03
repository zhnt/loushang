from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.storage_budget import (
    ManagedStorageAllocationV1,
    ManagedStorageBudgetV1,
)

from . import test_managed_registry as registry_fixtures

namespace = registry_fixtures.namespace
registry = registry_fixtures.registry
intent = registry_fixtures.intent

MIB = 1024 * 1024
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed storage")


def allocation(registry, *, kind="log", slot=0, size=10 * MIB, instance=None, service=0):
    request = intent(f"mux{service}", f"{service + 1:032x}", f"/workspace/{service}")
    registry.reserve_mux(request)
    return ManagedStorageAllocationV1(request.service.service_id, kind, instance, slot, size,
                                     sha256(f"root{service}".encode()).hexdigest(), (1, service + 1))


def test_exact_reservation_and_file_binding_are_durable_not_write_authority(registry):
    budget = ManagedStorageBudgetV1(registry)
    request = allocation(registry)
    first = budget.reserve(request)
    assert first.allocation == request and first.file_identity is None
    assert budget.reserve(request) == first
    bound = budget.bind_file(first, (1, 1024))
    assert bound.file_identity == (1, 1024)
    assert ManagedStorageBudgetV1(registry).reserve(request) == bound
    assert budget.bind_file(first, (1, 1024)) == bound
    with pytest.raises(ManagedStorageError, match="conflict"):
        budget.bind_file(first, (1, 2048))
    assert not hasattr(budget, "release") and not hasattr(bound, "write")


@pytest.mark.parametrize("field,value", [("capacity", MIB), ("root_key", "f" * 64),
                                          ("root_identity", (2, 1))])
def test_slot_cannot_be_retargeted_or_refunded(registry, field, value):
    budget = ManagedStorageBudgetV1(registry)
    request = allocation(registry, kind="temporary", size=2 * MIB, instance="a" * 32)
    budget.reserve(request)
    with pytest.raises(ManagedStorageError, match="conflict"):
        budget.reserve(replace(request, **{field: value}))
    assert budget.lookup(request) is not None


def test_log_and_trace_share_namespace_budget_across_services_and_reopen(registry):
    budget = ManagedStorageBudgetV1(registry)
    for service in range(4):
        for slot in range(5):
            budget.reserve(allocation(registry, slot=slot, service=service))
    extra = allocation(registry, kind="trace", service=4)
    with pytest.raises(ManagedStorageError, match="capacity"):
        ManagedStorageBudgetV1(registry).reserve(extra)
    assert budget.reserve(allocation(registry)).allocation.slot == 0
    with registry._database.transaction() as connection:
        assert connection.execute("SELECT sum(capacity) FROM storage_allocations").fetchone() == (200 * MIB,)


def test_temporary_limits_count_all_instances_and_unbound_reservations(registry):
    budget = ManagedStorageBudgetV1(registry)
    for index in range(4):
        budget.reserve(allocation(registry, kind="temporary", size=128 * MIB, instance=f"{index:032x}"))
    for instance in ("0" * 32, "f" * 32):
        with pytest.raises(ManagedStorageError, match="capacity"):
            budget.reserve(allocation(registry, kind="temporary", size=4096, slot=1, instance=instance))
    # A different kind has a separate byte budget.
    assert budget.reserve(allocation(registry)).file_identity is None


def test_temporary_instance_cannot_borrow_another_instances_unused_budget(registry):
    budget = ManagedStorageBudgetV1(registry)
    budget.reserve(allocation(registry, kind="temporary", size=128 * MIB, instance="a" * 32))
    with pytest.raises(ManagedStorageError, match="capacity"):
        budget.reserve(allocation(registry, kind="temporary", size=4096, slot=1, instance="a" * 32))
    budget.reserve(allocation(registry, kind="temporary", size=4096, instance="b" * 32))


@pytest.mark.parametrize("changes", [
    {"kind": "raw_stderr"}, {"slot": True}, {"slot": 5}, {"capacity": 1},
    {"kind": "trace", "slot": 2}, {"instance_id": "a" * 32},
    {"kind": "temporary"}, {"root_identity": (True, 1)}, {"root_key": "private/path"},
    {"kind": "temporary", "instance_id": "a" * 32, "slot": 256, "capacity": 4096},
])
def test_invalid_allocations_are_rejected_before_transactions(registry, changes):
    with pytest.raises(ValueError):
        replace(allocation(registry), **changes)


def test_committed_but_lost_receipt_remains_charged_once(registry, monkeypatch):
    budget = ManagedStorageBudgetV1(registry)
    request = allocation(registry)
    original = registry._database.transaction
    @contextmanager
    def lost(**kwargs):
        with original(**kwargs) as connection:
            yield connection
        if kwargs.get("write"):
            raise ManagedStorageError("unavailable")
    monkeypatch.setattr(registry._database, "transaction", lost)
    with pytest.raises(ManagedStorageError, match="unavailable"):
        budget.reserve(request)
    monkeypatch.setattr(registry._database, "transaction", original)
    recorded = budget.lookup(request)
    assert recorded is not None and budget.reserve(request) == recorded
    with original() as connection:
        assert connection.execute("SELECT count(*),sum(capacity) FROM storage_allocations").fetchone() == (1, 10 * MIB)
    monkeypatch.setattr(registry._database, "transaction", lost)
    with pytest.raises(ManagedStorageError, match="unavailable"):
        budget.bind_file(recorded, (1, 2048))
    monkeypatch.setattr(registry._database, "transaction", original)
    assert budget.lookup(request).file_identity == (1, 2048)
    assert budget.bind_file(recorded, (1, 2048)) == budget.lookup(request)


def child(root, namespace, request, *, mode="reserve"):
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("_storage_budget_child.py")), str(root),
         namespace.platform_home, json.dumps(asdict(request)), mode],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
    )


def test_two_processes_compete_for_last_namespace_segment(registry, namespace, tmp_path):
    budget = ManagedStorageBudgetV1(registry)
    for service in range(4):
        for slot in range(5 if service < 3 else 4):
            budget.reserve(allocation(registry, service=service, slot=slot))
    requests = [allocation(registry, service=service) for service in (4, 5)]
    children = [child(tmp_path / "registry", namespace, request) for request in requests]
    try:
        assert [process.stdout.readline().strip() for process in children] == ["ready", "ready"]
        with ThreadPoolExecutor(max_workers=2) as executor:
            outputs = list(executor.map(lambda process: process.communicate("go\n", timeout=15), children))
        assert all(process.returncode == 0 for process in children)
        assert sorted(output[0].strip() for output in outputs) == ["capacity", "reserved"]
        with registry._database.transaction() as connection:
            assert connection.execute("SELECT count(*),sum(capacity) FROM storage_allocations").fetchone() == (20, 200 * MIB)
    finally:
        for process in children:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)


def test_process_exit_after_reservation_does_not_refund_or_duplicate(registry, namespace, tmp_path):
    request = allocation(registry)
    process = child(tmp_path / "registry", namespace, request, mode="crash")
    try:
        assert process.stdout.readline().strip() == "ready"
        process.communicate("go\n", timeout=15)
        assert process.returncode == 23
        recorded = ManagedStorageBudgetV1(registry).lookup(request)
        assert recorded is not None and recorded.file_identity is None
        assert ManagedStorageBudgetV1(registry).reserve(request) == recorded
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)


def test_row_capacity_is_independent_of_bytes_and_does_not_block_existing_receipts(registry):
    budget = ManagedStorageBudgetV1(registry)
    first = allocation(registry, kind="temporary", size=4096, instance="0" * 32)
    # Exact schema fixture: 16 MiB, well below both byte ceilings; no files exist.
    with registry._database.transaction(write=True) as connection:
        connection.executemany("INSERT INTO storage_allocations VALUES (?,?,?,?,?,?,?,?,?,NULL,NULL)", [
            ("74656d7000000000" + f"{index + 1:016x}", first.service_id, "temporary", f"{index // 256:032x}",
             index % 256, 4096, first.root_key, *first.root_identity) for index in range(4096)
        ])
        connection.execute("UPDATE identity SET temporary_high_water=4096")
    existing = budget.lookup(first)
    assert existing is not None and budget.reserve(first) == existing
    assert budget.bind_file(existing, (1, 2048)).file_identity == (1, 2048)
    assert budget.reserve(first).file_identity == (1, 2048)
    with pytest.raises(ManagedStorageError, match="capacity"):
        budget.reserve(replace(first, instance_id=f"{16:032x}"))
    with registry._database.transaction() as connection:
        assert connection.execute("SELECT count(*),sum(capacity) FROM storage_allocations").fetchone() == (4096, 16 * MIB)
