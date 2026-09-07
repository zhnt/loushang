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
