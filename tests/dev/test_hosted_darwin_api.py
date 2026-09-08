"""Portable boundary controls and actual Darwin public-API primitives."""

from __future__ import annotations

import ctypes
import errno
import json
import os
import signal
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("code", [0, 7])
def test_native_exit_note_does_not_reap_before_waitable_exit(code):
    from tests.coding.test_hosted_darwin_primitives import _exit_observed

    results = iter([None, code])
    watch = SimpleNamespace(exited=lambda: {1234})
    api = SimpleNamespace(exited_unreaped=lambda pid: next(results))
    assert not _exit_observed(watch, api, 1234, code)
    assert _exit_observed(watch, api, 1234, code)


def test_fork_parent_settlement_keeps_interrupt_guard_and_ignores_broken_diagnostics(monkeypatch):
    from tests.coding import _hosted_primitive_child as module

    previous = signal.getsignal(signal.SIGINT)
    seen = []

    def close():
        handler = signal.getsignal(signal.SIGINT)
        assert callable(handler) and handler != previous
        handler(signal.SIGINT, None)
        seen.append("close")
        if len(seen) == 1:
            raise KeyboardInterrupt

    def wait(**kwargs):
        assert signal.getsignal(signal.SIGINT) != previous
        seen.append("wait")
        return 0

    monkeypatch.setattr(module, "print", lambda *a, **k: (_ for _ in ()).throw(OSError("closed")), raising=False)
    module._settle_fork_parent(SimpleNamespace(stdin=SimpleNamespace(close=close), wait=wait))
    assert seen == ["close", "close", "wait"]
    assert signal.getsignal(signal.SIGINT) == previous


def test_native_primitive_child_disables_site_before_test_body(monkeypatch):
    from tests.coding import _hosted_primitive_child as module

    calls = []
    process = SimpleNamespace(stdin=SimpleNamespace(close=lambda: None),
                              poll=lambda: 0, wait=lambda **kwargs: 0)
    monkeypatch.setattr(module.subprocess, "Popen", lambda args, **kwargs: calls.append((args, kwargs)) or process)
    with module._child("pass"):
        pass
    assert calls[0][0][1:4] == ["-I", "-S", "-c"]
    assert calls[0][1]["start_new_session"] == (os.name == "posix")


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group interrupt control")
@pytest.mark.parametrize("marker_failure", [False, True])
def test_observer_group_interrupt_cannot_interrupt_the_actual_reaping_parent(tmp_path, marker_failure):
    from tests.coding import _hosted_primitive_child as fixture
    from tests.coding._hosted_terminal import process_table
    from tests.coding.test_hosted_darwin_primitives import _until

    if marker_failure:
        (tmp_path / "fork-child").mkdir()  # Actual write_text OSError after fork.
    child_code = (
        "import os,sys,time\nfrom pathlib import Path\n"
        f"root=Path({str(tmp_path)!r})\n"
        "child=os.fork()\n"
        "if child == 0:\n"
        "    while not (root/'release').exists(): time.sleep(.01)\n"
        "    os._exit(0)\n"
        "code=0\n"
        "try:\n"
        "    (root/'fork-child').write_text(str(child))\n"
        "except OSError:\n"
        "    code=17\n"
        "    (root/'marker-failed').touch()\n"
        "finally:\n"
        "    while True:\n"
        "        try:\n"
        "            os.waitpid(child,0)\n"
        "            break\n"
        "        except (InterruptedError, KeyboardInterrupt): pass\n"
        "(root/'fork-reaped').write_text(str(child))\n"
        "sys.exit(code)\n"
    )
    driver_code = (
        "import os,signal,runpy,time,json\nfrom pathlib import Path\n"
        f"root=Path({str(tmp_path)!r})\n"
        f"fixture=runpy.run_path({str(Path(fixture.__file__))!r})\n"
        "signal.signal(signal.SIGINT, lambda *_: (root/'interrupted').touch())\n"
        f"with fixture['_child']({child_code!r}, forking=True) as parent:\n"
        "    try:\n"
        "        deadline=time.monotonic()+5\n"
        "        while not ((root/'fork-child').is_file() or (root/'marker-failed').exists()):\n"
        "            if time.monotonic() >= deadline: raise TimeoutError('fork publication')\n"
        "            time.sleep(.01)\n"
        "        (root/'ready').write_text(json.dumps({'driver':os.getpid(),'parent':parent.pid}))\n"
        "        while not (root/'release').exists(): time.sleep(.01)\n"
        "    finally:\n"
        "        (root/'release').touch()\n"
        f"    assert parent.wait(timeout=5) == {17 if marker_failure else 0}\n"
        "    assert (root/'fork-reaped').exists()\n"
    )
    with fixture._child(driver_code, forking=True) as driver:
        try:
            _until(lambda: (tmp_path / "ready").exists())
            identities = json.loads((tmp_path / "ready").read_text())
            parent = identities["parent"]
            table = process_table()
            children = [pid for pid, (ppid, _) in table.items() if ppid == parent]
            assert len(children) == 1
            child = children[0]
            assert (tmp_path / "marker-failed").exists() == marker_failure
            assert identities["driver"] == driver.pid and os.getpgid(driver.pid) == driver.pid
            assert os.getpgid(parent) == parent and os.getpgid(child) == parent
            os.killpg(driver.pid, signal.SIGINT)
            _until(lambda: (tmp_path / "interrupted").exists())
            table = process_table()
            assert table[parent][0] == driver.pid and "Z" not in table[parent][1]
            assert table[child][0] == parent and "Z" not in table[child][1]
        finally:
            (tmp_path / "release").touch()
        assert driver.wait(timeout=5) == 0
        assert int((tmp_path / "fork-reaped").read_text()) == child
        assert parent not in process_table() and child not in process_table()


def test_darwin_waitid_observes_without_reaping(monkeypatch):
    from tests.coding import _hosted_darwin_api as module

    calls = []

    def waitid(kind, pid, target, options):
        calls.append((kind, pid, options))
        info = ctypes.cast(target, ctypes.POINTER(module._SigInfo)).contents
        info.si_pid, info.si_code, info.si_status = pid, 1, 7
        info.si_signo = 20
        return 0

    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="darwin"))
    api = module.DarwinObservationApi(libc=SimpleNamespace(waitid=waitid))
    assert api.exited_unreaped(1234) == 7
    assert calls == [(1, 1234, 0x25)]  # P_PID; WNOHANG | WEXITED | WNOWAIT.
    assert ctypes.sizeof(module._SigInfo) == 104
    assert module._SigInfo.si_status.offset == 20
    assert module._SigInfo.si_addr.offset == 24
    assert module._SigInfo.si_value.offset == 32
    assert module._SigInfo.si_band.offset == 40
    assert module._SigInfo.padding.offset == 48


@pytest.mark.parametrize("status", [17, 18, 21, 22, 0, 9, 32])
def test_darwin_waitid_stopped_child_is_not_an_exit(monkeypatch, status):
    from tests.coding import _hosted_darwin_api as module

    def waitid(kind, pid, target, options):
        assert options == 0x25
        info = ctypes.cast(target, ctypes.POINTER(module._SigInfo)).contents
        info.si_pid, info.si_signo = pid, 20
        info.si_code, info.si_status = 5, status  # CLD_STOPPED, not CLD_EXITED.
        return 0

    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="darwin"))
    api = module.DarwinObservationApi(libc=SimpleNamespace(waitid=waitid))
    if status in {17, 18, 21, 22}:
        assert api.exited_unreaped(1234) is None
        assert api.exited_unreaped(1234) is None
    else:
        with pytest.raises(RuntimeError, match="unexpected native waitid state"):
            api.exited_unreaped(1234)


@pytest.mark.parametrize("result", ["live", "signal", "foreign", "unknown", "error"])
def test_darwin_waitid_never_infers_exit_from_invalid_evidence(monkeypatch, result):
    from tests.coding import _hosted_darwin_api as module

    def waitid(kind, pid, target, options):
        info = ctypes.cast(target, ctypes.POINTER(module._SigInfo)).contents
        if result == "error":
            ctypes.set_errno(errno.ECHILD)
            return -1
        if result != "live":
            info.si_signo = 20
            info.si_pid = pid + (result == "foreign")
            info.si_code = 2 if result == "signal" else 99
            info.si_status = 9
        return 0

    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="darwin"))
    api = module.DarwinObservationApi(libc=SimpleNamespace(waitid=waitid))
    if result in {"live", "signal"}:
        assert api.exited_unreaped(1234) == (None if result == "live" else -9)
    else:
        with pytest.raises(OSError if result == "error" else RuntimeError):
            api.exited_unreaped(1234)


def _native(events, *, admission_error=False):
    closed, changes = [], []

    class Queue:
        def control(self, changelist, max_events, timeout):
            if changelist:
                changes.extend(changelist)
                return [SimpleNamespace(ident=changelist[0].ident, flags=0x4000,
                                        data=errno.ESRCH if admission_error else 0)]
            return events.pop(0) if events else []

        def close(self):
            closed.append(True)

    native = SimpleNamespace(
        kqueue=Queue, kevent=lambda pid, **kw: SimpleNamespace(ident=pid, **kw),
        KQ_FILTER_PROC=-5, KQ_EV_ADD=1, KQ_EV_CLEAR=0x20,
        KQ_EV_ERROR=0x4000, KQ_NOTE_EXIT=0x80000000,
        KQ_NOTE_FORK=0x40000000, KQ_NOTE_EXEC=0x20000000,
    )
    return native, closed, changes


@pytest.mark.parametrize("fault", ["fork", "exec", "foreign", "error", "registration"])
def test_darwin_watch_rejects_unknown_topology_and_failed_registration(fault):
    from tests.coding._hosted_darwin_api import DarwinExitWatch, DarwinWatchEventError

    event = SimpleNamespace(ident=1234 if fault != "foreign" else 1235,
                            flags=0x4000 if fault == "error" else 0,
                            fflags={"fork": 0x40000000, "exec": 0x20000000}.get(fault, 0x80000000))
    native, closed, _ = _native([[event]], admission_error=fault == "registration")
    if fault == "registration":
        with pytest.raises(OSError):
            DarwinExitWatch([1234], native=native)
        assert closed == [True]
        return
    watch = DarwinExitWatch([1234], native=native)
    try:
        with pytest.raises(DarwinWatchEventError) as rejected:
            watch.exited()
        assert rejected.value.registered is (fault != "foreign")
        assert (rejected.value.flags, rejected.value.notes) == (event.flags, event.fflags)
        with pytest.raises(RuntimeError):
            watch.exited()  # Empty later observations cannot clear unknown debt.
    finally:
        watch.close()
    assert closed == [True]


def test_darwin_watch_records_only_registered_exit_events():
    from tests.coding._hosted_darwin_api import DarwinExitWatch

    native, closed, changes = _native([
        [SimpleNamespace(ident=1234, flags=0, fflags=0x80000000)],
        [SimpleNamespace(ident=1235, flags=0, fflags=0x80000000)],
    ])
    watch = DarwinExitWatch([1234, 1235], native=native)
    try:
        assert watch.exited() == {1234}
        assert watch.exited() == {1234, 1235}
        assert all(change.fflags == 0xE0000000 for change in changes)
        assert all(change.flags & 0x40 for change in changes)
    finally:
        watch.close()
        watch.close()
    assert closed == [True]


@pytest.mark.parametrize("combined", [False, True])
def test_owned_group_watch_records_fork_without_inventing_exit(combined):
    from tests.coding._hosted_darwin_api import DarwinExitWatch

    notes = 0x40000000 | (0x80000000 if combined else 0)
    native, _, _ = _native([
        [SimpleNamespace(ident=1235, flags=0x61, fflags=notes)],
        [SimpleNamespace(ident=1234, flags=0, fflags=0x80000000),
         SimpleNamespace(ident=1235, flags=0, fflags=0x80000000)],
    ])
    watch = DarwinExitWatch([1234, 1235], native=native, group_members=[1235])
    try:
        assert watch.exited() == ({1235} if combined else set())
        assert watch.forked == {1235}
        assert watch.exited() == {1234, 1235}
        assert watch.forked == {1235}
    finally:
        watch.close()


@pytest.mark.parametrize("pid,notes,flags", [
    (1234, 0x40000000, 0), (9999, 0x40000000, 0),
    (1235, 0x20000000, 0), (1235, 0xA0000000, 0),
    (1235, 1, 0), (1235, 0, 0), (1235, 0x40000000, 0x4000),
])
def test_owned_group_mode_does_not_admit_cli_forks_or_unknown_events(pid, notes, flags):
    from tests.coding._hosted_darwin_api import DarwinExitWatch

    native, _, _ = _native([[SimpleNamespace(ident=pid, flags=flags, fflags=notes)]])
    watch = DarwinExitWatch([1234, 1235], native=native, group_members=[1235])
    try:
        with pytest.raises(RuntimeError, match="topology"):
            watch.exited()
        with pytest.raises(RuntimeError, match="unavailable"):
            watch.exited()
    finally:
        watch.close()


@pytest.mark.parametrize("probe,rows,empty", [
    (None, {}, False), (PermissionError(), {}, False),
    (ProcessLookupError(), {1236: (1235, "S")}, False),
    (ProcessLookupError(), {1236: (1235, "Z")}, False),
    (ProcessLookupError(), {1236: (4321, "S")}, True),
])
def test_owned_group_absence_requires_signal_zero_and_all_members_gone(monkeypatch, probe, rows, empty):
    from tests.coding import _hosted_owned_group as group

    calls = []

    def killpg(pgid, sig):
        assert (pgid, sig) == (1235, 0)
        calls.append("probe")
        if probe is not None:
            raise probe

    monkeypatch.setattr(group.os, "killpg", killpg, raising=False)
    monkeypatch.setattr(group, "process_groups", lambda: calls.append("table") or rows)
    assert group.group_empty(1235) is empty
    assert calls == (["probe", "table"] if isinstance(probe, ProcessLookupError) else ["probe"])


@pytest.mark.parametrize("failure", ["probe", "table"])
def test_owned_group_observation_error_cannot_complete(monkeypatch, failure):
    from tests.coding import _hosted_owned_group as group

    def killpg(*_):
        raise OSError("observation failed") if failure == "probe" else ProcessLookupError()

    monkeypatch.setattr(group.os, "killpg", killpg, raising=False)
    monkeypatch.setattr(group, "process_groups", lambda: (_ for _ in ()).throw(OSError("table failed")))
    with pytest.raises(OSError):
        group.group_empty(1235)


@pytest.mark.skipif(os.name != "posix", reason="actual POSIX group and zombie observation")
def test_owned_group_family_keeps_actual_reaper_through_live_and_zombie_residual(tmp_path):
    from tests.coding.test_hosted_darwin_primitives import _owned_group

    _owned_group(tmp_path)


def test_group_family_readiness_is_published_only_after_complete_json(tmp_path, monkeypatch):
    from tests.coding._hosted_primitive_child import _publish_group_ready

    replace = Path.replace
    calls = []

    def publish(path, target):
        assert not target.exists()
        assert json.loads(path.read_text(encoding="utf-8")) == [1234, 1235]
        calls.append(True)
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", publish)
    _publish_group_ready(tmp_path, [1234, 1235])
    assert calls == [True]
    assert json.loads((tmp_path / "family-ready").read_text(encoding="utf-8")) == [1234, 1235]


@pytest.mark.parametrize("bad", ["empty", "missing-self", "duplicate", "malformed"])
def test_native_group_table_rejects_incomplete_or_invalid_output(monkeypatch, bad):
    from tests.coding import _hosted_owned_group as group

    me = os.getpid()
    output = {"empty": "", "missing-self": "1 1 S\n",
              "duplicate": f"{me} 10 S\n{me} 10 S\n", "malformed": f"{me} 10 S\ntruncated"}[bad]
    monkeypatch.setattr(group.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=output))
    with pytest.raises((RuntimeError, ValueError)):
        group.process_groups()


def test_git_environment_cannot_inherit_host_repository_or_helper_configuration(tmp_path):
    import subprocess

    from tests.coding._hosted_owned_group import isolated_git_environment

    repository, workspace = tmp_path / "repository", tmp_path / "repository" / "fixture"
    workspace.mkdir(parents=True)
    environment = {**os.environ, "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.fsmonitor",
                   "GIT_CONFIG_VALUE_0": "ambient-helper", "git_dir": "ambient-repository"}
    sealed = isolated_git_environment(workspace, ["--workspace", str(workspace)], environment)
    assert "git_dir" not in sealed and sealed["GIT_CONFIG_COUNT"] == "2"
    assert sealed["GIT_CONFIG_VALUE_0"] == "false"

    def git(cwd, *args, check=True):
        return subprocess.run(["git", "-C", str(cwd), *args], env=sealed,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=5, check=check)

    git(repository, "init", "--quiet")
    git(repository, "config", "--local", "core.fsmonitor", "ambient-helper")
    git(repository, "config", "--local", "core.hooksPath", "ambient-hooks")
    assert git(workspace, "rev-parse", "--show-toplevel", check=False).returncode != 0
    # Editable source queries can still find this repo, but config precedence
    # must suppress its external helpers without suppressing Git itself.
    assert git(repository, "config", "--get", "core.fsmonitor").stdout.strip() == "false"
    assert git(repository, "config", "--get", "core.hooksPath").stdout.strip() == os.devnull
    git(repository, "status", "--porcelain")


@pytest.mark.parametrize("fault", ["outside", "git-dir", "git-file", "missing-workspace"])
def test_git_seal_rejects_out_of_scope_or_repository_workspaces(tmp_path, fault):
    from tests.coding._hosted_owned_group import isolated_git_environment

    root = tmp_path / "fixture"
    root.mkdir()
    if fault == "git-dir":
        (root / ".git").mkdir()
    elif fault == "git-file":
        (root / ".git").write_text("gitdir: somewhere\n", encoding="utf-8")
    arguments = [] if fault == "missing-workspace" else ["--workspace", str(tmp_path if fault == "outside" else root)]
    with pytest.raises(ValueError):
        isolated_git_environment(root, arguments, {})
