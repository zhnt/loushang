from __future__ import annotations

import json
from pathlib import Path
from time import monotonic

import pytest

from loushang.apphost.managed._files import PrivateManagedDirectory
from loushang.apphost.managed.contracts import ManagedServiceKeyV1
from loushang.apphost.managed.event_log import (
    ManagedLifecycleEventV1,
    ManagedLifecycleLogV1,
)
from loushang.apphost.managed.namespace_admission import ManagedNamespaceAdmissionV1
from loushang.apphost.managed.paths import resolve_managed_service_paths
from loushang.apphost.managed.registry import ManagedMuxReservationV1
from loushang.apphost.managed.storage_budget import ManagedStorageBudgetV1
from loushang.coding.cli import lmux
from tests.apphost.test_managed_namespace_admission import tree

from . import test_lmux_status as fixtures

namespace = fixtures.namespace
pytestmark = fixtures.pytestmark


@pytest.fixture
def logs(namespace, tmp_path):
    admission = ManagedNamespaceAdmissionV1(namespace.namespace, runtime_root=str(namespace.platform.runtime),
                                             create_if_missing=True)
    directory = None
    service = ManagedServiceKeyV1("coding", str(tmp_path))
    try:
        registry = admission.open(deadline=monotonic() + 5)
        registry.reserve_mux(ManagedMuxReservationV1("dev", service, "b" * 32))
        paths = resolve_managed_service_paths(namespace.namespace, service, runtime_root=str(namespace.platform.runtime))
        directory = PrivateManagedDirectory(Path(paths.logs), create=True, create_parents=True)
        writer = ManagedLifecycleLogV1(directory, ManagedStorageBudgetV1(registry), service.service_id)
        for name in ("starting", "ready", "stopping", "stopped"):
            writer.write(ManagedLifecycleEventV1(name, "c" * 32))
        yield Path(paths.logs), service
    finally:
        if directory is not None:
            directory.close()
        admission.close()


@pytest.mark.parametrize("limit", ["0", "101", "-1", "true", "text"])
def test_bad_limit_rejects_before_default_resolution(namespace, tmp_path, monkeypatch, limit):
    from loushang.apphost.managed import defaults

    monkeypatch.setattr(defaults, "resolve_managed_defaults", lambda **kw: pytest.fail("invalid limit resolved paths"))
    with pytest.raises(SystemExit) as error:
        lmux.main(["logs", "-t", "dev", "--limit", limit])
    assert error.value.code == 2 and not tuple(tmp_path.iterdir())


def test_logs_are_bounded_pure_values_without_connection_or_writes(logs, tmp_path, monkeypatch, capsys):
    _, service = logs
    from loushang.coding.cli import lmux_command

    def forbidden(*args, **kwargs):
        pytest.fail("logs attempted activation or file mutation")

    monkeypatch.setattr(lmux_command, "ManagedConnectionLeaseV1", forbidden)
    monkeypatch.setattr(lmux_command, "ManagedServiceCoordinatorV1", forbidden)
    monkeypatch.setattr(PrivateManagedDirectory, "append_data", forbidden)
    monkeypatch.setattr(ManagedStorageBudgetV1, "reserve", forbidden)
    before = tree(tmp_path)
    assert lmux.main(["logs", "-t", "dev", "--limit", "2"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["observation"] == "bounded_tail" and not result["completeHistory"]
    assert result["scan"] == {"maxSegments": 5, "maxBytesPerSegment": 16384}
    assert [item["event"] for item in result["events"]] == ["stopping", "stopped"]
    assert [item["sequence"] for item in result["events"]] == [3, 4]
    assert all(item["instanceId"] == "c" * 32 for item in result["events"])
    assert lmux.main(["logs", "--server", service.service_id, "--limit", "2"]) == 0
    assert json.loads(capsys.readouterr().out) == result
    assert tree(tmp_path) == before


def test_bad_visible_frame_has_no_partial_output_or_secret(logs, tmp_path, capsys):
    root, _ = logs
    path = root / "lifecycle-0.jsonl"
    last = path.read_bytes().splitlines(keepends=True)[-1]
    path.write_bytes(b'{"message":"secret text"}\n' + last)
    before = tree(tmp_path)
    assert lmux.main(["logs", "-t", "dev", "--limit", "1"]) == 1
    captured = capsys.readouterr()
    assert not captured.out and captured.err == "lmux_invalid_record\n"
    assert tree(tmp_path) == before


def test_missing_namespace_logs_never_create_it(namespace, tmp_path, capsys):
    assert lmux.main(["logs", "-t", "dev"]) == 1
    assert capsys.readouterr().err == "lmux_not_found\n"
    assert not tuple(tmp_path.iterdir())
