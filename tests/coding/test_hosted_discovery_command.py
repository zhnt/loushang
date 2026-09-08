"""Explicit installed command selection; native wheel evidence is separate."""

from __future__ import annotations

import asyncio
import json

import pytest

from loushang.apphost.application import HostedApplicationError
from loushang.coding.cli import hosted

from .test_hosted_command import _argv


def test_G17_COMPAT_describe_discovery_is_explicit_and_read_only(tmp_path, capsys):
    assert hosted.main([*_argv(tmp_path), "--session-discovery", "--describe"]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out)["profile"] == "foreground-stdio-discovery/v1"
    assert str(tmp_path) not in output.out
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("enabled", [False, True])
def test_G17_COMPAT_main_passes_explicit_discovery_selection(
    tmp_path, monkeypatch, enabled
):
    calls = []

    def command(launch, *, session_discovery=False):
        calls.append((launch, session_discovery))
        return sentinel

    sentinel = object()
    monkeypatch.setattr(hosted, "CodingHostedCommandV1", command)
    monkeypatch.setattr(
        hosted, "execute_hosted_command", lambda value: 17 if value is sentinel else 1
    )
    flags = ["--session-discovery"] if enabled else []
    assert hosted.main([*_argv(tmp_path), *flags]) == 17
    assert len(calls) == 1 and calls[0][1] is enabled
    assert not tuple(tmp_path.iterdir())


def test_G17_COMPAT_legacy_parse_launch_does_not_silently_drop_selection(tmp_path):
    launch, describe = hosted.parse_launch(_argv(tmp_path))
    assert launch.workspace == tmp_path and describe is False
    with pytest.raises(SystemExit) as error:
        hosted.parse_launch([*_argv(tmp_path), "--session-discovery"])
    assert error.value.code == 2


@pytest.mark.parametrize("value", [None, 0, 1, "true"])
def test_G17_COMPAT_command_rejects_non_boolean_activation_before_bootstrap(
    tmp_path,
    monkeypatch,
    value,
):
    launch, _ = hosted.parse_launch(_argv(tmp_path))
    calls = []
    monkeypatch.setattr(
        hosted,
        "create_coding_hosted_attempt",
        lambda *args, **kwargs: calls.append(kwargs),
    )
    with pytest.raises(TypeError, match="invalid discovery activation"):
        hosted.CodingHostedCommandV1(launch, session_discovery=value)
    assert not calls and not tuple(tmp_path.iterdir())


def test_G17_COMPAT_missing_port_keeps_command_cleanup_ownership(tmp_path, monkeypatch):
    async def scenario():
        events = []

        class Application:
            discovery_client = None

            async def close(self):
                events.append("application.close")

        class Attempt:
            async def open(self):
                events.append("application.open")
                return Application()

        class Transport:
            def __init__(self, **kwargs):
                events.append("transport.create")

            async def close(self):
                events.append("transport.close")

        def bootstrap(*args, **kwargs):
            assert kwargs["session_discovery"] is True
            return Attempt()

        monkeypatch.setattr(hosted, "create_coding_hosted_attempt", bootstrap)
        monkeypatch.setattr(hosted, "InheritedStdioTransportV1", Transport)
        launch, _ = hosted.parse_launch(_argv(tmp_path))
        command = hosted.CodingHostedCommandV1(launch, session_discovery=True)
        with pytest.raises(
            HostedApplicationError, match="hosted_discovery_unavailable"
        ):
            await command.run(input_fd=0, output_fd=1)
        assert not command.cleanup_pending
        await command.close()
        assert events == [
            "application.open",
            "transport.create",
            "application.close",
            "transport.close",
        ]

    asyncio.run(asyncio.wait_for(scenario(), 5))
