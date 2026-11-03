from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from loushang.coding.cli import lmux

from .test_lmux_command import managed_cli as managed_cli


@pytest.mark.parametrize("args", [
    ["server", "start", "--name", "a" * 64],
    ["server", "start", "--name", "A" * 64],
    ["server", "start", "--name", "bad:name"],
    ["close-status", "--server", "build", "--operation", "a" * 32],
])
def test_bad_alias_and_historical_alias_forms_reject_before_lookup(monkeypatch, args):
    from loushang.apphost.managed import defaults

    monkeypatch.setattr(defaults, "resolve_managed_defaults", lambda **kw: pytest.fail("invalid alias lookup"))
    with pytest.raises(SystemExit) as error:
        lmux.main(args)
    assert error.value.code == 2


def test_real_alias_start_reuse_cross_cwd_diagnostics_and_stop(managed_cli, tmp_path, monkeypatch, capsys):
    _, commands = managed_cli
    assert lmux.main(["server", "start", "--name", "build"]) == 0
    ready = json.loads(capsys.readouterr().out)
    first = commands[-1]
    native = first.starter._starter._process
    reservation = first.alias_reservation
    assert reservation.name == "build"
    assert lmux.main(["server", "start", "--name", "build"]) == 0
    assert json.loads(capsys.readouterr().out) == ready
    assert commands[-1].alias_reservation == reservation
    assert commands[-1].starter._starter._process is None
    # A service cannot silently adopt a second label.
    assert lmux.main(["server", "start", "--name", "other"]) == 1
    assert commands[-1].starter is None and commands[-1].service is None
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    assert lmux.main(["server", "start", "--name", "build"]) == 1
    assert commands[-1].starter is None and commands[-1].service is None
    capsys.readouterr()
    assert lmux.main(["status", "--server", "build"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["serviceId"] == ready["serviceId"] and status["instanceId"] == ready["instanceId"]
    assert lmux.main(["logs", "--server", "build"]) == 0
    capsys.readouterr()
    assert lmux.main(["stop", "--server", "missing", "--yes"]) == 1
    assert commands[-1].stopper is None and native._process.poll() is None
    with ThreadPoolExecutor(max_workers=1) as pool:
        reaped = pool.submit(native._process.wait, 20)
        assert lmux.main(["stop", "--server", "build", "--yes"]) == 0
        assert reaped.result(timeout=2) == 0
    capsys.readouterr()
    assert lmux.main(["status", "--server", "build"]) == 0
    assert json.loads(capsys.readouterr().out)["serviceId"] == ready["serviceId"]
    assert not tuple(other.iterdir())


@pytest.mark.parametrize("same_service", [True, False])
def test_first_lookup_miss_reconciles_only_same_service_winner(managed_cli, tmp_path, monkeypatch, same_service):
    import os
    from dataclasses import replace
    from io import StringIO

    from loushang.apphost.managed._files import ManagedStorageError
    from loushang.apphost.managed.contracts import ManagedServiceKeyV1
    from loushang.apphost.managed.defaults import resolve_managed_defaults
    from loushang.apphost.managed.registry import ManagedRegistryV1

    module, _ = managed_cli
    original = ManagedRegistryV1.reserve_service_alias
    winners = []
    starts = []

    def race(registry, request, **kwargs):
        # Deterministically schedule the other caller's commit after this
        # caller's missing lookup and before its INSERT, with a distinct op.
        winner = replace(request, operation_id="f" * 32,
                         service=request.service if same_service else ManagedServiceKeyV1("coding", "/other"))
        original(registry, winner, **kwargs)
        winners.append(winner)
        return original(registry, request, **kwargs)

    monkeypatch.setattr(ManagedRegistryV1, "reserve_service_alias", race)
    monkeypatch.setattr(module.ManagedMuxCommand, "_prepare_starter", lambda owner, service: starts.append(service))
    command = module.ManagedMuxCommand(resolve_managed_defaults(), dict(os.environ), stdin=StringIO(), stdout=StringIO())
    try:
        args = lmux._parser().parse_args(["server", "start", "--name", "build"])
        if same_service:
            assert command.prepare(args)
            assert command.alias_reservation == winners[0]
            assert starts == [winners[0].service]
        else:
            with pytest.raises(ManagedStorageError, match="conflict"):
                command.prepare(args)
            assert not starts and command.service is None
    finally:
        command.close_native()


def test_committed_alias_lost_receipt_does_not_start_or_delete(managed_cli, monkeypatch, capsys):
    from loushang.apphost.managed._files import ManagedStorageError
    from loushang.apphost.managed.registry import ManagedRegistryV1

    _, commands = managed_cli
    original = ManagedRegistryV1.reserve_service_alias

    def lost(registry, request, **kwargs):
        original(registry, request, **kwargs)
        raise ManagedStorageError("unavailable")

    monkeypatch.setattr(ManagedRegistryV1, "reserve_service_alias", lost)
    assert lmux.main(["server", "start", "--name", "build"]) == 1
    command = commands[-1]
    assert command.alias_reservation is not None
    assert command.native_closed and command.service is None and command.starter is None
    capsys.readouterr()
    assert lmux.main(["status", "--server", "build"]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["serviceId"] == command.alias_reservation.service.service_id
    assert record["instanceId"] is None
