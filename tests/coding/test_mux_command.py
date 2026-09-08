from __future__ import annotations

import json

import pytest

from loushang.coding.cli.mux import main


def _selector(root):
    return ["--connection-root", str(root / "connections"), "--endpoint", "workspace"]


def _serve(root):
    return [
        *_selector(root),
        "serve",
        "--workspace",
        str(root),
        "--application-root",
        str(root / "applications"),
        "--cwd-sessions",
        str(root / "cwd-sessions"),
        "--home-sessions",
        str(root / "home-sessions"),
    ]


def test_G16_COMMAND_describe_and_help_do_not_create_state(tmp_path, capsys):
    with pytest.raises(SystemExit) as help_exit:
        main(["--help"])
    assert help_exit.value.code == 0
    capsys.readouterr()
    assert main([*_serve(tmp_path), "--describe"]) == 0
    captured = capsys.readouterr()
    value = json.loads(captured.out)
    assert value["profile"] == "local-detachable/v1"
    assert value["endpoint"] == "workspace" and value["productId"] == "coding"
    assert {item["scope"] for item in value["scopes"]} == {"cwd", "user_home"}
    assert "key" not in value and "port" not in value
    assert captured.err == "" and str(tmp_path) not in captured.out
    assert not tuple(tmp_path.iterdir())


def test_G16_COMMAND_close_requires_explicit_confirmation_before_io(tmp_path):
    with pytest.raises(SystemExit) as missing:
        main([*_selector(tmp_path), "close", "dev"])
    assert missing.value.code == 2
    assert not tuple(tmp_path.iterdir())


def test_G16_COMMAND_missing_endpoint_is_not_autostart_or_discovery(tmp_path, capsys):
    assert main([*_selector(tmp_path), "list"]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "not_found" in captured.err
    assert str(tmp_path) not in captured.err
    assert not tuple(tmp_path.iterdir())


def test_G16_COMMAND_attach_rejects_non_terminal_before_connection_io(tmp_path):
    with pytest.raises(SystemExit) as missing_tty:
        main([*_selector(tmp_path), "attach", "dev"])
    assert missing_tty.value.code == 2
    assert not tuple(tmp_path.iterdir())


def test_G16_COMMAND_failed_shell_settlement_still_closes_connection(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError
    from loushang.coding.cli import mux
    from loushang.harnesstui.mux import shell, terminal

    events = []

    class Directory:
        def __init__(self, root):
            pass

        def close(self):
            events.append("directory.close")

    class Connection:
        def __init__(self, *args, **kwargs):
            self.client = object()
            self.scopes = (SimpleNamespace(scope="cwd", fingerprint="scope"),)
            self.discovery_client = None

        async def start(self):
            events.append("connection.start")

        async def close(self):
            events.append("connection.close")

    class Shell:
        def __init__(self, *args, **kwargs):
            pass

        async def close(self):
            events.append("shell.close")
            raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)

    async def run(*args, **kwargs):
        events.append("terminal.run")
        return 0

    monkeypatch.setattr(mux, "LocalConnectionDirectoryV1", Directory)
    monkeypatch.setattr(mux, "LocalAppClientConnectionV1", Connection)
    monkeypatch.setattr(shell, "HostedMuxShellV1", Shell)
    monkeypatch.setattr(terminal, "run_hosted_mux_shell", run)
    command = mux._ClientCommand(tmp_path, "workspace", "attach", "dev", None)
    with pytest.raises(AppServiceError) as error:
        asyncio.run(command.run())
    assert error.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
    assert events == [
        "connection.start", "terminal.run", "shell.close",
        "connection.close", "directory.close",
    ]
    assert command.cleanup_pending  # The process boundary must not report success.
    assert not tuple(tmp_path.iterdir())
