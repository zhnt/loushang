from __future__ import annotations

import json
import os
import select
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from loushang.hosting import service_group as service_group_module
from loushang.hosting.errors import HostingError
from loushang.hosting.service import LinuxServiceObserverV1
from loushang.hosting.service_group import (
    LinuxServiceGroupObservationV1,
    linux_current_boot_id,
    linux_service_group_absent_after_restart,
    linux_service_group_recovery_status,
)

from .test_service_process import launched as launched

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux service group observations"
)


@pytest.mark.parametrize("boot", [b"", b"not-a-boot-id", b"\xff" * 36])
def test_current_boot_identity_refuses_invalid_procfs_value(monkeypatch, boot):
    original = service_group_module._read_file

    def changed(path, *args, **kwargs):
        if path == "/proc/sys/kernel/random/boot_id":
            return boot
        return original(path, *args, **kwargs)

    monkeypatch.setattr(service_group_module, "_read_file", changed)
    with pytest.raises(HostingError):
        linux_current_boot_id()


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


def test_reopened_group_absence_requires_same_boot_and_namespace(
    launched, monkeypatch
):
    owner, endpoint, _, _ = launched
    identity = owner.identity
    assert linux_current_boot_id() == identity.boot_id
    assert not linux_service_group_absent_after_restart(identity)
    assert linux_service_group_recovery_status(identity) == "present"
    assert _reopened_group_status(identity) == "present"

    old_boot = replace(
        identity, boot_id="00000000-0000-0000-0000-000000000000"
    )
    with pytest.raises(HostingError):
        linux_service_group_absent_after_restart(old_boot)
    with monkeypatch.context() as patch:
        patch.setattr(os, "killpg", lambda *_args: pytest.fail("prior-boot probe"))
        assert linux_service_group_recovery_status(old_boot) == (
            "prior_boot_absent"
        )
    with pytest.raises(HostingError):
        linux_service_group_absent_after_restart(
            replace(identity, pid_namespace_inode=identity.pid_namespace_inode + 1)
        )
    assert linux_service_group_recovery_status(
        replace(identity, pid_namespace_inode=identity.pid_namespace_inode + 1)
    ) == "context_stale"

    endpoint.sendall(b"Q")
    owner._process.wait(timeout=5)
    owner.close()
    assert linux_service_group_absent_after_restart(identity)
    assert linux_service_group_recovery_status(identity) == "absent"
    assert _reopened_group_status(identity) == "absent"


def test_reopened_group_probe_does_not_treat_denial_as_absence(launched, monkeypatch):
    owner, _, _, _ = launched
    identity = owner.identity

    def denied(*_args):
        raise PermissionError("probe denied")

    def failed(*_args):
        raise OSError("probe failed")

    with monkeypatch.context() as patch:
        patch.setattr(os, "killpg", denied)
        assert not linux_service_group_absent_after_restart(identity)
    with monkeypatch.context() as patch:
        patch.setattr(os, "killpg", failed)
        with pytest.raises(HostingError):
            linux_service_group_absent_after_restart(identity)


def test_reopened_group_keeps_descendant_after_leader_exit() -> None:
    leader_read, leader_write = os.pipe()
    descendant_read, descendant_write = os.pipe()
    script = """
import os, subprocess, sys
child = subprocess.Popen(
    [sys.executable, '-c', 'import os,sys; os.read(int(sys.argv[1]),1)', sys.argv[2]],
    pass_fds=(int(sys.argv[2]),),
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
print(child.pid, flush=True)
os.read(int(sys.argv[1]), 1)
"""
    leader = subprocess.Popen(
        [sys.executable, "-c", script, str(leader_read), str(descendant_read)],
        pass_fds=(leader_read, descendant_read),
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    os.close(leader_read)
    os.close(descendant_read)
    leader_observer = descendant_observer = None
    try:
        assert leader.stdout is not None
        assert select.select([leader.stdout], [], [], 5)[0]
        descendant_pid = int(leader.stdout.readline())
        leader_observer = LinuxServiceObserverV1.capture(leader.pid)
        group = LinuxServiceGroupObservationV1(leader_observer)
        group.admit()
        descendant_observer = LinuxServiceObserverV1.capture(descendant_pid)
        os.write(leader_write, b"x")
        leader.wait(timeout=5)
        assert leader_observer.exited(timeout=1)
        assert not descendant_observer.exited()
        assert not linux_service_group_absent_after_restart(leader_observer.identity)
        assert _reopened_group_status(leader_observer.identity) == "present"
    finally:
        os.close(leader_write)
        os.close(descendant_write)
        leader.communicate(timeout=5)
        if descendant_observer is not None:
            assert descendant_observer.exited(timeout=5)
            descendant_observer.close()
        if leader_observer is not None:
            leader_observer.close()


def _reopened_group_status(identity) -> str:
    script = """
import json, sys
from loushang.hosting.service import LinuxServiceIdentityV1
from loushang.hosting.service_group import linux_service_group_absent_after_restart
identity = LinuxServiceIdentityV1(**json.loads(sys.argv[1]))
print('absent' if linux_service_group_absent_after_restart(identity) else 'present')
"""
    environment = dict(
        os.environ,
        PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"),
    )
    result = subprocess.run(
        [sys.executable, "-c", script, json.dumps(asdict(identity))],
        capture_output=True,
        text=True,
        timeout=5,
        env=environment,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()
