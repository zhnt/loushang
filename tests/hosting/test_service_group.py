from __future__ import annotations

import os
import sys

import pytest

from loushang.hosting.errors import HostingError
from loushang.hosting.service_group import LinuxServiceGroupObservationV1

from .test_service_process import launched as launched

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux service group observations")


def test_original_live_group_then_reaped_exit(launched, monkeypatch):
    owner, endpoint, _, _ = launched
    group = LinuxServiceGroupObservationV1(owner._observer)
    group.admit()
    original = os.killpg
    probes = []

    def probe(pid, sig):
        assert sig == 0 and pid == owner.identity.pid
        probes.append((pid, sig))
        return original(pid, sig)

    monkeypatch.setattr(os, "killpg", probe)
    assert not group.exited() and not probes
    endpoint.sendall(b"Q")
    owner._process.wait(timeout=5)
    assert group.exited() and len(probes) == 1
    assert not owner.handles_closed


@pytest.mark.parametrize("field", ["getpgid", "getsid"])
def test_not_a_detached_session_leader_is_rejected(launched, monkeypatch, field):
    owner, _, _, _ = launched
    monkeypatch.setattr(os, field, lambda pid: pid + 1)
    with pytest.raises(HostingError):
        LinuxServiceGroupObservationV1(owner._observer).admit()


def test_unadmitted_or_closed_borrow_never_probes_numeric_group(launched, monkeypatch):
    owner, _, _, _ = launched
    group = LinuxServiceGroupObservationV1(owner._observer)
    monkeypatch.setattr(os, "killpg", lambda *a: pytest.fail("unadmitted probe"))
    with pytest.raises(HostingError):
        group.exited()
    group.admit()
    owner.close()
    with pytest.raises(HostingError):
        group.exited()


@pytest.mark.parametrize("error", [PermissionError, OSError])
def test_failed_group_probe_never_proves_exit(launched, monkeypatch, error):
    owner, endpoint, _, _ = launched
    group = LinuxServiceGroupObservationV1(owner._observer)
    group.admit()
    endpoint.sendall(b"Q")
    owner._process.wait(timeout=5)

    def probe(*a):
        raise error("private native details")

    with monkeypatch.context() as patch:
        patch.setattr(os, "killpg", probe)
        if error is PermissionError:
            assert not group.exited()
        else:
            with pytest.raises(HostingError):
                group.exited()
