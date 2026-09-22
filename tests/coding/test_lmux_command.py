from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

import pytest

from loushang.coding.cli import lmux


def _failure_diagnostic(command):
    """Original failure locations only; never stringify exceptions or locals."""
    from loushang.apphost.managed._files import ManagedStorageError
    from loushang.appserver.local_record import LocalRecordError, LocalRecordErrorCodeV1
    from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError

    error = command.failure
    if error is None:
        return {"type": None, "code": None, "frames": []}
    code = None
    if isinstance(error, ManagedStorageError) and type(error.code) is str and error.code in {
        "unsupported", "unavailable", "not_found", "conflict", "busy", "closed", "invalid_record", "capacity",
    }:
        code = error.code
    elif isinstance(error, (AppServiceError, LocalRecordError)) and type(error.code) in (
        AppErrorCodeV1, LocalRecordErrorCodeV1,
    ):
        code = error.code.value
    root = Path(__file__).parents[2]
    frames = []
    for frame, line in traceback.walk_tb(error.__traceback__):
        path = Path(frame.f_code.co_filename)
        filename = str(path.relative_to(root)) if path.is_relative_to(root) else path.name
        frames.append({"file": filename, "line": line, "function": frame.f_code.co_name})
    return {"type": type(error).__name__, "code": code, "frames": frames}


@pytest.mark.parametrize("kind,expected", [("managed", "busy"), ("local", "local_record_not_found"),
                                          ("app", "operation_unavailable"), ("other", None)])
def test_failure_diagnostic_retains_locations_but_not_exception_messages_or_untrusted_codes(kind, expected):
    from types import SimpleNamespace

    from loushang.apphost.managed._files import ManagedStorageError
    from loushang.appserver.local_record import LocalRecordError, LocalRecordErrorCodeV1
    from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError

    secret = "private-message-and-authority-token"
    error = {"managed": lambda: ManagedStorageError("busy"),
             "local": lambda: LocalRecordError(LocalRecordErrorCodeV1.NOT_FOUND),
             "app": lambda: AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE),
             "other": lambda: RuntimeError(secret)}[kind]()
    error.args = (secret,)
    error.add_note(secret)
    if kind == "other":
        error.code = secret
    try:
        raise error
    except Exception as original:
        report = _failure_diagnostic(SimpleNamespace(failure=original))
    assert report["type"] == type(error).__name__ and report["code"] == expected
    assert report["frames"][-1]["function"] == "test_failure_diagnostic_retains_locations_but_not_exception_messages_or_untrusted_codes"
    assert report["frames"][-1]["file"] == "tests/coding/test_lmux_command.py"
    assert report["frames"][-1]["line"] > 0
    assert secret not in json.dumps(report)


def test_help_does_not_resolve_namespace(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    with pytest.raises(SystemExit) as caught:
        lmux.main(["--help"])
    assert caught.value.code == 0
    assert "attach" in capsys.readouterr().out
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("args", [[], ["new", "-s", "dev"], ["attach"], ["attach", "-t", "dev"]])
def test_interactive_commands_reject_non_tty_before_default_lookup(tmp_path, monkeypatch, args):
    from loushang.apphost.managed import defaults

    monkeypatch.setattr(defaults, "resolve_managed_defaults", lambda **k: pytest.fail("non-tty native lookup"))
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    with pytest.raises(SystemExit) as caught:
        lmux.main(args)
    assert caught.value.code == 2
    assert not list(tmp_path.iterdir())


def test_ls_missing_namespace_is_empty_and_readonly(tmp_path, monkeypatch, capsys):
    from loushang.apphost.managed import defaults

    monkeypatch.setattr(defaults, "linux_machine_key", lambda **k: "a" * 32)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    monkeypatch.setenv("LOUSHANG_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.delenv("LOUSHANG_TMPDIR", raising=False)
    assert lmux.main(["ls"]) == 0
    assert json.loads(capsys.readouterr().out) == {"muxes": [], "nextAfter": None}
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("args", [["new"], ["new", "-s", "bad:name"], ["attach", "-t", "bad:name"], ["stop"]])
def test_invalid_commands_have_no_side_effects(tmp_path, monkeypatch, args):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    with pytest.raises(SystemExit) as caught:
        lmux.main(args)
    assert caught.value.code == 2
    assert not list(tmp_path.iterdir())


@pytest.fixture
def managed_cli(tmp_path, monkeypatch, capsys):
    from loushang.apphost.managed import defaults
    from loushang.coding.cli import lmux_command as module

    monkeypatch.setattr(defaults, "linux_machine_key", lambda **k: "a" * 32)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    monkeypatch.setenv("LOUSHANG_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.delenv("LOUSHANG_TMPDIR", raising=False)
    monkeypatch.chdir(tmp_path)
    original_main = lmux.main

    def invoke(args):
        # pytest reinstalls capture streams between fixture and call phases.
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        return original_main(args)

    monkeypatch.setattr(lmux, "main", invoke)
    commands = []
    original = module.ManagedMuxCommand

    class Command(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.failure = None
            commands.append(self)

        async def run(self):
            try:
                await super().run()
            except Exception as error:
                self.failure = error
                raise

    monkeypatch.setattr(module, "ManagedMuxCommand", Command)
    monkeypatch.setattr(os, "_exit", lambda code: pytest.fail(f"unexpected hard exit {code}"))
    try:
        yield module, commands
    finally:
        from loushang.hosting.service import LinuxServiceObserverV1

        from .test_managed_process_entry import _stop_original

        for command in commands:
            coordinator = command.starter if command.starter is not None else (
                command.creation._coordinator if command.creation is not None else None
            )
            if coordinator is None:
                continue
            starter = coordinator._starter
            native = starter._process
            observer = None
            if native is not None and native._process is not None and native._process.poll() is None:
                observer = LinuxServiceObserverV1.reopen(native.identity)
            _stop_original(starter, observer)


@pytest.mark.parametrize("first_name", ["dev", "main"])
def test_real_cli_cold_new_global_ls_attach_and_warm_new(managed_cli, tmp_path, monkeypatch, capsys, first_name):
    from loushang.harnesstui.mux import terminal

    _, commands = managed_cli
    attached = []

    async def screen(shell, **kwargs):
        await shell.start()
        attached.append(shell.state)
        return 0

    monkeypatch.setattr(terminal, "run_hosted_mux_shell", screen)
    assert lmux.main([] if first_name == "main" else ["new", "-s", first_name]) == 0, _failure_diagnostic(commands[-1])
    starter = commands[0].creation._coordinator._starter
    assert starter._process._process.poll() is None
    assert commands[0].native_closed and not commands[0].active
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(other)
    capsys.readouterr()
    assert lmux.main(["ls"]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert [item["name"] for item in listing["muxes"]] == [first_name]
    assert listing["muxes"][0]["workspace"] == str(tmp_path)
    assert listing["muxes"][0]["status"] == "unknown" and listing["muxes"][0]["tabs"] is None
    assert lmux.main(["attach", "-t", first_name]) == 0, repr(commands[-1].failure)
    assert commands[-1].creation is None
    assert lmux.main(["new", "-s", "second", "--workspace", str(tmp_path)]) == 0
    assert commands[-1].creation._coordinator._starter._process is None
    assert len(attached) == 3
    assert lmux.main(["new", "-s", first_name]) == 1
    assert commands[-1].service is None and commands[-1].creation is None
    assert not list(other.iterdir())
    assert starter._process._process.poll() is None


def test_stop_and_explicit_restart_restore_mux_without_recreating_it(managed_cli, tmp_path, monkeypatch, capsys):
    from concurrent.futures import ThreadPoolExecutor

    from loushang.apphost.managed.contracts import ManagedServiceKeyV1
    from loushang.harnesstui.mux import terminal

    _, commands = managed_cli
    seen = []

    async def screen(shell, **kwargs):
        await shell.start()
        seen.append(await shell._client.list_muxes())
        return 0

    monkeypatch.setattr(terminal, "run_hosted_mux_shell", screen)
    assert lmux.main(["new", "-s", "dev"]) == 0, repr(commands[-1].failure)
    first = commands[-1].creation._coordinator._starter
    service_id = ManagedServiceKeyV1("coding", str(tmp_path)).service_id

    def stop(native):
        # This test process is the actual original Popen parent. An unrelated
        # stop client must not fabricate reaping from pidfd readiness.
        with ThreadPoolExecutor(max_workers=1) as pool:
            reaped = pool.submit(native._process.wait, 20)
            assert lmux.main(["stop", "--server", service_id, "--yes"]) == 0
            assert reaped.result(timeout=2) == 0

    stop(first._process)
    assert commands[-1].stopper.state.cleanly_stopped
    assert lmux.main(["attach", "-t", "dev"]) == 1
    assert commands[-1].starter is None and commands[-1].creation is None
    assert lmux.main(["start", "-t", "dev"]) == 0
    second = commands[-1].starter._starter
    assert first._state.handoff.instance != second._state.handoff.instance
    assert lmux.main(["attach", "-t", "dev"]) == 0, repr(commands[-1].failure)
    assert seen[0].mux_spaces == seen[1].mux_spaces
    stop(second._process)
    assert lmux.main(["stop", "--server", service_id, "--yes"]) == 0


def test_noninteractive_stop_requires_confirmation_before_lookup(tmp_path, monkeypatch):
    from loushang.apphost.managed import defaults

    monkeypatch.setattr(defaults, "resolve_managed_defaults", lambda **k: pytest.fail("lookup before confirmation"))
    with pytest.raises(SystemExit) as caught:
        lmux.main(["stop", "--server", "a" * 64])
    assert caught.value.code == 2
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("args", [["close", "-t", "dev"],
    ["close", "--server", "a" * 64, "--operation", "b" * 32, "--continue"]])
def test_noninteractive_close_requires_confirmation_before_lookup(monkeypatch, args):
    from loushang.apphost.managed import defaults

    monkeypatch.setattr(defaults, "resolve_managed_defaults", lambda **k: pytest.fail("lookup before confirmation"))
    with pytest.raises(SystemExit) as caught:
        lmux.main(args)
    assert caught.value.code == 2


@pytest.mark.parametrize("args", [["close", "--server", "a" * 64, "--yes"],
    ["close", "-t", "dev", "--operation", "b" * 32, "--yes"],
    ["close", "-t", "dev", "--continue", "--yes"],
    ["close-status", "--server", "a" * 64, "--operation", "bad"],
    ["close-status", "--server", "a" * 64, "--operation", "b" * 32, "--yes"]])
def test_invalid_close_forms_never_resolve_defaults(monkeypatch, args):
    from loushang.apphost.managed import defaults

    monkeypatch.setattr(defaults, "resolve_managed_defaults", lambda **k: pytest.fail("invalid form lookup"))
    with pytest.raises(SystemExit) as caught:
        lmux.main(args)
    assert caught.value.code == 2


def test_close_status_accepts_non_tty_without_confirmation(monkeypatch):
    from loushang.coding.cli import lmux_command

    calls = []
    monkeypatch.setattr(lmux_command, "execute", lambda args, **k: calls.append(args.action) or 0)
    assert lmux.main(["close-status", "--server", "a" * 64, "--operation", "b" * 32]) == 0
    assert calls == ["close-status"]


@pytest.mark.parametrize("fault", ["permit_ack", "before_rpc", "restart"])
def test_public_close_explicit_continuation_recovers_unsent_intent(managed_cli, monkeypatch, capsys, fault):
    from concurrent.futures import ThreadPoolExecutor

    from loushang.apphost.managed.connection import ManagedConnectionLeaseV1
    from loushang.apphost.managed.mux_management import ManagedMuxManagerV1
    from loushang.appserver.remote_client import RemoteAppClientV1
    from loushang.harnesstui.mux import terminal

    _, commands = managed_cli

    async def screen(shell, **kwargs):
        await shell.start()
        return 0

    monkeypatch.setattr(terminal, "run_hosted_mux_shell", screen)
    assert lmux.main(["new", "-s", "dev"]) == 0, _failure_diagnostic(commands[-1])
    native = commands[-1].creation._coordinator._starter._process
    original_issue, original_close = ManagedMuxManagerV1.issue_close, RemoteAppClientV1.close_managed_mux
    calls = []

    def lost_receipt(manager, *args, **kwargs):
        original_issue(manager, *args, **kwargs)
        raise RuntimeError("test permit receipt lost")

    async def unsent(client, request):
        calls.append(request)
        raise RuntimeError("test failed before sending close")

    async def counted(client, request):
        calls.append(request)
        return await original_close(client, request)

    if fault == "permit_ack":
        monkeypatch.setattr(ManagedMuxManagerV1, "issue_close", lost_receipt)
    else:
        monkeypatch.setattr(RemoteAppClientV1, "close_managed_mux", unsent)
    capsys.readouterr()
    assert lmux.main(["close", "-t", "dev", "--yes"]) == 1
    planned = json.loads(capsys.readouterr().out.splitlines()[0])
    assert planned["status"] == "planned_close" and not planned["reconciled"]
    previous = len(calls)
    assert previous == (0 if fault == "permit_ack" else 1)
    monkeypatch.setattr(ManagedMuxManagerV1, "issue_close", original_issue)
    monkeypatch.setattr(RemoteAppClientV1, "close_managed_mux", counted)
    history = ["--server", planned["serviceId"], "--operation", planned["operationId"]]
    if fault == "restart":
        with ThreadPoolExecutor(max_workers=1) as pool:
            reaped = pool.submit(native._process.wait, 20)
            assert lmux.main(["stop", "--server", planned["serviceId"], "--yes"]) == 0
            assert reaped.result(timeout=2) == 0
        assert lmux.main(["start", "-t", "dev"]) == 0
        capsys.readouterr()
        assert lmux.main(["close-status", *history]) == 1
        stale = json.loads(capsys.readouterr().out)
        assert stale["status"] == "reauthorization_required"
        assert stale["nextCommand"] == ["lmux", "close", *history]
        assert commands[-1].connection is None
    assert lmux.main(["close", *history, "--yes"]) == 1
    unknown = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert unknown["nextCommand"] == ["lmux", "close", *history, "--continue"]
    assert unknown["requiresConfirmation"] and not unknown["automaticReplay"]
    assert lmux.main(["close-status", *history]) == 1
    assert len(calls) == previous
    assert lmux.main(["close", *history, "--continue", "--yes"]) == 0, repr(commands[-1].failure)
    assert len(calls) == previous + 1
    assert calls[-1].operation_id == planned["operationId"]
    assert calls[-1].mux_space_id == planned["muxId"]
    assert commands[-1].close_result.phase.value == "closed"
    assert lmux.main(["new", "-s", "dev"]) == 0, repr(commands[-1].failure)
    # Cached status needs no connection or renewed permit, even though a new
    # Mux now uses the old display name.
    monkeypatch.setattr(ManagedConnectionLeaseV1, "__init__", lambda *a, **k: pytest.fail("cached status connected"))
    monkeypatch.setattr(ManagedMuxManagerV1, "issue_close", lambda *a, **k: pytest.fail("status issued permission"))
    monkeypatch.setattr(ManagedMuxManagerV1, "record_close", lambda *a, **k: pytest.fail("status reconciled"))
    capsys.readouterr()
    assert lmux.main(["close-status", *history]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "closed" and result["historical"]
    assert lmux.main(["ls"]) == 0
    assert [item["name"] for item in json.loads(capsys.readouterr().out)["muxes"]] == ["dev"]


def test_close_confirmation_cancels_before_permit_or_connection(managed_cli, monkeypatch):
    from io import StringIO

    from loushang.apphost.managed.connection import ManagedConnectionLeaseV1
    from loushang.apphost.managed.mux_management import ManagedMuxManagerV1
    from loushang.harnesstui.mux import terminal

    _, commands = managed_cli

    async def screen(shell, **kwargs):
        await shell.start()
        return 0

    monkeypatch.setattr(terminal, "run_hosted_mux_shell", screen)
    assert lmux.main(["new", "-s", "dev"]) == 0
    monkeypatch.setattr(ManagedConnectionLeaseV1, "__init__", lambda *a, **k: pytest.fail("cancelled close connected"))
    monkeypatch.setattr(ManagedMuxManagerV1, "issue_close", lambda *a, **k: pytest.fail("cancelled close issued"))
    for answer in ("", "\n", "no\n", "yes", "yes     no\n"):
        monkeypatch.setattr(sys, "stdin", StringIO(answer))
        assert lmux.main(["close", "-t", "dev"]) == 0
        assert commands[-1].native_closed and commands[-1].close_request is None


def test_close_deadline_after_issuance_prevents_rpc_and_status_rejects_wrong_origin(managed_cli, monkeypatch, capsys):
    from dataclasses import replace
    from time import monotonic

    from loushang.apphost.managed.mux_management import ManagedMuxManagerV1
    from loushang.appserver.managed_mux_close import (
        ManagedMuxClosePhaseV1,
        ManagedMuxCloseStateV1,
    )
    from loushang.appserver.remote_client import RemoteAppClientV1
    from loushang.harnesstui.mux import terminal

    _, commands = managed_cli

    async def screen(shell, **kwargs):
        await shell.start()
        return 0

    monkeypatch.setattr(terminal, "run_hosted_mux_shell", screen)
    assert lmux.main(["new", "-s", "dev"]) == 0
    original_issue = ManagedMuxManagerV1.issue_close

    def late_receipt(manager, *args, **kwargs):
        result = original_issue(manager, *args, **kwargs)
        commands[-1].deadline = monotonic() - 1
        return result

    async def forbidden(*args):
        pytest.fail("expired native receipt started close RPC")

    monkeypatch.setattr(ManagedMuxManagerV1, "issue_close", late_receipt)
    monkeypatch.setattr(RemoteAppClientV1, "close_managed_mux", forbidden)
    assert lmux.main(["close", "-t", "dev", "--yes"]) == 1
    request = commands[-1].close_request
    assert request is not None and commands[-1].close_result is None
    monkeypatch.setattr(ManagedMuxManagerV1, "issue_close", original_issue)

    async def wrong_origin(client, value):
        assert value == request
        result = ManagedMuxCloseStateV1(value.operation_id, value.instance_id, value.creation_operation_id,
                                       value.name, value.mux_space_id, ManagedMuxClosePhaseV1.CLOSED)
        return replace(result, instance_id="9" * 32)

    monkeypatch.setattr(RemoteAppClientV1, "read_managed_mux_close", wrong_origin)
    capsys.readouterr()
    assert lmux.main(["close-status", "--server", request.service_id, "--operation", request.operation_id]) == 1
    assert not capsys.readouterr().out
    assert commands[-1].close_result is None


@pytest.mark.parametrize("race", ["name_reuse", "instance", "other_operation"])
def test_close_confirmation_race_rejects_original_preview(managed_cli, monkeypatch, race):
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace
    from io import StringIO
    from time import monotonic

    from loushang.appserver.remote_client import RemoteAppClientV1
    from loushang.harnesstui.mux import terminal

    module, commands = managed_cli
    diagnostic = Path.cwd() / "close-failure-probe.jsonl"
    factory = module.coding_managed_process_request

    def probed(*args, **kwargs):
        request = factory(*args, **kwargs)
        return replace(request, argv=(request.argv[0], str(Path(__file__).with_name("_managed_close_probe.py")),
                                      *request.argv[3:], str(diagnostic)))

    monkeypatch.setattr(module, "coding_managed_process_request", probed)

    async def screen(shell, **kwargs):
        await shell.start()
        return 0

    monkeypatch.setattr(terminal, "run_hosted_mux_shell", screen)
    assert lmux.main(["new", "-s", "dev"]) == 0
    native = commands[-1].creation._coordinator._starter._process
    original_close = RemoteAppClientV1.close_managed_mux
    frozen = []
    calls = []
    race_completed = []
    cycles = 8 if race == "name_reuse" else 1

    async def counted(client, request):
        calls.append(request)
        assert not frozen or request.operation_id != frozen[0].close_operation
        return await original_close(client, request)

    monkeypatch.setattr(RemoteAppClientV1, "close_managed_mux", counted)

    class Confirm(StringIO):
        def readline(self, limit=-1):
            outer = commands[-1]
            frozen.append(outer)
            service_id = outer.close_reservation.service.service_id
            if race == "name_reuse":
                for _ in range(cycles):
                    assert lmux.main(["close", "-t", "dev", "--yes"]) == 0
                    assert lmux.main(["new", "-s", "dev"]) == 0
                assert commands[-1].creation.result.mux_space_id != outer.close_inspection.creation.mux_space_id
            elif race == "instance":
                with ThreadPoolExecutor(max_workers=1) as pool:
                    reaped = pool.submit(native._process.wait, 20)
                    assert lmux.main(["stop", "--server", service_id, "--yes"]) == 0
                    assert reaped.result(timeout=2) == 0
                assert lmux.main(["start", "-t", "dev"]) == 0
                assert commands[-1].starter._starter._state.handoff.instance.instance_id != outer.close_instance_id
            else:
                winner = outer.close_manager.issue_close(outer.close_reservation, operation_id="e" * 32,
                                                        deadline=monotonic() + 5, wait_for_lock=True)
                assert winner.operation_id != outer.close_operation
            race_completed.append(race)
            return "yes\n"

    monkeypatch.setattr(sys, "stdin", Confirm())
    assert lmux.main(["close", "-t", "dev"]) == 1
    assert race_completed == [race], diagnostic.read_text() if diagnostic.exists() else "no child failure record"
    assert len(frozen) == 1 and frozen[0].close_request is None
    assert frozen[0].native_closed and not frozen[0].active
    assert len(calls) == (cycles if race == "name_reuse" else 0)
    assert lmux.main(["attach", "-t", "dev"]) == 0


@pytest.mark.parametrize("answer", ["\n", "", "no\n", "yes     no\n", "yes\n"])
def test_stop_confirmation_requires_complete_line_before_operation(managed_cli, monkeypatch, answer):
    from io import StringIO

    from loushang.apphost.managed.contracts import ManagedServiceKeyV1

    module, commands = managed_cli
    # A pending durable service is sufficient to test confirmation; no process
    # needs to be launched or terminated for this input-boundary regression.
    monkeypatch.setattr(module, "_execute", lambda *a, **k: 0)
    assert lmux.main(["new", "-s", "pending"]) == 0
    service = commands[-1].service
    assert service is None  # Native admission handles settled by command finalizer.
    key = ManagedServiceKeyV1("coding", str(Path.cwd()))
    # prepare new has reserved the name but run has not created a journal state.
    # Supply a recorded state through the existing journal read seam, not a fake
    # confirmation implementation.
    from types import SimpleNamespace

    from loushang.apphost.managed.contracts import ManagedInstanceRefV1
    from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1

    instance = ManagedInstanceRefV1(commands[0].defaults.namespace.namespace_key, key.service_id, "b" * 32)
    monkeypatch.setattr(ManagedServiceJournalV1, "read", lambda *a, **k: SimpleNamespace(handoff=SimpleNamespace(instance=instance)))
    stream = StringIO(answer)
    monkeypatch.setattr(sys, "stdin", stream)
    assert lmux.main(["stop", "--server", key.service_id]) == 0
    command = commands[-1]
    assert (command.stopper is not None) == (answer == "yes\n")
    assert command.native_closed and not command.active


def test_attach_missing_target_never_initializes_or_starts(managed_cli, tmp_path):
    _, commands = managed_cli
    assert lmux.main(["attach", "-t", "missing"]) == 1
    assert not list(tmp_path.iterdir())
    assert commands[0].creation is None and commands[0].native_closed


def test_attach_does_not_follow_name_reused_during_connection(managed_cli, monkeypatch):
    import asyncio
    from time import monotonic

    from loushang.apphost.managed._files import ManagedStorageError
    from loushang.apphost.managed.connection import (
        ManagedConnectionLeaseV1,
        _settled_native,
    )
    from loushang.apphost.managed.mux_management import ManagedMuxManagerV1
    from loushang.apphost.managed.registry import ManagedMuxReservationV1
    from loushang.coding.managed_process import APPLICATION_ID
    from loushang.harnesstui.mux import terminal

    _, commands = managed_cli
    attached = []

    async def screen(shell, **kwargs):
        await shell.start()
        attached.append(shell.state.mux_space_id)
        return 0

    monkeypatch.setattr(terminal, "run_hosted_mux_shell", screen)
    assert lmux.main(["new", "-s", "dev"]) == 0, _failure_diagnostic(commands[-1])
    original_prepare = ManagedConnectionLeaseV1.prepare
    replaced = []

    async def native(operation):
        deadline = monotonic() + 5
        while True:
            try:
                return await _settled_native(operation)
            except ManagedStorageError as error:
                if error.code != "busy" or monotonic() >= deadline:
                    raise
                await asyncio.sleep(0.01)

    async def replace_after_connect(connection, **kwargs):
        await original_prepare(connection, **kwargs)
        command = commands[-1]
        registry, journal = command.namespace.registry, command.journal
        state = await native(lambda: journal.read(deadline=monotonic() + 5))
        reservation = await native(lambda: registry.resolve("dev"))
        manager = ManagedMuxManagerV1(registry, journal, command.defaults.namespace, reservation.service,
                                      state.handoff.instance, application_id=APPLICATION_ID)
        request = await native(lambda: manager.issue_close(
            reservation, operation_id="d" * 32, deadline=monotonic() + 5))
        closed = await connection.managed_mux_close_client.close_managed_mux(request)
        await native(lambda: manager.record_close(request, closed, deadline=monotonic() + 5))
        new = ManagedMuxReservationV1("dev", reservation.service, "e" * 32)
        await native(lambda: registry.reserve_mux(new, deadline=monotonic() + 5))
        create = await native(lambda: manager.issue_create(new, deadline=monotonic() + 5))
        created = await connection.managed_mux_client.create_managed_mux(create)
        await native(lambda: manager.record_created(create, created, deadline=monotonic() + 5))
        replaced.append(created.mux_space_id)

    monkeypatch.setattr(ManagedConnectionLeaseV1, "prepare", replace_after_connect)
    status = lmux.main(["attach", "-t", "dev"])
    assert replaced, repr(commands[-1].failure)
    assert status == 1
    assert len(attached) == len(replaced) == 1 and attached[0] != replaced[0]
    assert commands[-1].native_closed and not commands[-1].active
    monkeypatch.setattr(ManagedConnectionLeaseV1, "prepare", original_prepare)
    assert lmux.main(["attach", "-t", "dev"]) == 0
    assert attached == [attached[0], replaced[0]]


@pytest.mark.parametrize("args", [[], ["attach"]])
@pytest.mark.parametrize("changed", ["reservation", "instance", "missing", "stop"])
def test_automatic_selection_does_not_replace_frozen_observation(managed_cli, monkeypatch, changed, args):
    from dataclasses import replace

    from loushang.apphost.managed.discovery import ManagedDiscoveryV1
    from loushang.harnesstui.mux import terminal

    module, commands = managed_cli
    entered = []

    async def screen(shell, **kwargs):
        await shell.start()
        entered.append(shell.state)
        return 0

    monkeypatch.setattr(terminal, "run_hosted_mux_shell", screen)
    assert lmux.main(["new", "-s", "dev"]) == 0
    resolve = ManagedDiscoveryV1.resolve

    def changed_after_selection(discovery, *args, **kwargs):
        observed = resolve(discovery, *args, **kwargs)
        if changed == "reservation":
            return replace(observed, reservation=replace(observed.reservation, operation_id="e" * 32))
        if changed == "missing":
            return None
        if changed == "stop":
            return replace(observed, stop_requested=True)
        return replace(observed, instance=replace(observed.instance, instance_id="f" * 32))

    monkeypatch.setattr(ManagedDiscoveryV1, "resolve", changed_after_selection)
    monkeypatch.setattr(module.ManagedMuxCommand, "_select_probe", lambda *a: pytest.fail("unexpected selector"))
    assert lmux.main(args) == 1
    assert len(entered) == 1
    assert commands[-1].connection is commands[-1].creation is commands[-1].starter is None
    assert commands[-1].native_closed and not commands[-1].active


def test_runner_construction_failure_settles_original_native_owners(managed_cli, monkeypatch):
    module, commands = managed_cli

    def fail(*a, **k):
        raise RuntimeError("private failure")

    monkeypatch.setattr(module, "_execute", fail)
    assert lmux.main(["new", "-s", "pending"]) == 1
    command = commands[0]
    assert command.native_closed and command.namespace is command.service is command.journal is None
    assert command.creation._coordinator._starter._process is None


def test_runner_refuses_to_enter_settles_original_native_owners(managed_cli, monkeypatch):
    from loushang.coding.cli import mux

    _, commands = managed_cli

    class Runner:
        def run(self, coroutine):
            coroutine.close()
            raise RuntimeError("runner refused before execution")

        def close(self):
            pass

    monkeypatch.setattr(mux.asyncio, "Runner", Runner)
    assert lmux.main(["new", "-s", "pending"]) == 1
    assert commands[0].native_closed and commands[0].namespace is None


def test_bare_preserves_pending_names_in_selector_instead_of_creating_main(managed_cli, monkeypatch, capsys):
    from io import StringIO

    module, commands = managed_cli
    with monkeypatch.context() as patch:
        patch.setattr(module, "_execute", lambda *a, **k: 1)
        assert lmux.main(["new", "-s", "pending"]) == 1
    capsys.readouterr()
    stdin = StringIO("\n")
    monkeypatch.setattr(stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys, "stdin", stdin)
    assert lmux.main([]) == 0
    assert '"name": "pending"' in capsys.readouterr().out
    assert commands[-1].creation is None
    assert commands[-1].probe_result is not None
    assert not commands[-1].probe.cleanup_pending
    assert commands[-1].native_closed


@pytest.mark.parametrize("missing", ["registry", "witness", "database", "lock"])
def test_ls_damaged_namespace_is_not_an_empty_first_start(managed_cli, monkeypatch, capsys, tmp_path, missing):
    from loushang.apphost.managed.paths import (
        resolve_managed_admission_root,
        resolve_managed_registry_root,
    )

    from ..apphost.test_managed_namespace_admission import tree

    module, commands = managed_cli
    monkeypatch.setattr(module, "_execute", lambda *a, **k: 1)
    assert lmux.main(["new", "-s", "pending"]) == 1
    namespace = commands[0].defaults.namespace
    source = Path(resolve_managed_registry_root(namespace) if missing == "registry" else resolve_managed_admission_root(namespace))
    if missing in ("database", "lock"):
        source = Path(resolve_managed_registry_root(namespace)) / ("registry.sqlite3" if missing == "database" else "registry.lock")
    source.rename(tmp_path / "held-original")
    before = tree(tmp_path)
    capsys.readouterr()
    assert lmux.main(["ls"]) == 1
    assert capsys.readouterr().out == ""
    assert tree(tmp_path) == before
