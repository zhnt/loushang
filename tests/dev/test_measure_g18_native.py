from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/dev/measure_g18_native.py"
SPEC = importlib.util.spec_from_file_location("measure_g18_native", SCRIPT)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


@pytest.mark.skipif(
    sys.platform != "linux" or sys.version_info[:2] != (3, 11),
    reason="pinned Linux CPython 3.11 observer scope",
)
@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
def test_stdio_observer_scope_restores_borrowed_policy_and_signal(outcome):
    import signal

    from tests.coding import _g18_native_probe as probe

    original = asyncio.get_event_loop_policy()
    original_signal = signal.getsignal(signal.SIGCHLD)
    original_watcher = original.get_child_watcher()
    failure = (
        RuntimeError("original stdio failure")
        if outcome == "error"
        else asyncio.CancelledError()
    )

    async def operation():
        assert type(asyncio.get_child_watcher()) is asyncio.SafeChildWatcher
        if outcome != "success":
            raise failure

    try:
        with probe.stdio_observer_scope() as identity:
            assert asyncio.get_event_loop_policy() is not original
            assert identity == {
                "backend": "cpython311-safe-child-watcher-v1",
                "watcher": "asyncio.unix_events.SafeChildWatcher",
                "python": sys.version,
            }
            asyncio.run(operation())
    except BaseException as error:
        assert outcome != "success" and error is failure
    else:
        assert outcome == "success"
    assert asyncio.get_event_loop_policy() is original
    assert original.get_child_watcher() is original_watcher
    assert signal.getsignal(signal.SIGCHLD) == original_signal


@pytest.mark.parametrize("fault", ["platform", "python", "thread", "loop", "signal"])
def test_stdio_observer_refuses_unsupported_context_before_operation(
    monkeypatch, fault
):
    import signal

    from tests.coding import _g18_native_probe as probe

    original = asyncio.get_event_loop_policy()
    if fault == "platform":
        monkeypatch.setattr(probe.sys, "platform", "unsupported")
    elif fault == "python":
        monkeypatch.setattr(probe.sys, "version_info", (3, 12))
    elif fault == "thread":
        monkeypatch.setattr(probe.threading, "current_thread", lambda: object())
    elif fault == "loop":
        monkeypatch.setattr(probe.asyncio, "get_running_loop", lambda: object())
    else:
        monkeypatch.setattr(probe.signal, "getsignal", lambda _: signal.SIG_IGN)
    with pytest.raises(RuntimeError, match="G14 observer"):
        with probe.stdio_observer_scope():
            pytest.fail("unsupported scope must not reach the Product operation")
    assert asyncio.get_event_loop_policy() is original


@pytest.mark.skipif(
    sys.platform != "linux" or sys.version_info[:2] != (3, 11),
    reason="pinned Linux CPython 3.11 observer scope",
)
@pytest.mark.parametrize("outcome", ["success", "error", "cancel", "unknown-thread"])
def test_stdio_observer_real_children_keep_exact_ownership(tmp_path, outcome):
    program = f"""
import asyncio, os, signal, subprocess, sys, threading
from pathlib import Path
sys.path.insert(0, {str(SCRIPT.parents[2])!r})
from tests.coding._g18_native_probe import stdio_observer_scope
outcome = {outcome!r}
Path('controller.pid').write_text(str(os.getpid()))
original_policy = asyncio.get_event_loop_policy()
original_signal = signal.getsignal(signal.SIGCHLD)
foreign = subprocess.Popen([sys.executable, '-I', '-c', 'raise SystemExit(7)'])
Path('foreign.pid').write_text(str(foreign.pid))
# Observe without reaping: a broad waitpid(-1) watcher would steal this exit.
os.waitid(os.P_PID, foreign.pid, os.WEXITED | os.WNOWAIT)
async def operation():
    command = 'import sys; sys.stdin.buffer.read(1)' if outcome in {{'error', 'cancel'}} else 'pass'
    child = await asyncio.create_subprocess_exec(sys.executable, '-I', '-c', command,
                                               stdin=asyncio.subprocess.PIPE)
    Path('child.pid').write_text(str(child.pid))
    try:
        if outcome == 'error':
            raise RuntimeError('original stdio failure')
        if outcome == 'cancel':
            raise asyncio.CancelledError()
        assert await child.wait() == 0
    finally:
        if child.returncode is None:
            child.kill()
        await child.wait()
try:
    with stdio_observer_scope():
        asyncio.run(operation())
finally:
    assert asyncio.get_event_loop_policy() is original_policy
    assert signal.getsignal(signal.SIGCHLD) == original_signal
    assert foreign.wait() == 7, 'observer reaped an unregistered child'
    Path('restored-and-foreign-exit-preserved').touch()
if outcome == 'unknown-thread':
    hold = threading.Event()
    worker = threading.Thread(target=hold.wait, name='g18-unowned-thread', daemon=True)
    worker.start()
"""
    options = dict(cwd=tmp_path, environment={}, timeout=30)
    if outcome == "success":
        runner.owner.run_python([sys.executable, "-I", "-c", program], **options)
    else:
        with pytest.raises(subprocess.CalledProcessError) as caught:
            runner.owner.run_python([sys.executable, "-I", "-c", program], **options)
        assert caught.value.returncode == 1
        if outcome == "unknown-thread":
            assert [
                item["name"] for item in caught.value.evidence_threads["threads"]
            ] == ["g18-unowned-thread"]
    assert (tmp_path / "restored-and-foreign-exit-preserved").exists()
    for name in ("controller.pid", "foreign.pid", "child.pid"):
        with pytest.raises(ProcessLookupError):
            os.kill(int((tmp_path / name).read_text()), 0)
    assert not list(tmp_path.glob("g17-probe-*"))


@pytest.mark.parametrize("fault", [None, "missing", "watcher", "python"])
def test_stdio_receipt_binds_explicit_observer_backend(tmp_path, fault):
    value = observation(tmp_path, tmp_path)
    value.update(
        case="g14-stdio",
        milestones={
            "protocol_ready_seconds": 3.0,
            "first_command_seconds": 0.1,
            "settlement_seconds": 0.2,
        },
        stdio_observer={
            "backend": "cpython311-safe-child-watcher-v1",
            "watcher": "asyncio.unix_events.SafeChildWatcher",
            "python": sys.version,
        },
    )
    value["spawns"][0]["argv"] = [str(tmp_path / "bin/loushang-hosted")]
    if fault == "missing":
        del value["stdio_observer"]
    elif fault == "watcher":
        value["stdio_observer"]["watcher"] = "asyncio.unix_events.ThreadedChildWatcher"
    elif fault == "python":
        value["stdio_observer"]["python"] = "foreign interpreter"
    if fault is None:
        runner.validate_observation(
            value,
            "g14-stdio",
            tmp_path,
            tmp_path,
            tmp_path,
            observer_python=sys.version,
        )
    else:
        with pytest.raises(ValueError):
            runner.validate_observation(
                value,
                "g14-stdio",
                tmp_path,
                tmp_path,
                tmp_path,
                observer_python=sys.version,
            )


@pytest.mark.skipif(
    sys.platform != "linux" or sys.version_info[:2] != (3, 11),
    reason="pinned Linux CPython 3.11 observer scope",
)
@pytest.mark.parametrize("fault", ["install", "loop-attach", "close"])
def test_stdio_scope_setup_or_close_failure_restores_policy(monkeypatch, fault):
    import signal

    from tests.coding import _g18_native_probe as probe

    original = asyncio.get_event_loop_policy()
    original_signal = signal.getsignal(signal.SIGCHLD)
    policy = asyncio.DefaultEventLoopPolicy()
    watcher = asyncio.SafeChildWatcher()
    created = []
    set_loop = policy.set_event_loop
    close = watcher.close
    error = RuntimeError("injected stdio scope failure")

    def attach(loop):
        set_loop(loop)
        if loop is not None:
            created.append(loop)
            if fault == "loop-attach":
                raise error

    def install(value):
        raise error

    def fail_close():
        close()
        raise error

    monkeypatch.setattr(probe.asyncio, "DefaultEventLoopPolicy", lambda: policy)
    monkeypatch.setattr(probe.asyncio, "SafeChildWatcher", lambda: watcher)
    monkeypatch.setattr(policy, "set_event_loop", attach)
    if fault == "install":
        monkeypatch.setattr(policy, "set_child_watcher", install)
    elif fault == "close":
        monkeypatch.setattr(watcher, "close", fail_close)

    async def operation():
        return None

    coroutine = operation()
    try:
        with pytest.raises(RuntimeError) as caught:
            with probe.stdio_observer_scope():
                asyncio.run(coroutine)
        assert caught.value is error
    finally:
        coroutine.close()
    assert all(loop.is_closed() for loop in created)
    assert asyncio.get_event_loop_policy() is original
    assert signal.getsignal(signal.SIGCHLD) == original_signal


@pytest.mark.parametrize(
    "options",
    [
        ["--fixed-slot"],
        ["--fixed-slot", "--cache-mode", "warm"],
        ["--fixed-slot", "--requirements", "requirements.txt"],
        ["--cache-mode", "absent"],
        ["--requirements", "requirements.txt"],
        *[
            [
                "--fixed-slot",
                "--cache-mode",
                "warm",
                "--requirements",
                "requirements.txt",
                option,
            ]
            for option in (
                "--home-isolation-only",
                "--restored-recovery-preflight",
                "--slot-switch-recovery-preflight",
            )
        ],
    ],
)
def test_fixed_native_cli_refuses_ambiguous_conditions_before_side_effects(
    tmp_path, monkeypatch, options
):
    def unexpected(*args, **kwargs):
        pytest.fail("invalid CLI must not reach installation or source verification")

    monkeypatch.setattr(runner.inert, "source_pair", unexpected)
    monkeypatch.setattr(runner.inert, "verify_pinned_install", unexpected)
    output = tmp_path / "output"
    with pytest.raises(SystemExit) as error:
        runner.main(
            [
                "--install-a",
                str(tmp_path / "a"),
                "--install-b",
                str(tmp_path / "b"),
                "--observer-install",
                str(tmp_path / "observer"),
                "--wheel",
                str(tmp_path / "baseline.whl"),
                "--output",
                str(output),
                *options,
            ]
        )
    assert error.value.code == 2
    assert not output.exists()


def test_native_failure_snapshot_is_bounded_and_does_not_read_process_inputs(tmp_path):
    from tests.coding._g18_native_probe import failure_process_snapshot

    process = tmp_path / "123"
    process.mkdir()
    (process / "status").write_text("x" * 9000)
    (process / "environ").write_text("private-not-a-counter")
    result = failure_process_snapshot(123, proc=tmp_path)
    assert len(result["status"]) == 8192
    assert result["stat"] == "FileNotFoundError"
    assert "environ" not in result and "cmdline" not in result


def _diagnostic_proc_process(root, pid, parent, *, children="", threads=1):
    fields = ["S", str(parent), *(["0"] * 17), str(pid * 10)]
    stat = f"{pid} (diagnostic worker) " + " ".join(fields)
    base = root / str(pid)
    base.mkdir(parents=True)
    for name, value in {
        "stat": stat,
        "status": "Threads: 1",
        "wchan": "ep_poll",
        "io": "read_bytes: 0",
        "schedstat": "10 20 3",
    }.items():
        (base / name).write_text(value)
    for offset in range(threads):
        task = base / "task" / str(pid + offset)
        task.mkdir(parents=True)
        for name, value in {
            "stat": stat,
            "wchan": "ep_poll",
            "schedstat": "10 20 3",
            "stack": "kernel_wait",
            "children": children if not offset else "",
        }.items():
            (task / name).write_text(value)
    (base / "environ").write_text("PRIVATE_CANARY")
    (base / "cmdline").write_text("PRIVATE_CANARY")
    return base


def test_seed_diagnostic_real_coordinator_prepares_once_without_samples(
    tmp_path, monkeypatch
):
    test_fixed_native_collector_orders_cache_and_owner_and_never_counts_failed_warmup(
        tmp_path, monkeypatch, "warm", None, seed_only=True
    )


def test_diagnostic_tree_links_descendants_and_omits_private_inputs(tmp_path):
    from tests.coding._g18_native_probe import failure_tree_snapshot

    _diagnostic_proc_process(tmp_path, 123, 1, children="456")
    _diagnostic_proc_process(tmp_path, 456, 123)
    value = failure_tree_snapshot(123, 1230, proc=tmp_path)
    assert value["complete"]
    assert [p["pid"] for p in value["processes"]] == [123, 456]
    assert all(p["usable"] for p in value["processes"])
    assert all(t["usable"] for p in value["processes"] for t in p["threads"])
    assert "PRIVATE_CANARY" not in json.dumps(value)


@pytest.mark.parametrize("fault", ["root", "missing", "parent", "thread", "permission"])
def test_diagnostic_tree_refuses_races_and_records_unavailable_state(
    tmp_path, monkeypatch, fault
):
    import io

    from tests.coding import _g18_native_probe as probe

    base = _diagnostic_proc_process(tmp_path, 123, 1, children="456")
    child = _diagnostic_proc_process(tmp_path, 456, 123)
    original = Path.open
    calls = 0
    target = base / "task/123/stat" if fault == "thread" else base / "stat"

    def changed(path, *args, **kwargs):
        nonlocal calls
        if fault == "permission" and path.name == "stack":
            raise PermissionError("unavailable kernel stack")
        if fault == "missing" and path == child / "stat":
            raise FileNotFoundError
        if path == target and fault in {"root", "thread"}:
            calls += 1
            if calls >= 2:
                return io.BytesIO(b"123 (worker) S 1 " + b"0 " * 17 + b"9999")
        if fault == "parent" and path == child / "stat":
            return io.BytesIO(b"456 (worker) S 777 " + b"0 " * 17 + b"4560")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", changed)
    value = probe.failure_tree_snapshot(123, 1230, proc=tmp_path)
    assert not value["complete"]
    if fault == "root":
        assert not any(p["usable"] for p in value["processes"])
    if fault in {"missing", "parent"}:
        assert not any(p["pid"] == 456 and p["usable"] for p in value["processes"])
    if fault == "thread":
        assert not value["processes"][0]["threads"][0]["usable"]


@pytest.mark.parametrize("limit", ["process", "thread", "payload", "time", "no-pin"])
def test_diagnostic_tree_bounds_include_enumeration_and_serialization(tmp_path, limit):
    from tests.coding._g18_native_probe import failure_tree_snapshot

    base = _diagnostic_proc_process(
        tmp_path,
        123,
        1,
        children=" ".join(str(n) for n in range(200, 212)),
        threads=12 if limit == "thread" else 1,
    )
    for pid in range(200, 212):
        node = _diagnostic_proc_process(
            tmp_path, pid, 123, threads=8 if limit == "payload" else 1
        )
        if limit == "payload":
            for path in node.rglob("stack"):
                path.write_text("\x00" * 12000)
    if limit == "payload":
        (base / "status").write_text("\x00" * 12000)
    ticks = iter([0, 2, 2, 2, 2])
    options = {"clock": lambda: next(ticks, 2)} if limit == "time" else {}
    value = failure_tree_snapshot(
        123, None if limit == "no-pin" else 1230, proc=tmp_path, **options
    )
    assert not value["complete"]
    assert len(value["processes"]) <= 8
    assert all(len(p["threads"]) <= 8 for p in value["processes"])
    assert len(json.dumps(value).encode()) <= 256 * 1024
    if limit in {"time", "no-pin"}:
        assert not value["processes"]


@pytest.mark.parametrize("diagnostic", [False, True])
@pytest.mark.skipif(sys.platform != "linux", reason="Linux native diagnostic PTY")
def test_diagnostic_failure_preserves_original_exception_and_default_has_no_tree(
    tmp_path, monkeypatch, diagnostic
):
    import pty
    import termios
    from contextlib import contextmanager
    from types import SimpleNamespace

    from tests.coding import _g18_native_probe as probe

    calls = []
    monkeypatch.setattr(probe, "FAILURE_TREE_DIAGNOSTIC", diagnostic)
    monkeypatch.setattr(pty, "openpty", lambda: (1, 2))
    monkeypatch.setattr(termios, "tcgetattr", lambda _: [])
    monkeypatch.setattr(
        probe, "diagnostic_identity", lambda _: calls.append("pin") or 1230
    )
    monkeypatch.setattr(probe, "failure_process_snapshot", lambda _: {})

    def unavailable(*args):
        calls.append("tree")
        raise KeyboardInterrupt("diagnostic failed")

    @contextmanager
    def terminal(*args, **kwargs):
        pty.openpty()
        try:
            yield SimpleNamespace(diagnostics=SimpleNamespace(pid=123))
        finally:
            calls.append("cleanup")

    monkeypatch.setattr(probe, "failure_tree_snapshot", unavailable)
    monkeypatch.setattr(probe, "foreground_terminal", terminal)
    error = TimeoutError("original ready timeout")
    with pytest.raises(TimeoutError) as caught:
        with probe.observed_terminal([], tmp_path, {}, failure_report={}):
            raise error
    assert caught.value is error
    assert calls == (["pin", "tree", "cleanup"] if diagnostic else ["cleanup"])


@pytest.mark.parametrize(
    "extra",
    [
        ["--checkpoint"],
        ["--resume"],
        ["--pause-after", "1"],
        ["--cases", "recovery-cwd"],
        ["--home-isolation-only"],
        ["--cache-mode", "absent"],
    ],
)
def test_seed_diagnostic_rejects_incompatible_modes_before_product(
    tmp_path, monkeypatch, extra
):
    test_fixed_native_cli_refuses_ambiguous_conditions_before_side_effects(
        tmp_path,
        monkeypatch,
        [
            "--fixed-slot",
            "--cache-mode",
            "warm",
            "--requirements",
            str(tmp_path / "requirements"),
            "--seed-preparation-diagnostic",
            *extra,
        ],
    )


@pytest.mark.parametrize("phase", ["aa", "ab", "owner-failure"])
def test_seed_diagnostic_cli_is_zero_sample_and_retains_final_pins(
    tmp_path, monkeypatch, phase
):
    from types import SimpleNamespace

    pins, calls = [], []
    source = {"commit": "baseline", "lock_sha256": "lock", "wheel_sha256": "same"}
    sources = {side: dict(source) for side in ("a", "b")}
    if phase == "ab":
        sources["b"]["wheel_sha256"] = "different"
    monkeypatch.setattr(
        runner.inert,
        "source_pair",
        lambda *_: ({side: tmp_path / side for side in ("a", "b")}, sources),
    )
    monkeypatch.setattr(
        runner.inert,
        "provenance_module",
        lambda: SimpleNamespace(helper_manifest=lambda _: {"helper": "fixed"}),
    )
    monkeypatch.setattr(runner.platform, "system", lambda: "Linux")
    monkeypatch.setattr(runner.os, "sched_getaffinity", lambda _: {0}, raising=False)

    def pin(prefix, *_):
        pins.append(prefix)
        return dict(python="same", dependencies=[], entries={})

    error = TimeoutError("original owner failure")

    def collect(*args, **kwargs):
        assert args[2] == ["recovery-cwd"]
        assert args[-2]["seed_diagnostic"] is True
        assert args[-2]["samples"] == []
        calls.append("seed")
        if phase == "owner-failure":
            raise error

    monkeypatch.setattr(runner.inert, "verify_pinned_install", pin)
    monkeypatch.setattr(runner, "provision_slot", lambda *_: object())
    monkeypatch.setattr(runner, "collect_fixed_native", collect)
    monkeypatch.setattr(
        runner.inert,
        "comparison_module",
        lambda: pytest.fail("diagnostic cannot compare"),
    )
    output = tmp_path / "out"
    args = [
        "--install-a",
        str(tmp_path / "a"),
        "--install-b",
        str(tmp_path / "b"),
        "--observer-install",
        str(tmp_path / "observer"),
        "--wheel",
        str(tmp_path / "wheel"),
        "--output",
        str(output),
        "--scratch-parent",
        str(tmp_path),
        "--fixed-slot",
        "--cache-mode",
        "warm",
        "--requirements",
        str(tmp_path / "requirements"),
        "--seed-preparation-diagnostic",
    ]
    if phase == "ab":
        with pytest.raises(SystemExit) as caught:
            runner.main(args)
        assert caught.value.code == 2 and not output.exists() and not pins and not calls
        return
    if phase == "owner-failure":
        with pytest.raises(TimeoutError) as caught:
            runner.main(args)
        assert caught.value is error
    else:
        assert runner.main(args) == 0
    value = json.loads((output / "report.json").read_text())
    assert value["scope"] == "linux-seed-startup-diagnostic"
    assert value["samples"] == [] and calls == ["seed"]
    assert value["comparison"]["verdict"] == "not-evaluated"
    assert len(pins) == (3 if phase == "owner-failure" else 6)
    assert value["status"] == (
        "failed" if phase == "owner-failure" else "complete-record-only"
    )


def test_diagnostic_observer_publication_failure_does_not_replace_owner_error(
    tmp_path, monkeypatch
):
    from contextlib import nullcontext
    from types import SimpleNamespace

    import loushang.coding
    from tests.coding import _g18_native_probe as probe

    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setattr(
        probe,
        "sys",
        SimpleNamespace(platform="linux", prefix=str(tmp_path / "install")),
    )
    monkeypatch.setattr(
        loushang.coding, "__file__", str(tmp_path / "install/lib/coding.py")
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.setattr(probe, "measured_entries", lambda _: nullcontext())
    error = TimeoutError("original ready failure")

    def fail(_):
        raise error

    publications = []

    def publication(*args):
        publications.append(True)
        if len(publications) > 1:
            raise OSError("publication failure")

    monkeypatch.setattr(probe, "_guarded", fail)
    monkeypatch.setattr(probe, "publish", publication)
    with pytest.raises(TimeoutError) as caught:
        probe.main(
            root, "prepare:recovery-cwd", tmp_path / "report.json", tmp_path / "install"
        )
    assert caught.value is error
    assert "publication failed" in error.__notes__[0]


@pytest.mark.parametrize("change", [None, "bytes", "missing"])
def test_native_report_cannot_complete_when_trusted_helpers_change(
    tmp_path, monkeypatch, change
):
    from types import SimpleNamespace

    calls = []

    def manifest(root):
        calls.append(root)
        if len(calls) == 2 and change == "missing":
            raise FileNotFoundError("helper removed during sampling")
        return {"tests/helper.py": "changed" if len(calls) == 2 and change else "same"}

    source = {"commit": "baseline", "lock_sha256": "lock", "wheel_sha256": "wheel"}
    monkeypatch.setattr(runner.platform, "system", lambda: "Linux")
    monkeypatch.setattr(runner.os, "sched_getaffinity", lambda _: {0}, raising=False)
    monkeypatch.setattr(
        runner.inert,
        "source_pair",
        lambda *_: (
            {side: tmp_path / "baseline.whl" for side in ("a", "b")},
            {side: source for side in ("a", "b")},
        ),
    )
    monkeypatch.setattr(
        runner.inert,
        "provenance_module",
        lambda: SimpleNamespace(helper_manifest=manifest),
    )
    monkeypatch.setattr(
        runner.inert,
        "verify_pinned_install",
        lambda *_: dict(python="same", dependencies=[], entries={}),
    )
    monkeypatch.setattr(runner, "run_sample", lambda *args, **_: None)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(runner.tempfile, "mkdtemp", lambda **_: str(scratch))
    output = tmp_path / "output"
    args = [
        "--install-a",
        str(tmp_path / "a"),
        "--install-b",
        str(tmp_path / "b"),
        "--observer-install",
        str(tmp_path / "observer"),
        "--output",
        str(output),
        "--wheel",
        str(tmp_path / "baseline.whl"),
        "--home-isolation-only",
    ]
    if change:
        with pytest.raises((ValueError, FileNotFoundError)):
            runner.main(args)
    else:
        assert runner.main(args) == 0
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == ("failed" if change else "complete-record-only")
    assert len(calls) == 2
    assert report["helpers_before"] == {"tests/helper.py": "same"}


@pytest.mark.parametrize(
    "outcome",
    [
        "pass",
        "regression",
        "inconclusive",
        "helpers",
        "install",
        "owner",
        "missing",
        "short",
        "grouping",
        "partial",
        "nonfixed",
    ],
)
@pytest.mark.parametrize("phase", ["aa", "ab"])
def test_native_main_publishes_comparison_only_after_all_evidence_gates(
    tmp_path, monkeypatch, outcome, phase
):
    from types import SimpleNamespace

    from tests.dev.test_g18_comparison import native_samples

    source = dict(commit="baseline", lock_sha256="lock", wheel_sha256="wheel")
    manifest_calls = []

    def manifest(_):
        manifest_calls.append(True)
        return {
            "helper": "changed"
            if outcome == "helpers" and len(manifest_calls) == 2
            else "same"
        }

    pins = []

    def pin(*_):
        pins.append(True)
        return dict(
            python="changed" if outcome == "install" and len(pins) == 4 else "same",
            dependencies=[],
            entries={},
        )

    def collect(*args, temporary_parent):
        assert temporary_parent == tmp_path
        report = args[-2]
        assert report["comparison"]["verdict"] == "not-evaluated"
        report["samples"] = native_samples(
            right=1.2 if outcome == "regression" else 1.0
        )
        if outcome == "inconclusive":
            for sample in report["samples"]:
                if sample["block"] == 1:
                    sample["milestones"] = {
                        metric: 1.3 for metric in sample["milestones"]
                    }
        if outcome == "missing":
            report["samples"].pop()
        if outcome == "owner":
            raise RuntimeError("retained owner rejected cleanup")

    monkeypatch.setattr(runner.platform, "system", lambda: "Linux")
    monkeypatch.setattr(runner.os, "sched_getaffinity", lambda _: {0}, raising=False)
    monkeypatch.setattr(
        runner.inert,
        "source_pair",
        lambda *_: (
            {side: tmp_path / "baseline.whl" for side in ("a", "b")},
            {
                side: {**source, "wheel_sha256": side if phase == "ab" else "wheel"}
                for side in ("a", "b")
            },
        ),
    )
    monkeypatch.setattr(
        runner.inert,
        "provenance_module",
        lambda: SimpleNamespace(helper_manifest=manifest),
    )
    monkeypatch.setattr(runner.inert, "verify_pinned_install", pin)
    monkeypatch.setattr(runner, "provision_slot", lambda *_: object())
    monkeypatch.setattr(runner, "collect_fixed_native", collect)
    monkeypatch.setattr(runner, "run_sample", lambda *_, **__: None)
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    def temporary(**kwargs):
        assert kwargs["dir"] == tmp_path
        return str(scratch)

    monkeypatch.setattr(runner.tempfile, "mkdtemp", temporary)
    output = tmp_path / "output"
    options = ["--fixed-slot", "--cache-mode", "warm", "--requirements", "locked.txt"]
    if outcome == "short":
        options += ["--blocks", "1", "--pairs-per-block", "1"]
    elif outcome == "grouping":
        options += ["--blocks", "4", "--pairs-per-block", "5"]
    elif outcome == "partial":
        options += ["--cases", "embedded"]
    elif outcome == "nonfixed":
        options = ["--cases", "embedded", "--blocks", "1", "--pairs-per-block", "1"]
    args = [
        "--install-a",
        str(tmp_path / "a"),
        "--install-b",
        str(tmp_path / "b"),
        "--observer-install",
        str(tmp_path / "observer"),
        "--wheel",
        "baseline.whl",
        "--scratch-parent",
        str(tmp_path),
        "--output",
        str(output),
        *options,
    ]
    if outcome in {"helpers", "install", "owner", "missing"}:
        with pytest.raises((ValueError, RuntimeError)):
            runner.main(args)
    else:
        # Collection remains advisory, including a negative timing verdict.
        assert runner.main(args) == 0
    report = json.loads((output / "report.json").read_text())
    assert report["scratch_parent"] == str(tmp_path)
    assert report["scratch_device"] == scratch.stat().st_dev
    if outcome in {"pass", "regression", "inconclusive"}:
        assert report["status"] == "complete-record-only"
        assert report["comparison"]["verdict"] == (
            "inconclusive" if phase == "aa" and outcome == "regression" else outcome
        )
        assert report["comparison"]["phase"] == phase
        assert sum(map(len, report["comparison"]["cases"].values())) == 41
    else:
        assert report["comparison"]["verdict"] == "not-evaluated"
        assert report["comparison"]["reason"]
        assert report["status"] == (
            "failed"
            if outcome in {"helpers", "install", "owner", "missing"}
            else "complete-record-only"
        )


@pytest.mark.parametrize("kind", ["fixed", "restored"])
def test_recovery_allocators_receive_explicit_temporary_parent(
    tmp_path, monkeypatch, kind
):
    from types import SimpleNamespace

    parent, output = tmp_path / "parent", tmp_path / "output"
    parent.mkdir()
    output.mkdir()
    calls = []

    class AllocationWitness(Exception):
        pass

    def allocate(temporary_parent, artifacts):
        calls.append((temporary_parent, artifacts))
        raise AllocationWitness

    monkeypatch.setattr(runner.recovery_state, "RecoveryState", allocate)
    monkeypatch.setattr(
        runner.bytecode_policy,
        "BytecodePolicy",
        lambda *_: SimpleNamespace(external=lambda _: output / "pyc"),
    )
    with pytest.raises(AllocationWitness):
        if kind == "fixed":
            runner.collect_fixed_native(
                object(),
                "absent",
                ["recovery-cwd"],
                1,
                1,
                tmp_path / "observer",
                {},
                {},
                output,
                {},
                output / "report.json",
                temporary_parent=parent,
            )
        else:
            runner.restored_recovery_preflight(
                tmp_path / "prefix",
                tmp_path / "observer",
                output,
                {},
                output / "report.json",
                temporary_parent=parent,
            )
    assert calls == [(parent, output)]


@pytest.mark.parametrize("collector", ["inert", "native"])
@pytest.mark.parametrize("kind", ["missing", "file"])
def test_invalid_scratch_parent_is_rejected_before_source_or_output(
    tmp_path, monkeypatch, collector, kind
):
    target = runner.inert if collector == "inert" else runner
    source_owner = runner.inert
    monkeypatch.setattr(
        source_owner,
        "source_pair",
        lambda *_: pytest.fail("must reject parent before source inspection"),
    )
    parent, output = tmp_path / "parent", tmp_path / "output"
    if kind == "file":
        parent.write_text("not a directory")
    options = (
        ["--observer-install", str(tmp_path / "observer")]
        if collector == "native"
        else []
    )
    with pytest.raises(SystemExit) as caught:
        target.main(
            [
                "--install-a",
                str(tmp_path / "a"),
                "--install-b",
                str(tmp_path / "b"),
                "--wheel",
                "baseline.whl",
                "--scratch-parent",
                str(parent),
                "--output",
                str(output),
                *options,
            ]
        )
    assert caught.value.code == 2 and not output.exists()


@pytest.mark.parametrize("cache_mode", ["warm", "absent"])
@pytest.mark.parametrize("fault", [None, "pre", "cache", "owner", "post"])
def test_fixed_native_collector_orders_cache_and_owner_and_never_counts_failed_warmup(
    tmp_path, monkeypatch, cache_mode, fault, seed_only=False
):
    if __import__("sys").platform != "linux":
        pytest.skip("Linux native fixed slot")
    slot = runner.installation_slot.InstallationSlot(tmp_path)
    for side in ("a", "b"):

        def install(prefix, *, side=side):
            prefix.mkdir()
            (prefix / "variant").write_text(side)
            (prefix / "module.py").write_text("source remains installed")
            (prefix / "module.pyc").write_bytes(b"initial cache")

        slot.provision(side, install)
    output = tmp_path / "output"
    output.mkdir()
    report = dict(
        samples=[],
        scratch=str(tmp_path / "scratch"),
        slot_builds=[{"installation": {"side": side}} for side in ("a", "b")],
    )
    if seed_only:
        report["seed_diagnostic"] = True
    path = output / "report.json"
    sources = {side: {"wheel_sha256": side} for side in ("a", "b")}
    events = []
    original_state = runner.recovery_state.RecoveryState
    monkeypatch.setattr(
        runner.recovery_state,
        "RecoveryState",
        lambda _, artifacts: original_state(tmp_path, artifacts),
    )

    def verify(prefix, wheel, control, expected_hash):
        side = (prefix / "variant").read_text()
        assert prefix == slot.prefix and wheel == Path(side) and expected_hash == side
        phase, _, number = control.name.split("-")
        events.append((phase, int(number)))
        (prefix / "module.pyc").write_bytes(b"verification may populate caches")
        if phase == fault and number == "1":
            raise ValueError("fixed sample source check failed")
        return {"side": side}

    prepare_cache = runner.bytecode_policy.BytecodePolicy.prepare

    def cache(self, side, mode):
        number = report["samples"][-1]["iteration"]
        events.append(("cache", number))
        if fault == "cache" and number == 1:
            raise ValueError("cache preparation failed")
        return prepare_cache(self, side, mode)

    def owner(argv, *, cwd, environment, timeout):
        if seed_only:
            assert argv[-1] == "--failure-tree"
            assert timeout == 240
            assert not any("FAILURE_TREE" in key for key in environment)
        workspace, receipt = Path(argv[3]), Path(argv[5])
        stage, case = argv[4].split(":") if ":" in argv[4] else ("fresh", argv[4])
        number = 0 if stage == "prepare" else report["samples"][-1]["iteration"]
        events.append(("owner", number))
        if number:
            # No active-prefix Python verification may intervene after clearing.
            assert events[-3:] == [
                ("pre", number),
                ("cache", number),
                ("owner", number),
            ]
            installed = runner.bytecode_policy.inventory(slot.prefix, installation=True)
            external = runner.bytecode_policy.inventory(
                Path(environment["PYTHONPYCACHEPREFIX"])
            )
            if cache_mode == "absent":
                assert not installed and not external
            else:
                assert installed
            if fault == "owner" and number == 1:
                raise TimeoutError("original native witness failed")
        value = observation(slot.prefix, workspace.parent, tmp_path / "observer")
        value.update(case=case)

        def launch(index):
            selector = (
                workspace / "other-workspace"
                if case == "recovery-global" and (stage == "restored" or index == 1)
                else workspace
            )
            command = [
                str(slot.prefix / "bin/loushang-hosted-tui"),
                "--workspace",
                str(selector),
                "--application-root",
                str(workspace / "application"),
                "--cwd-sessions",
                str(workspace / "cwd"),
                "--home-sessions",
                str(workspace / "home"),
            ]
            if stage == "restored" or index == 1:
                command.extend(["--mux", "picker"])
            return dict(
                pid=123 + index, start=1.0 + index * 2, argv=command, cwd=str(workspace)
            )

        if stage != "fresh":
            value["recovery_stage"] = stage
        if stage == "prepare":
            (workspace / "seed").write_bytes(b"immutable baseline state")
            scope = "cwd" if case == "recovery-cwd" else "user_home"
            value.update(
                spawns=[],
                milestones={},
                seed=dict(
                    scope=scope,
                    history=f"G17 canonical history recovered in {scope}",
                    session_count=1,
                    shape={"synthetic": "coordinator test"},
                    files={
                        "seed": hashlib.sha256(b"immutable baseline state").hexdigest()
                    },
                ),
                seed_setup=[
                    dict(status="settled", settled_at=2.0 + i * 2, spawns=[launch(i)])
                    for i in range(2)
                ],
            )
        else:
            value["spawns"] = [launch(0)]
            if stage == "restored":
                assert (workspace / "seed").read_bytes() == b"immutable baseline state"
                (workspace / "seed").write_bytes(
                    b"sample output; next sample must reset"
                )
                value["seed"] = "coordinator-verified-snapshot"
                value["milestones"].update(
                    history_visible_seconds=1.0, spawn_through_first_command_seconds=4.0
                )
            (slot.prefix / "module.pyc").write_bytes(b"generated by measured run")
            (Path(environment["PYTHONPYCACHEPREFIX"]) / "generated.pyc").write_bytes(
                b"external generated cache"
            )
        receipt.write_text(json.dumps(value))

    monkeypatch.setattr(runner.inert, "verify_pinned_install", verify)
    monkeypatch.setattr(runner.bytecode_policy.BytecodePolicy, "prepare", cache)
    monkeypatch.setattr(runner.owner, "run_python", owner)
    cases = ("foreground", "recovery-cwd", "recovery-global")
    if seed_only:
        cases = ("recovery-cwd",)
    args = (
        slot,
        cache_mode,
        cases,
        2,
        2,
        tmp_path / "observer",
        {side: Path(side) for side in ("a", "b")},
        sources,
        output,
        report,
        path,
    )
    if seed_only:
        runner.collect_fixed_native(*args)
        assert report["samples"] == []
        assert len(report["seed_setup"]) == 1 and report["seed_setup"][0]["valid"]
        assert events == [("pre", 0), ("owner", 0), ("post", 0)]
        assert not slot.receipt["busy"] and not slot.receipt["failed"]
        return
    if fault:
        with pytest.raises((ValueError, TimeoutError)):
            runner.collect_fixed_native(*args)
        assert slot.receipt["failed"]
        assert len(report["samples"]) == 1
        assert report["samples"][0]["warmup"] is True
        assert report["samples"][0]["valid"] is False
        assert report["samples"][0]["status"] == "failed"
        assert (
            ("owner", 1) in events
            if fault in ("owner", "post")
            else ("owner", 1) not in events
        )
    else:
        runner.collect_fixed_native(*args)
        assert len(report["samples"]) == 36
        assert sum(sample["warmup"] for sample in report["samples"]) == 12
        assert all(sample["valid"] for sample in report["samples"])
        assert all(
            len(sample["load_before"]) == len(sample["load_after"]) == 3
            for sample in report["samples"] + report["seed_setup"]
        )
        for sample in report["samples"]:
            number = sample["iteration"]
            assert [event for event in events if event[1] == number] == [
                (phase, number) for phase in ("pre", "cache", "owner", "post")
            ]
            evidence = sample["cache"]["before"]
            assert runner.inert.digest(Path(evidence["path"])) == evidence["sha256"]
            cache_receipt = json.loads(Path(evidence["path"]).read_text())
            assert cache_receipt["mode"] == cache_mode
            if cache_mode == "absent":
                assert not any(cache_receipt["ready"].values())
        for case in cases[1:]:
            samples = [sample for sample in report["samples"] if sample["case"] == case]
            assert [sample["recovery_input"]["restores"] for sample in samples] == list(
                range(1, 13)
            )
            assert len({sample["recovery_input"]["sha256"] for sample in samples}) == 1
            assert all(
                sample["recovery_input"]["age_before_observer_seconds"] >= 0
                for sample in samples
            )
        assert [sample["case"] for sample in report["samples"][18:24:2]] == list(
            reversed(cases)
        )


def observation(prefix, root, observer_prefix=None):
    observer_prefix = observer_prefix or prefix
    return {
        "schema_version": 2,
        "case": "embedded",
        "status": "observed",
        "valid": False,
        "milestones": {
            "ready_frame_seconds": 3.0,
            "first_command_seconds": 0.2,
            "settlement_seconds": 0.4,
        },
        "observer_origin": str(observer_prefix / "lib/loushang/coding/__init__.py"),
        "observer_prefix": str(observer_prefix),
        "measured_prefix": str(prefix),
        "sample_id": str(root.resolve()),
        "seed": "empty",
        "seed_setup": [],
        "spawns": [
            {
                "pid": 123,
                "start": 1.0,
                "argv": [str(prefix / "bin/loushang"), "--tui"],
                "cwd": str(root / "workspace"),
            }
        ],
    }


def isolation_observation(prefix, root, observer_prefix=None, *, prepare=True):
    ambient = root / "ambient-home"
    models = ambient / ".loushang/models"
    if prepare:
        models.mkdir(parents=True, exist_ok=True)
        (models / "g18-poison.json").write_bytes(b"{")
        (ambient / "sentinel").write_bytes(b"unchanged")
    value = observation(prefix, root, observer_prefix)
    value.update(case="home-isolation", milestones={}, spawns=[])
    controls = []
    for index, (case, isolated, witness) in enumerate(
        (
            ("embedded", False, "poison-invalid-json"),
            ("embedded", True, "ready-exited"),
            ("foreground", False, "session-unavailable"),
            ("foreground", True, "member-opened"),
        )
    ):
        workspace = (
            root
            / "workspace"
            / f"{case}-{'private' if isolated else 'leaked'}"
            / "workspace"
        )
        executable = "loushang" if case == "embedded" else "loushang-hosted-tui"
        spawn = dict(
            pid=123 + index,
            start=index + 1.0,
            argv=[str(prefix / "bin" / executable)],
            cwd=str(workspace),
        )
        milestones = (
            dict(rejected_exit_seconds=1.0)
            if index == 0
            else dict(ready_frame_seconds=1.0, settlement_seconds=1.0)
        )
        if case == "foreground":
            milestones["control_witness_seconds"] = 1.0
        controls.append(
            dict(
                case=case,
                isolated=isolated,
                witness=witness,
                status="settled",
                measured_prefix=str(prefix),
                spawns=[spawn],
                milestones=milestones,
                exit_code=1 if index == 0 else 0,
            )
        )
        value["spawns"].append(spawn)
    before = runner.inert.fingerprint_tree(ambient)
    value["isolation"] = dict(
        ambient_before=before,
        ambient_after=dict(before),
        environment_unchanged=True,
        controls=controls,
    )
    return value


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "missing-control",
        "no-new",
        "wrong-witness",
        "exit-zero",
        "not-settled",
        "changed-ambient",
        "file-write",
        "parent-environment",
        "cwd",
        "entry",
        "order",
    ],
)
def test_real_home_control_receipt_needs_all_witnesses_and_unchanged_inputs(
    tmp_path, fault
):
    value = isolation_observation(tmp_path, tmp_path)
    isolation = value["isolation"]
    if fault == "missing-control":
        isolation["controls"].pop()
    elif fault == "no-new":
        del isolation["controls"][2]["milestones"]["control_witness_seconds"]
    elif fault == "wrong-witness":
        isolation["controls"][2]["witness"] = "ready-exited"
    elif fault == "exit-zero":
        isolation["controls"][0]["exit_code"] = 0
    elif fault == "not-settled":
        isolation["controls"][1]["status"] = "running"
    elif fault == "changed-ambient":
        isolation["ambient_after"]["sentinel"] = "different"
    elif fault == "file-write":
        (tmp_path / "ambient-home/sentinel").write_text("modified")
    elif fault == "parent-environment":
        isolation["environment_unchanged"] = False
    elif fault == "cwd":
        value["spawns"][0]["cwd"] = str(tmp_path)
    elif fault == "entry":
        value["spawns"][0]["argv"][0] = "/foreign/loushang"
    elif fault == "order":
        value["spawns"][1]["start"] = value["spawns"][0]["start"]
    if fault:
        with pytest.raises(ValueError):
            runner.validate_observation(
                value, "home-isolation", tmp_path, tmp_path, tmp_path
            )
    else:
        runner.validate_observation(
            value, "home-isolation", tmp_path, tmp_path, tmp_path
        )


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "exit-zero",
        "no-rejection",
        "ambient-write",
        "late-bad-member",
        "late-good-error",
        "late-default-ready",
        "late-default-error",
    ],
)
def test_home_control_drives_first_member_not_only_empty_ready(
    tmp_path, monkeypatch, fault
):
    import os
    import time
    from contextlib import contextmanager

    from tests.coding import _g18_native_probe as probe

    value = isolation_observation(tmp_path, tmp_path)
    value["spawns"] = []
    ambient = tmp_path / "ambient-home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("HOME", str(ambient))
    monkeypatch.setenv("USERPROFILE", str(ambient))
    bytecode = tmp_path / "collector-output/bytecode-a"
    monkeypatch.setenv("PYTHONPYCACHEPREFIX", str(bytecode))
    environment_before = dict(os.environ)
    calls = []

    class Driver:
        diagnostics = None

        def __init__(self, leaked=False):
            self.leaked = leaked
            self.raw_output = (
                str(ambient / ".loushang/models/g18-poison.json")
                + ": models registry file has invalid JSON"
            )
            if fault == "late-default-error":
                self.raw_output = ""

        def write(self, text):
            assert text == "/new cwd G18 isolation\r"
            calls.append("new")
            self.raw_output += (
                "session_unavailable"
                if self.leaked and fault != "no-rejection"
                else "*1"
            )

        def read_until(self, predicate, *, timeout):
            assert predicate(self.raw_output), "control witness missing"

        def wait(self, *, timeout):
            return 0 if fault == "exit-zero" else 1

    @contextmanager
    def spawn(executable):
        yield dict(
            pid=123, start=time.perf_counter(), argv=[executable], cwd="test-only"
        )

    @contextmanager
    def terminal(argv, root, environment, **kwargs):
        assert Path(environment["PYTHONPYCACHEPREFIX"]) == bytecode / root.parent.name
        assert environment["HOME"] == str(ambient)
        assert environment["TERM"] == "xterm-256color"
        assert "PYTHONPATH" not in environment
        assert Path(environment["LOUSHANG_HOME"]).is_relative_to(root.parent)
        calls.append("bad-default")
        driver = Driver(True)
        yield driver, None, None
        if fault == "late-default-ready":
            driver.raw_output += "Welcome to Loushang CLI"
        elif fault == "late-default-error":
            driver.raw_output += (
                str(ambient / ".loushang/models/g18-poison.json")
                + ": models registry file has invalid JSON"
            )

    def foreground(
        root,
        control,
        *,
        embedded,
        interaction,
        first_use,
        environment,
        interaction_milestone,
    ):
        assert first_use is False
        assert Path(environment["PYTHONPYCACHEPREFIX"]) == bytecode / root.parent.name
        assert environment["TERM"] == "xterm-256color"
        assert "PYTHONPATH" not in environment
        assert Path(environment["LOUSHANG_HOME"]).is_relative_to(root.parent)
        leaked = environment["HOME"] == str(ambient)
        assert leaked is not control["isolated"]
        calls.append(
            "good-default" if embedded else "bad-hosted" if leaked else "good-hosted"
        )
        if interaction:
            driver = Driver(leaked)
            interaction(driver)
            if fault == ("late-bad-member" if leaked else "late-good-error"):
                driver.raw_output += "*1" if leaked else "session_unavailable"
        if fault == "ambient-write":
            (ambient / "new-file").write_text("unexpected")

    monkeypatch.setattr(probe, "observe_spawn", spawn)
    monkeypatch.setattr(probe, "observed_terminal", terminal)
    monkeypatch.setattr(probe, "foreground", foreground)
    if fault and fault != "late-default-error":
        with pytest.raises(AssertionError):
            probe.home_isolation(workspace, value)
    else:
        probe.home_isolation(workspace, value)
        assert calls == [
            "bad-default",
            "good-default",
            "bad-hosted",
            "new",
            "good-hosted",
            "new",
        ]
        assert (
            value["isolation"]["ambient_before"] == value["isolation"]["ambient_after"]
        )
        assert value["isolation"]["environment_unchanged"] is True
        assert dict(os.environ) == environment_before


@pytest.mark.parametrize(
    "fault",
    [
        "case",
        "status",
        "valid",
        "schema",
        "missing",
        "nan",
        "negative",
        "origin",
        "observer-prefix",
        "measured-prefix",
        "sample",
        "spawns",
        "seed",
        "extra",
        "spawn-cwd",
        "spawn-executable",
    ],
)
def test_native_receipt_rejects_missing_invalid_or_foreign_evidence(tmp_path, fault):
    value = observation(tmp_path, tmp_path)
    if fault == "case":
        value["case"] = "foreground"
    elif fault == "status":
        value["status"] = "failed"
    elif fault == "valid":
        value["valid"] = True
    elif fault == "schema":
        value["schema_version"] = 99
    elif fault == "missing":
        del value["milestones"]["settlement_seconds"]
    elif fault in {"nan", "negative"}:
        value["milestones"]["first_command_seconds"] = (
            float("nan") if fault == "nan" else -1
        )
    elif fault == "origin":
        value["observer_origin"] = "/foreign/loushang/coding/__init__.py"
    elif fault in {"observer-prefix", "measured-prefix"}:
        value[fault.replace("-", "_")] = "/wrong/install"
    elif fault == "sample":
        value["sample_id"] = str(tmp_path / "wrong-sample")
    elif fault in {"spawns", "seed"}:
        del value[fault]
    elif fault == "extra":
        value["side"] = "b"
    elif fault == "spawn-cwd":
        value["spawns"][0]["cwd"] = "/wrong-workspace"
    else:
        value["spawns"][0]["argv"][0] = "/other/bin/loushang"
    with pytest.raises(ValueError):
        runner.validate_observation(value, "embedded", tmp_path, tmp_path, tmp_path)


@pytest.mark.parametrize(
    "fault", [None, "leftovers", "no-receipt", "bad-receipt", "cancelled"]
)
def test_native_attempt_only_passes_after_supervisor_approval(
    tmp_path, monkeypatch, fault
):
    prefix = tmp_path / "install"
    observer_prefix = tmp_path / "reference-observer"
    root = tmp_path / "sample"
    report = {"samples": []}
    path = tmp_path / "report.json"

    def supervise(argv, *, cwd, environment, timeout):
        pending = json.loads(path.read_text())["samples"][0]
        assert pending["status"] == "running" and pending["valid"] is False
        assert Path(environment["HOME"]).is_relative_to(root)
        assert "PYTHONPATH" not in environment
        assert argv[1] == "-I" and Path(argv[2]) == runner.PROBE
        assert argv[0] == str(observer_prefix / "bin/python")
        assert argv[6] == str(prefix)
        assert argv[7] == str(path.parent / "observer-bytecode")
        if fault != "no-receipt":
            (root / "native.json").write_text(
                "{broken"
                if fault == "bad-receipt"
                else json.dumps(observation(prefix, root, observer_prefix))
            )
        if fault == "cancelled":
            raise KeyboardInterrupt
        if fault:
            raise subprocess.CalledProcessError(1, argv)

    monkeypatch.setattr(runner.owner, "run_python", supervise)
    kwargs = (
        prefix,
        "embedded",
        root,
        tmp_path / "pyc",
        report,
        path,
        dict(side="a", block=0, pair=0),
    )
    if fault:
        with pytest.raises(
            KeyboardInterrupt if fault == "cancelled" else subprocess.CalledProcessError
        ):
            runner.run_sample(*kwargs, observer_prefix=observer_prefix)
    else:
        runner.run_sample(*kwargs, observer_prefix=observer_prefix)
    (sample,) = json.loads(path.read_text())["samples"]
    assert sample["valid"] is (fault is None)
    assert sample["status"] == ("complete" if fault is None else "failed")
    assert sample["case"] == "embedded" and sample["pair"] == 0
    if fault == "leftovers":
        assert sample["partial_observation"]["status"] == "observed"


def test_native_failure_retains_owner_thread_diagnostic_without_passing(
    tmp_path, monkeypatch
):
    evidence = {
        "threads": [{"name": "g18-thread-witness", "stack": []}],
        "truncated": False,
    }
    error = subprocess.CalledProcessError(1, ["owned-observer"])
    error.evidence_threads = evidence

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(runner.owner, "run_python", fail)
    report, path = {"samples": []}, tmp_path / "report.json"
    with pytest.raises(subprocess.CalledProcessError) as caught:
        runner.run_sample(
            tmp_path / "install",
            "g14-stdio",
            tmp_path / "sample",
            tmp_path / "pyc",
            report,
            path,
            dict(side="a", block=0, pair=0),
            observer_prefix=tmp_path / "observer",
        )
    assert caught.value is error
    (sample,) = json.loads(path.read_text())["samples"]
    assert sample["status"] == "failed" and sample["valid"] is False
    assert sample["owner_threads"] == evidence


@pytest.mark.parametrize("fault", [None, "input-replaced", "collector-environment"])
def test_home_control_parent_pins_original_input_not_self_consistent_receipts(
    tmp_path, monkeypatch, fault
):
    prefix, observer_prefix = tmp_path / "installation", tmp_path / "observer"
    root, path = tmp_path / "control", tmp_path / "report.json"
    report = {"samples": []}

    def supervise(argv, *, cwd, environment, timeout):
        assert argv[0] == str(observer_prefix / "bin/python")
        assert argv[4] == "home-isolation" and timeout == 360
        assert (
            environment["HOME"]
            == environment["USERPROFILE"]
            == str(root / "ambient-home")
        )
        assert environment["LOUSHANG_HOME"] != environment["HOME"]
        assert Path(environment["LOUSHANG_HOME"]).is_relative_to(root)
        if fault == "input-replaced":
            (root / "ambient-home/sentinel").write_bytes(
                b"changed before observer snapshot"
            )
        elif fault == "collector-environment":
            monkeypatch.setenv("G18_WRONG_PARENT_WRITE", "test")
        value = isolation_observation(prefix, root, observer_prefix, prepare=False)
        (root / "native.json").write_text(json.dumps(value))

    monkeypatch.setattr(runner.owner, "run_python", supervise)
    arguments = (
        prefix,
        "home-isolation",
        root,
        tmp_path / "bytecode",
        report,
        path,
        dict(side="a", block=0, pair=0, warmup=False),
    )
    if fault:
        with pytest.raises(ValueError):
            runner.run_sample(*arguments, observer_prefix=observer_prefix)
    else:
        runner.run_sample(*arguments, observer_prefix=observer_prefix)
    (sample,) = json.loads(path.read_text())["samples"]
    assert sample["valid"] is (fault is None)


def test_embedded_close_requires_main_screen_not_another_completed_panel_frame():
    from tests.coding._g18_native_probe import embedded_main_frame

    initial = "\x1b[?2026h\x1b[H\x1b[2J› \r\nidle\x1b[?2026l"
    panel = "\x1b[?2026h\x1b[3;1HHotkeys:\r\nEnter/Esc to close\x1b[?2026l"
    before = initial + panel
    checkpoint = len(before)
    assert not embedded_main_frame(before, after=checkpoint)
    assert not embedded_main_frame(before + panel, after=checkpoint)
    close = "\x1b[?2026h\x1b[3;1H\x1b[2K\r\n\x1b[2K\x1b[?2026l"
    assert not embedded_main_frame(before + close[:-1], after=checkpoint)
    assert embedded_main_frame(before + close, after=checkpoint)


def test_embedded_screen_projection_accepts_existing_keyboard_and_cell_queries():
    from tests.coding._g18_native_probe import embedded_main_frame

    queries = "\x1b[?u\x1b[16t\x1b[>4;2m"
    frame = "\x1b[?2026h\x1b[H› \r\nidle\x1b[?2026l"
    assert embedded_main_frame(queries + frame, after=len(queries))


def recovery_seed(root, scope_name):
    from loushang.ai.types import UserMessage
    from loushang.appserver.protocol import SessionIdentityV1, SessionScopeV1
    from loushang.appservice.continuity import (
        ApplicationContinuityRecordV1,
        MuxMemberContinuityV1,
        MuxSpaceContinuityV1,
        encode_application_continuity_record,
    )
    from loushang.coding.hosted_catalog import CodingHostedSessionCatalogV1
    from loushang.coding.session_manager import SessionManager
    from tests.coding.test_hosted_catalog import _intent
    from tests.coding.test_hosted_client import _launch

    scope = next(
        item for item in _launch(root).scopes if item.scope.value == scope_name
    )

    async def create():
        candidate = await CodingHostedSessionCatalogV1((scope,)).create_candidate(
            _intent(scope)
        )
        envelope = candidate.projection.envelope
        await candidate.close()
        (path,) = scope.session_dir.glob("*.jsonl")
        manager = await SessionManager.open(path)
        try:
            await manager.append_message(
                UserMessage(
                    role="user",
                    content=f"G17 canonical history recovered in {scope_name}",
                    timestamp=1.0,
                )
            )
        finally:
            await manager.dispose_runtime_profile()
        # CLI2 restores the appended history before CLI3 is measured.
        reopened = await SessionManager.open(path)
        await reopened.dispose_runtime_profile()
        return envelope

    identity = asyncio.run(create())
    record = ApplicationContinuityRecordV1(
        "coding.default",
        "coding",
        5,
        (
            MuxSpaceContinuityV1("main-id", "main", 3),
            MuxSpaceContinuityV1(
                "picker-id",
                "picker",
                2,
                (
                    MuxMemberContinuityV1(
                        "member-id",
                        f"Session {identity.session_id[:12]}",
                        1,
                        SessionIdentityV1(
                            "coding",
                            identity.continuity_id,
                            identity.session_id,
                            SessionScopeV1(scope_name),
                            scope.fingerprint,
                        ),
                    ),
                ),
            ),
        ),
    )
    directory = root / "application"
    directory.mkdir(mode=0o700)
    path = directory / "coding.default.json"
    path.write_bytes(encode_application_continuity_record(record))
    return scope, record, path


@pytest.mark.parametrize("scope_name", ["cwd", "user_home"])
def test_recovery_seed_validates_linked_state_without_mutating_files(
    tmp_path, scope_name
):
    from tests.coding._g18_native_probe import validate_recovery_seed

    recovery_seed(tmp_path, scope_name)
    before = {
        str(path.relative_to(tmp_path)): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    seed = validate_recovery_seed(tmp_path, scope_name)
    assert seed["scope"] == scope_name
    assert seed["shape"]["record_revision"] == 5
    assert seed["shape"]["muxes"] == [["main", 3, 0], ["picker", 2, 1]]
    assert seed["shape"]["record_kinds"] == ["agent.message"]
    assert seed["files"] == {
        name: hashlib.sha256(data).hexdigest() for name, data in before.items()
    }
    assert before == {
        str(path.relative_to(tmp_path)): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize(
    "fault",
    [
        "revision",
        "member",
        "identity",
        "history",
        "extra-session",
        "extra-app",
        "index",
        "store",
        "directory-index",
    ],
)
def test_recovery_seed_rejects_changed_workload(tmp_path, fault):
    from loushang.appservice.continuity import encode_application_continuity_record
    from tests.coding._g18_native_probe import validate_recovery_seed

    scope, record, path = recovery_seed(tmp_path, "cwd")
    if fault == "revision":
        record = replace(record, record_revision=6)
    elif fault == "member":
        record = replace(
            record,
            mux_spaces=(
                record.mux_spaces[0],
                replace(record.mux_spaces[1], members=()),
            ),
        )
    elif fault == "identity":
        member = record.mux_spaces[1].members[0]
        member = replace(member, session=replace(member.session, session_id="f" * 64))
        record = replace(
            record,
            mux_spaces=(
                record.mux_spaces[0],
                replace(record.mux_spaces[1], members=(member,)),
            ),
        )
    elif fault in {"history", "extra-session"}:
        (session,) = scope.session_dir.glob("*.jsonl")
        if fault == "history":
            session.write_bytes(
                session.read_bytes().replace(b"G17 canonical", b"G18 different")
            )
        else:
            (scope.session_dir / "extra.jsonl").write_bytes(session.read_bytes())
    elif fault == "extra-app":
        (path.parent / "extra.json").write_bytes(path.read_bytes())
    elif fault == "directory-index":
        (scope.session_dir / ".session-index.json").write_text("{}")
    else:
        (session,) = scope.session_dir.glob("*.jsonl")
        suffix = ".store.json" if fault == "store" else ".model-input-v2.index.json"
        session.with_name(session.name + suffix).write_text("{}")
    path.write_bytes(encode_application_continuity_record(record))
    with pytest.raises((ValueError, AssertionError)):
        validate_recovery_seed(tmp_path, "cwd")


def test_recovery_shape_normalizes_linked_ids_but_keeps_profile_metadata(tmp_path):
    from tests.coding._g18_native_probe import validate_recovery_seed

    seeds = []
    for name in ("a", "b"):
        root = tmp_path / name
        root.mkdir()
        recovery_seed(root, "cwd")
        seeds.append(validate_recovery_seed(root, "cwd"))
    assert seeds[0]["shape"] == seeds[1]["shape"]
    assert seeds[0]["files"] != seeds[1]["files"]
    assert len(seeds[0]["shape"]["header_metadata"]) > 2


def test_opaque_recovery_records_nested_journals_without_calling_them_sessions(
    tmp_path,
):
    from tests.coding._g18_native_probe import validate_recovery_seed

    recovery_seed(tmp_path, "cwd")
    paths = (
        "cwd/plugin-state/capability/decisions.jsonl",
        "platform/state/plugin/continuity.jsonl",
        "platform/data/plugin/package-lock.json",
        "home/private/.lease",
    )
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"opaque Product-owned bytes\n")
    before = {
        str(p.relative_to(tmp_path)): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    seed = validate_recovery_seed(tmp_path, "cwd", opaque_input=True)
    assert seed["session_count"] == 1
    assert seed["files"] == {
        name: hashlib.sha256(data).hexdigest() for name, data in before.items()
    }
    assert before == {
        str(p.relative_to(tmp_path)): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    with pytest.raises(AssertionError, match="unexpected recovery input"):
        validate_recovery_seed(tmp_path, "cwd")


@pytest.mark.parametrize("case", ["recovery-cwd", "recovery-global"])
def test_restored_cli3_reuses_original_history_witness_and_scope(
    tmp_path, monkeypatch, case
):
    from tests.coding import _g18_native_probe as probe

    (tmp_path / "other-workspace").mkdir()
    seen = []
    driver = object()
    monkeypatch.setattr(probe, "_picker_resume", lambda *args: seen.append(args))

    def foreground(root, report, *, arguments, interaction, exit_command):
        assert root == tmp_path and report["case"] == case
        workspace = (
            tmp_path / "other-workspace" if case == "recovery-global" else tmp_path
        )
        assert arguments[1] == str(workspace)
        assert arguments[-2:] == ["--mux", "picker"]
        assert exit_command == "\x02d"
        interaction(driver)

    monkeypatch.setattr(probe, "foreground", foreground)
    probe.restored_recovery(tmp_path, dict(case=case))
    assert len(seen) == 1 and seen[0][0] is driver and seen[0][3] == 1
    assert seen[0][2].value == ("user_home" if case == "recovery-global" else "cwd")
    assert seen[0][1] == f"G17 canonical history recovered in {seen[0][2].value}"


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "pending-owner",
        "missing-milestone",
        "foreign-entry",
        "missing-setup",
        "empty-seed",
        "missing-seed",
        "wrong-scope",
        "wrong-history",
        "wrong-count",
        "invalid-hash",
        "wrong-hash",
        "missing-file",
        "extra-file",
        "missing-settled",
        "nan-settled",
        "overlap-settled",
        "extra-setup-field",
        "pre-pin",
        "pre-error",
        "post-pin",
        "post-error",
    ],
)
@pytest.mark.parametrize("with_slot", [False, True])
def test_recovery_preflight_owns_setup_reset_and_failed_evidence(
    tmp_path, monkeypatch, fault, with_slot
):
    import os

    if os.name != "posix" or __import__("sys").platform != "linux":
        pytest.skip("Linux-native reset integration")
    gate_fault = fault in {"pre-pin", "pre-error", "post-pin", "post-error"}
    if gate_fault and not with_slot:
        pytest.skip("per-operation installation gates belong to the slot mode")
    prefix, observer = tmp_path / "slot", tmp_path / "observer"
    output = tmp_path / "output"
    output.mkdir()
    report = dict(samples=[])
    path = output / "report.json"
    calls = []
    checks = []
    slot = None
    if with_slot:
        slot = runner.installation_slot.InstallationSlot(tmp_path)
        prefix = slot.prefix
        for side in ("a", "b"):

            def build(active, *, side=side):
                active.mkdir()
                (active / "variant").write_text(side)

            slot.provision(side, build)
        report["slot_builds"] = [
            {"installation": {"side": side}} for side in ("a", "b")
        ]

        def verify(active, wheel, control, expected_hash):
            side = (active / "variant").read_text()
            assert wheel == Path(side) and expected_hash == side
            checks.append(control.name)
            # Fail the first restored sample, after its real seed/reset path was
            # successfully admitted; not merely the provisioning check.
            if gate_fault and control.name == f"{fault.split('-')[0]}-identity-1":
                if fault.endswith("error"):
                    raise ValueError("simulated per-sample pin failure")
                return {"side": "foreign installed bytes"}
            return {"side": side}

        monkeypatch.setattr(runner.inert, "verify_pinned_install", verify)
    options = dict(
        slot=slot,
        wheels={side: Path(side) for side in ("a", "b")},
        sources={side: {"wheel_sha256": side} for side in ("a", "b")},
    )

    # Use pytest's task root, never the machine's shared temporary root.
    original_state = runner.recovery_state.RecoveryState
    monkeypatch.setattr(
        runner.recovery_state,
        "RecoveryState",
        lambda parent, artifacts: original_state(tmp_path, artifacts),
    )

    def owned(argv, *, cwd, environment, timeout):
        workspace, receipt = Path(argv[3]), Path(argv[5])
        stage, case = argv[4].split(":")
        subject = workspace.parent
        assert not cwd.is_relative_to(subject)
        assert argv[:3] == [str(observer / "bin/python"), "-I", str(runner.PROBE)]
        assert argv[6] == str(prefix)
        assert Path(environment["HOME"]).is_relative_to(subject)
        calls.append((stage, case))
        if fault == "pending-owner":
            (workspace / "retained").write_text("owner failure")
            raise RuntimeError("owner did not succeed")
        value = observation(prefix, subject, observer)
        value.update(case=case, recovery_stage=stage, milestones={}, spawns=[])

        def launch(index):
            workspace_arg = (
                workspace / "other-workspace"
                if case == "recovery-global" and (stage == "restored" or index == 1)
                else workspace
            )
            command = [
                str(prefix / "bin/loushang-hosted-tui"),
                "--workspace",
                str(workspace_arg),
                "--application-root",
                str(workspace / "application"),
                "--cwd-sessions",
                str(workspace / "cwd"),
                "--home-sessions",
                str(workspace / "home"),
            ]
            if stage == "restored" or index == 1:
                command.extend(["--mux", "picker"])
            if fault == "foreign-entry":
                command[0] = "/foreign/bin/loushang-hosted-tui"
            return dict(
                pid=123 + index, start=index * 2 + 1.0, argv=command, cwd=str(workspace)
            )

        if stage == "prepare":
            (workspace / "seed").write_bytes(b"opaque input")
            (workspace / "second").write_bytes(b"also opaque")
            scope = "cwd" if case == "recovery-cwd" else "user_home"
            value.update(
                seed=dict(
                    scope=scope,
                    history=f"G17 canonical history recovered in {scope}",
                    session_count=1,
                    shape={"synthetic": "parent wiring test only"},
                    files={
                        name: hashlib.sha256(
                            (workspace / name).read_bytes()
                        ).hexdigest()
                        for name in ("seed", "second")
                    },
                ),
                seed_setup=[
                    dict(status="settled", spawns=[launch(i)], settled_at=i * 2 + 2.0)
                    for i in range(2)
                ],
            )
            if fault == "missing-setup":
                value["seed_setup"] = []
            elif fault == "empty-seed":
                value["seed"] = {}
            elif fault == "missing-seed":
                del value["seed"]
            elif fault == "wrong-scope":
                value["seed"]["scope"] = "user_home"
            elif fault == "wrong-history":
                value["seed"]["history"] = "other history"
            elif fault == "wrong-count":
                value["seed"]["session_count"] = True
            elif fault == "invalid-hash":
                value["seed"]["files"]["seed"] = "invalid"
            elif fault == "wrong-hash":
                value["seed"]["files"]["seed"] = "0" * 64
            elif fault == "missing-file":
                del value["seed"]["files"]["second"]
            elif fault == "extra-file":
                value["seed"]["files"]["unbound"] = "0" * 64
            elif fault == "missing-settled":
                del value["seed_setup"][0]["settled_at"]
            elif fault == "nan-settled":
                value["seed_setup"][0]["settled_at"] = float("nan")
            elif fault == "overlap-settled":
                value["seed_setup"][0]["settled_at"] = 3.5
            elif fault == "extra-setup-field":
                value["seed_setup"][0]["unverified"] = True
        else:
            assert (workspace / "seed").read_bytes() == b"opaque input"
            assert not (workspace / "extra").exists()
            (workspace / "seed").write_bytes(b"sample mutation")
            (workspace / "extra").touch()
            value.update(
                seed="coordinator-verified-snapshot",
                spawns=[launch(0)],
                milestones=dict.fromkeys(
                    (
                        "ready_frame_seconds",
                        "history_visible_seconds",
                        "first_command_seconds",
                        "spawn_through_first_command_seconds",
                        "settlement_seconds",
                    ),
                    1.0,
                ),
            )
            if fault == "missing-milestone":
                del value["milestones"]["history_visible_seconds"]
        receipt.write_text(json.dumps(value))

    monkeypatch.setattr(runner.owner, "run_python", owned)
    if fault:
        with pytest.raises((RuntimeError, ValueError)):
            runner.restored_recovery_preflight(
                prefix, observer, output, report, path, **options
            )
        assert report["samples"][-1]["status"] == "failed"
        assert report["samples"][-1]["valid"] is False
        assert all(case == "recovery-cwd" for _, case in calls)
        if gate_fault:
            assert slot.receipt["failed"]
            assert len(report["samples"]) == 2
            if fault.startswith("pre"):
                assert calls == [("prepare", "recovery-cwd")]
                assert "observation" not in report["samples"][-1]
                assert checks == ["pre-identity-0", "post-identity-0", "pre-identity-1"]
            else:
                assert calls == [
                    ("prepare", "recovery-cwd"),
                    ("restored", "recovery-cwd"),
                ]
                assert report["samples"][-1]["observation"]["status"] == "observed"
                assert checks == [
                    "pre-identity-0",
                    "post-identity-0",
                    "pre-identity-1",
                    "post-identity-1",
                ]
            assert slot.receipt["active"] == "a"  # No B switch after a failed gate.
    else:
        runner.restored_recovery_preflight(
            prefix, observer, output, report, path, **options
        )
        assert calls == [
            (stage, case)
            for case in ("recovery-cwd", "recovery-global")
            for stage in (
                ("prepare", "restored", "restored", "restored")
                if with_slot
                else ("prepare", "restored", "restored")
            )
        ]
        assert len(report["samples"]) == (8 if with_slot else 6)
        assert all(sample["valid"] for sample in report["samples"])
        assert [sample["snapshot"]["restores"] for sample in report["samples"]] == list(
            range(4 if with_slot else 3)
        ) * 2
        if with_slot:
            assert [sample["side"] for sample in report["samples"]] == [
                "a",
                "a",
                "b",
                "a",
            ] * 2
            assert (
                checks
                == [
                    f"{phase}-identity-{iteration}"
                    for iteration in range(4)
                    for phase in ("pre", "post")
                ]
                * 2
            )


@pytest.mark.parametrize(
    "fault",
    [None, "installer-exit", "owner-cleanup", "requirements", "wheel", "verification"],
)
def test_slot_provisioning_uses_owned_installer_and_stops_on_invalid_evidence(
    tmp_path, monkeypatch, fault
):
    if __import__("sys").platform != "linux":
        pytest.skip("Linux fixed installation slot")
    monkeypatch.setattr(runner.inert, "ROOT", tmp_path)
    monkeypatch.setattr(runner.shutil, "which", lambda _: "/trusted/uv")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("frozen hash-pinned dependency export")
    wheel = tmp_path / "baseline.whl"
    wheel.write_bytes(b"synthetic wheel; not installed by this test")
    sources = {
        side: {"wheel_sha256": runner.inert.digest(wheel)} for side in ("a", "b")
    }
    if fault == "wheel":
        wheel.write_bytes(b"modified after source receipt")
    reference = dict(
        python="frozen Python",
        dependencies=[["dependency", "1"]],
        entries={"entry": "target"},
    )
    output = tmp_path / "output"
    output.mkdir()
    report = {}
    path = output / "report.json"
    calls = []

    def capture(argv, *, cwd, env, timeout):
        assert argv[:4] == ["/trusted/uv", "--no-config", "--offline", "--cache-dir"]
        assert timeout == 120 and cwd.parent == output
        assert Path(env["HOME"]).is_relative_to(cwd)
        assert report["slot"]["busy"] is True
        calls.append(argv)
        if "venv" in argv:
            assert Path(argv[-1]) == Path(report["slot"]["prefix"])
            Path(argv[-1]).mkdir()
        else:
            assert argv[argv.index("--python") + 1] == str(
                Path(report["slot"]["prefix"]) / "bin/python"
            )
            assert "--no-deps" in argv
        if fault == "requirements":
            requirements.write_text("modified while installer ran")
        return dict(
            exit_code=1 if fault == "installer-exit" else 0,
            failure="observer_cleanup_required" if fault == "owner-cleanup" else None,
            stdout="",
            stderr="normal uv diagnostics",
        )

    def verify(prefix, pinned, control, expected_hash):
        assert prefix == Path(report["slot"]["prefix"])
        assert pinned == wheel and expected_hash == sources["a"]["wheel_sha256"]
        if fault == "verification":
            return {**reference, "python": "wrong interpreter"}
        return dict(reference)

    monkeypatch.setattr(runner.inert, "capture", capture)
    monkeypatch.setattr(runner.inert, "verify_pinned_install", verify)
    if fault:
        with pytest.raises(ValueError):
            runner.provision_slot(
                requirements,
                dict.fromkeys(("a", "b"), wheel),
                sources,
                reference,
                output,
                report,
                path,
            )
        assert len(report["slot_builds"]) == 1
        assert report["slot_builds"][0]["status"] == "failed"
        assert report["slot"]["failed"]
        assert len(calls) <= 3
    else:
        slot = runner.provision_slot(
            requirements,
            dict.fromkeys(("a", "b"), wheel),
            sources,
            reference,
            output,
            report,
            path,
        )
        assert len(calls) == 6
        assert all(item["status"] == "complete" for item in report["slot_builds"])
        assert slot.receipt["active"] is None and not slot.prefix.exists()
        assert all((slot.root / side).is_dir() for side in ("a", "b"))


@pytest.mark.parametrize(
    "fault", [None, "setup-status", "setup-order", "overlap", "file-path", "file-hash"]
)
def test_recovery_receipt_requires_settled_setup_before_measured_spawn(tmp_path, fault):
    value = observation(tmp_path, tmp_path)
    value["case"] = "recovery-cwd"
    value["milestones"]["history_visible_seconds"] = 4.0
    value["seed"] = {
        "scope": "cwd",
        "history": "G17 canonical history recovered in cwd",
        "session_count": 1,
        "shape": {"record_revision": 5},
        "files": {"cwd/session.jsonl": "a" * 64},
    }
    value["spawns"][0].update(
        start=5.0, argv=[str(tmp_path / "bin/loushang-hosted-tui")]
    )
    value["seed_setup"] = [
        {
            "status": "settled",
            "spawns": [{**value["spawns"][0], "start": start}],
            "settled_at": start + 1,
        }
        for start in (1.0, 3.0)
    ]
    if fault == "setup-status":
        value["seed_setup"][0]["status"] = "running"
    elif fault == "setup-order":
        value["seed_setup"].reverse()
    elif fault == "overlap":
        value["spawns"][0]["start"] = 3.5
    elif fault == "file-path":
        value["seed"]["files"] = {"../foreign": "a" * 64}
    elif fault == "file-hash":
        value["seed"]["files"]["cwd/session.jsonl"] = "bad"
    if fault:
        with pytest.raises(ValueError):
            runner.validate_observation(
                value, "recovery-cwd", tmp_path, tmp_path, tmp_path
            )
    else:
        runner.validate_observation(value, "recovery-cwd", tmp_path, tmp_path, tmp_path)


def test_measured_entry_selection_does_not_change_observer_interpreter(tmp_path):
    import sys

    from tests.coding import _g18_native_probe as probe

    before = sys.executable
    hosted = probe.test_hosted_subprocess._installed_command
    mux = probe.test_mux_product_terminal._installed
    with probe.measured_entries(tmp_path):
        assert probe.test_hosted_subprocess._installed_command() == str(
            tmp_path / "bin/loushang-hosted"
        )
        assert probe.test_mux_product_terminal._installed() == str(
            tmp_path / "bin/loushang-mux"
        )
        assert probe._child.__wrapped__.__globals__["_installed_command"]() == str(
            tmp_path / "bin/loushang-hosted"
        )
        assert probe._product.__wrapped__.__globals__["_installed"]() == str(
            tmp_path / "bin/loushang-mux"
        )
        assert sys.executable == before
        assert probe.test_mux_product_terminal.sys.executable == str(
            tmp_path / "bin/python"
        )
    assert probe.test_hosted_subprocess._installed_command is hosted
    assert probe.test_mux_product_terminal._installed is mux


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "missing-tool",
        "wrong-server",
        "spawn_through_first_model_seconds",
        "review_detach_settlement_seconds",
        "dev_detach_settlement_seconds",
        "reattach_detach_settlement_seconds",
    ],
)
def test_product_first_use_receipt_requires_distinct_milestones_and_transport(
    tmp_path, fault
):
    value = observation(tmp_path, tmp_path)
    value["case"] = "product-first-use"
    value["milestones"] = dict.fromkeys(
        (
            "server_ready_seconds",
            "review_attach_frame_seconds",
            "dev_attach_frame_seconds",
            "reattach_frame_seconds",
            "first_model_seconds",
            "spawn_through_first_model_seconds",
            "first_approval_seconds",
            "first_tool_seconds",
            "interrupt_seconds",
            "review_detach_settlement_seconds",
            "dev_detach_settlement_seconds",
            "reattach_detach_settlement_seconds",
            "settlement_seconds",
        ),
        1.0,
    )
    value["spawns"] = [
        {
            **value["spawns"][0],
            "argv": [
                str(tmp_path / "bin/python"),
                str(runner.PROBE.with_name("_local_product_child.py")),
            ],
        }
    ] + [
        {
            **value["spawns"][0],
            "pid": 124 + i,
            "argv": [str(tmp_path / "bin/loushang-mux"), "attach", name],
        }
        for i, name in enumerate(("review", "dev", "dev"))
    ]
    if fault == "missing-tool":
        del value["milestones"]["first_tool_seconds"]
    elif fault == "wrong-server":
        value["spawns"][0]["argv"][1] = "/not-the-product-transport.py"
    elif fault:
        del value["milestones"][fault]
    if fault:
        with pytest.raises(ValueError):
            runner.validate_observation(
                value, "product-first-use", tmp_path, tmp_path, tmp_path
            )
    else:
        runner.validate_observation(
            value, "product-first-use", tmp_path, tmp_path, tmp_path
        )


@pytest.mark.parametrize("create_delay", [0, 10])
def test_local_mux_cumulative_metric_includes_create_without_changing_actions(
    tmp_path, monkeypatch, create_delay
):
    from contextlib import contextmanager

    from tests.coding import _g18_native_probe as probe

    clock = [1.0]
    commands, writes = [], []
    monkeypatch.setattr(probe.time, "perf_counter", lambda: clock[0])

    class Process:
        def poll(self):
            return None

        def wait(self, *, timeout):
            clock[0] += 1
            return 0

        def write(self, text):
            writes.append(text)
            clock[0] += 1

    @contextmanager
    def product(root, *, installed):
        assert installed is True
        clock[0] += 1
        yield Process(), {}
        clock[0] += 1

    @contextmanager
    def terminal(*args, **kwargs):
        yield Process(), None, None
        clock[0] += 1

    @contextmanager
    def spawn(executable):
        yield {"start": clock[0]}

    def see(*args, **kwargs):
        clock[0] += 1

    def command(root, environment, *args):
        commands.append(args)
        clock[0] += 1 + (create_delay if args[0] == "create" else 0)
        return {"muxes": [{"members": 1}]}

    monkeypatch.setattr(probe, "_product", product)
    monkeypatch.setattr(probe, "_command", command)
    monkeypatch.setattr(probe, "_see", see)
    monkeypatch.setattr(probe, "observed_terminal", terminal)
    monkeypatch.setattr(probe, "observe_spawn", spawn)
    monkeypatch.setattr(probe, "assert_active_terminal", lambda *_: None)
    report = {"measured_prefix": str(tmp_path), "spawns": [], "milestones": {}}
    probe.local_mux(tmp_path, report)
    values = report["milestones"]
    assert values["spawn_through_first_command_seconds"] == 5 + create_delay
    assert values["first_command_seconds"] == 2
    assert values["detach_settlement_seconds"] == values["stop_settlement_seconds"] == 3
    assert commands == [("create", "g18"), ("list",), ("stop",)]
    assert writes == ["/new user_home G18 member\r", "\x02d"]


@pytest.mark.parametrize("failed_witness", [None, "APPROVED_PREVIEW_EXECUTED", "*1 |"])
@pytest.mark.parametrize("delayed_phase", [None, "new", "review", "dev", "reattach"])
def test_product_adapter_reuses_workflow_and_records_only_completed_first_witnesses(
    tmp_path, monkeypatch, failed_witness, delayed_phase
):
    import time
    from contextlib import contextmanager

    from tests.coding import _g18_native_probe as probe

    fixture = probe.test_mux_product_terminal
    launches, marked, writes = [], [], []
    pending_spawns = []
    clock = [1.0]
    terminals = []
    monkeypatch.setattr(probe.time, "perf_counter", lambda: clock[0])
    report = {
        "measured_prefix": str(tmp_path / "measured"),
        "spawns": [],
        "milestones": {},
    }

    class Driver:
        raw_output = ""
        diagnostics = None
        waited = False

        def write(self, text):
            writes.append(text)
            clock[0] += 1 + (
                10 if delayed_phase == "new" and text.startswith("/new") else 0
            )

        def is_alive(self):
            return True

        def wait(self, *, timeout):
            self.waited = True
            clock[0] += 1
            return 0

    class Server:
        def poll(self):
            return None

        def wait(self, *, timeout):
            clock[0] += 1
            return 0

    @contextmanager
    def product(root, *, discovery):
        assert discovery is True
        pending_spawns[-1]["start"] = time.perf_counter()
        clock[0] += 1
        yield Server(), {}
        clock[0] += 1

    @contextmanager
    def terminal(*args, **kwargs):
        pending_spawns[-1]["start"] = time.perf_counter()
        driver = Driver()
        name = ("review", "dev", "reattach")[len(terminals)]
        terminals.append(name)
        yield driver, None, None
        assert driver.waited
        clock[0] += 1 + (10 if delayed_phase == name else 0)

    @contextmanager
    def spawn(executable):
        launches.append(executable)
        # Real observe_spawn publishes only after Popen, not on context entry.
        receipt = {}
        pending_spawns.append(receipt)
        try:
            yield receipt
        finally:
            assert pending_spawns.pop() is receipt

    def see(driver, text, *, after=0):
        clock[0] += 1
        if text == failed_witness:
            raise TimeoutError("original witness failed")

    def command(root, environment, *args):
        clock[0] += 1
        return {"muxes": [{"name": name, "members": 1} for name in ("dev", "review")]}

    original_mark = probe.mark

    def mark(value, metric, start):
        marked.append(metric)
        original_mark(value, metric, start)

    monkeypatch.setattr(fixture, "_product", product)
    monkeypatch.setattr(fixture, "_command", command)
    monkeypatch.setattr(fixture, "_see", see)
    monkeypatch.setattr(probe, "observed_terminal", terminal)
    monkeypatch.setattr(probe, "observe_spawn", spawn)
    monkeypatch.setattr(probe, "assert_active_terminal", lambda *_: None)
    monkeypatch.setattr(probe, "mark", mark)
    if failed_witness:
        with pytest.raises(TimeoutError, match="original witness failed"):
            probe.product_first_use(tmp_path, report)
        missing = (
            "first_tool_seconds"
            if failed_witness == "APPROVED_PREVIEW_EXECUTED"
            else "interrupt_seconds"
        )
        assert missing not in report["milestones"]
        assert "settlement_seconds" not in report["milestones"]
    else:
        probe.product_first_use(tmp_path, report)
        assert (
            launches
            == [str(tmp_path / "measured/bin/python")]
            + [str(tmp_path / "measured/bin/loushang-mux")] * 3
        )
        assert len(report["milestones"]) == 13
        values = report["milestones"]
        assert values["spawn_through_first_model_seconds"] == 11 + (
            20 if delayed_phase == "new" else 0
        )
        for name in ("review", "dev", "reattach"):
            assert values[name + "_detach_settlement_seconds"] == 3 + (
                10 if delayed_phase == name else 0
            )
        # These original intervals cannot see the injected /new or detach delay.
        assert values["first_model_seconds"] == values["first_tool_seconds"] == 2
        assert values["settlement_seconds"] == 3
        assert (
            marked.count("first_model_seconds") == 1
        )  # Reattach replays the same text.
        assert all(value > 0 for value in report["milestones"].values())
        assert all(
            text in writes for text in ("hello\r", "approval\r", "/approve\r", "\x03")
        )


@pytest.mark.parametrize(
    "control",
    ["\x1bc", "\x1b_apc\x1b\\", "\x1b]1337;File=unsupported\x07", "\x08", "\x9b"],
)
def test_embedded_screen_projection_rejects_unknown_controls_instead_of_preserving_stale_main(
    control,
):
    from tests.coding._g18_native_probe import embedded_main_frame

    initial = "\x1b[?2026h› \r\nidle\x1b[?2026l"
    frame = "\x1b[?2026h" + control + "\x1b[?2026l"
    with pytest.raises(ValueError, match="unsupported Embedded"):
        embedded_main_frame(initial + frame, after=len(initial))
