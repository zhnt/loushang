from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


_MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "coding"
    / "extensions"
    / "hol_guard.py"
)
_SPEC = importlib.util.spec_from_file_location("hol_guard_extension_example", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
hol_guard = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hol_guard)


class _API:
    def __init__(self) -> None:
        self.callback = None

    def on(self, event_name, callback) -> None:
        assert event_name == "tool_call"
        self.callback = callback


def _event(tool_name: str = "shell", command: object = "printf ok"):
    return SimpleNamespace(
        tool_call=SimpleNamespace(name=tool_name),
        args={"command": command},
    )


def _completed(payload: object, *, returncode: int = 0):
    return subprocess.CompletedProcess(
        args=["hol-guard"],
        returncode=returncode,
        stdout=json.dumps(payload),
        stderr="",
    )


def test_register_allows_only_explicit_benign_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _API()
    hol_guard.register(api)
    assert api.callback is not None

    monkeypatch.setattr(
        hol_guard.subprocess,
        "run",
        lambda *args, **kwargs: _completed(
            {
                "minimum_action": "allow",
                "classification": {"explicitly_benign": True},
            }
        ),
    )

    assert api.callback(_event(), None) is None


@pytest.mark.parametrize(
    "payload",
    [
        {
            "minimum_action": "review",
            "classification": {"explicitly_benign": False},
        },
        {
            "minimum_action": "allow",
            "classification": {"explicitly_benign": False},
        },
        {"minimum_action": "allow"},
    ],
)
def test_register_blocks_non_authoritative_results(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    api = _API()
    hol_guard.register(api)
    assert api.callback is not None
    monkeypatch.setattr(
        hol_guard.subprocess,
        "run",
        lambda *args, **kwargs: _completed(payload),
    )

    decision = api.callback(_event(), None)

    assert decision is not None
    assert decision.block is True


@pytest.mark.parametrize(
    "replacement",
    [
        lambda *args, **kwargs: _completed({}, returncode=1),
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["hol-guard"],
            returncode=0,
            stdout="{",
            stderr="",
        ),
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd=["hol-guard"], timeout=10)
        ),
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("hol-guard")),
    ],
)
def test_register_fails_closed_on_guard_errors(
    monkeypatch: pytest.MonkeyPatch,
    replacement,
) -> None:
    api = _API()
    hol_guard.register(api)
    assert api.callback is not None
    monkeypatch.setattr(hol_guard.subprocess, "run", replacement)

    decision = api.callback(_event(), None)

    assert decision is not None
    assert decision.block is True


def test_register_blocks_missing_command() -> None:
    api = _API()
    hol_guard.register(api)
    assert api.callback is not None

    decision = api.callback(_event(command=None), None)

    assert decision is not None
    assert decision.block is True


def test_register_ignores_unmapped_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _API()
    hol_guard.register(api)
    assert api.callback is not None

    def unexpected(*args, **kwargs):
        raise AssertionError("HOL Guard should not run for unmapped tools")

    monkeypatch.setattr(hol_guard.subprocess, "run", unexpected)

    assert api.callback(_event(tool_name="read"), None) is None


def test_guard_invocation_uses_command_test_json(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _completed(
            {
                "minimum_action": "allow",
                "classification": {"explicitly_benign": True},
            }
        )

    monkeypatch.setattr(hol_guard.subprocess, "run", fake_run)

    assert hol_guard._guard_decision("printf ok") is None
    assert captured["args"] == [
        "hol-guard",
        "command",
        "test",
        "printf ok",
        "--json",
    ]
    assert captured["kwargs"]["timeout"] == 10.0
    assert captured["kwargs"]["check"] is False
