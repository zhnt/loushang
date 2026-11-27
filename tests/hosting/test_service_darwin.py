from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

from loushang.hosting import machine_identity, service_darwin
from loushang.hosting.errors import HostingError, HostingFailureCategory


def test_darwin_native_entry_points_guard_an_unsupported_platform(monkeypatch):
    monkeypatch.setattr(service_darwin, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(service_darwin, "os", SimpleNamespace())
    monkeypatch.setattr(machine_identity, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(machine_identity, "subprocess", SimpleNamespace())
    with pytest.raises(HostingError) as observer:
        service_darwin.DarwinServiceObserverV1.capture(123)
    assert observer.value.category is HostingFailureCategory.PLATFORM_UNSUPPORTED
    with pytest.raises(HostingError) as machine:
        machine_identity.darwin_machine_key(domain="loushang.managed.machine/v1")
    assert machine.value.category is HostingFailureCategory.PLATFORM_UNSUPPORTED


@pytest.mark.requires_host_runtime
@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin libproc and kqueue")
def test_darwin_service_identity_and_original_group_exit():
    assert len(machine_identity.darwin_machine_key(domain="loushang.managed.machine/v1")) == 32
    with subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(20)"],
        start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ) as process:
        first = None
        try:
            first = service_darwin.DarwinServiceObserverV1.capture(process.pid)
            second = service_darwin.DarwinServiceObserverV1.reopen(first.identity)
            try:
                assert not first.exited()
                process.terminate()
                assert first.exited(timeout=5)
                assert second.exited(timeout=5)
                process.wait(timeout=5)
                assert first.scope_exited()
            finally:
                second.close()
        finally:
            if first is not None:
                first.close()
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
