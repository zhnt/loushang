from __future__ import annotations

import plistlib
import sys
from types import SimpleNamespace

import pytest

from loushang.coding import macos_service
from loushang.coding.managed_service import ServiceControlError

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Unix launchd adapter")


def test_launchd_agent_uses_bundled_python_and_does_not_persist_tokens(tmp_path, monkeypatch):
    (tmp_path / "state/macos-host").mkdir(parents=True)
    python = tmp_path / "bundle/runtime/bin/python3"
    monkeypatch.setattr(macos_service, "_python", lambda: python)
    monkeypatch.setenv("OPENAI_API_KEY", "secret-must-not-enter-plist")
    agent = macos_service._write_agent(tmp_path, "test.host")
    content = agent.read_bytes()
    value = plistlib.loads(content)
    assert value["ProgramArguments"] == [str(python), "-I", "-m", "loushang.coding.foreground_host"]
    assert b"secret-must-not-enter-plist" not in content
    assert value["KeepAlive"] == {"SuccessfulExit": False}


def test_launchd_status_rejects_stale_pid_without_probing(tmp_path, monkeypatch):
    root = tmp_path / "state/macos-host"
    root.mkdir(parents=True)
    (root / "endpoint.json").write_text('{"pid": 11, "instanceId": "old"}')
    monkeypatch.setattr(macos_service, "_launchctl", lambda *_: SimpleNamespace(returncode=0, stdout="\tpid = 22\n"))
    assert macos_service._status(tmp_path, "user/501/test") == {"state": "starting"}


def test_launchd_stale_instance_cannot_stop_new_service(tmp_path, monkeypatch):
    monkeypatch.setattr(macos_service, "resolve_platform_home", lambda: tmp_path)
    monkeypatch.setattr(macos_service, "_status", lambda *_: {"state": "running", "instanceId": "new"})
    monkeypatch.setattr(macos_service, "_launchctl", lambda *_: pytest.fail("must not signal service"))
    with pytest.raises(ServiceControlError, match="instance_changed"):
        macos_service.control_launchd_service("stop", "old")


def test_launchd_refuses_other_writable_control_directory(tmp_path, monkeypatch):
    state = tmp_path / "state/macos-host"
    state.mkdir(parents=True)
    state.chmod(0o777)
    monkeypatch.setattr(macos_service, "resolve_platform_home", lambda: tmp_path)
    monkeypatch.setattr(macos_service, "_launchctl", lambda *_: pytest.fail("must not load an unsafe plist"))
    with pytest.raises(ServiceControlError, match="unsafe_state_directory"):
        macos_service.control_launchd_service("start", None)


def test_launchd_stop_wait_does_not_accept_an_instance_replacement(monkeypatch):
    monkeypatch.setattr(macos_service, "_launchctl", lambda *_: SimpleNamespace(returncode=0, stdout="\tpid = 22\n"))
    with pytest.raises(ServiceControlError, match="instance_changed"):
        macos_service._wait_for_exit("user/501/test", 11)
