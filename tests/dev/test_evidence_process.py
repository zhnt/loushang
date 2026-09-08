"""Actual supervisor timeout/interrupt against multi-generation native groups."""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import sysconfig
import threading
import time
import venv as venv_module
from pathlib import Path
from types import SimpleNamespace

import pytest

_PATH = Path(__file__).resolve().parents[2] / "scripts/dev/_evidence_process.py"
_SPEC = importlib.util.spec_from_file_location("_evidence_process", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
supervisor = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(supervisor)


def _windows_layout(root):
    base, venv = root / "base", root / "venv"
    base.mkdir()
    (venv / "Scripts").mkdir(parents=True)
    executable = venv / "Scripts/python.exe"
    executable.touch()
    (base / "python.exe").touch()
    (base / f"python{sys.version_info.major}{sys.version_info.minor}.dll").touch()
    (venv / "pyvenv.cfg").write_text(f"home = {base}\n")
    return base, venv, executable


def test_windows_controller_bypasses_only_target_venv_redirector(tmp_path):
    native = supervisor._support("_evidence_windows")
    base, _, executable = _windows_layout(tmp_path)
    environment = {"PythonExecutable": "bad", "__pyvenv_launcher__": "bad", "KEEP": "yes"}
    program, clean = native.prepare_controller(str(executable), environment)
    assert program == str(base / "python.exe")
    assert clean == {"KEEP": "yes", "__PYVENV_LAUNCHER__": str(executable)}
    assert environment["PythonExecutable"] == "bad"


@pytest.mark.parametrize("fault", ["relative", "duplicate", "nested", "pth-base", "pth-venv", "dll", "large"])
def test_windows_controller_rejects_ambiguous_or_site_enabling_layout(tmp_path, fault):
    native = supervisor._support("_evidence_windows")
    base, venv, executable = _windows_layout(tmp_path)
    config = venv / "pyvenv.cfg"
    if fault == "relative":
        config.write_text("home = relative\n")
    elif fault == "duplicate":
        config.write_text(f"home = {base}\nhome = {base}\n")
    elif fault == "nested":
        (base / "pyvenv.cfg").write_text(f"home = {base}\n")
    elif fault.startswith("pth"):
        directory = base if fault == "pth-base" else executable.parent
        (directory / "python311._pth").write_text("import site\n")
    elif fault == "dll":
        (base / f"python{sys.version_info.major}{sys.version_info.minor}.dll").unlink()
    else:
        config.write_text("x" * 65537)
    with pytest.raises(ValueError):
        native.prepare_controller(str(executable), {})


def test_windows_controller_base_interpreter_does_not_inherit_venv_override(tmp_path):
    native = supervisor._support("_evidence_windows")
    base, _, _ = _windows_layout(tmp_path)
    program, environment = native.prepare_controller(str(base / "python.exe"), {
        "PYTHONEXECUTABLE": "bad", "__PYVENV_LAUNCHER__": "bad",
    })
    assert program == str(base / "python.exe") and environment == {}


@pytest.mark.parametrize("fault", [None, "pid", "site", "extra", "boolean", "job"])
def test_windows_admission_requires_actual_wrapper_and_single_owned_process(tmp_path, fault):
    result = tmp_path / "pytest-controller-result"
    value = {"pid": 77, "no_site": 1}
    if fault in {"pid", "site"}:
        value["pid" if fault == "pid" else "no_site"] = 0
    elif fault == "extra":
        value["extra"] = 1
    elif fault == "boolean":
        value["no_site"] = True
    result.with_suffix(".admission").write_text(json.dumps(value))
    process = SimpleNamespace(pid=77, args=["controlled"])
    job = SimpleNamespace(active=lambda: 2 if fault == "job" else 1)
    arguments = (process, job, result, time.monotonic() + 1, threading.Event())
    if fault is None:
        supervisor._await_admission(*arguments)
    else:
        with pytest.raises(ValueError, match="identity"):
            supervisor._await_admission(*arguments)


def test_windows_failed_admission_terminates_assigned_job_before_release():
    events = []
    counts = iter([2, 0])
    job = SimpleNamespace(active=lambda: next(counts),
                          terminate=lambda: events.append("terminate"),
                          close=lambda: events.append("close-job"))
    process = SimpleNamespace(returncode=1, wait=lambda **_: events.append("wait"),
                              stdin=SimpleNamespace(close=lambda: events.append("close-pipe")))
    assert supervisor._cleanup(process, job, forced=True, state={"not_admitted": True})
    assert events == ["terminate", "wait", "close-job", "close-pipe"]


def test_windows_admission_observes_interrupt_during_final_job_query(tmp_path):
    result = tmp_path / "pytest-controller-result"
    result.with_suffix(".admission").write_text(json.dumps({"pid": 77, "no_site": 1}))
    interrupted = threading.Event()

    def active():
        interrupted.set()
        return 1

    with pytest.raises(KeyboardInterrupt):
        supervisor._await_admission(SimpleNamespace(pid=77), SimpleNamespace(active=active),
                                    result, time.monotonic() + 1, interrupted)


@pytest.mark.parametrize("fault", ["cancelled", "expired"])
def test_windows_late_admission_never_starts_tests_and_reclaims_job(tmp_path, monkeypatch, fault):
    events, handlers = [], []
    clock = [0]
    counts = iter([1, 1, 0])

    def active():
        if fault == "cancelled":
            handlers[0]()
        else:
            clock[0] = 4
        return next(counts)

    job = SimpleNamespace(active=active, terminate=lambda: events.append("terminate"),
                          close=lambda: events.append("close-job"))

    def spawn(*args, **kwargs):
        (tmp_path / "pytest-controller-result.admission").write_text(
            json.dumps({"pid": 77, "no_site": 1})
        )
        return SimpleNamespace(pid=77, args=["controlled"], returncode=1,
                               wait=lambda **_: events.append("wait"),
                               stdin=SimpleNamespace(close=lambda: events.append("close-pipe")))

    def handler(number, callback):
        handlers.append(callback)
        return lambda *_: None

    monkeypatch.setattr(supervisor, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(supervisor, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(supervisor.subprocess, "CREATE_NEW_PROCESS_GROUP", 0, raising=False)
    monkeypatch.setattr(supervisor.subprocess, "Popen", spawn)
    monkeypatch.setattr(signal, "signal", handler)
    monkeypatch.setattr(supervisor, "_send", lambda _, message: events.append(message))
    monkeypatch.setattr(supervisor, "_support", lambda _: SimpleNamespace(
        prepare_controller=lambda executable, env: (executable, env), EvidenceJob=lambda _: job,
    ))
    with pytest.raises(KeyboardInterrupt if fault == "cancelled" else subprocess.TimeoutExpired):
        supervisor.run_pytest([sys.executable, "-I", "-m", "pytest"],
                              cwd=tmp_path, environment={}, timeout=3)
    assert events == ["terminate", "wait", "close-job", "close-pipe"]


@pytest.mark.skipif(os.name != "nt", reason="actual CPython Windows venv and Job admission")
def test_windows_native_controller_preserves_venv_and_defers_site_until_job(tmp_path, monkeypatch):
    venv = tmp_path / "separate-venv"
    # No redirector or subprocess is needed for a no-pip fixture layout.
    with monkeypatch.context() as setup:
        def unexpected_spawn(*args, **kwargs):
            raise AssertionError("venv fixture setup must not spawn an unowned process")

        setup.setattr(subprocess, "Popen", unexpected_spawn)
        venv_module.EnvBuilder(with_pip=False).create(venv)
    marker = tmp_path / "site-executed"
    packages = Path(sysconfig.get_path("purelib"))
    site = venv / "Lib/site-packages"
    # Share only pytest's dependency directory for this fixture, not a Product
    # acceptance claim. Full wheel tests still verify their own installed bytes.
    (site / "evidence.pth").write_text(
        f"{packages.as_posix()}\nimport pathlib; pathlib.Path({str(marker)!r}).touch()\n",
        encoding="utf-8",
    )
    argv, environment = _fixture(tmp_path, "normal")
    executable = venv / "Scripts/python.exe"
    argv[0] = str(executable)
    (tmp_path / "test_fault.py").write_text(
        "import os, sys, pytest\nfrom pathlib import Path\n"
        "def test_isolated_venv():\n"
        f"    assert Path(sys.executable) == Path({str(executable)!r})\n"
        f"    assert Path(sys.prefix) == Path({str(venv)!r})\n"
        f"    assert Path({str(marker)!r}).exists()\n"
        f"    assert Path(pytest.__file__).is_relative_to(Path({str(packages)!r}))\n"
        "    assert not any(k.lower() == '__pyvenv_launcher__' for k in os.environ)\n"
    )
    environment.update({"PYTHONEXECUTABLE": "untrusted", "__PYVENV_LAUNCHER__": "untrusted"})
    native = supervisor._support("_evidence_windows")
    admitted, closed = [], []
    admission = supervisor._await_admission

    def admit(process, job, *args):
        admission(process, job, *args)
        assert not marker.exists(), "site ran before the Job/start gate"
        assert job.active() == 1
        admitted.append(process.pid)

    class Job(native.EvidenceJob):
        def close(self):
            assert self.active() == 0
            super().close()
            closed.append(True)

    monkeypatch.setattr(supervisor, "_await_admission", admit)
    monkeypatch.setattr(supervisor, "_support", lambda _: SimpleNamespace(
        EvidenceJob=Job, prepare_controller=native.prepare_controller,
    ))
    supervisor.run_pytest(argv, cwd=tmp_path, environment=environment, timeout=20)
    assert len(admitted) == 1 and closed == [True] and marker.exists()

@pytest.mark.skipif(os.name != "posix", reason="POSIX adopted branch accounting")
@pytest.mark.parametrize("boundary", ["reap", "resume"])
def test_evidence_branch_reparenting_cannot_disappear_between_cleanup_retries(monkeypatch, boundary):
    native = supervisor._support("_evidence_posix")
    # root -> middle -> A/B; after B is reaped, middle exits and A moves
    # outside the retained root. No signal is ever sent to a real PID here.
    table = {9001: (9000, "S"), 9002: (9001, "S"),
             9003: (9002, "S"), 9004: (9002, "S")}
    signals = []
    snapshots = []

    def signal_process(pid, number):
        signals.append((pid, number))
        if number == signal.SIGSTOP:
            parent, _ = table[pid]
            table[pid] = (parent, "T")
        elif number == signal.SIGKILL:
            table[pid] = (table[pid][0], "Z")
        elif number == signal.SIGCONT:
            if pid == 9002 and table.get(9004, (None, None))[1] == "Z":
                del table[9004]
                table[9002] = (9001, "S")
                if boundary == "reap":
                    table[9002] = (9001, "Z")
                    table[9003] = (8000, "T")
            elif pid in table:
                table[pid] = (table[pid][0], "S")

    monkeypatch.setattr(native, "_table", lambda _: dict(table))
    reconcile = native._reconcile

    def after_snapshot(*args):
        reconcile(*args)
        if boundary == "resume" and 9004 not in table:
            snapshots.append(None)
            if len(snapshots) == 2:  # Exit after finally's last ps snapshot.
                table[9002] = (9001, "Z")
                table[9003] = (8000, "T")

    monkeypatch.setattr(native, "_reconcile", after_snapshot)
    monkeypatch.setattr(native.os, "kill", signal_process)
    monkeypatch.setattr(supervisor, "_support", lambda _: native)

    def send(_, message):
        if message.startswith("reap "):
            table.pop(int(message.split()[1]))
        return True

    monkeypatch.setattr(supervisor, "_send", send)
    process = SimpleNamespace(pid=9001, returncode=0, wait=lambda **_: 0,
                              stdin=SimpleNamespace(close=lambda: None))
    state = {}
    for _ in range(2):
        with pytest.raises(RuntimeError, match="adopted.*parent"):
            supervisor._cleanup(process, None, forced=False, state=state)
        assert "leftovers" not in state  # No empty-tree proof, even on retry.
    assert (9001, signal.SIGKILL) not in signals
    assert (9003, signal.SIGKILL) not in signals
    assert (9003, signal.SIGCONT) not in signals


@pytest.mark.skipif(sys.platform != "linux", reason="independent Linux fixture subreaper")
@pytest.mark.parametrize("timeout", [False, True])
def test_evidence_native_branch_parent_exit_retains_debt_until_actual_reaping(tmp_path, timeout):
    argv, environment = _fixture(tmp_path, "normal")
    fixture = str(Path(__file__).with_name("_evidence_branch_fixture.py"))
    (tmp_path / "test_fault.py").write_text(
        "import runpy\ndef test_branch():\n"
        f"    runpy.run_path({fixture!r}, run_name='__main__')\n"
    )
    if timeout:
        (tmp_path / "hold-branch").touch()
        with pytest.raises(subprocess.TimeoutExpired):
            supervisor.run_pytest(argv, cwd=tmp_path, environment=environment, timeout=3)
        assert (tmp_path / "branch.ready").exists()
        assert not (tmp_path / "branch.done").exists()
    else:
        supervisor.run_pytest(argv, cwd=tmp_path, environment=environment, timeout=20)
        assert (tmp_path / "branch.done").read_text() == "native reaper cleared it"
    assert (tmp_path / "branch.settled").read_text() == "fixture reaped"
    for name in ("branch.root", "middle", "A", "B"):
        with pytest.raises(ProcessLookupError):
            os.kill(int((tmp_path / name).read_text()), 0)


_MIDDLE = """
import os, subprocess, sys, threading, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(60)'],
    start_new_session=os.name == 'posix')
Path('grandchild.pid').write_text(str(child.pid))
stop = threading.Event()
threading.Thread(target=lambda: (sys.stdin.readline(), stop.set()), daemon=True).start()
while child.poll() is None and not stop.wait(0.02):
    pass
if child.poll() is None:
    child.terminate()
child.wait()
"""


def _fixture(root, mode):
    test = root / "test_fault.py"
    test.write_text(
        "import os, subprocess, sys, time\nfrom pathlib import Path\n"
        "def test_owned_tree():\n"
        f"    child = subprocess.Popen([sys.executable, '-I', '-c', {_MIDDLE!r}], "
        "stdin=subprocess.PIPE, start_new_session=os.name == 'posix')\n"
        "    Path('child.pid').write_text(str(child.pid))\n"
        "    while not Path('grandchild.pid').exists(): time.sleep(0.01)\n"
        f"    mode = {mode!r}\n"
        "    if mode == 'leak': return\n"
        "    try:\n"
        "        Path('interrupt.ready').write_text('finally armed')\n"
        "        while mode != 'normal':\n"
        "            try: time.sleep(0.02)\n"
        "            except KeyboardInterrupt:\n"
        "                if mode != 'stubborn': raise\n"
        "    finally:\n"
        "        child.stdin.write(b'stop\\n'); child.stdin.flush()\n"
        "        child.wait(timeout=5)\n"
        "        Path('finally.done').write_text('done')\n"
    )
    config = root / "pytest.ini"
    config.write_text("[pytest]\n")
    environment = {key: value for key, value in os.environ.items() if key.lower() not in {
        "pythonpath", "pythonhome", "pytest_addopts"
    }}
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return [sys.executable, "-I", "-m", "pytest", "-c", str(config), str(test), "-q"], environment


def _assert_gone(root):
    for name in ("child.pid", "grandchild.pid"):
        pid = int((root / name).read_text())
        if os.name == "posix":
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
        else:
            # The supervisor already requires native Job active-count zero;
            # do not use os.kill(pid, 0), which terminates processes on Windows.
            assert pid > 0


@pytest.mark.parametrize("mode", ["normal", "cooperative", "stubborn", "leak"])
def test_evidence_supervisor_retains_multigeneration_owner_until_reaped(tmp_path, mode):
    argv, environment = _fixture(tmp_path, mode)
    expected = None if mode == "normal" else (
        subprocess.CalledProcessError if mode == "leak" else subprocess.TimeoutExpired
    )
    if expected is None:
        supervisor.run_pytest(argv, cwd=tmp_path, environment=environment, timeout=3)
    else:
        with pytest.raises(expected):
            supervisor.run_pytest(
                argv, cwd=tmp_path, environment=environment, timeout=3,
                cleanup_timeout=0.5 if mode == "stubborn" else 10,
            )
    _assert_gone(tmp_path)
    if mode in {"normal", "cooperative"}:
        assert (tmp_path / "finally.done").read_text() == "done"


@pytest.mark.skipif(os.name != "posix", reason="native parent SIGINT regression")
def test_evidence_supervisor_repeated_interrupt_keeps_finally_owner(tmp_path):
    argv, environment = _fixture(tmp_path, "cooperative")

    def interrupt():
        deadline = time.monotonic() + 5
        while not (tmp_path / "interrupt.ready").exists():
            assert time.monotonic() < deadline
            time.sleep(0.01)
        os.kill(os.getpid(), signal.SIGINT)
        time.sleep(0.01)
        os.kill(os.getpid(), signal.SIGINT)

    thread = threading.Thread(target=interrupt)
    thread.start()
    try:
        with pytest.raises(KeyboardInterrupt):
            supervisor.run_pytest(argv, cwd=tmp_path, environment=environment, timeout=10)
    finally:
        thread.join(timeout=5)
    assert not thread.is_alive()
    _assert_gone(tmp_path)
    assert (tmp_path / "finally.done").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX retained identity phases")
@pytest.mark.parametrize("fault", ["pipe-close", "late-exit"])
def test_evidence_cleanup_never_readopts_after_root_wait_or_release(monkeypatch, fault):
    events = []

    class Pipe:
        def write(self, value):
            events.append("release")

        def flush(self):
            pass

        def close(self):
            if fault == "pipe-close":
                raise OSError("closed-pipe-fault")

    class Process:
        pid, returncode, stdin = 12345, None, Pipe()

        def wait(self, timeout):
            events.append("wait")
            if fault == "late-exit" and events.count("wait") == 1:
                raise subprocess.TimeoutExpired("owned-root", timeout)
            self.returncode = 0
            return 0

        def kill(self):
            events.append("owned-Popen-kill")

    def adopt(*_, **kwargs):
        events.append("adopt")
        return 0

    monkeypatch.setattr(supervisor, "_support", lambda _: SimpleNamespace(reclaim_descendants=adopt))
    monkeypatch.setattr(os, "kill", lambda *args: events.append("resume-frozen-root"))
    process, state = Process(), {}
    if fault == "late-exit":
        with pytest.raises(subprocess.TimeoutExpired):
            supervisor._cleanup(process, None, forced=False, state=state)
        process.returncode = 0  # Root exited after the first bounded join.
        supervisor._cleanup(process, None, forced=True, state=state)
    else:
        assert not supervisor._cleanup(process, None, forced=False, state=state)
    assert events.count("adopt") == 1


@pytest.mark.skipif(os.name != "posix", reason="POSIX native retry signal")
def test_evidence_cleanup_debt_retains_owner_even_when_diagnostic_write_fails(tmp_path, monkeypatch):
    argv, environment = _fixture(tmp_path, "normal")
    original = supervisor._cleanup
    failures = []

    def cleanup(process, *args, **kwargs):
        if not failures:
            failures.append(process.pid)
            assert (tmp_path / "pytest-controller-result").exists()
            raise RuntimeError("injected-cleanup-debt")
        return original(process, *args, **kwargs)

    class BrokenDiagnostic:
        def write(self, text):
            if "cleanup pending" in text:
                assert tmp_path.is_dir()
                os.kill(failures[0], 0)  # The exact retained root is still alive.
                os.kill(os.getpid(), signal.SIGINT)  # Explicit retry intent.
                raise OSError("diagnostic pipe broke")

        def flush(self):
            pass

    monkeypatch.setattr(supervisor, "_cleanup", cleanup)
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stderr", BrokenDiagnostic())
        with pytest.raises(RuntimeError, match="injected-cleanup-debt"):
            supervisor.run_pytest(argv, cwd=tmp_path, environment=environment, timeout=3)
    _assert_gone(tmp_path)
    with pytest.raises(ProcessLookupError):
        os.kill(failures[0], 0)


@pytest.mark.skipif(os.name != "posix", reason="POSIX frozen-root handoff")
def test_evidence_empty_tree_keeps_live_spawning_thread_frozen_until_kill(tmp_path, monkeypatch):
    argv, environment = _fixture(tmp_path, "normal")
    test = tmp_path / "test_fault.py"
    test.write_text(
        "import subprocess, sys, threading, time\nfrom pathlib import Path\n"
        "def test_background_spawn():\n"
        "    def spawn():\n"
        "        while not Path('allow-spawn').exists(): time.sleep(0.001)\n"
        "        child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(.1)'], start_new_session=True)\n"
        "        Path('unexpected-child').write_text(str(child.pid))\n"
        "        child.wait()\n"
        "    threading.Thread(target=spawn, daemon=True).start()\n"
    )
    load = supervisor._support
    handoffs = []

    def support(name):
        module = load(name)
        reclaim = module.reclaim_descendants

        def held(root, reap, **kwargs):
            result = reclaim(root, reap, **kwargs)
            (tmp_path / "allow-spawn").write_text("the live thread would spawn now")
            time.sleep(0.05)
            assert "T" in module._table(time.monotonic() + 1)[root][1]
            assert not (tmp_path / "unexpected-child").exists()
            handoffs.append(root)
            return result

        module.reclaim_descendants = held
        return module

    monkeypatch.setattr(supervisor, "_support", support)
    with pytest.raises(subprocess.CalledProcessError):
        supervisor.run_pytest(argv, cwd=tmp_path, environment=environment, timeout=3)
    assert len(handoffs) == 1
    assert not (tmp_path / "unexpected-child").exists()
    with pytest.raises(ProcessLookupError):
        os.kill(handoffs[0], 0)


def test_evidence_job_admission_failure_keeps_root_wait_in_retry_guard(tmp_path, monkeypatch):
    events, handlers = [], []

    class Pipe:
        def close(self):
            events.append("pipe-close")

    class Process:
        stdin, returncode = Pipe(), None

        def kill(self):
            events.append("kill-unadmitted-root")

        def wait(self, timeout):
            events.append("wait")
            if events.count("wait") == 1:
                raise subprocess.TimeoutExpired("unadmitted-root", timeout)
            self.returncode = 1

    def job(process):
        raise RuntimeError("AssignJob-fault")

    def signal_handler(number, handler):
        handlers.append(handler)
        return lambda *_: None

    class Diagnostic:
        def write(self, text):
            if "cleanup pending" in text:
                assert events.count("wait") == 1
                handlers[0]()

        def flush(self):
            pass

    monkeypatch.setattr(supervisor, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(supervisor.subprocess, "CREATE_NEW_PROCESS_GROUP", 0, raising=False)
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(supervisor, "_support", lambda _: SimpleNamespace(
        EvidenceJob=job, prepare_controller=lambda executable, env: (executable, env),
    ))
    monkeypatch.setattr(signal, "signal", signal_handler)
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stderr", Diagnostic())
        with pytest.raises(RuntimeError, match="AssignJob-fault"):
            supervisor.run_pytest(
                [sys.executable, "-I", "-m", "pytest"], cwd=tmp_path, environment={}, timeout=1
            )
    assert events == ["kill-unadmitted-root", "wait", "kill-unadmitted-root", "wait", "pipe-close"]


@pytest.mark.parametrize("fault", ["write", "replace", "malformed", "unreadable"])
def test_evidence_receipt_fault_retains_root_until_physical_cleanup(tmp_path, monkeypatch, fault):
    argv, environment = _fixture(tmp_path, "normal")
    script = (
        "import os\nfrom pathlib import Path\n"
        "def test_break_result_publication():\n"
        "    Path('controller.pid').write_text(str(os.getpid()))\n"
    )
    if fault in {"write", "malformed"}:
        script += (
            "    original = Path.write_text\n"
            "    def write(self, data, *args, **kwargs):\n"
            "        if self.name == 'pytest-controller-result.pending':\n"
            + ("            raise OSError('receipt-write-fault')\n" if fault == "write" else
               "            data = '{}'\n")
            + "        return original(self, data, *args, **kwargs)\n"
            "    Path.write_text = write\n"
        )
    elif fault == "replace":
        script += (
            "    original = Path.replace\n"
            "    def replace(self, target):\n"
            "        if self.name == 'pytest-controller-result.pending':\n"
            "            raise OSError('receipt-replace-fault')\n"
            "        return original(self, target)\n"
            "    Path.replace = replace\n"
        )
    (tmp_path / "test_fault.py").write_text(script)
    if fault == "unreadable":
        read = Path.read_text

        def unreadable(self, *args, **kwargs):
            if self.name == "pytest-controller-result":
                raise PermissionError("receipt-read-fault")
            return read(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", unreadable)
    expected = {"write": subprocess.TimeoutExpired, "replace": subprocess.TimeoutExpired,
                "malformed": ValueError, "unreadable": PermissionError}[fault]
    cleanup = supervisor._cleanup
    live_roots = []

    def retained(process, *args, **kwargs):
        assert process.returncode is None
        if os.name == "posix":
            os.kill(process.pid, 0)
        live_roots.append(process.pid)
        return cleanup(process, *args, **kwargs)

    monkeypatch.setattr(supervisor, "_cleanup", retained)
    with pytest.raises(expected):
        supervisor.run_pytest(
            argv, cwd=tmp_path, environment=environment, timeout=2, cleanup_timeout=0.1
        )
    assert len(live_roots) == 1
    if os.name == "posix":
        with pytest.raises(ProcessLookupError):
            os.kill(live_roots[0], 0)
