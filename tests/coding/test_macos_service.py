from __future__ import annotations

import plistlib
import sys
from types import SimpleNamespace

import pytest

from loushang.apphost.managed.launchd import ManagedLaunchdService
from loushang.coding.hosted import macos_service
from loushang.coding.hosted.managed.service import ServiceControlError
from loushang.hosting import service_launchd

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Unix launchd adapter")


@pytest.fixture(autouse=True)
def _launchd_platform(monkeypatch):
    monkeypatch.setattr(service_launchd, "sys", SimpleNamespace(platform="darwin"))


def test_launchd_agent_uses_bundled_python_and_does_not_persist_tokens(standalone_workspace, monkeypatch):
    home = standalone_workspace
    root = home / "state/macos-host"
    python = home / "bundle/runtime/bin/python3"
    monkeypatch.setattr(macos_service, "resolve_platform_home", lambda: home)
    monkeypatch.setattr(macos_service, "_python", lambda: python)
    monkeypatch.setenv("OPENAI_API_KEY", "secret-must-not-enter-plist")
    agent = root / "host.plist"
    root.parent.mkdir(mode=0o700)
    root.mkdir(mode=0o700)
    started = False

    def launchctl(operation, target, *arguments):
        nonlocal started
        if operation == "bootstrap":
            (root / "endpoint.json").write_text('{"pid": 22, "instanceId": "selected"}')
            started = True
            return SimpleNamespace(returncode=0)
        assert operation == "print"
        if target.count("/") == 1:
            return SimpleNamespace(returncode=0)
        return SimpleNamespace(returncode=0 if started else 1, stdout="\tpid = 22\n")

    async def probe(self, instance, *, stop=False):
        return "verified"

    monkeypatch.setattr(service_launchd, "_launchctl", launchctl)
    monkeypatch.setattr(ManagedLaunchdService, "_probe", probe)
    macos_service.control_launchd_service("start", None)
    content = agent.read_bytes()
    value = plistlib.loads(content)
    assert value["ProgramArguments"] == [str(python), "-I", "-m", 'loushang.coding.hosted.foreground']
    assert b"secret-must-not-enter-plist" not in content
    assert value["KeepAlive"] == {"SuccessfulExit": False}
    assert value["LimitLoadToSessionType"] == "Background"


def test_launchd_status_rejects_stale_pid_without_probing(tmp_path, monkeypatch):
    root = tmp_path / "state/macos-host"
    root.mkdir(parents=True)
    (root / "endpoint.json").write_text('{"pid": 11, "instanceId": "old"}')
    monkeypatch.setattr(macos_service, "resolve_platform_home", lambda: tmp_path)
    monkeypatch.setattr(service_launchd, "_launchctl", lambda *_: SimpleNamespace(returncode=0, stdout="\tpid = 22\n"))
    monkeypatch.setattr(ManagedLaunchdService, "_probe", lambda *_: pytest.fail("must not probe stale endpoint"))
    assert macos_service.control_launchd_service("status", None) == {"state": "starting"}


def test_launchd_stale_instance_cannot_stop_new_service(standalone_workspace, monkeypatch):
    monkeypatch.setattr(macos_service, "resolve_platform_home", lambda: standalone_workspace)
    monkeypatch.setattr(ManagedLaunchdService, "_status", lambda *_: {"state": "running", "instanceId": "new"})
    monkeypatch.setattr(service_launchd, "_launchctl", lambda *_: pytest.fail("must not signal service"))
    with pytest.raises(ServiceControlError, match="instance_changed"):
        macos_service.control_launchd_service("stop", "old")


def test_launchd_refuses_other_writable_control_directory(tmp_path, monkeypatch):
    state = tmp_path / "state/macos-host"
    state.mkdir(parents=True)
    state.chmod(0o777)
    monkeypatch.setattr(macos_service, "resolve_platform_home", lambda: tmp_path)
    monkeypatch.setattr(service_launchd, "_launchctl", lambda *_: pytest.fail("must not load an unsafe plist"))
    with pytest.raises(ServiceControlError, match="unsafe_state_directory"):
        macos_service.control_launchd_service("start", None)


def test_launchd_stop_wait_does_not_accept_an_instance_replacement(monkeypatch):
    monkeypatch.setattr(service_launchd, "_launchctl", lambda *_: SimpleNamespace(returncode=0, stdout="\tpid = 22\n"))
    with pytest.raises(service_launchd.LaunchdJobError, match="instance_changed"):
        service_launchd.LaunchdUserJob("test").wait_for_exit(11)
