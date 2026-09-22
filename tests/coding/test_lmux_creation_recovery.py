from __future__ import annotations

import json
import sys
from io import StringIO

import pytest

from loushang.coding.cli import lmux

from .test_lmux_command import _failure_diagnostic
from .test_lmux_command import managed_cli as managed_cli


def _json_lines(output):
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


def _tree(root):
    return {str(path.relative_to(root)): (path.lstat().st_mode, path.lstat().st_ino,
                                         path.lstat().st_mtime_ns,
                                         path.read_bytes() if path.is_file() else None)
            for path in (root, *sorted(root.rglob("*")))}


@pytest.mark.parametrize("fault", ["reservation_ack", "permit_ack", "before_rpc", "after_rpc", "record_ack"])
def test_real_creation_recovery_uses_original_operation_without_query_replay(
    managed_cli, tmp_path, monkeypatch, capsys, fault,
):
    from loushang.apphost.managed._files import ManagedStorageError
    from loushang.apphost.managed.mux_management import ManagedMuxManagerV1
    from loushang.apphost.managed.registry import ManagedRegistryV1
    from loushang.appserver.remote_client import RemoteAppClientV1
    from loushang.harnesstui.mux import terminal

    _, commands = managed_cli
    calls, attached = [], []
    original_rpc = RemoteAppClientV1.create_managed_mux

    async def rpc(client, request):
        calls.append(request)
        return await original_rpc(client, request)

    async def screen(shell, **kwargs):
        await shell.start()
        attached.append(shell.state.mux_space_id)
        return 0

    monkeypatch.setattr(RemoteAppClientV1, "create_managed_mux", rpc)
    monkeypatch.setattr(terminal, "run_hosted_mux_shell", screen)
    injected = []
    with monkeypatch.context() as patch:
        if fault in ("reservation_ack", "permit_ack", "record_ack"):
            cls, name = ((ManagedRegistryV1, "reserve_mux") if fault == "reservation_ack" else
                         (ManagedMuxManagerV1, "issue_create") if fault == "permit_ack" else
                         (ManagedMuxManagerV1, "record_created"))
            original = getattr(cls, name)

            def lost(owner, *args, **kwargs):
                original(owner, *args, **kwargs)
                injected.append(fault)
                raise ManagedStorageError("unavailable")

            patch.setattr(cls, name, lost)
        else:
            async def lost_rpc(client, request):
                calls.append(request)
                if fault == "after_rpc":
                    await original_rpc(client, request)
                injected.append(fault)
                raise ManagedStorageError("unavailable")

            patch.setattr(RemoteAppClientV1, "create_managed_mux", lost_rpc)
        assert lmux.main(["new", "-s", "dev"]) == 1
    assert injected == [fault]
    original_intent = commands[0].creation_reservation
    assert original_intent is not None and not attached
    planned = _json_lines(capsys.readouterr().out)[0]
    assert planned["status"] == "planned_creation" and planned["muxId"] is None
    assert planned["operationId"] == original_intent.operation_id
    assert planned["activeReservation"] is None and not planned["automaticReplay"]
    server, operation = original_intent.service.service_id, original_intent.operation_id
    arguments = ["--server", server, "--operation", operation]
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(other)
    before_calls = len(calls)
    # Read-only query neither connects/starts nor issues a permit, including
    # the case where no service-admission record has ever been created.
    before = _tree(tmp_path)
    for verb in ("create-status", "create"):
        assert lmux.main([verb, *arguments]) == (0 if fault == "record_ack" else 1)
        report = _json_lines(capsys.readouterr().out)[-1]
        assert report["status"] == ("created" if fault == "record_ack" else "unknown")
        assert report["operationId"] == operation and report["liveStatus"] == "not_probed"
        assert commands[-1].creation is commands[-1].connection is commands[-1].service is None
    assert _tree(tmp_path) == before and len(calls) == before_calls
    assert lmux.main(["ls"]) == 0
    listed = _json_lines(capsys.readouterr().out)[-1]["muxes"]
    assert listed[0]["creationOperationId"] == operation
    assert lmux.main(["create", *arguments, "--continue", "--yes"]) == 0, _failure_diagnostic(commands[-1])
    report = _json_lines(capsys.readouterr().out)[-1]
    assert report["status"] == "created" and report["operationId"] == operation
    assert report["workspace"] == str(tmp_path)
    assert len(calls) == before_calls + (0 if fault == "record_ack" else 1)
    assert all(request.operation_id == operation and request.name == "dev" for request in calls)
    assert not attached  # Recovery is scriptable, never implicitly a TUI entry.
    assert commands[-1].native_closed and not commands[-1].active
    assert lmux.main(["attach", "-t", "dev"]) == 0
    assert attached == [report["muxId"]]
    capsys.readouterr()
    assert lmux.main(["create-status", *arguments]) == 0
    assert _json_lines(capsys.readouterr().out)[-1]["muxId"] == report["muxId"]
    # Original name protection is still in force; new never adopts old intent.
    assert lmux.main(["new", "-s", "dev", "--workspace", str(tmp_path)]) == 1
    assert len(calls) == before_calls + (0 if fault == "record_ack" else 1)
    if fault == "record_ack":
        assert lmux.main(["close", "-t", "dev", "--yes"]) == 0
        assert lmux.main(["new", "-s", "dev", "--workspace", str(tmp_path)]) == 0
        replacement = commands[-1].creation.result
        assert replacement.operation_id != operation and replacement.mux_space_id != report["muxId"]
        capsys.readouterr()
        count = len(calls)
        assert lmux.main(["create-status", *arguments]) == 0
        history = _json_lines(capsys.readouterr().out)[-1]
        assert history["muxId"] == report["muxId"] and not history["activeReservation"]
        assert "continueCommand" not in history
        assert lmux.main(["create", *arguments, "--continue", "--yes"]) == 1
        assert len(calls) == count and commands[-1].creation is None


@pytest.mark.parametrize("answer", ["", "\n", "no\n", "yes     no\n"])
def test_confirmation_rejection_does_not_admit_or_start_service(managed_cli, monkeypatch, capsys, answer):
    module, commands = managed_cli
    with monkeypatch.context() as patch:
        patch.setattr(module.ManagedMuxCommand, "_prepare_creation_owner", lambda *_: (_ for _ in ()).throw(RuntimeError()))
        assert lmux.main(["new", "-s", "pending"]) == 1
    reservation = commands[-1].creation_reservation
    capsys.readouterr()
    monkeypatch.setattr(sys, "stdin", StringIO(answer))
    assert lmux.main(["create", "--server", reservation.service.service_id,
                      "--operation", reservation.operation_id, "--continue"]) == 0
    assert commands[-1].creation is commands[-1].service is commands[-1].connection is None


def test_confirmation_race_does_not_adopt_released_name(managed_cli, monkeypatch):
    from loushang.apphost.managed.registry import ManagedMuxReservationV1

    module, commands = managed_cli
    with monkeypatch.context() as patch:
        patch.setattr(module.ManagedMuxCommand, "_prepare_creation_owner", lambda *_: (_ for _ in ()).throw(RuntimeError()))
        assert lmux.main(["new", "-s", "pending"]) == 1
    reservation = commands[-1].creation_reservation
    raced = []

    class Confirm(StringIO):
        def readline(self, size=-1):
            registry = commands[-1].namespace.registry
            # Storage-level target-replacement fault, not a public release API.
            with registry._database.transaction(write=True) as connection:
                connection.execute("DELETE FROM muxes WHERE operation_id=?", (reservation.operation_id,))
            winner = ManagedMuxReservationV1(reservation.name, reservation.service, "e" * 32)
            registry.reserve_mux(winner)
            assert registry.resolve(reservation.name) == winner
            raced.append(True)
            return "yes\n"

    monkeypatch.setattr(sys, "stdin", Confirm())
    assert lmux.main(["create", "--server", reservation.service.service_id,
                      "--operation", reservation.operation_id, "--continue"]) == 1
    assert raced == [True]
    assert commands[-1].creation is commands[-1].service is commands[-1].connection is None


def test_release_after_recheck_is_rejected_by_original_reserve_before_start(managed_cli, monkeypatch):
    from loushang.apphost.managed.coordinator import ManagedServiceCoordinatorV1
    from loushang.apphost.managed.registry import (
        ManagedMuxReservationV1,
        ManagedRegistryV1,
    )
    from loushang.appserver.remote_client import RemoteAppClientV1

    module, commands = managed_cli
    with monkeypatch.context() as patch:
        patch.setattr(module.ManagedMuxCommand, "_prepare_creation_owner", lambda *_: (_ for _ in ()).throw(RuntimeError()))
        assert lmux.main(["new", "-s", "pending"]) == 1
    reservation = commands[-1].creation_reservation
    original = ManagedRegistryV1.reserve_mux
    races, starts, rpcs = [], [], []

    def replace_before_reserve(registry, request, **kwargs):
        assert commands[-1].creation_recovery and commands[-1].creation is not None
        with registry._database.transaction(write=True) as connection:
            connection.execute("DELETE FROM muxes WHERE operation_id=?", (reservation.operation_id,))
        winner = ManagedMuxReservationV1(reservation.name, reservation.service, "e" * 32)
        original(registry, winner, **kwargs)
        assert registry.resolve(reservation.name) == winner
        races.append(True)
        return original(registry, request, **kwargs)

    async def unexpected_start(*args, **kwargs):
        starts.append(True)
        raise AssertionError("must not start")

    async def unexpected_rpc(*args, **kwargs):
        rpcs.append(True)
        raise AssertionError("must not create")

    monkeypatch.setattr(ManagedRegistryV1, "reserve_mux", replace_before_reserve)
    monkeypatch.setattr(ManagedServiceCoordinatorV1, "ensure_started", unexpected_start)
    monkeypatch.setattr(RemoteAppClientV1, "create_managed_mux", unexpected_rpc)
    assert lmux.main(["create", "--server", reservation.service.service_id,
                      "--operation", reservation.operation_id, "--continue", "--yes"]) == 1
    assert races == [True] and starts == rpcs == []
    assert commands[-1].creation._coordinator._starter._process is None
    assert commands[-1].creation.result is None


def test_prior_instance_unreceived_creation_is_not_guessed_safe_after_clean_restart(managed_cli, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from loushang.apphost.managed._files import ManagedStorageError
    from loushang.apphost.managed.mux_management import ManagedMuxManagerV1
    from loushang.appserver.remote_client import RemoteAppClientV1

    _, commands = managed_cli
    original_issue = ManagedMuxManagerV1.issue_create
    issued, observed = [], []

    def lost_permit(manager, *args, **kwargs):
        result = original_issue(manager, *args, **kwargs)
        issued.append(result)
        raise ManagedStorageError("unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(ManagedMuxManagerV1, "issue_create", lost_permit)
        assert lmux.main(["new", "-s", "pending"]) == 1
    assert len(issued) == 1
    reservation = commands[0].creation_reservation
    native = commands[0].creation._coordinator._starter._process
    service_id = reservation.service.service_id
    with ThreadPoolExecutor(max_workers=1) as pool:
        reaped = pool.submit(native._process.wait, 20)
        assert lmux.main(["stop", "--server", service_id, "--yes"]) == 0
        assert reaped.result(timeout=2) == 0
    assert lmux.main(["start", "-t", "pending"]) == 0
    new_instance = commands[-1].starter._starter._state.handoff.instance.instance_id
    assert new_instance != issued[0].instance_id
    original_rpc = RemoteAppClientV1.create_managed_mux

    async def inspect_rejection(client, request):
        assert (await client.list_muxes()).mux_spaces == ()
        try:
            return await original_rpc(client, request)
        finally:
            observed.append((request, (await client.list_muxes()).mux_spaces))

    monkeypatch.setattr(RemoteAppClientV1, "create_managed_mux", inspect_rejection)
    assert lmux.main(["create", "--server", service_id, "--operation", reservation.operation_id,
                      "--continue", "--yes"]) == 1
    assert len(observed) == 1 and observed[0][1] == ()
    assert observed[0][0].operation_id == reservation.operation_id
    assert observed[0][0].instance_id == new_instance
    assert commands[-1].creation.result is None
    assert lmux.main(["create-status", "--server", service_id, "--operation", reservation.operation_id]) == 1
    assert len(observed) == 1


@pytest.mark.parametrize("wrong", ["service", "operation"])
def test_recovery_wrong_identity_is_readonly_and_never_adopts_current_name(managed_cli, tmp_path, monkeypatch, wrong):
    module, commands = managed_cli
    with monkeypatch.context() as patch:
        patch.setattr(module.ManagedMuxCommand, "_prepare_creation_owner", lambda *_: (_ for _ in ()).throw(RuntimeError()))
        assert lmux.main(["new", "-s", "pending"]) == 1
    reservation = commands[-1].creation_reservation
    before = _tree(tmp_path)
    args = ["--server", "e" * 64 if wrong == "service" else reservation.service.service_id,
            "--operation", "e" * 32 if wrong == "operation" else reservation.operation_id]
    for verb, extra in (("create-status", []), ("create", ["--continue", "--yes"])):
        assert lmux.main([verb, *args, *extra]) == 1
        assert commands[-1].creation is commands[-1].service is commands[-1].connection is None
    assert _tree(tmp_path) == before


@pytest.mark.parametrize("args", [
    ["create-status", "--server", "a" * 64, "--operation", "b" * 32],
    ["create", "--server", "a" * 64, "--operation", "b" * 32],
    ["create", "--server", "a" * 64, "--operation", "b" * 32, "--continue", "--yes"],
])
def test_non_tty_queries_and_confirmed_continue_do_not_initialize_missing_namespace(tmp_path, monkeypatch, args):
    from loushang.apphost.managed import defaults

    monkeypatch.setattr(defaults, "linux_machine_key", lambda **_: "a" * 32)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    monkeypatch.setenv("LOUSHANG_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.delenv("LOUSHANG_TMPDIR", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert lmux.main(args) == 1  # not_found, not a TTY parser rejection.
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("arguments", [
    ["create"], ["create-status", "--server", "alias", "--operation", "b" * 32],
    ["create", "--server", "a" * 64, "--operation", "bad"],
    ["create", "--server", "a" * 64, "--operation", "b" * 32, "--yes"],
    ["create", "--server", "a" * 64, "--operation", "b" * 32, "--continue"],
])
def test_invalid_or_unconfirmed_non_tty_creation_recovery_has_zero_lookup(monkeypatch, arguments):
    from loushang.coding.cli import lmux_command

    monkeypatch.setattr(lmux_command, "resolve_managed_defaults", lambda **_: pytest.fail("unexpected lookup"))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    with pytest.raises(SystemExit) as caught:
        lmux.main(arguments)
    assert caught.value.code == 2
