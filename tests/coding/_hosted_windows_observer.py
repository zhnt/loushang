"""Real ConPTY observation; must run inside the independent evidence Job."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path

from loushang.tui.cell_width import strip_control_sequences

from ._hosted_terminal import foreground_terminal
from ._hosted_windows_api import SuspendedThreads, WindowsObservationApi
from .test_hosted_client import _argv
from .test_hosted_client_terminal import _installed
from .test_mux_terminal_process import _terminal_environment


def _receipt(driver, root, name, timeout):
    driver.read_until(lambda _: (root / name).is_file() or (root / "failed").is_file(), timeout=timeout)
    assert not (root / "failed").exists(), "native console witness failed"
    return json.loads((root / name).read_text(encoding="utf-8"))


def _pin_chain(api, root, witness, handles):
    table = api.entries()
    assert table.get(root) == witness, "controller identity changed"
    chain = []
    parent = root
    while True:
        descriptor = api.open_process(parent)
        handles.callback(api.close, descriptor)
        assert not api.ended(descriptor), "observed process already exited"
        chain.append((parent, descriptor))
        children = [pid for pid, owner in table.items() if owner == parent]
        if not children:
            break
        # No tool turns occur in these cases. Account for console-script
        # launcher shims, but reject unknown/branching topologies before faults.
        assert len(children) == 1 and len(chain) < 8, (
            "unexpected native entry process tree", _tree_fact(api, parent, children, chain),
        )
        parent = children[0]
    assert len(chain) >= 2, "ready/cancel observation must include a real Hosted child"
    current = api.entries()
    parent = witness
    for pid, descriptor in chain:
        assert current.get(pid) == parent and not api.ended(descriptor), "process identity changed"
        parent = pid
    return chain


def _tree_fact(api, parent, children, chain):
    # Bounded diagnostic only: image basenames, never command lines or env.
    names = getattr(api, "process_names", {})
    return {
        "parent": (parent, names.get(parent)),
        "chain": [(pid, names.get(pid)) for pid, _ in chain[:8]],
        "children": [(pid, names.get(pid)) for pid in children[:16]],
        "child_count": len(children),
    }


def _controller_chain(chain, started, console):
    pids = [pid for pid, _ in chain]
    witness = pids.index(started["witness"])
    controller = pids.index(started["pid"])
    assert controller == witness + 1, "console launcher is not the witness child"
    assert started["witness"] in console and started["pid"] in console
    result = chain[controller:]
    detached = [index for index, (pid, _) in enumerate(result) if pid not in console]
    assert detached and detached[0] > 0, "Hosted CREATE_NO_WINDOW child not observed"
    assert detached == list(range(detached[0], len(result))), "ambiguous Hosted role boundary"
    return result


def observe(root, *, force_exit=False, cancel_start=False, cancel_recovery=False):
    api = WindowsObservationApi()
    receipts = root / "witness"
    receipts.mkdir()
    cancelled = cancel_start or cancel_recovery
    script = "_hosted_recovery_cancel.py" if cancel_recovery else "_hosted_start_cancel.py"
    executable = ([sys.executable, "-I", str(Path(__file__).with_name(script))]
                  if cancelled else [_installed()])
    witness = Path(__file__).with_name("_hosted_windows_witness.py")
    with foreground_terminal(
        [sys.executable, "-I", str(witness), str(receipts), *executable, *_argv(root)],
        cwd=root, env=_terminal_environment(root), columns=100, rows=30,
    ) as driver:
        try:
            started = _receipt(driver, receipts, "started", 15)
            driver.read_until(
                lambda out: (root / "recovery-held").is_file() if cancel_recovery else
                ("G17 publication held" if cancel_start else "/exit ends app")
                in strip_control_sequences(out), timeout=35,
            )
            (receipts / "sample.request").touch()
            sample = _receipt(driver, receipts, "sample", 5)
            active = sample["modes"]
            if cancelled:
                assert active == started["baseline"]
            else:
                assert active != started["baseline"]
                assert not active[0] & 0x0001, "processed input still enabled"
                assert active[0] & 0x0080, "extended input flags not configured"
                assert active[1] & 0x0005 == 0x0005, "VT/processed output not configured"
            with ExitStack() as handles:
                handles.callback(api.retry_closes)
                chain = _pin_chain(api, driver.diagnostics.pid, os.getpid(), handles)
                chain = _controller_chain(chain, started, set(sample["console"]))
                pid, process = chain[-1]
                suspended = SuspendedThreads(api, pid, process)
                handles.callback(suspended.close)
                if force_exit:
                    suspended.stop()
                driver.write("\x03" if cancelled else "/exit\r")
                finished = _receipt(driver, receipts, "finished", 25)
                assert finished["code"] == (130 if cancelled else 1 if force_exit else 0)
                assert finished["modes"] == started["baseline"]
                assert all(api.ended(handle) for _, handle in chain), "Hosted process remains"
                if cancelled:
                    assert "G17 terminal invoked" not in driver.raw_output
                    assert "/exit ends app" not in strip_control_sequences(driver.raw_output)
                    assert "hosted_interrupted" in driver.raw_output
                if cancel_start:
                    assert "G17 publication cancelled" in driver.raw_output
                    assert "G17 late lease returned" in driver.raw_output
        finally:
            (receipts / "release").touch()
        assert driver.wait(timeout=10) == 0, driver.diagnostics
        assert driver.diagnostics.termination is None
    assert not driver.diagnostics.reader_alive


def scenario(root, case):
    if case == "heartbeat":
        _heartbeat(root)
    elif case == "recovery-cancel":
        from .test_hosted_entry_evidence import _observe_recovery_cancel

        _observe_recovery_cancel(root, observer=observe)
    else:
        assert case in {"real", "start-cancel", "forced-exit"}
        observe(root, cancel_start=case == "start-cancel", force_exit=case == "forced-exit")


def _heartbeat(root):
    """Native negative control: stopped execution, then resumed progress.

    Runs only beneath the retained evidence Job. Failed assertions leave the
    fixture owned by that Job, whose cleanup cannot turn a failure into a pass.
    """
    api = WindowsObservationApi()
    child = subprocess.Popen(
        [sys.executable, "-I", "-c",
         "import os, time\nfrom pathlib import Path\n"
         "root = Path('.')\n"
         "with (root / 'heartbeat').open('ab', buffering=0) as output:\n"
         "    (root / 'pid').write_text(str(os.getpid()))\n"
         "    while not (root / 'stop').exists():\n"
         "        output.write(b'.')\n        time.sleep(0.01)\n"],
        cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
    )

    def until(predicate):
        deadline = time.monotonic() + 10
        while not predicate():
            assert child.poll() is None, "heartbeat fixture exited early"
            if time.monotonic() >= deadline:
                raise TimeoutError("heartbeat fixture made no progress")
            time.sleep(0.01)

    heartbeat = root / "heartbeat"
    until(lambda: heartbeat.exists() and heartbeat.stat().st_size >= 3)
    actual = int((root / "pid").read_text())
    with ExitStack() as handles:
        handles.callback(api.retry_closes)
        # A base interpreter has no venv shim, so this fixture admits one node.
        table = api.entries()
        expected_parent = os.getpid()
        pid = child.pid
        process = None
        for _ in range(8):
            assert table.get(pid) == expected_parent
            process = api.open_process(pid)
            handles.callback(api.close, process)
            assert not api.ended(process)
            if pid == actual:
                break
            children = [key for key, parent in table.items() if parent == pid]
            assert len(children) == 1, _tree_fact(api, pid, children, [])
            expected_parent, pid = pid, children[0]
        assert pid == actual and process is not None
        assert api.entries().get(actual) == expected_parent and not api.ended(process)
        fault = SuspendedThreads(api, actual, process)
        handles.callback(fault.close)
        fault.stop()
        stopped_size = heartbeat.stat().st_size
        time.sleep(0.2)
        assert heartbeat.stat().st_size == stopped_size, "suspended target still executes"
        assert not api.ended(process), "termination must not stand in for suspension"
        fault.close()
        until(lambda: heartbeat.stat().st_size > stopped_size)
        (root / "stop").touch()
        assert child.wait(timeout=10) == 0
        assert api.ended(process)
