from __future__ import annotations

import json
import sqlite3
from time import monotonic

import pytest

from loushang.apphost.managed._database import DATABASE_NAME
from loushang.apphost.managed.contracts import ManagedServiceKeyV1
from loushang.apphost.managed.namespace_admission import ManagedNamespaceAdmissionV1
from loushang.apphost.managed.registry import (
    ManagedMuxReservationV1,
    ManagedServiceAliasReservationV1,
)
from loushang.coding.cli import lmux
from tests.apphost.test_managed_namespace_admission import tree

from .test_lmux_status import namespace as namespace


def test_missing_status_namespace_is_empty_without_creation(namespace, tmp_path, capsys):
    assert lmux.main(["status"]) == 0
    assert json.loads(capsys.readouterr().out) == {"services": [], "observation": "recorded_only", "liveStatus": "not_probed"}
    assert not tuple(tmp_path.iterdir())


def test_status_summary_includes_services_without_mux_from_other_cwd(namespace, tmp_path, monkeypatch, capsys):
    from loushang.coding.cli import lmux_command

    owner = ManagedNamespaceAdmissionV1(namespace.namespace, runtime_root=str(namespace.platform.runtime), create_if_missing=True)
    empty, populated = ManagedServiceKeyV1("coding", "/empty"), ManagedServiceKeyV1("coding", "/populated")
    try:
        registry = owner.open(deadline=monotonic() + 5)
        registry.reserve_service_alias(ManagedServiceAliasReservationV1("build", empty, "a" * 32))
        registry.reserve_mux(ManagedMuxReservationV1("main", populated, "b" * 32))
    finally:
        owner.close()
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)

    def forbidden(*args, **kwargs):
        raise AssertionError("summary must not admit a service, start or connect")

    monkeypatch.setattr(lmux_command, "ManagedServiceAdmissionV1", forbidden)
    monkeypatch.setattr(lmux_command, "ManagedServiceCoordinatorV1", forbidden)
    monkeypatch.setattr(lmux_command, "ManagedConnectionLeaseV1", forbidden)
    before = tree(tmp_path)
    assert lmux.main(["status"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["observation"] == "recorded_only" and result["liveStatus"] == "not_probed"
    services = {item["serviceId"]: item for item in result["services"]}
    assert set(services) == {empty.service_id, populated.service_id}
    assert services[empty.service_id]["reservedMuxes"] == []
    assert services[populated.service_id]["reservedMuxes"] == ["main"]
    assert all(item["instanceId"] is None and item["recordedPhase"] is None for item in services.values())
    assert not tuple(other.iterdir())
    assert tree(tmp_path) == before


@pytest.mark.parametrize("damage", ["missing_database", "unsupported_version"])
def test_damaged_namespace_is_not_an_empty_summary(namespace, tmp_path, capsys, damage):
    from pathlib import Path

    from loushang.apphost.managed.paths import resolve_managed_registry_root

    owner = ManagedNamespaceAdmissionV1(namespace.namespace, runtime_root=str(namespace.platform.runtime), create_if_missing=True)
    try:
        owner.open(deadline=monotonic() + 5)
    finally:
        owner.close()
    database = Path(resolve_managed_registry_root(namespace.namespace)) / DATABASE_NAME
    if damage == "missing_database":
        database.unlink()  # Only this fixture's private, freshly created DB.
    else:
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA user_version=42")
    before = tree(tmp_path)
    assert lmux.main(["status"]) == 1
    captured = capsys.readouterr()
    assert not captured.out and captured.err.startswith("lmux_")
    assert tree(tmp_path) == before
