import os
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256

import pytest

from loushang.apphost.managed import storage_budget
from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.storage_budget import ManagedStorageBudgetV1

from .test_managed_files import directory as directory
from .test_managed_storage_budget import allocation
from .test_managed_storage_budget import namespace as namespace
from .test_managed_storage_budget import pytestmark as pytestmark
from .test_managed_storage_budget import registry as registry


def prepare(registry, directory):
    root, owner = directory
    allocations = tuple(replace(
        allocation(registry, kind="temporary", slot=slot, size=4096, instance="a" * 32),
        root_key=sha256(os.fsencode(root)).hexdigest(), root_identity=owner._identity,
    ) for slot in (0, 1))
    budget = ManagedStorageBudgetV1(registry)
    attempt = budget.prepare_temporary_creation(allocations, owner=owner)
    return budget, attempt


def test_uncreated_release_never_uses_other_stream_proof(registry, directory):
    root, owner = directory
    budget, attempt = prepare(registry, directory)
    first, second = attempt.creations
    reservations = budget.reserve_temporary_creation(attempt)
    with owner.lock("data.lock", create=True):
        owner.create_data(second, binding=attempt)  # File exists; inode is not bound yet.
    owner.fence_data_creation(first, binding=attempt)
    budget.release_uncreated_temporary(attempt, 0)
    with pytest.raises(ManagedStorageError, match="unavailable"):
        budget.release_uncreated_temporary(attempt, 1)
    assert budget.lookup(attempt.allocations[0]) is None
    assert budget.lookup(attempt.allocations[1]) == reservations[1]
    assert (root / second.name).exists()
    replacement = budget.reserve(attempt.allocations[0])
    budget.release_uncreated_temporary(attempt, 0)
    assert budget.lookup(attempt.allocations[0]) == replacement


def test_unknown_reserve_cannot_mint_uncreated_refund(registry, directory, monkeypatch):
    _, owner = directory
    budget, attempt = prepare(registry, directory)
    original = budget._database.transaction

    @contextmanager
    def lost_receipt(**kwargs):
        with original(**kwargs) as connection:
            yield connection
        raise OSError("lost reserve commit receipt")

    with monkeypatch.context() as patch:
        patch.setattr(budget._database, "transaction", lost_receipt)
        with pytest.raises(OSError):
            budget.reserve_temporary_creation(attempt)
    for creation in attempt.creations:
        owner.fence_data_creation(creation, binding=attempt)
    with pytest.raises(ManagedStorageError, match="unavailable"):
        budget.release_uncreated_temporary(attempt, 0)
    with pytest.raises(ManagedStorageError, match="conflict"):
        budget.reserve_temporary_creation(attempt)
    assert all(budget.lookup(allocation) is not None for allocation in attempt.allocations)
    result = budget.reconcile_temporary_creation(attempt)
    assert isinstance(result, tuple) and attempt.phase == "reserved"
    for index in (0, 1):
        budget.release_uncreated_temporary(attempt, index)
    with budget._database.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM storage_creation_origins").fetchone()[0] == 0


def test_unknown_refund_commit_retries_original_accounting_only(registry, directory, monkeypatch):
    _, owner = directory
    budget, attempt = prepare(registry, directory)
    budget.reserve_temporary_creation(attempt)
    for creation in attempt.creations:
        owner.fence_data_creation(creation, binding=attempt)
    original = budget._database.transaction

    @contextmanager
    def lost_receipt(**kwargs):
        with original(**kwargs) as connection:
            yield connection
        raise OSError("lost refund commit receipt")

    with monkeypatch.context() as patch:
        patch.setattr(budget._database, "transaction", lost_receipt)
        with pytest.raises(OSError):
            budget.release_uncreated_temporary(attempt, 0)
    budget.release_uncreated_temporary(attempt, 0)
    budget.release_uncreated_temporary(attempt, 1)
    assert all(budget.lookup(allocation) is None for allocation in attempt.allocations)


def test_capacity_refusal_then_released_space_allows_same_owner_retry(registry, directory, monkeypatch):
    from .test_managed_temporary_release import prepare as prepare_blocker

    _, owner = directory
    monkeypatch.setattr(storage_budget, "TEMPORARY_INSTANCE_BYTES", 8192)
    budget, blocker, removal = prepare_blocker(registry, directory, slot=2)
    release = budget.prepare_temporary_release(blocker, owner=owner, removal=removal)
    budget, attempt = prepare(registry, directory)
    refused = budget.reserve_temporary_creation(attempt)
    assert isinstance(refused, storage_budget.ManagedTemporaryPairCapacityRefusedV1)
    for creation in attempt.creations:
        owner.fence_data_creation(creation, binding=attempt)
    with owner.lock("data.lock"):
        owner.remove_data(removal)
    budget.release_temporary(release)
    budget, fresh = prepare(registry, directory)
    assert fresh.allocation_ids[0] > attempt.allocation_ids[1]
    result = budget.reserve_temporary_creation(fresh)
    assert isinstance(result, tuple)
    for index, creation in enumerate(fresh.creations):
        owner.fence_data_creation(creation, binding=fresh)
        budget.release_uncreated_temporary(fresh, index)


def test_rolled_back_attempt_cannot_adopt_other_origin_with_same_ids(registry, directory, monkeypatch):
    _, owner = directory
    budget, attempt = prepare(registry, directory)
    original = budget._database.transaction

    @contextmanager
    def rollback(**kwargs):
        with original(**kwargs) as connection:
            yield connection
            raise OSError("rollback original transaction")

    with monkeypatch.context() as patch:
        patch.setattr(budget._database, "transaction", rollback)
        with pytest.raises(ManagedStorageError, match="unavailable"):
            budget.reserve_temporary_creation(attempt)
    for creation in attempt.creations:
        owner.fence_data_creation(creation, binding=attempt)
    budget.reserve_temporary_pair(attempt.allocations, allocation_ids=attempt.allocation_ids,
                                  _creation_origin="b" * 32 if attempt.origin_id != "b" * 32 else "c" * 32)
    with pytest.raises(ManagedStorageError, match="conflict"):
        budget.reconcile_temporary_creation(attempt)
    assert attempt.phase == "unknown"
    assert all(budget.lookup(allocation) is not None for allocation in attempt.allocations)


def test_rolled_back_original_attempt_reconciles_absence_without_creation_authority(registry, directory, monkeypatch):
    _, owner = directory
    budget, attempt = prepare(registry, directory)
    original = budget._database.transaction

    @contextmanager
    def rollback(**kwargs):
        with original(**kwargs) as connection:
            yield connection
            raise OSError("rollback original transaction")

    with monkeypatch.context() as patch:
        patch.setattr(budget._database, "transaction", rollback)
        with pytest.raises(ManagedStorageError, match="unavailable"):
            budget.reserve_temporary_creation(attempt)
    assert budget.reconcile_temporary_creation(attempt) is None
    assert attempt.phase == "unreserved"
    assert all(creation._completion is None for creation in attempt.creations)
    with pytest.raises(ManagedStorageError, match="conflict"):
        budget.reserve_temporary_creation(attempt)
    for creation in attempt.creations:
        owner.fence_data_creation(creation, binding=attempt)


def test_second_origin_insert_failure_rolls_back_pair_and_sequence(registry, directory, monkeypatch):
    _, owner = directory
    budget, attempt = prepare(registry, directory)
    original = budget._database.transaction

    class Connection:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def execute(self, sql, parameters=()):
            if sql.startswith("INSERT INTO storage_creation_origins") and parameters[0] == attempt.allocation_ids[1]:
                raise OSError("second origin insert failed")
            return self.connection.execute(sql, parameters)

    @contextmanager
    def fail_second(**kwargs):
        with original(**kwargs) as connection:
            yield Connection(connection)

    with monkeypatch.context() as patch:
        patch.setattr(budget._database, "transaction", fail_second)
        with pytest.raises(ManagedStorageError, match="unavailable"):
            budget.reserve_temporary_creation(attempt)
    with original() as connection:
        assert connection.execute("SELECT count(*) FROM storage_creation_origins").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM storage_allocations").fetchone()[0] == 0
        assert connection.execute("SELECT temporary_high_water FROM identity").fetchone()[0] == 0
    assert budget.reconcile_temporary_creation(attempt) is None
    for creation in attempt.creations:
        owner.fence_data_creation(creation, binding=attempt)
