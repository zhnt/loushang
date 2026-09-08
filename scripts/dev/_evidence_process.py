"""Retain pytest's process-tree owner until physical cleanup is proven.

The child cannot normally exit before a parent release handshake. POSIX uses
that retained, normal-reaping Python parent to freeze and reclaim descendants;
Windows admits it to an independent non-breakaway Job before tests may start.
"""

from __future__ import annotations

import _thread
import importlib.util
import json
import os
import runpy
import signal
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import suppress
from pathlib import Path


def _support(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("evidence process support missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _send(process, message):
    with suppress(OSError, ValueError):
        process.stdin.write((message + "\n").encode())
        process.stdin.flush()
        return True
    return False


def _await_result(process, result, deadline, interrupted=None):
    while time.monotonic() < deadline:
        if interrupted is not None and interrupted.is_set():
            raise KeyboardInterrupt
        if result.is_file():
            value = json.loads(result.read_text())
            if (
                type(value) is not dict or set(value) != {"code", "force_cleanup"}
                or type(value["code"]) is not int or not 0 <= value["code"] <= 255
                or type(value["force_cleanup"]) is not bool
            ):
                raise ValueError("invalid evidence controller receipt")
            return value
        # Keep the root PID reserved even if it violates the release handshake.
        time.sleep(0.02)
    raise subprocess.TimeoutExpired(process.args, 0)


def _cleanup(process, job, *, forced, state):
    if state.get("observation") is not None:
        # Do this before any tree scan, signal, release or root reap: a CLI may
        # have orphaned an unobserved child before a later scan sees an empty tree.
        _support("_evidence_observation").require_closed(
            state["observation"], not_started=bool(state.get("not_admitted")),
        )
    if state.get("not_admitted") and job is None:
        leftovers = False
        process.kill()  # -I -S gate has not been allowed to execute site/tests.
    elif job is not None:
        active = job.active()
        state.setdefault("active_before_cleanup", active)
        leftovers = state.setdefault("leftovers", active > 1)
        if forced or leftovers:
            job.terminate()
        else:
            _send(process, "release")
        deadline = time.monotonic() + 10
        while job.active():
            if time.monotonic() >= deadline:
                raise TimeoutError("evidence Job cleanup pending")
            time.sleep(0.02)
    else:
        # No poll/reap between adoption and completion. The child stays alive
        # after pytest returns, so even a successful test cannot hide an orphan.
        if "leftovers" not in state:
            state["leftovers"] = _support("_evidence_posix").reclaim_descendants(
                process.pid, lambda pid: _send(process, f"reap {pid}"),
                ledger=state.setdefault("tree", {}),
            ) > 0
        leftovers = state["leftovers"]
        if forced:
            process.kill()  # All its adopted descendants are now reaped.
        elif not state.get("released"):
            if not _send(process, "release"):
                process.kill()
                leftovers = True
            else:
                os.kill(process.pid, signal.SIGCONT)
                state["released"] = True
    process.wait(timeout=10)
    if job is not None:
        job.close()
    with suppress(OSError, ValueError):
        process.stdin.close()
    return leftovers or process.returncode != 0


def _await_admission(process, job, result, deadline, interrupted):
    admission = result.with_suffix(".admission")
    while time.monotonic() < deadline:
        if interrupted.is_set():
            raise KeyboardInterrupt
        if admission.is_file():
            value = json.loads(admission.read_text())
            if (type(value) is not dict or set(value) != {"pid", "no_site"}
                    or type(value["pid"]) is not int or value["pid"] != process.pid
                    or type(value["no_site"]) is not int or value["no_site"] != 1
                    or job.active() != 1):
                raise ValueError("controller native admission identity mismatch")
            if interrupted.is_set():
                raise KeyboardInterrupt
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(process.args, 0)
            return
        time.sleep(0.02)
    raise subprocess.TimeoutExpired(process.args, 0)


def run_pytest(argv, *, cwd, environment, timeout, cleanup_timeout=60, observation=False):
    """argv is the exact isolated Python -I -m pytest command from the runner."""
    if argv[1:4] != ["-I", "-m", "pytest"]:
        raise ValueError("evidence supervisor requires isolated pytest")
    return _run_controller(argv, argv[4:], "--child", cwd=cwd, environment=environment,
                           timeout=timeout, cleanup_timeout=cleanup_timeout,
                           observation=observation)


def run_python(argv, *, cwd, environment, timeout, cleanup_timeout=60):
    """Run a trusted isolated probe under the same retained process owner."""
    if (len(argv) < 3 or argv[1] != "-I" or
            not (argv[2] == "-c" and len(argv) >= 4 or Path(argv[2]).is_absolute())):
        raise ValueError("evidence probe requires isolated code or an absolute script")
    # Multiple probes may share a cwd with the full pytest controller. Their
    # receipts must not collide; this directory is removed only after the
    # retained owner has returned with physical cleanup established.
    with tempfile.TemporaryDirectory(prefix="g17-probe-", dir=cwd) as private:
        return _run_controller(argv, argv[2:], "--python-child", cwd=cwd, environment=environment,
                               timeout=timeout, cleanup_timeout=cleanup_timeout,
                               control_root=Path(private))


def _run_controller(argv, arguments, mode, *, cwd, environment, timeout, cleanup_timeout,
                    control_root=None, observation=False):
    result = (control_root or cwd) / "pytest-controller-result"
    if result.exists() or result.with_suffix(".admission").exists():
        raise ValueError("evidence result path already exists")
    native = _support("_evidence_windows") if os.name == "nt" else None
    executable = argv[0]
    if native is not None:
        executable, environment = native.prepare_controller(executable, environment)
    state = {}
    if os.name == "posix":
        ledger = _support("_evidence_observation")
        # Ownership context belongs to this supervisor, not its configurable
        # child environment. A reduced child env cannot detach nested debt.
        parent = os.environ.get(ledger.ENVIRONMENT_KEY)
        state["observation"] = ledger.create(
            control_root or cwd, parent=parent, observation=observation,
        )
        environment = {key: value for key, value in environment.items()
                       if key.upper() != ledger.ENVIRONMENT_KEY}
        environment[ledger.ENVIRONMENT_KEY] = str(state["observation"]["path"])
    elif observation:
        raise ValueError("native observation receipts require POSIX supervision")
    interrupted = threading.Event()
    previous = signal.signal(signal.SIGINT, lambda *_: interrupted.set())
    process = job = None
    failure = None
    status = 1
    receipt = None
    try:
        deadline = time.monotonic() + timeout
        try:
            process = subprocess.Popen(
                [executable, "-I", "-S", str(Path(__file__).resolve()), mode, str(result), *arguments],
                cwd=cwd, env=environment, stdin=subprocess.PIPE,
                start_new_session=os.name == "posix",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
        except OSError:
            # Popen's synchronous OS-error path has no surviving returned child;
            # do not strand an observation that was never allowed to execute.
            # An ambiguous interruption is deliberately not treated as no-spawn.
            if state.get("observation") is not None:
                ledger.require_closed(state["observation"], not_started=True)
            raise
        try:
            if native is not None:
                job = native.EvidenceJob(process)
                _await_admission(process, job, result, min(deadline, time.monotonic() + 10), interrupted)
            if interrupted.is_set():
                raise KeyboardInterrupt
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(process.args, 0)
        except BaseException as error:
            failure = error
            state["not_admitted"] = True
        else:
            _send(process, "start")
            try:
                receipt = _await_result(process, result, deadline, interrupted)
            except BaseException as error:
                failure = error
                _send(process, "interrupt")
                with suppress(Exception):
                    receipt = _await_result(process, result, time.monotonic() + cleanup_timeout)
        forced = state.get("not_admitted") or receipt is None or receipt["force_cleanup"]
        if receipt is not None:
            status = receipt["code"]
        while True:
            try:
                leftovers = _cleanup(process, job, forced=forced, state=state)
                break
            except Exception as error:
                # Do not return into TemporaryDirectory deletion or abandon
                # the controller on incomplete physical proof. Ctrl+C retries.
                interrupted.clear()
                with suppress(OSError, ValueError):
                    print(f"evidence cleanup pending ({type(error).__name__}); owner and {cwd} retained; Ctrl+C retries", file=sys.stderr, flush=True)
                failure = failure or error
                forced = True
                while not interrupted.wait(0.1):
                    pass
        if failure is not None:
            raise failure
        if status or leftovers:
            with suppress(OSError, ValueError):
                print(
                    f"evidence failed: status={status}, leftovers={leftovers}, "
                    f"force_cleanup={forced}, job_active={state.get('active_before_cleanup')}",
                    file=sys.stderr, flush=True,
                )
            raise subprocess.CalledProcessError(status or 1, argv)
    finally:
        signal.signal(signal.SIGINT, previous)


def _isolate_stdin():
    """Detach both native stdin and Python's view from the private control pipe."""
    with open(os.devnull, "rb") as empty:
        os.dup2(empty.fileno(), 0)
    if os.name == "nt":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        # Windows subprocess uses GetStdHandle, not sys.stdin or CRT fd lookup.
        set_handle = ctypes.WinDLL("kernel32", use_last_error=True).SetStdHandle
        set_handle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
        set_handle.restype = wintypes.BOOL
        if not set_handle(wintypes.DWORD(-10), wintypes.HANDLE(msvcrt.get_osfhandle(0))):
            raise ctypes.WinError(ctypes.get_last_error())
    sys.stdin = open(os.devnull)


def _child(result, arguments, *, python=False):
    if os.name == "nt":
        admission = result.with_suffix(".admission.pending")
        admission.write_text(json.dumps({"pid": os.getpid(), "no_site": sys.flags.no_site}))
        admission.replace(result.with_suffix(".admission"))
    # pytest fd capture must never replace the supervisor's control descriptor.
    control = os.fdopen(os.dup(sys.stdin.fileno()))
    os.set_inheritable(control.fileno(), False)
    if control.readline().strip() != "start":
        result.write_text(json.dumps({"code": 1, "force_cleanup": True}))
        while True:
            time.sleep(0.1)  # No start admission; retain root until native reap.
    active, release = threading.Event(), threading.Event()
    active.set()

    def interrupt(*_):
        if active.is_set():
            raise KeyboardInterrupt

    signal.signal(signal.SIGINT, interrupt)

    def commands():
        for line in control:
            if line.strip() == "interrupt" and active.is_set():
                _thread.interrupt_main()
            elif line.strip() == "release":
                release.set()
                return
            elif line.startswith("reap ") and os.name == "posix":
                with suppress(ChildProcessError):
                    os.waitpid(int(line.split()[1]), 0)
        # A lost control channel requests cleanup, but never grants release.
        if active.is_set():
            _thread.interrupt_main()

    reader = threading.Thread(target=commands, daemon=True)
    code = 1
    try:
        reader.start()
        # Pytest and tests must not consume the supervisor's control channel.
        _isolate_stdin()
        import site

        site.main()  # -S keeps .pth/sitecustomize behind the start/Job gate.
        if python:
            sys.argv = ["-c", *arguments[2:]] if arguments[0] == "-c" else list(arguments)
            try:
                if arguments[0] == "-c":
                    exec(compile(arguments[1], "<evidence-probe>", "exec"), {"__name__": "__main__"})
                else:
                    runpy.run_path(arguments[0], run_name="__main__")
                code = 0
            except SystemExit as error:
                code = 0 if error.code is None else error.code if type(error.code) is int and 0 <= error.code <= 255 else 1
        else:
            import pytest

            code = int(pytest.main(arguments))
    except KeyboardInterrupt:
        code = 130
    except BaseException:
        import traceback

        traceback.print_exc()
    finally:
        active.clear()
        # After publishing the result, only the known control reader and main
        # thread may execute. Unknown live Python threads force native cleanup.
        try:
            with suppress(OSError, ValueError):
                sys.stdout.flush()
                sys.stderr.flush()
            unsafe = any(thread not in {threading.current_thread(), reader}
                         for thread in threading.enumerate())
            if unsafe:
                code = code or 1
            staged = result.with_suffix(".pending")
            staged.write_text(json.dumps({"code": code, "force_cleanup": unsafe}))
            staged.replace(result)
        except BaseException:
            code = code or 1
            with suppress(OSError, ValueError):
                print("evidence result publication failed; owner retained", file=sys.stderr, flush=True)
        finally:
            while not release.wait(0.1):
                pass
            reader.join(timeout=1)
    # Pytest finalizers have run. Do not run arbitrary interpreter atexit hooks
    # after the parent has established the no-more-descendants proof.
    os._exit(code)


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in {"--child", "--python-child"}:
        raise SystemExit("private evidence controller requires an explicit child mode")
    raise SystemExit(_child(Path(sys.argv[2]), sys.argv[3:], python=sys.argv[1] == "--python-child"))
