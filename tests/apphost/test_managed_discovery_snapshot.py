import sqlite3
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from time import monotonic

import pytest

from loushang.apphost.managed import discovery as module
from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.contracts import ManagedContractError, ManagedServiceKeyV1
from tests.apphost.test_managed_connection import committed
from tests.apphost.test_managed_namespace_admission import tree

from .test_managed_discovery import discovery as discovery
from .test_managed_discovery import owners as owners
from .test_managed_discovery import pytestmark as pytestmark


def test_snapshot_includes_unnamed_services_and_is_readonly(owners, discovery):
    reader, registry = discovery
    state = committed(owners)
    extra = ManagedServiceKeyV1("coding", "/another-workspace")
    with registry._database.transaction(write=True) as connection:
        connection.execute("INSERT INTO services VALUES (?,?,?,?)",
                           (extra.service_id, extra.product_id, extra.workspace, extra.profile))
    before = tree(registry._database._directory._root)
    result = reader.snapshot_namespace(deadline=monotonic() + 5)
    assert len(result.services) == 2 and len(result.muxes) == 1
    assert next(item for item in result.services if item.service == extra).instance is None
    assert result.muxes[0].instance == state.handoff.instance
    assert tree(registry._database._directory._root) == before
    with pytest.raises(FrozenInstanceError):
        result.services = ()
    with pytest.raises(ManagedContractError):
        replace(result, services=())
    with pytest.raises(ManagedContractError):
        replace(result, muxes=result.muxes * 2)
    with registry._database.transaction(write=True) as connection:
        connection.execute("DELETE FROM muxes")
    assert len(result.muxes) == 1
    assert reader.snapshot_namespace(deadline=monotonic() + 5).muxes == ()


@pytest.mark.parametrize("limit", ["MAX_SERVICES", "MAX_MUXES"])
def test_snapshot_limits_reject_instead_of_truncate(discovery, monkeypatch, limit):
    from loushang.apphost.managed.registry import ManagedMuxReservationV1

    reader, registry = discovery
    monkeypatch.setattr(module, limit, 1)
    initial = reader.snapshot_namespace(deadline=monotonic() + 5)
    assert len(initial.services) == len(initial.muxes) == 1
    if limit == "MAX_SERVICES":
        extra = ManagedServiceKeyV1("coding", "/second-workspace")
        with registry._database.transaction(write=True) as connection:
            connection.execute("INSERT INTO services VALUES (?,?,?,?)",
                               (extra.service_id, extra.product_id, extra.workspace, extra.profile))
    else:
        registry.reserve_mux(ManagedMuxReservationV1("second", initial.services[0].service, "e" * 32))
    with pytest.raises(ManagedStorageError, match="capacity"):
        reader.snapshot_namespace(deadline=monotonic() + 5)


def test_snapshot_uses_one_read_transaction_and_excludes_concurrent_change(discovery, monkeypatch):
    reader, registry = discovery
    original = registry._database.transaction
    calls = []
    attempts = []
    database = registry._database._directory._root / "registry.sqlite3"

    @contextmanager
    def transaction(**kwargs):
        calls.append(kwargs)
        with original(**kwargs) as connection:
            class Proxy:
                def execute(self, sql, parameters):
                    cursor = connection.execute(sql, parameters)
                    if "ORDER BY m.name" in sql:
                        with sqlite3.connect(database, timeout=0) as other:
                            with pytest.raises(sqlite3.OperationalError, match="locked"):
                                other.execute("DELETE FROM muxes")
                                other.commit()
                            other.rollback()
                        attempts.append(True)
                    return cursor
            yield Proxy()

    monkeypatch.setattr(registry._database, "transaction", transaction)
    result = reader.snapshot_namespace(deadline=monotonic() + 5)
    assert len(calls) == 1 and not calls[0].get("write", False)
    assert attempts == [True] and len(result.muxes) == 1


def test_snapshot_rejects_corruption_and_closed_owner(discovery):
    reader, registry = discovery
    with registry._database.transaction(write=True) as connection:
        connection.execute("UPDATE services SET workspace='/tampered'")
    with pytest.raises(ManagedStorageError, match="invalid_record"):
        reader.snapshot_namespace(deadline=monotonic() + 5)
    registry.close()
    with pytest.raises(ManagedStorageError, match="closed"):
        reader.snapshot_namespace(deadline=monotonic() + 5)


def test_snapshot_rechecks_deadline_after_transaction_exit(discovery, monkeypatch):
    from loushang.apphost.managed import _files

    reader, registry = discovery
    original = registry._database.transaction
    expired = False

    @contextmanager
    def transaction(**kwargs):
        nonlocal expired
        with original(**kwargs) as connection:
            yield connection
        expired = True

    monkeypatch.setattr(registry._database, "transaction", transaction)
    monkeypatch.setattr(_files, "monotonic", lambda: 11.0 if expired else 1.0)
    with pytest.raises(ManagedStorageError, match="busy"):
        reader.snapshot_namespace(deadline=10.0)
    assert expired
