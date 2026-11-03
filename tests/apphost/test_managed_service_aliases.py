from __future__ import annotations

from dataclasses import replace
from time import monotonic

import pytest

from loushang.apphost.managed import registry as module
from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.contracts import ManagedContractError, ManagedServiceKeyV1

from .test_managed_registry import namespace as namespace
from .test_managed_registry import pytestmark as pytestmark
from .test_managed_registry import registry as registry


def intent(name="build", workspace="/build", operation="a" * 32):
    return module.ManagedServiceAliasReservationV1(name, ManagedServiceKeyV1("coding", workspace), operation)


def test_alias_reopens_independently_of_cwd_without_mux(registry, namespace, tmp_path, monkeypatch):
    request = intent()
    assert registry.reserve_service_alias(request) == request
    assert registry.reserve_service_alias(request) == request
    registry.close()
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    reopened = module.ManagedRegistryV1(tmp_path / "registry", namespace)
    try:
        assert reopened.resolve_service_alias("build") == request
        assert reopened.resolve_service_alias("missing") is None
        assert reopened.list_muxes() == ()
        with reopened._database.transaction() as connection:
            for table in ("muxes", "mux_intents", "mux_authorities", "instances", "service_controls"):
                assert connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
    finally:
        reopened.close()


@pytest.mark.parametrize("change", [dict(name="other"), dict(operation_id="b" * 32),
    dict(service=ManagedServiceKeyV1("coding", "/other")),
    dict(name="other", service=ManagedServiceKeyV1("coding", "/other"))])
def test_alias_cannot_rebind_name_service_or_operation(registry, change):
    original = intent()
    registry.reserve_service_alias(original)
    with pytest.raises(ManagedStorageError, match="conflict"):
        registry.reserve_service_alias(replace(original, **change))
    assert registry.resolve_service_alias("build") == original
    with registry._database.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM services").fetchone() == (1,)


@pytest.mark.parametrize("name", ["", "bad:name", "../escape", "a" * 65, "a" * 64, "0" * 64, "A" * 64])
def test_invalid_alias_rejects_without_io(name):
    with pytest.raises(ManagedContractError):
        intent(name=name)


def test_alias_capacity_is_atomic_but_exact_retry_still_works(registry, monkeypatch):
    original = intent()
    registry.reserve_service_alias(original)
    monkeypatch.setattr(module, "MAX_SERVICES", 1)
    assert registry.reserve_service_alias(original) == original
    with pytest.raises(ManagedStorageError, match="capacity"):
        registry.reserve_service_alias(intent("second", "/second", "b" * 32))
    assert registry.resolve_service_alias("second") is None
    with registry._database.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM services").fetchone() == (1,)


def test_alias_and_mux_names_are_independent(registry):
    original = intent()
    registry.reserve_service_alias(original)
    mux = module.ManagedMuxReservationV1("build", ManagedServiceKeyV1("coding", "/other"), "c" * 32)
    registry.reserve_mux(mux)
    assert registry.resolve("build") == mux
    assert registry.resolve_service_alias("build") == original


def test_expired_alias_calls_do_not_commit(registry):
    with pytest.raises(ManagedStorageError):
        registry.reserve_service_alias(intent(), deadline=monotonic() - 1)
    assert registry.resolve_service_alias("build") is None
    with pytest.raises(ManagedStorageError):
        registry.resolve_service_alias("build", deadline=monotonic() - 1)


@pytest.mark.parametrize("write", [True, False])
def test_alias_post_transaction_deadline_preserves_exact_intent(registry, monkeypatch, write):
    from contextlib import contextmanager

    request = intent()
    if not write:
        registry.reserve_service_alias(request)
    transaction = registry._database.transaction
    expired = []

    @contextmanager
    def late(**kwargs):
        with transaction(**kwargs) as connection:
            yield connection
        expired.append(True)

    def check(deadline):
        if expired:
            raise ManagedStorageError("unavailable")

    with monkeypatch.context() as fault:
        fault.setattr(registry._database, "transaction", late)
        fault.setattr(module, "_check_deadline", check)
        with pytest.raises(ManagedStorageError, match="unavailable"):
            if write:
                registry.reserve_service_alias(request)
            else:
                registry.resolve_service_alias(request.name)
    assert registry.resolve_service_alias(request.name) == request
    assert registry.reserve_service_alias(request) == request


def test_alias_insert_failure_rolls_back_service(registry, monkeypatch):
    from contextlib import contextmanager

    transaction = registry._database.transaction

    class Connection:
        def __init__(self, original):
            self.original = original

        def execute(self, sql, *args):
            if sql.startswith("INSERT INTO service_aliases"):
                raise RuntimeError("injected alias insert failure")
            return self.original.execute(sql, *args)

    @contextmanager
    def failed(**kwargs):
        with transaction(**kwargs) as connection:
            yield Connection(connection)

    with monkeypatch.context() as fault:
        fault.setattr(registry._database, "transaction", failed)
        with pytest.raises(RuntimeError):
            registry.reserve_service_alias(intent())
    assert registry.resolve_service_alias("build") is None
    with transaction() as connection:
        assert connection.execute("SELECT count(*) FROM services").fetchone() == (0,)


@pytest.mark.parametrize("same_service", [True, False])
def test_competing_alias_reservations_have_one_winner(registry, namespace, tmp_path, same_service):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    other = module.ManagedRegistryV1(tmp_path / "registry", namespace)
    barrier = Barrier(2)
    first = intent()
    second = intent("other" if same_service else "build", "/build" if same_service else "/other", "b" * 32)

    def reserve(owner, request):
        barrier.wait(timeout=5)
        try:
            return owner.reserve_service_alias(request, deadline=monotonic() + 5, wait_for_lock=True)
        except ManagedStorageError as error:
            return error.code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(reserve, registry, first), pool.submit(reserve, other, second)
            results = [a.result(timeout=10), b.result(timeout=10)]
        assert results.count("conflict") == 1
        with registry._database.transaction() as connection:
            assert connection.execute("SELECT count(*) FROM service_aliases").fetchone() == (1,)
            assert connection.execute("SELECT count(*) FROM services").fetchone() == (1,)
    finally:
        other.close()
