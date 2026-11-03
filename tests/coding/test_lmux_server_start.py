from __future__ import annotations

import json
import sys

import pytest

from loushang.apphost.managed.contracts import ManagedServiceKeyV1
from loushang.coding.cli import lmux

from .test_lmux_command import managed_cli as managed_cli

CLI_MAIN = lmux.main


@pytest.mark.parametrize("args", [["server"], ["server", "stop"],
    ["server", "start", "-t", "dev"]])
def test_invalid_server_forms_reject_before_defaults(monkeypatch, args):
    from loushang.apphost.managed import defaults

    monkeypatch.setattr(defaults, "resolve_managed_defaults", lambda **kw: pytest.fail("invalid form lookup"))
    with pytest.raises(SystemExit) as caught:
        lmux.main(args)
    assert caught.value.code == 2


def test_server_start_is_scriptable(monkeypatch):
    from loushang.coding.cli import lmux_command

    calls = []
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    monkeypatch.setattr(lmux_command, "execute", lambda args, **kw: calls.append(args) or 0)
    assert lmux.main(["server", "start", "--workspace", "/example"]) == 0
    assert calls[0].action == "server" and calls[0].workspace == "/example"


@pytest.mark.parametrize("duration", ["0", "-1", "3601", "1.5", "invalid"])
def test_invalid_trace_duration_rejects_before_defaults(monkeypatch, duration):
    from loushang.coding.cli import lmux_command

    monkeypatch.setattr(lmux_command, "execute", lambda *a, **kw: pytest.fail("invalid trace executed"))
    with pytest.raises(SystemExit) as caught:
        CLI_MAIN(["server", "start", "--trace-for", duration])
    assert caught.value.code == 2


def test_real_trace_start_and_reuse_do_not_renew_request(managed_cli, capsys):
    _, commands = managed_cli
    status = lmux.main(["server", "start", "--trace-for", "60"])
    first = json.loads(capsys.readouterr().out)
    if status != 0:
        from pathlib import Path

        logs = Path(commands[-1].starter._starter._layout.paths.logs)
        pytest.fail(f"trace startup result: {first!r}; log files: {sorted(p.name for p in logs.iterdir())!r}")
    assert first["status"] == "service_ready"
    assert first["trace"]["status"] == "applied"
    assert first["trace"]["deadlineMs"] == commands[-1].trace_deadline_ms
    assert first["trace"]["operationId"] == commands[-1].starter.operation_id
    assert first["trace"]["observation"] == "historical_configuration_not_write_guarantee"
    native = commands[-1].starter._starter._process
    assert native._process.poll() is None
    assert lmux.main(["server", "start", "--trace-for", "120"]) == 1
    reused = json.loads(capsys.readouterr().out)
    assert reused["status"] == "service_ready"
    assert reused["instanceId"] == first["instanceId"]
    assert reused["trace"]["status"] == "not_applied_reused_instance"
    assert reused["trace"]["operationId"] != first["trace"]["operationId"]
    assert commands[-1].starter._starter._process is None
    assert native._process.poll() is None


@pytest.mark.parametrize("outcome", ["expired", "not_confirmed", "conflict", "invalid_record", "unavailable", "unexpected"])
def test_trace_observation_outcome_preserves_ready_service(managed_cli, monkeypatch, capsys, outcome):
    from loushang.apphost.managed._files import ManagedStorageError
    from loushang.apphost.managed.coordinator import ManagedServiceCoordinatorV1

    _, commands = managed_cli
    observations = []

    async def observe(owner, **kwargs):
        observations.append(owner.instance)
        if outcome in {"expired", "not_confirmed"}:
            return outcome
        if outcome == "unexpected":
            raise RuntimeError("private diagnostic detail")
        raise ManagedStorageError(outcome)

    monkeypatch.setattr(ManagedServiceCoordinatorV1, "observe_requested_trace", observe)
    assert lmux.main(["server", "start", "--trace-for", "60"]) == 1
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert captured.err == ""
    assert len(observations) == 1
    assert result["status"] == "service_ready"
    assert result["serviceId"] == observations[0].service_id
    assert result["instanceId"] == observations[0].instance_id
    if outcome in {"expired", "not_confirmed"}:
        assert result["trace"]["status"] == outcome
        assert "errorCode" not in result["trace"]
    else:
        assert result["trace"]["status"] == "observation_failed"
        assert result["trace"]["errorCode"] == ("unavailable" if outcome == "unexpected" else outcome)
    assert "private diagnostic detail" not in captured.out
    assert commands[-1].starter._starter._process._process.poll() is None
    assert commands[-1].native_closed


def test_real_empty_service_start_reuse_then_new(managed_cli, tmp_path, monkeypatch, capsys):
    from loushang.apphost.managed.coordinator import ManagedServiceCoordinatorV1
    from loushang.harnesstui.mux import terminal

    _, commands = managed_cli
    original_start = ManagedServiceCoordinatorV1.ensure_started
    inspected = []

    async def checked_start(coordinator, **kwargs):
        ready = await original_start(coordinator, **kwargs)
        assert not (await ready.client.list_muxes()).mux_spaces
        inspected.append(ready.instance)
        return ready

    async def screen(shell, **kwargs):
        await shell.start()
        return 0

    monkeypatch.setattr(ManagedServiceCoordinatorV1, "ensure_started", checked_start)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdin, "readline", lambda *a: pytest.fail("server read stdin"))
    monkeypatch.setattr(terminal, "run_hosted_mux_shell", lambda *a, **k: pytest.fail("server entered terminal"))
    assert CLI_MAIN(["server", "start"]) == 0, repr(commands[-1].failure)
    first = json.loads(capsys.readouterr().out)
    service_id = ManagedServiceKeyV1("coding", str(tmp_path)).service_id
    assert first["status"] == "service_ready" and first["serviceId"] == service_id
    assert commands[-1].creation is None and commands[-1].native_closed
    assert not (commands[-1].defaults.platform.data / "sessions").exists()
    native = commands[-1].starter._starter._process
    assert native._process.poll() is None
    assert lmux.main(["ls"]) == 0
    assert json.loads(capsys.readouterr().out)["muxes"] == []
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    assert lmux.main(["server", "start", "--workspace", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out) == first
    assert commands[-1].starter._starter._process is None
    assert lmux.main(["status", "--server", service_id]) == 0
    assert json.loads(capsys.readouterr().out)["instanceId"] == first["instanceId"]
    assert len(inspected) == 2 and inspected[0] == inspected[1]
    monkeypatch.setattr(ManagedServiceCoordinatorV1, "ensure_started", original_start)
    monkeypatch.setattr(terminal, "run_hosted_mux_shell", screen)
    assert lmux.main(["new", "-s", "dev", "--workspace", str(tmp_path)]) == 0
    assert commands[-1].creation._coordinator._starter._process is None
    assert native._process.poll() is None
    assert not tuple(other.iterdir())


def test_missing_workspace_does_not_admit_namespace(managed_cli, tmp_path):
    _, commands = managed_cli
    assert lmux.main(["server", "start", "--workspace", str(tmp_path / "missing")]) == 1
    assert commands[-1].namespace is None and commands[-1].native_closed
    assert not tuple(tmp_path.iterdir())


def test_coordinator_construction_failure_closes_original_admission(managed_cli, tmp_path, monkeypatch, capsys):
    module, commands = managed_cli
    retained = []

    def fail(journal, *args, **kwargs):
        retained.extend((commands[-1].namespace, commands[-1].service))
        raise RuntimeError("injected coordinator construction failure")

    monkeypatch.setattr(module, "ManagedServiceCoordinatorV1", fail)
    assert lmux.main(["server", "start"]) == 1
    assert capsys.readouterr().err == "lmux_unavailable\n"
    assert commands[-1].native_closed and commands[-1].starter is None
    assert commands[-1].service is None and commands[-1].namespace is None
    assert all(not owner.cleanup_pending for owner in retained)
    # A durable admitted service is not deleted to hide a failed command.
    service_id = ManagedServiceKeyV1("coding", str(tmp_path)).service_id
    assert lmux.main(["status", "--server", service_id]) == 0
    recorded = json.loads(capsys.readouterr().out)
    assert recorded["serviceId"] == service_id and recorded["instanceId"] is None
    assert lmux.main(["ls"]) == 0
    assert json.loads(capsys.readouterr().out)["muxes"] == []
