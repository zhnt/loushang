"""Portable wiring checks, never Windows native acceptance substitutes."""

from __future__ import annotations

import subprocess
import threading
from contextlib import ExitStack
from types import SimpleNamespace

import pytest

from tests.coding import _hosted_windows_witness as witness
from tests.coding._hosted_windows_api import SuspendedThreads, WindowsObservationApi
from tests.coding._hosted_windows_observer import (
    _assert_exited,
    _controller_chain,
    _pin_chain,
    _tree_fact,
)


@pytest.mark.parametrize("image,accepted", [
    (r"C:\WINDOWS\system32\ConHost.exe", True),
    (r"C:\workspace\conhost.exe", False),
    ("C:\\workspace\\\U0001f600\\python.exe", False),
    (r"C:\Windows\System32\conhost.exe.fake", False),
])
def test_windows_console_image_uses_pinned_full_path(image, accepted):
    class ImageApi(WindowsObservationApi):
        def __init__(self):
            pass

        def call(self, name, arguments, result, *values):
            if name == "QueryFullProcessImageNameW":
                handle, flags, buffer, size = values
                assert handle == 44 and flags == 0
                buffer.value = image
                size._obj.value = len(image.encode("utf-16-le")) // 2
                return 1
            assert name == "GetSystemDirectoryW"
            values[0].value = r"C:\Windows\System32"
            return len(values[0].value)

    assert ImageApi().is_console_host(44) is accepted


def test_windows_system_directory_length_counts_wide_characters():
    directory = "C:\\\U0001f600\\System32"
    image = directory + "\\conhost.exe"

    class ImageApi(WindowsObservationApi):
        def __init__(self):
            pass

        def call(self, name, arguments, result, *values):
            if name == "QueryFullProcessImageNameW":
                values[2].value = image
                values[3]._obj.value = len(image.encode("utf-16-le")) // 2
                return 1
            assert name == "GetSystemDirectoryW"
            values[0].value = directory
            return len(directory.encode("utf-16-le")) // 2

    assert ImageApi().is_console_host(44)


@pytest.mark.parametrize("stage", ["image-failed", "image-truncated", "directory-failed", "directory-truncated"])
def test_windows_console_image_rejects_incomplete_native_queries(stage):
    class ImageApi(WindowsObservationApi):
        def __init__(self):
            pass

        def call(self, name, arguments, result, *values):
            if name == "QueryFullProcessImageNameW":
                if stage == "image-failed":
                    return 0
                values[2].value = r"C:\Windows\System32\conhost.exe"
                values[3]._obj.value = 32768 if stage == "image-truncated" else len(values[2].value)
                return 1
            assert name == "GetSystemDirectoryW"
            return 0 if stage == "directory-failed" else 32768

    with pytest.raises(RuntimeError, match="query"):
        ImageApi().is_console_host(44)


class TreeApi:
    def __init__(self, table, *, current=None, images=None):
        self.tables = iter([table, table if current is None else current])
        self.images = images or {3: r"C:\Windows\System32\conhost.exe"}
        self.opened, self.closed, self.dead = [], [], set()

    def entries(self):
        return next(self.tables)

    def open_process(self, pid):
        self.opened.append(pid)
        return pid

    def close(self, handle):
        self.closed.append(handle)

    def ended(self, handle):
        return handle in self.dead

    def is_console_host(self, handle):
        assert handle in self.opened
        return self.images.get(handle, "python.exe").lower() == (
            r"c:\windows\system32\conhost.exe"
        )


def test_windows_tree_retains_console_sidecar_outside_fault_chain():
    api = TreeApi({1: 99, 2: 1, 3: 2, 4: 2})
    with ExitStack() as handles:
        chain, sidecars = _pin_chain(api, 1, 99, handles)
        assert chain == [(1, 1), (2, 2), (4, 4)]
        assert sidecars == [(3, 3)]
        api.dead.update([1, 2, 4])
        with pytest.raises(AssertionError, match="remains"):
            _assert_exited(api, chain, sidecars, deadline=0)
        api.dead.add(3)
        _assert_exited(api, chain, sidecars, deadline=0)
    assert sorted(api.closed) == [1, 2, 3, 4]


def test_windows_single_child_console_host_cannot_be_fault_target():
    api = TreeApi({1: 99, 2: 1, 3: 2})
    with pytest.raises(AssertionError, match="main-chain target"), ExitStack() as handles:
        _pin_chain(api, 1, 99, handles)
    assert sorted(api.closed) == [1, 2, 3]


@pytest.mark.parametrize("case", ["lookalike", "second", "descendant", "reparent", "new", "api"])
def test_windows_tree_rejects_unverified_console_branches(case, monkeypatch):
    table = {1: 99, 2: 1, 3: 2, 4: 2}
    current = dict(table)
    images = {3: r"C:\Windows\System32\conhost.exe"}
    if case == "lookalike":
        images[3] = r"C:\workspace\conhost.exe"
    elif case == "second":
        table.update({5: 4, 6: 4})
        current = dict(table)
        images[5] = images[3]
    elif case == "descendant":
        table[5] = 3
    elif case == "reparent":
        current[3] = 99
    elif case == "new":
        current[5] = 4
    api = TreeApi(table, current=current, images=images)
    if case == "api":
        monkeypatch.setattr(api, "is_console_host", lambda _: (_ for _ in ()).throw(OSError()))
    with pytest.raises((AssertionError, OSError)), ExitStack() as handles:
        _pin_chain(api, 1, 99, handles)
    assert sorted(api.closed) == sorted(api.opened)


def test_windows_tree_failure_diagnostics_are_bounded_metadata_only():
    api = SimpleNamespace(process_names={1: "python.exe", 2: "conhost.exe"})
    facts = _tree_fact(api, 1, list(range(2, 102)), [(pid, 0) for pid in range(20)])
    assert facts["parent"] == (1, "python.exe")
    assert facts["children"][0] == (2, "conhost.exe")
    assert facts["child_count"] == 100
    assert len(facts["children"]) == 16 and len(facts["chain"]) == 8
    assert set(facts) == {"parent", "children", "chain", "child_count"}


def test_windows_probe_collection_is_confined_and_imports_test_helpers(tmp_path, monkeypatch):
    from tests.coding import test_hosted_windows_evidence as evidence

    def collect(argv, *, cwd, environment, timeout):
        assert argv[argv.index("--rootdir") + 1] == str(tmp_path)
        assert argv[argv.index("--confcutdir") + 1] == str(tmp_path)
        result = subprocess.run(
            [*argv, "--collect-only"], cwd=cwd, env=environment,
            capture_output=True, text=True, timeout=timeout,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "1 test collected" in result.stdout

    monkeypatch.setattr(evidence, "runpy", SimpleNamespace(run_path=lambda _: {"run_pytest": collect}))
    evidence.run_observation(tmp_path, "real")


class Api:
    def __init__(self):
        self.threads = {10: 2}
        self.closed, self.suspended, self.resumed = [], [], []
        self.confirmed = []
        self.dead = set()
        self.close_error = False

    def entries(self, *, threads=False):
        assert threads
        return dict(self.threads)

    def ended(self, handle):
        return handle in self.dead

    def open_thread(self, tid, pid):
        assert self.threads[tid] == pid
        return tid

    def suspend(self, handle):
        self.suspended.append(handle)
        if handle == 10:
            self.threads[11] = 2  # Created before its parent thread was stopped.

    def resume(self, handle):
        self.resumed.append(handle)

    def confirm_stopped(self, handle):
        assert handle in self.suspended
        self.confirmed.append(handle)

    def close(self, handle):
        if self.close_error:
            self.close_error = False
            raise OSError("close retry")
        self.closed.append(handle)


def test_windows_fault_reaches_fixed_point_and_undoes_only_own_increments():
    api = Api()
    fault = SuspendedThreads(api, 2, 20)
    fault.stop()
    assert api.suspended == [10, 11]
    assert api.confirmed == [10, 11]
    api.close_error = True
    with pytest.raises(ExceptionGroup):
        fault.close()
    fault.close()
    assert api.resumed == [10, 11], "handle close retry must not decrement twice"
    assert set(api.closed) == {10, 11}
    assert not fault.handles


def test_windows_fault_does_not_resume_terminated_threads():
    api = Api()
    fault = SuspendedThreads(api, 2, 20)
    fault.stop()
    api.dead.update([10, 11, 20])
    fault.close()
    assert not api.resumed and set(api.closed) == {10, 11}


def test_windows_fault_partial_suspend_failure_remains_recoverable(monkeypatch):
    api = Api()
    original = api.suspend

    def suspend(handle):
        if handle == 11:
            raise OSError("suspend failed")
        original(handle)

    monkeypatch.setattr(api, "suspend", suspend)
    fault = SuspendedThreads(api, 2, 20)
    with pytest.raises(OSError, match="suspend failed"):
        fault.stop()
    fault.close()
    assert api.resumed == [10]
    assert set(api.closed) == {10, 11}


def test_windows_fault_suspend_and_close_failure_keeps_unpaused_handle(monkeypatch):
    api = Api()
    monkeypatch.setattr(api, "suspend", lambda _: (_ for _ in ()).throw(OSError("suspend")))
    fault = SuspendedThreads(api, 2, 20)
    with pytest.raises(OSError, match="suspend"):
        fault.stop()
    api.close_error = True
    with pytest.raises(ExceptionGroup):
        fault.close()
    assert fault.handles == {10: 10} and not api.resumed
    fault.close()
    assert not fault.handles and not api.resumed and api.closed == [10]


def test_windows_fault_confirmation_failure_still_undoes_suspend(monkeypatch):
    api = Api()
    monkeypatch.setattr(api, "confirm_stopped", lambda _: (_ for _ in ()).throw(OSError("context")))
    fault = SuspendedThreads(api, 2, 20)
    with pytest.raises(OSError, match="context"):
        fault.stop()
    fault.close()
    assert api.resumed == [10] and api.closed == [10]


def test_windows_fault_interrupted_suspend_handoff_retains_uncertain_ownership():
    class InterruptedSet(set):
        def add(self, value):
            raise KeyboardInterrupt

    api = Api()
    fault = SuspendedThreads(api, 2, 20)
    fault.suspended = InterruptedSet()
    with pytest.raises(KeyboardInterrupt):
        fault.stop()
    assert fault.uncertain == {10} and fault.handles == {10: 10}
    with pytest.raises(ExceptionGroup, match="cleanup pending"):
        fault.close()
    assert not api.closed and not api.resumed


def test_windows_fault_interrupted_resume_does_not_repeat_effect(monkeypatch):
    api = Api()
    fault = SuspendedThreads(api, 2, 20)
    fault.stop()

    def interrupted_resume(handle):
        api.resumed.append(handle)
        raise KeyboardInterrupt

    monkeypatch.setattr(api, "resume", interrupted_resume)
    with pytest.raises(KeyboardInterrupt):
        fault.close()
    # Simulate ExitStack re-entering cleanup after the explicit resume failed.
    monkeypatch.setattr(api, "resume", api.resumed.append)
    with pytest.raises(ExceptionGroup, match="cleanup pending"):
        fault.close()
    assert api.resumed == [10, 11]
    assert fault.uncertain == {10} and fault.handles == {10: 10}
    assert api.closed == [11]


def test_windows_witness_and_controller_shims_do_not_stand_in_for_hosted():
    chain = [(pid, pid + 10) for pid in range(1, 7)]
    started = {"witness": 2, "pid": 3}
    assert _controller_chain(chain, started, {1, 2, 3, 4}) == chain[2:]
    with pytest.raises(AssertionError, match="not observed"):
        _controller_chain(chain[:4], started, {1, 2, 3, 4})
    with pytest.raises(AssertionError, match="ambiguous"):
        _controller_chain(chain, started, {1, 2, 3, 4, 6})


def test_windows_process_chain_rejects_changed_ancestry_and_closes_handles():
    from contextlib import ExitStack

    class ChainApi(Api):
        def __init__(self):
            super().__init__()
            self.tables = iter([{1: 99, 2: 1, 3: 2}, {1: 99, 2: 1, 3: 55}])

        def entries(self):
            return next(self.tables)

        def open_process(self, pid):
            return pid

        def is_console_host(self, handle):
            return False

    api = ChainApi()
    with pytest.raises(AssertionError, match="identity changed"), ExitStack() as handles:
        _pin_chain(api, 1, 99, handles)
    assert api.closed == [3, 2, 1]


def test_windows_witness_samples_same_console_before_releasing(tmp_path, monkeypatch):
    facts = []

    class Console:
        def protect_witness_interrupt(self):
            facts.append("handler")

        def modes(self):
            facts.append("mode")
            return [7, 3]

        def console_processes(self):
            return [10]

    class Process:
        pid = 10
        polls = 0

        def poll(self):
            self.polls += 1
            return None if self.polls == 1 else 0

        def wait(self):
            facts.append("wait")
            return 0

    def spawn(arguments):
        assert facts == ["handler", "mode"]
        (tmp_path / "sample.request").touch()
        return Process()

    publish = witness.publish

    def record(root, name, value):
        facts.append(name)
        publish(root, name, value)
        if name == "finished":
            (root / "release").touch()

    monkeypatch.setattr(witness, "publish", record)
    assert witness.witness(tmp_path, ["actual-command"], api=Console(), spawn=spawn) == 0
    assert facts == ["handler", "mode", "started", "mode", "sample", "wait", "mode", "finished"]


def test_windows_witness_receipt_failure_does_not_release_itself(tmp_path, monkeypatch):
    failed = threading.Event()
    result = []

    class Console:
        def protect_witness_interrupt(self):
            raise OSError("observer admission")

    def publish(*args):
        failed.set()
        raise OSError("receipt unavailable")

    monkeypatch.setattr(witness, "publish", publish)
    thread = threading.Thread(target=lambda: result.append(witness.witness(tmp_path, [], api=Console())))
    thread.start()
    try:
        assert failed.wait(2)
        assert thread.is_alive() and not result
    finally:
        (tmp_path / "release").touch()
        thread.join(timeout=2)
    assert not thread.is_alive() and result == [1]
