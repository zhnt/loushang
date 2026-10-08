from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from threading import Barrier
from time import monotonic

import pytest

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.contracts import ManagedContractError
from loushang.apphost.managed.storage_budget import (
    ManagedStorageBudgetV1,
    ManagedTemporaryPairCapacityRefusedV1,
)

from .test_managed_storage_budget import allocation
from .test_managed_storage_budget import namespace as namespace
from .test_managed_storage_budget import pytestmark as pytestmark
from .test_managed_storage_budget import registry as registry

IDS = ("74656d70000000000000000000000001", "74656d70000000000000000000000002")
MIB = 1024 * 1024


def pair(registry, *, size=4096):
    first = allocation(registry, kind="temporary", size=size, instance="a" * 32)
    return first, replace(first, slot=1)


def test_pair_success_preserves_order_and_original_ids(registry):
    budget, request = ManagedStorageBudgetV1(registry), pair(registry)
    result = budget.reserve_temporary_pair(request, allocation_ids=IDS)
    assert tuple(item.allocation for item in result) == request
    assert tuple(item.allocation_id for item in result) == IDS
    assert tuple(budget.lookup(item) for item in request) == result
    assert budget.lookup_temporary_pair(request, allocation_ids=IDS) == result


def test_released_rows_do_not_allow_old_ids_to_be_admitted_again(registry):
    budget, request = ManagedStorageBudgetV1(registry), pair(registry)
    assert budget.next_temporary_pair_ids() == IDS
    budget.reserve_temporary_pair(request, allocation_ids=IDS)
    # Simulate settled accounting only: the real native-proof release API is
    # intentionally not under test here and is not implemented yet.
    with budget._database.transaction(write=True) as connection:
        connection.execute("DELETE FROM storage_allocations WHERE allocation_id IN (?,?)", IDS)
    next_ids = budget.next_temporary_pair_ids()
    assert next_ids == tuple("74656d7000000000" + f"{value:016x}" for value in (3, 4))
    with pytest.raises(ManagedStorageError, match="conflict"):
        budget.reserve_temporary_pair(request, allocation_ids=IDS)
    assert budget.lookup_temporary_pair(request, allocation_ids=IDS) is None
    assert budget.reserve_temporary_pair(request, allocation_ids=next_ids)[0].allocation_id == next_ids[0]


def test_single_temporary_reservation_uses_the_same_sequence(registry):
    budget, request = ManagedStorageBudgetV1(registry), pair(registry)
    first = budget.reserve(request[0])
    assert first.allocation_id == IDS[0]
    assert budget.next_temporary_pair_ids() == (
        IDS[1], "74656d70000000000000000000000003",
    )


def test_temporary_sequence_exhaustion_never_wraps(registry):
    budget = ManagedStorageBudgetV1(registry)
    with budget._database.transaction(write=True) as connection:
        connection.execute("UPDATE identity SET temporary_high_water=?", (2**63 - 1,))
    with pytest.raises(ManagedStorageError, match="capacity"):
        budget.next_temporary_pair_ids()


def test_noncanonical_temporary_id_rejected_before_read_or_candidate(registry):
    budget, request = ManagedStorageBudgetV1(registry), pair(registry)
    budget.reserve_temporary_pair(request, allocation_ids=IDS)
    with budget._database.transaction(write=True) as connection:
        connection.execute("UPDATE identity SET temporary_high_water=16")
        connection.execute("UPDATE storage_allocations SET allocation_id=? WHERE allocation_id=?",
                           ("74656d7000000000000000000000000A", IDS[0]))
    with pytest.raises(ManagedStorageError, match="invalid_record"):
        budget.next_temporary_pair_ids()
    with pytest.raises(ManagedStorageError, match="invalid_record"):
        registry.list_muxes()


def test_combined_capacity_refusal_has_no_partial_charge(registry):
    budget, request = ManagedStorageBudgetV1(registry), pair(registry, size=68 * MIB)
    result = budget.reserve_temporary_pair(request, allocation_ids=IDS)
    assert isinstance(result, ManagedTemporaryPairCapacityRefusedV1)
    assert result.allocations == request and result.namespace_key == registry._database._namespace
    assert result.allocation_ids == IDS
    assert all(budget.lookup(item) is None for item in request)


@pytest.mark.parametrize("slot", [0, 1])
def test_existing_slot_is_conflict_not_refusal_or_adoption(registry, slot):
    budget, request = ManagedStorageBudgetV1(registry), pair(registry, size=68 * MIB)
    existing = budget.reserve(request[slot])
    with pytest.raises(ManagedStorageError, match="conflict"):
        budget.reserve_temporary_pair(request, allocation_ids=IDS)
    assert budget.lookup(request[slot]) == existing and budget.lookup(request[1 - slot]) is None


def test_second_insert_failure_rolls_back_entire_pair(registry, monkeypatch):
    budget, request = ManagedStorageBudgetV1(registry), pair(registry)
    original = budget._database.transaction

    @contextmanager
    def transaction(**kwargs):
        with original(**kwargs) as connection:
            class Proxy:
                inserts = 0

                def execute(self, sql, args=()):
                    if sql.startswith("INSERT INTO storage_allocations"):
                        self.inserts += 1
                        if self.inserts == 2:
                            raise ManagedStorageError("unavailable")
                    return connection.execute(sql, args)

                def __getattr__(self, name):
                    return getattr(connection, name)
            yield Proxy()

    with monkeypatch.context() as patch:
        patch.setattr(budget._database, "transaction", transaction)
        with pytest.raises(ManagedStorageError, match="unavailable"):
            budget.reserve_temporary_pair(request, allocation_ids=IDS)
    assert all(budget.lookup(item) is None for item in request)


@pytest.mark.parametrize("refused", [True, False])
def test_transaction_exit_error_never_returns_capacity_refusal(registry, monkeypatch, refused):
    budget, request = ManagedStorageBudgetV1(registry), pair(registry, size=68 * MIB if refused else 4096)
    original = budget._database.transaction

    @contextmanager
    def transaction(**kwargs):
        with original(**kwargs) as connection:
            yield connection
        raise ManagedStorageError("capacity")  # Includes a lost commit receipt.

    with monkeypatch.context() as patch:
        patch.setattr(budget._database, "transaction", transaction)
        with pytest.raises(ManagedStorageError, match="capacity"):
            budget.reserve_temporary_pair(request, allocation_ids=IDS)
    rows = tuple(budget.lookup(item) for item in request)
    if refused:
        assert rows == (None, None)
    else:
        assert tuple(item.allocation_id for item in rows) == IDS
        assert budget.lookup_temporary_pair(request, allocation_ids=IDS) == rows


def test_pair_lookup_is_one_readonly_transaction(registry, monkeypatch):
    budget, request = ManagedStorageBudgetV1(registry), pair(registry)
    original = budget._database.transaction
    calls = []

    @contextmanager
    def transaction(**kwargs):
        calls.append(kwargs)
        with original(**kwargs) as connection:
            yield connection

    monkeypatch.setattr(budget._database, "transaction", transaction)
    assert budget.lookup_temporary_pair(request, allocation_ids=IDS) is None
    assert len(calls) == 1 and not calls[0].get("write", False)


@pytest.mark.parametrize("change", ["half", "other_ids", "other_slots", "other_root", "bound"])
def test_pair_lookup_never_adopts_another_attempt(registry, change):
    budget, request = ManagedStorageBudgetV1(registry), pair(registry)
    if change == "half":
        with registry._database.transaction(write=True) as connection:
            value = request[0]
            connection.execute("INSERT INTO storage_allocations VALUES (?,?,?,?,?,?,?,?,?,NULL,NULL)",
                               (IDS[0], *value._key(), value.capacity, value.root_key, *value.root_identity))
            connection.execute("UPDATE identity SET temporary_high_water=2")
    else:
        original = budget.reserve_temporary_pair(request, allocation_ids=IDS)
        if change == "bound":
            bound = budget.bind_file(original[0], (1, 999))
            assert budget.lookup_temporary_pair(request, allocation_ids=IDS) == (bound, original[1])
            return
    if change == "other_ids":
        ids = ("e" * 32, "f" * 32)
    else:
        ids = IDS
    if change == "other_slots":
        request = tuple(replace(item, slot=item.slot + 2) for item in request)
    elif change == "other_root":
        request = tuple(replace(item, root_identity=(1, 999)) for item in request)
    with pytest.raises(ManagedStorageError, match="conflict"):
        budget.lookup_temporary_pair(request, allocation_ids=ids)


@pytest.mark.parametrize("scope", ["instance", "namespace"])
def test_two_contenders_only_one_pair_fits_budget(registry, scope):
    budget, request = ManagedStorageBudgetV1(registry), pair(registry, size=48 * MIB)
    if scope == "namespace":
        for index in range(1, 4):
            budget.reserve(allocation(registry, kind="temporary", size=128 * MIB,
                                      instance="b" * 32, service=index))
    other = tuple(replace(item, slot=item.slot + 2,
                          instance_id="b" * 32 if scope == "namespace" else item.instance_id) for item in request)
    ready = Barrier(2)
    candidates = budget.next_temporary_pair_ids()

    def reserve(values, ids):
        ready.wait(timeout=5)
        try:
            return budget.reserve_temporary_pair(values, allocation_ids=ids)
        except ManagedStorageError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(reserve, request, candidates)
        second = executor.submit(reserve, other, candidates)
        results = [first.result(timeout=10), second.result(timeout=10)]
    assert sum(isinstance(result, ManagedStorageError) for result in results) == 1
    assert all(str(result) == "managed_storage_conflict" for result in results if isinstance(result, ManagedStorageError))
    assert sum(budget.lookup(item) is not None for item in (*request, *other)) == 2
    loser = request if isinstance(results[0], ManagedStorageError) else other
    refused = budget.reserve_temporary_pair(loser, allocation_ids=budget.next_temporary_pair_ids())
    assert isinstance(refused, ManagedTemporaryPairCapacityRefusedV1)


@pytest.mark.parametrize("change", ["duplicate", "instance", "root", "length"])
def test_bad_pair_rejected_before_transaction(registry, monkeypatch, change):
    budget, request = ManagedStorageBudgetV1(registry), pair(registry)
    if change == "duplicate":
        request = (request[0], request[0])
    elif change == "instance":
        request = (request[0], replace(request[1], instance_id="b" * 32))
    elif change == "root":
        request = (request[0], replace(request[1], root_identity=(1, 999)))
    else:
        request = request[:1]
    monkeypatch.setattr(budget._database, "transaction", lambda **kw: pytest.fail("invalid pair reached IO"))
    with pytest.raises(ManagedContractError):
        budget.reserve_temporary_pair(request, allocation_ids=IDS)


def test_existing_allocation_id_cannot_be_reused_for_new_slots(registry):
    budget, request = ManagedStorageBudgetV1(registry), pair(registry)
    budget.reserve_temporary_pair(request, allocation_ids=IDS)
    other = tuple(replace(item, slot=item.slot + 2) for item in request)
    with pytest.raises(ManagedStorageError, match="conflict"):
        budget.reserve_temporary_pair(other, allocation_ids=IDS)
    assert all(budget.lookup(item) is None for item in other)


@pytest.mark.parametrize("ids", [("c" * 32, "c" * 32), ("bad", "d" * 32), ("c" * 32,), list(IDS)])
def test_bad_ids_never_enter_transaction(registry, monkeypatch, ids):
    budget, request = ManagedStorageBudgetV1(registry), pair(registry)
    monkeypatch.setattr(budget._database, "transaction", lambda **kw: pytest.fail("invalid IDs reached IO"))
    with pytest.raises(ManagedContractError):
        budget.reserve_temporary_pair(request, allocation_ids=ids)


@pytest.mark.parametrize("refused", [True, False])
@pytest.mark.parametrize("operation", ["reserve", "lookup"])
def test_final_deadline_prevents_pair_or_refusal_delivery(registry, monkeypatch, refused, operation):
    from loushang.apphost.managed import _files

    budget, request = ManagedStorageBudgetV1(registry), pair(registry, size=68 * MIB if refused else 4096)
    original = budget._database.transaction
    if operation == "lookup" and not refused:
        budget.reserve_temporary_pair(request, allocation_ids=IDS)
    expired = False
    deadline = monotonic() + 5

    @contextmanager
    def transaction(**kwargs):
        nonlocal expired
        with original(**kwargs) as connection:
            yield connection
        expired = True

    with monkeypatch.context() as patch:
        patch.setattr(budget._database, "transaction", transaction)
        patch.setattr(_files, "monotonic", lambda: deadline + 1 if expired else deadline - 1)
        with pytest.raises(ManagedStorageError, match="busy"):
            method = budget.reserve_temporary_pair if operation == "reserve" else budget.lookup_temporary_pair
            method(request, allocation_ids=IDS, deadline=deadline)
    assert expired
    assert all((budget.lookup(item) is None) == refused for item in request)
