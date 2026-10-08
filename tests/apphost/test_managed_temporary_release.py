import os
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
from time import monotonic

import pytest

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.storage_budget import ManagedStorageBudgetV1

from .test_managed_files import directory as directory
from .test_managed_storage_budget import allocation
from .test_managed_storage_budget import namespace as namespace
from .test_managed_storage_budget import pytestmark as pytestmark
from .test_managed_storage_budget import registry as registry


def prepare(registry, directory, *, name="stdout", slot=0, snapshot=None):
    root, owner = directory
    if snapshot is None:
        with owner.lock("data.lock", create=True):
            snapshot = owner.append_data(name, b"original", expected=None, capacity=4096)
    request = replace(allocation(registry, kind="temporary", slot=slot, size=4096, instance="a" * 32),
                      root_key=sha256(os.fsencode(root)).hexdigest(), root_identity=owner._identity)
    budget = ManagedStorageBudgetV1(registry)
    reserved = budget.bind_file(budget.reserve(request), snapshot.identity)
    removal = owner.prepare_data_removal(name, "removed-" + name, expected=snapshot, capacity=4096)
    return budget, reserved, removal


def test_release_requires_completion_and_does_not_touch_reused_slot(registry, directory):
    budget, reserved, removal = prepare(registry, directory)
    _, owner = directory
    binding = budget.prepare_temporary_release(reserved, owner=owner, removal=removal)
    with pytest.raises(ManagedStorageError, match="unavailable"):
        budget.release_temporary(binding)
    assert budget.lookup(reserved.allocation) == reserved
    with owner.lock("data.lock"):
        owner.remove_data(removal)
    budget.release_temporary(binding)
    assert budget.lookup(reserved.allocation) is None
    replacement = budget.reserve(reserved.allocation)
    assert replacement.allocation_id != reserved.allocation_id
    budget.release_temporary(binding)
    assert budget.lookup(reserved.allocation) == replacement


def test_cross_binding_two_valid_files_cannot_release_the_wrong_charge(registry, directory):
    root, owner = directory
    with owner.lock("data.lock", create=True):
        first_snapshot = owner.append_data("stdout", b"original", expected=None, capacity=4096)
        second_snapshot = owner.append_data("stderr", b"original", expected=None, capacity=4096)
    budget, first, first_removal = prepare(registry, directory, snapshot=first_snapshot)
    second_budget, second, second_removal = prepare(
        registry, directory, name="stderr", slot=1, snapshot=second_snapshot,
    )
    binding = budget.prepare_temporary_release(first, owner=owner, removal=first_removal)
    with pytest.raises(ManagedStorageError, match="conflict"):
        second_budget.prepare_temporary_release(first, owner=owner, removal=second_removal)
    assert (root / "stderr").read_bytes() == b"original"
    assert budget.lookup(first.allocation) == first
    assert budget.lookup(second.allocation) == second
    valid = second_budget.prepare_temporary_release(second, owner=owner, removal=second_removal)
    with owner.lock("data.lock"):
        owner.remove_data(first_removal)
        owner.remove_data(second_removal)
    budget.release_temporary(binding)
    assert budget.lookup(second.allocation) == second
    second_budget.release_temporary(valid)


def test_unknown_release_commit_retries_accounting_only(registry, directory, monkeypatch):
    budget, reserved, removal = prepare(registry, directory)
    _, owner = directory
    binding = budget.prepare_temporary_release(reserved, owner=owner, removal=removal)
    with owner.lock("data.lock"):
        owner.remove_data(removal)
    original = budget._database.transaction

    @contextmanager
    def lost_receipt(**kwargs):
        with original(**kwargs) as connection:
            yield connection
        raise OSError("commit receipt lost")

    with monkeypatch.context() as patch:
        patch.setattr(budget._database, "transaction", lost_receipt)
        with pytest.raises(OSError, match="commit receipt lost"):
            budget.release_temporary(binding)
    assert budget.lookup(reserved.allocation) is None

    def no_delete(*args, **kwargs):
        raise AssertionError("accounting retry must not delete files")
    monkeypatch.setattr(os, "unlink", no_delete)
    budget.release_temporary(binding)


def test_release_capacity_failure_keeps_original_charge_and_completion(registry, directory, monkeypatch):
    budget, reserved, removal = prepare(registry, directory)
    _, owner = directory
    binding = budget.prepare_temporary_release(reserved, owner=owner, removal=removal)
    with owner.lock("data.lock"):
        owner.remove_data(removal)

    def reject(connection):
        raise ManagedStorageError("capacity")

    with monkeypatch.context() as patch:
        patch.setattr(budget._database, "admit_growth", reject)
        with pytest.raises(ManagedStorageError, match="capacity"):
            budget.release_temporary(binding)
        assert budget.lookup(reserved.allocation) == reserved
    assert removal.phase == "complete"
    budget.release_temporary(binding)
    with monkeypatch.context() as patch:
        patch.setattr(budget._database, "admit_growth", reject)
        budget.release_temporary(binding)  # Already missing: no mutation admission.


@pytest.mark.parametrize("expired", [False, True])
def test_release_deadline_covers_native_completion_mutex(registry, directory, monkeypatch, expired):
    budget, reserved, removal = prepare(registry, directory)
    _, owner = directory
    binding = budget.prepare_temporary_release(reserved, owner=owner, removal=removal)
    with owner.lock("data.lock"):
        owner.remove_data(removal)
    waits = []

    class HeldMutex:
        def acquire(self, *, timeout):
            assert not expired, "expired calls must not enter the mutex"
            waits.append(timeout)
            assert 0 <= timeout <= 1
            return False

    def no_database(**kwargs):
        raise AssertionError("completion deadline must fail before database entry")

    with monkeypatch.context() as patch:
        patch.setattr(owner, "_mutex", HeldMutex())
        patch.setattr(budget._database, "transaction", no_database)
        with pytest.raises(ManagedStorageError, match="busy"):
            budget.release_temporary(binding, deadline=monotonic() + (-1 if expired else 1))
    assert len(waits) == (0 if expired else 1)
    assert budget.lookup(reserved.allocation) == reserved
    budget.release_temporary(binding)
