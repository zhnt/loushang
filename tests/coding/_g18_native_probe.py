"""Linux G18 observations in the existing retained evidence Python wrapper.

Only test-side Popen/PTY observation and a scoped G14 child watcher are added.
Product argv, runtime deadlines,
Host lifetime owners remain the existing G14/G16/G17 fixtures. Embedded ready
also requires the session status bar: the screen-first welcome is not readiness.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from contextlib import closing, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# The installed interpreter resolves Product modules from its wheel. Only test
# support is admitted from the checkout; never put checkout/src on sys.path.
ROOT = Path(__file__).resolve().parents[2]
FAILURE_TREE_DIAGNOSTIC = False
sys.path.insert(0, str(ROOT))
if __name__ == "__main__":
    if len(sys.argv) not in (6, 7) or (
        len(sys.argv) == 7
        and (sys.argv[6] != "--failure-tree" or sys.argv[2] != "prepare:recovery-cwd")
    ):
        raise SystemExit("invalid native observer diagnostic arguments")
    FAILURE_TREE_DIAGNOSTIC = len(sys.argv) == 7
    # -I deliberately ignores PYTHONPYCACHEPREFIX. Only the observer uses this
    # fixed cache; the measured commands inherit their own explicit environment.
    sys.pycache_prefix = str(Path(sys.argv[5]))

from loushang.tui.cell_width import strip_control_sequences  # noqa: E402
from loushang.tui.terminal import (  # noqa: E402
    FakeScreen,
    TerminalOperation,
    TerminalSize,
)
from scripts.dev.measure_g18_startup import (  # noqa: E402
    fingerprint_tree,
    private_environment,
)
from tests.coding import test_hosted_subprocess, test_mux_product_terminal  # noqa: E402
from tests.coding._hosted_terminal import (  # noqa: E402
    foreground_terminal,
    process_table,
)
from tests.coding.test_hosted_client import _argv  # noqa: E402
from tests.coding.test_hosted_client_terminal import (  # noqa: E402
    _picker_resume,
    _picker_workflow,
)
from tests.coding.test_hosted_entry_evidence import _guarded  # noqa: E402
from tests.coding.test_hosted_subprocess import _child  # noqa: E402
from tests.coding.test_mux_command import _selector  # noqa: E402
from tests.coding.test_mux_product_terminal import (  # noqa: E402
    _command,
    _product,
    _see,
)
from tests.coding.test_mux_terminal_process import _terminal_environment  # noqa: E402
from tests.tui.terminal_process_support.environment import (  # noqa: E402
    terminal_test_environment,
)

CASES = (
    "embedded",
    "foreground",
    "local-mux",
    "g14-stdio",
    "recovery-cwd",
    "recovery-global",
    "product-first-use",
)


def publish(path, value):
    pending = path.with_suffix(".next")
    pending.write_text(json.dumps(value, indent=2) + "\n")
    pending.replace(path)


@contextmanager
def observe_spawn(executable):
    """Timestamp immediately before the actual Product Popen, not fixture setup."""
    original = subprocess.Popen
    observation = {}

    def spawn(argv, *args, **kwargs):
        if str(argv[0]) == str(executable) and not observation:
            observation.update(
                start=time.perf_counter(),
                argv=list(map(str, argv)),
                cwd=str(Path(kwargs.get("cwd", Path.cwd())).resolve()),
            )
            process = original(argv, *args, **kwargs)
            observation["pid"] = process.pid
            return process
        return original(argv, *args, **kwargs)

    with patch.object(subprocess, "Popen", spawn):
        yield observation
    assert "pid" in observation, "the intended real Product was not observed"


def failure_process_snapshot(pid, *, proc=Path("/proc")):
    """Failure-only, bounded Linux counters; no argv, environment or user data."""
    result = {}
    for name in ("stat", "status", "wchan", "io", "schedstat"):
        try:
            with (proc / str(pid) / name).open() as stream:
                result[name] = stream.read(8192)
        except OSError as error:
            result[name] = type(error).__name__
    for name in ("cpu", "io", "memory"):
        try:
            with (proc / "pressure" / name).open() as stream:
                result["pressure_" + name] = stream.read(1024)
        except OSError as error:
            result["pressure_" + name] = type(error).__name__
    return result


def _stat_identity(value):
    fields = value.rsplit(") ", 1)[1].split()
    return int(fields[1]), int(fields[19])  # PPID, starttime; comm may contain spaces.


def diagnostic_identity(pid, *, proc=Path("/proc")):
    try:
        with (proc / str(pid) / "stat").open() as stream:
            return _stat_identity(stream.read(4096))[1]
    except (OSError, ValueError, IndexError):
        return None


def failure_tree_snapshot(pid, starttime, *, proc=Path("/proc"), clock=time.monotonic):
    """Diagnostic-only non-atomic counters, never process adoption or signalling."""
    result = {"complete": True, "processes": [], "issues": []}
    deadline, remaining = clock() + 1, 256 * 1024

    def issue(reason):
        result["complete"] = False
        if reason not in result["issues"]:
            result["issues"].append(reason)

    def available():
        if remaining <= 0 or clock() >= deadline:
            issue("budget_exhausted")
            return False
        return True

    def read(path):
        nonlocal remaining
        if not available():
            return "<budget_exhausted>"
        try:
            with path.open("rb") as stream:
                value = stream.read(min(4096, remaining))
            remaining -= len(value)
            if len(value) == 4096:
                issue("read_truncated")
            return value.decode("utf-8", errors="replace")
        except OSError as error:
            issue(type(error).__name__)
            return f"<{type(error).__name__}>"

    def identity(path):
        try:
            return _stat_identity(read(path / "stat"))
        except (ValueError, IndexError):
            issue("identity_unavailable")
            return None

    def chain_valid(chain):
        for index, (ancestor, expected) in enumerate(chain):
            value = identity(proc / str(ancestor))
            if (
                value is None
                or value[1] != expected
                or (index and value[0] != chain[index - 1][0])
            ):
                issue("identity_or_parent_changed")
                return False
        return True

    if starttime is None:
        issue("root_identity_unavailable")
        return result
    pending, seen = [[(pid, starttime)]], {pid}
    while pending and available():
        chain = pending.pop(0)
        current, expected = chain[-1]
        if not chain_valid(chain):
            continue
        base = proc / str(current)
        entry = {"pid": current, "starttime": expected, "usable": False, "threads": []}
        result["processes"].append(entry)
        for name in ("status", "wchan", "schedstat", "io"):
            entry[name] = read(base / name)
        children = set()
        try:
            with os.scandir(base / "task") as tasks:
                for count, task in enumerate(tasks):
                    if count >= 8 or not available():
                        issue("thread_enumeration_truncated")
                        break
                    if not task.name.isdigit():
                        issue("invalid_thread_entry")
                        continue
                    thread = Path(task.path)
                    before = identity(thread)
                    item = {"tid": int(task.name), "usable": False}
                    entry["threads"].append(item)
                    if before is None:
                        continue
                    item["starttime"] = before[1]
                    for name in ("wchan", "schedstat", "stack"):
                        item[name] = read(thread / name)
                    candidates = read(thread / "children").split()
                    if before == identity(thread):
                        item["usable"] = True
                        for child in candidates:
                            if not child.isdigit():
                                issue("invalid_child_entry")
                                continue
                            if len(children) >= 8:
                                issue("child_enumeration_truncated")
                                break
                            children.add(int(child))
                    else:
                        issue("thread_identity_changed")
        except OSError as error:
            issue(type(error).__name__)
        entry["usable"] = chain_valid(chain)
        if not entry["usable"]:
            continue
        for child in sorted(children):
            if child in seen:
                continue
            if len(seen) >= 8 or not available():
                issue("process_enumeration_truncated")
                break
            seen.add(child)
            child_identity = identity(proc / str(child))
            if child_identity is None or child_identity[0] != current:
                issue("child_relationship_changed")
                continue
            pending.append([*chain, (child, child_identity[1])])
    if pending:
        issue("process_enumeration_truncated")
    if not chain_valid([(pid, starttime)]):
        for entry in result["processes"]:
            entry["usable"] = False
    if len(json.dumps(result).encode()) > 256 * 1024:
        return {"complete": False, "processes": [], "issues": ["serialized_size_limit"]}
    return result


@contextmanager
def observed_terminal(argv, root, environment, *, failure_report=None):
    import pty
    import termios

    openpty = pty.openpty
    terminals = []

    def open_observed():
        master, slave = openpty()
        terminals.append((master, termios.tcgetattr(slave)))
        return master, slave

    with (
        patch.object(pty, "openpty", open_observed),
        foreground_terminal(
            argv,
            cwd=root,
            env=environment,
            columns=100,
            rows=30,
        ) as driver,
    ):
        ((master, original),) = terminals
        pinned = (
            diagnostic_identity(driver.diagnostics.pid)
            if FAILURE_TREE_DIAGNOSTIC
            else None
        )
        try:
            yield driver, master, original
        except BaseException as error:
            if failure_report is not None:
                try:
                    failure_report["failure_process"] = failure_process_snapshot(
                        driver.diagnostics.pid
                    )
                    if FAILURE_TREE_DIAGNOSTIC:
                        failure_report["failure_tree"] = failure_tree_snapshot(
                            driver.diagnostics.pid, pinned
                        )
                except BaseException as diagnostic_error:
                    error.add_note(
                        f"failure diagnostics unavailable: {type(diagnostic_error).__name__}"
                    )
            raise
        assert not driver.is_alive()
        assert termios.tcgetattr(master) == original, "terminal modes not restored"
        assert driver.diagnostics.termination is None, (
            "fixture fallback is not normal success"
        )
    assert not driver.diagnostics.reader_alive, "native reader did not settle"
    assert driver.diagnostics.termination is None


def mark(report, name, started):
    report["milestones"][name] = time.perf_counter() - started


def assert_active_terminal(master, original):
    import termios

    active = termios.tcgetattr(master)
    assert active != original and not active[3] & (termios.ECHO | termios.ICANON)


def embedded_main_frame(output, *, after):
    """Replay a completed real frame with the existing terminal test model.

    A stale/background panel redraw is not a close acknowledgement. This heavier
    witness is outside first-command timing; no Product renderer is substituted.
    """
    end = output.rfind("\x1b[?2026l")
    if end < after:
        return False
    screen = _replay_embedded_output(output[:end])
    visible = "\n".join(screen.visible_lines)
    return (
        "›" in visible
        and "idle" in visible
        and "Hotkeys" not in visible
        and "Enter/Esc to close" not in visible
    )


def _replay_embedded_output(output):
    # FakeScreen consumes structured cursor operations, not raw cursor CSI.
    # Adapt only the sequences emitted by this existing inline terminal fixture;
    # reject unsupported screen mutations instead of inventing a successful view.
    screen = FakeScreen.empty(TerminalSize(columns=100, rows=30))
    tokens = re.split(
        r"(\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\))", output
    )
    for token in tokens:
        if not token:
            continue
        if token.startswith("\x1b]"):
            if not token[2:].startswith(("0;", "2;", "8;", "9;4;")):
                raise ValueError("unsupported Embedded OSC screen sequence")
            continue  # Only known title/hyperlink/progress operations.
        if token in {"\x1b[?u", "\x1b[16t", "\x1b[>4;2m", "\x1b[>4;0m"}:
            continue  # Existing queries / keyboard modes never draw cells.
        if not token.startswith("\x1b[") or token.endswith("m"):
            if not token.startswith("\x1b[") and any(
                (ord(char) < 32 and char not in "\r\n") or 127 <= ord(char) <= 159
                for char in token
            ):
                raise ValueError("unsupported Embedded screen control")
            operation = TerminalOperation("write", text=token)
        else:
            body, final = token[2:-1], token[-1]
            if final in "hl" and body in {"?25", "?2004", "?1004", "?2026"}:
                continue
            if final in "nc":
                continue  # Query response remains the real driver's concern.
            values = [int(value or "1") for value in body.split(";")]
            amount = values[0]
            if final in "Hf":
                operation = TerminalOperation(
                    "move_cursor",
                    row=amount - 1,
                    column=(values[1] if len(values) > 1 else 1) - 1,
                )
            elif final in "AB":
                operation = TerminalOperation(
                    "move_relative", lines=amount * (-1 if final == "A" else 1)
                )
            elif final == "G":
                operation = TerminalOperation("move_column", column=amount - 1)
            elif final in "CD":
                operation = TerminalOperation(
                    "move_column",
                    column=screen.cursor_column + amount * (1 if final == "C" else -1),
                )
            elif final == "K" and body == "2":
                operation = TerminalOperation("clear_line")
            elif final == "J" and body in {"", "0", "2", "3"}:
                operation = TerminalOperation(
                    {
                        "": "clear_from_cursor",
                        "0": "clear_from_cursor",
                        "2": "clear_screen",
                        "3": "clear_scrollback",
                    }[body]
                )
            else:
                raise ValueError(f"unsupported Embedded screen sequence: {token!r}")
        screen = screen.apply((operation,))
    return screen


def ready(driver, embedded=False):
    driver.read_until(
        lambda out: (
            (
                "Welcome to Loushang CLI" in strip_control_sequences(out)
                and "perm=" in strip_control_sequences(out)
                and "\x1b[?2004h" in out
                and "\x1b[?1004h" in out
            )
            if embedded
            else "/exit ends app" in strip_control_sequences(out)
        ),
        timeout=35,
    )


def foreground(
    root,
    report,
    *,
    embedded=False,
    arguments=None,
    interaction=None,
    first_use=True,
    exit_command=None,
    environment=None,
    interaction_milestone="history_visible_seconds",
):
    executable = str(
        Path(report["measured_prefix"])
        / "bin"
        / ("loushang" if embedded else "loushang-hosted-tui")
    )
    argv = [executable, *(["--tui"] if embedded else arguments or _argv(root))]
    with observe_spawn(executable) as spawn:
        report["spawns"].append(spawn)
        with observed_terminal(
            argv,
            root,
            _terminal_environment(root) if environment is None else environment,
            failure_report=report,
        ) as (
            driver,
            master,
            original,
        ):
            ready(driver, embedded)
            mark(report, "ready_frame_seconds", spawn["start"])
            assert_active_terminal(master, original)
            children = [
                pid
                for pid, entry in process_table().items()
                if entry[0] == spawn["pid"]
            ]
            if not embedded:
                assert children, "foreground must own a real Hosted child"
                assert all(
                    os.getpgid(pid) != os.getpgid(spawn["pid"]) for pid in children
                )
            if interaction is not None:
                interaction(driver)
                mark(report, interaction_milestone, spawn["start"])
            if first_use:
                checkpoint = len(driver.raw_output)
                first = time.perf_counter()
                if embedded:
                    driver.write("/hotkeys\r")
                    driver.read_until(
                        lambda out: (
                            "Hotkeys:" in strip_control_sequences(out[checkpoint:])
                            and "Enter/Esc to close" in out[checkpoint:]
                            and out.rfind("\x1b[?2026l")
                            > out.rfind("Enter/Esc to close")
                        ),
                        timeout=30,
                    )
                    first_finished = time.perf_counter()
                    closed = len(driver.raw_output)
                    driver.write("\r")  # Local panel's documented close action.
                    driver.read_until(
                        lambda out: embedded_main_frame(out, after=closed), timeout=10
                    )
                    mark(report, "panel_close_observation_seconds", first_finished)
                elif interaction is None:
                    driver.write("/new cwd G18 member\r")
                    _see(driver, "*1", after=checkpoint)
                    first_finished = time.perf_counter()
                else:
                    scope = "global" if report["case"] == "recovery-global" else "cwd"
                    driver.write(f"/sessions {scope}\r")
                    _see(driver, "select a saved Session", after=checkpoint)
                    first_finished = time.perf_counter()
                    # Ctrl+B,d is a shell-global action before picker routing.
                    # Exit from the completed picker directly; a preceding bare
                    # Esc could merge with Ctrl+B into a different key event.
                    assert exit_command == "\x02d"
                report["milestones"]["first_command_seconds"] = first_finished - first
                report["milestones"]["spawn_through_first_command_seconds"] = (
                    first_finished - spawn["start"]
                )
            exit_started = time.perf_counter()
            driver.write(exit_command or ("/quit\r" if embedded else "/exit\r"))
            assert driver.wait(timeout=25) == 0, driver.diagnostics
            assert all(pid not in process_table() for pid in children), (
                "child/zombie remains"
            )
        mark(report, "settlement_seconds", exit_started)


def home_isolation(root, report):
    """Four actual launches: sensitivity and protected HOME for each entry.

    This is a correctness control, not a timing sample or file-access monitor.
    The wrapper's ambient HOME is synthetic; no real user input is touched.
    """
    ambient = root.parent / "ambient-home"
    assert Path.home() == ambient and os.environ["USERPROFILE"] == str(ambient)
    poison = ambient / ".loushang/models/g18-poison.json"
    before = fingerprint_tree(ambient)
    assert poison.read_bytes() == b"{"
    parent_environment = dict(os.environ)
    prefix = Path(report["measured_prefix"])
    # The collector owns this per-installation cache under its output directory.
    # Keep each correctness control separate without filling the temporary
    # filesystem with disposable bytecode; HOME/state/cwd remain fresh/private.
    bytecode = Path(parent_environment["PYTHONPYCACHEPREFIX"])
    assert bytecode.is_absolute()
    report["isolation"] = {"ambient_before": before, "controls": []}
    for case in ("embedded", "foreground"):
        for isolated in (False, True):
            control_root = root / f"{case}-{'private' if isolated else 'leaked'}"
            workspace = control_root / "workspace"
            workspace.mkdir(parents=True, mode=0o700)
            environment = private_environment(
                control_root / "environment", prefix, bytecode / control_root.name
            )
            environment = {
                key: value
                for key, value in terminal_test_environment(
                    ROOT, base=environment
                ).items()
                if key.casefold() not in {"pythonpath", "pythonhome"}
            }
            environment.update(COLUMNS="100", LINES="30")
            if not isolated:
                environment.update(HOME=str(ambient), USERPROFILE=str(ambient))
            control = {
                "case": case,
                "isolated": isolated,
                "status": "running",
                "measured_prefix": str(prefix),
                "spawns": [],
                "milestones": {},
            }
            report["isolation"]["controls"].append(control)
            if case == "embedded" and not isolated:
                executable = str(prefix / "bin/loushang")
                with observe_spawn(executable) as spawn:
                    control["spawns"].append(spawn)
                    with observed_terminal(
                        [executable, "--tui"],
                        workspace,
                        environment,
                        failure_report=control,
                    ) as (driver, _, __):
                        code = driver.wait(timeout=35)
                        assert code is not None and code > 0, driver.diagnostics
                    # Process exit alone is not final-output evidence. The
                    # context also settles the PTY reader before we inspect it.
                    output = strip_control_sequences(driver.raw_output)
                    assert (
                        str(poison) in output
                        and "models registry file has invalid JSON" in output
                    )
                    assert "Welcome to Loushang CLI" not in output
                    control["exit_code"] = code
                    mark(control, "rejected_exit_seconds", spawn["start"])
                control["witness"] = "poison-invalid-json"
            else:
                views = []

                def interaction(driver, isolated=isolated, views=views):
                    checkpoint = len(driver.raw_output)
                    views.append((driver, checkpoint))
                    driver.write("/new cwd G18 isolation\r")
                    _see(
                        driver,
                        "*1" if isolated else "session_unavailable",
                        after=checkpoint,
                    )
                    output = strip_control_sequences(driver.raw_output[checkpoint:])
                    assert (
                        ("session_unavailable" not in output)
                        if isolated
                        else ("*1" not in output)
                    )

                foreground(
                    workspace,
                    control,
                    embedded=case == "embedded",
                    interaction=interaction if case == "foreground" else None,
                    first_use=False,
                    environment=environment,
                    interaction_milestone="control_witness_seconds",
                )
                if case == "foreground":
                    ((driver, checkpoint),) = views
                    final_output = strip_control_sequences(
                        driver.raw_output[checkpoint:]
                    )
                    assert (
                        "session_unavailable" if isolated else "*1"
                    ) not in final_output, (
                        "opposite outcome appeared before reader settlement"
                    )
                control["exit_code"] = 0
                control["witness"] = (
                    "ready-exited"
                    if case == "embedded"
                    else "member-opened"
                    if isolated
                    else "session-unavailable"
                )
            control["status"] = "settled"
            report["spawns"].extend(control["spawns"])
    after = fingerprint_tree(ambient)
    assert after == before, "ambient HOME inventory or bytes changed"
    assert dict(os.environ) == parent_environment, "observer environment changed"
    report["isolation"].update(ambient_after=after, environment_unchanged=True)


def local_mux(root, report):
    executable = str(Path(report["measured_prefix"]) / "bin/loushang-mux")
    with observe_spawn(executable) as server_spawn:
        report["spawns"].append(server_spawn)
        with _product(root, installed=True) as (server, environment):
            mark(report, "server_ready_seconds", server_spawn["start"])
            _command(root, environment, "create", "g18")
            with observe_spawn(executable) as attach_spawn:
                report["spawns"].append(attach_spawn)
                with observed_terminal(
                    [executable, *_selector(root), "attach", "g18"],
                    root,
                    environment,
                    failure_report=report,
                ) as (driver, master, original):
                    _see(driver, "g18 |")
                    mark(report, "attach_frame_seconds", attach_spawn["start"])
                    assert_active_terminal(master, original)
                    first = time.perf_counter()
                    driver.write("/new user_home G18 member\r")
                    _see(driver, "*1")
                    mark(report, "first_command_seconds", first)
                    mark(
                        report,
                        "spawn_through_first_command_seconds",
                        server_spawn["start"],
                    )
                    detach = time.perf_counter()
                    driver.write("\x02d")
                    assert driver.wait(timeout=15) == 0, driver.diagnostics
                mark(report, "detach_settlement_seconds", detach)
            assert server.poll() is None, "local detach must preserve server"
            listed = _command(root, environment, "list")
            assert listed["muxes"][0]["members"] == 1
            stop = time.perf_counter()
            _command(root, environment, "stop")
            assert server.wait(timeout=20) == 0
        mark(report, "stop_settlement_seconds", stop)


@contextmanager
def stdio_observer_scope():
    """Own only this pinned Linux observer's asyncio child notification backend.

    The complete asyncio.run() must stay inside this scope. ThreadedChildWatcher
    can notify process.wait() before its waiter thread exits; SafeChildWatcher
    dispatches registered-PID notifications on the loop itself. Neither closing
    this watcher nor restoring the policy proves Product cleanup: the original
    fixture and retained process owner still make that decision.
    """
    if (
        sys.platform != "linux"
        or sys.implementation.name != "cpython"
        or sys.version_info[:2] != (3, 11)
        or threading.current_thread() is not threading.main_thread()
    ):
        raise RuntimeError("G14 observer requires Linux CPython 3.11 main thread")
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("G14 observer requires a fresh synchronous scope")
    previous_signal = signal.getsignal(signal.SIGCHLD)
    if previous_signal != signal.SIG_DFL:
        raise RuntimeError("G14 observer requires default SIGCHLD ownership")
    previous_policy = asyncio.get_event_loop_policy()
    policy = asyncio.DefaultEventLoopPolicy()
    watcher = asyncio.SafeChildWatcher()
    try:
        # Prevent an implicit new loop during failure cleanup. If Runner setup
        # fails after assigning a loop, that loop remains owned by this policy.
        policy.set_event_loop(None)
        policy.set_child_watcher(watcher)
        asyncio.set_event_loop_policy(policy)
        yield {
            "backend": "cpython311-safe-child-watcher-v1",
            "watcher": f"{type(watcher).__module__}.{type(watcher).__qualname__}",
            "python": sys.version,
        }
    finally:
        try:
            watcher.close()
        finally:
            try:
                try:
                    unfinished_loop = policy.get_event_loop()
                except RuntimeError:
                    unfinished_loop = None
                if unfinished_loop is not None:
                    unfinished_loop.close()
            finally:
                try:
                    asyncio.set_event_loop_policy(previous_policy)
                finally:
                    signal.signal(signal.SIGCHLD, previous_signal)


async def stdio(root, report):
    executable = str(Path(report["measured_prefix"]) / "bin/loushang-hosted")
    with observe_spawn(executable) as spawn:
        report["spawns"].append(spawn)
        async with _child(root, installed=True) as client:
            mark(report, "protocol_ready_seconds", spawn["start"])
            first = time.perf_counter()
            assert not (await client.list_muxes()).mux_spaces
            mark(report, "first_command_seconds", first)
            close = time.perf_counter()
        mark(report, "settlement_seconds", close)


def product_first_use(root, report):
    """Observe the original G17 discovery Product workflow, synthetic transport only.

    The server is the existing test transport composition, not a shipped-console
    startup claim. Every terminal and protocol operation remains the real fixture.
    """
    fixture = test_mux_product_terminal
    product, see, command = fixture._product, fixture._see, fixture._command
    starts = {}
    prefix = Path(report["measured_prefix"])
    executable = str(prefix / "bin/loushang-mux")
    triggers = {
        "hello\r": "first_model_seconds",
        "approval\r": "first_approval_seconds",
        "/approve\r": "first_tool_seconds",
        "\x03": "interrupt_seconds",
    }
    witnesses = {
        "真实跨进程回复": "first_model_seconds",
        "*1!": "first_approval_seconds",
        "APPROVED_PREVIEW_EXECUTED": "first_tool_seconds",
        "*1 |": "interrupt_seconds",
    }

    class ObservedInput:
        def __init__(self, driver, detach_metric):
            self.driver = driver
            self.detach_metric = detach_metric

        def __getattr__(self, name):
            return getattr(self.driver, name)

        def write(self, text):
            if text in triggers:
                starts[triggers[text]] = time.perf_counter()
            if text == "\x02d":
                starts[self.detach_metric] = time.perf_counter()
            return self.driver.write(text)

    def observe_see(driver, text, *, after=0):
        see(driver, text, after=after)  # Original witness and deadline.
        metric = witnesses.get(text)
        if metric in starts and metric not in report["milestones"]:
            mark(report, metric, starts[metric])
            if metric == "first_model_seconds":
                mark(
                    report, "spawn_through_first_model_seconds", starts["server_spawn"]
                )

    @contextmanager
    def observe_product(workspace, **kwargs):
        with observe_spawn(str(prefix / "bin/python")) as spawn:
            report["spawns"].append(spawn)
            with product(workspace, **kwargs) as ready:
                starts["server_spawn"] = spawn["start"]
                mark(report, "server_ready_seconds", spawn["start"])
                yield ready

    attachment = 0

    @contextmanager
    def observe_terminal(workspace, environment, name):
        nonlocal attachment
        metric = (
            "review_attach_frame_seconds",
            "dev_attach_frame_seconds",
            "reattach_frame_seconds",
        )[attachment]
        detach_metric = (
            "review_detach_settlement_seconds",
            "dev_detach_settlement_seconds",
            "reattach_detach_settlement_seconds",
        )[attachment]
        attachment += 1
        with observe_spawn(executable) as spawn:
            report["spawns"].append(spawn)
            with observed_terminal(
                [executable, *_selector(workspace), "attach", name],
                workspace,
                environment,
                failure_report=report,
            ) as (driver, master, original):
                see(driver, name + " |")
                mark(report, metric, spawn["start"])
                assert_active_terminal(master, original)
                yield ObservedInput(driver, detach_metric)
            # Include the existing terminal context/reader settlement, not only
            # wait() or the later, independent server STOP.
            mark(report, detach_metric, starts[detach_metric])

    def observe_command(workspace, environment, *args):
        if args == ("stop",):
            starts["settlement_seconds"] = time.perf_counter()
        return command(workspace, environment, *args)

    with (
        patch.object(fixture, "_product", observe_product),
        patch.object(fixture, "_terminal", observe_terminal),
        patch.object(fixture, "_see", observe_see),
        patch.object(fixture, "_command", observe_command),
    ):
        fixture.test_G16_PRODUCT_TERMINAL_two_muxes_approval_detach_reattach_and_interrupt(
            root,
            lambda *_: None,
            discovery=True,
        )
    assert attachment == 3
    mark(report, "settlement_seconds", starts["settlement_seconds"])


def validate_recovery_seed(root, scope_name, *, opaque_input=False):
    """Read the exact G17 workload before CLI3, without opening a runtime/store.

    Volatile identifiers are checked as links, not compared across fresh roots.
    Reuse installed codecs and read-only index checks; never repair a seed here.
    """
    from loushang.ai.types import UserMessage
    from loushang.apphost import SessionCreateRequestV1
    from loushang.appservice.continuity import decode_application_continuity_record
    from loushang.coding.hosted_catalog import (
        CODING_HOSTED_COMPATIBILITY_ID,
        _create_identity,
    )
    from loushang.harness.conversation.stores.file import (
        _build_store_head,
        _encode_store_head,
    )
    from loushang.harness.journal import JsonlSnapshot
    from loushang.harness.transcript.jsonl_file import (
        _LOAD_INDEX_COMPATIBILITY_TOKEN,
        _STORE_HEAD_COMPATIBILITY_TOKEN,
        agent_transcript_journal,
        decode_agent_transcript_bytes,
    )
    from loushang.harness.transcript.model_input_v2_index_file import _build_manifest
    from tests.coding.test_hosted_client import _launch

    scope = next(
        item for item in _launch(root).scopes if item.scope.value == scope_name
    )
    files = {}
    directories = (
        (root,)
        if opaque_input
        else (
            root / "application",
            root / "cwd",
            root / "home",
            root / "session-assets",
        )
    )
    for directory in directories:
        assert not directory.is_symlink(), "symlink recovery root"
        for path in sorted(directory.rglob("*")):
            assert not path.is_symlink(), "symlink recovery input"
            if path.is_file():
                files[path] = path.read_bytes()
            else:
                assert path.is_dir(), "non-regular recovery input"
    sessions = [
        path
        for path in files
        if path.parent in {root / "cwd", root / "home"} and path.suffix == ".jsonl"
    ]
    assert len(sessions) == 1, "recovery needs exactly one canonical Session"
    (session_path,) = sessions
    assert session_path.parent == scope.session_dir, "wrong recovery scope"
    application = root / "application/coding.default.json"
    assert [
        path
        for path in files
        if path.parent == root / "application" and path.suffix == ".json"
    ] == [application], "unexpected application record inventory"
    record = decode_application_continuity_record(files[application])
    muxes = [[mux.name, mux.revision, len(mux.members)] for mux in record.mux_spaces]
    assert record.application_id == "coding.default" and record.product_id == "coding"
    assert record.record_revision == 5 and muxes == [
        ["main", 3, 0],
        ["picker", 2, 1],
    ], "recovery mux workload changed"
    (member,) = record.mux_spaces[1].members
    identity = member.session
    assert (
        member.position == 1 and member.title == f"Session {identity.session_id[:12]}"
    )
    assert (
        identity.scope == scope.scope
        and identity.scope_fingerprint == scope.fingerprint
    )
    assert session_path.name == f"hosted-{identity.session_id}.jsonl"
    raw = files[session_path]
    assert raw.endswith(b"\n"), "partial recovery transcript"
    header, records = decode_agent_transcript_bytes(raw, source_path=session_path)
    assert (
        header.conversation_id == identity.session_id
        and header.parent_conversation_id is None
    )
    assert header.metadata["cwd"] == str(root)
    hosted = dict(header.metadata["coding.hosted"])
    assert type(hosted["version"]) is int
    assert set(hosted) == {
        "version",
        "compatibilityId",
        "continuityId",
        "sessionId",
        "scope",
        "scopeFingerprint",
        "operationId",
    }
    assert hosted == {
        "version": 1,
        "compatibilityId": CODING_HOSTED_COMPATIBILITY_ID,
        "continuityId": identity.continuity_id,
        "sessionId": identity.session_id,
        "scope": scope_name,
        "scopeFingerprint": scope.fingerprint,
        "operationId": hosted["operationId"],
    }
    assert (
        _create_identity(
            SessionCreateRequestV1(
                "coding",
                scope.fingerprint,
                hosted["operationId"],
                requested_continuity_id=identity.continuity_id,
                requested_scope=scope.discovery_scope,
            )
        )
        == identity.session_id
    ), "canonical create identity mismatch"
    history = f"G17 canonical history recovered in {scope_name}"
    assert len(records) == 1, "recovery history workload changed"
    (message,) = records
    assert message.kind == "agent.message" and message.parent_id is None
    assert message.payload_version == 1 and not message.metadata
    assert len(raw.splitlines()) == 2, "unexpected transcript lines"
    assert isinstance(message.payload, UserMessage)
    assert message.payload.role == "user" and message.payload.content == history
    assert message.payload.timestamp == 1.0
    index_path = session_path.with_name(
        session_path.name + ".model-input-v2.index.json"
    )
    assert index_path in files, "warm restoration index missing"
    expected_index = _build_manifest(
        raw,
        JsonlSnapshot(header=header, records=tuple(records), diagnostics=()),
        compatibility_token=_LOAD_INDEX_COMPATIBILITY_TOKEN,
    )
    assert json.loads(files[index_path]) == expected_index, (
        "warm restoration index changed"
    )
    store_path = session_path.with_name(session_path.name + ".store.json")
    assert store_path in files, "canonical Store metadata missing"
    store = json.loads(files[store_path])
    assert set(store) == {"create_operation_id", "head"}
    assert store["head"] == _encode_store_head(
        _build_store_head(
            agent_transcript_journal(session_path),
            records,
            record_id=lambda item: item.record_id,
            compatibility_token=_STORE_HEAD_COMPATIBILITY_TOKEN,
        )
    ), "canonical Store head changed"
    assert (
        store["create_operation_id"]
        == f"create:{scope.session_dir}:{identity.session_id}"
    )
    allowed = {application, session_path, index_path, store_path}
    checked = (
        [
            path
            for path in files
            if path.parent in {root / "application", root / "cwd", root / "home"}
        ]
        if opaque_input
        else files
    )
    assert all(path in allowed or path.name.endswith(".lock") for path in checked), (
        "unexpected recovery input: "
        + repr(
            [
                str(path.relative_to(root))
                for path in checked
                if path not in allowed and not path.name.endswith(".lock")
            ]
        )
    )
    # Include all actual input bytes, including locks; IDs/mtime are never
    # treated as a cross-sample equality proof. Shape is the paired workload.
    metadata = json.loads(raw.splitlines()[0])["metadata"]
    metadata["cwd"] = "$workspace"
    metadata["coding.hosted"] = {
        **hosted,
        "continuityId": "$continuity",
        "sessionId": "$session",
        "scopeFingerprint": "$scope",
        "operationId": "$create-operation",
    }
    return {
        "scope": scope_name,
        "history": history,
        "session_count": 1,
        "shape": {
            "record_revision": record.record_revision,
            "muxes": muxes,
            "record_kinds": [item.kind for item in records],
            "record_payload_versions": [message.payload_version],
            "record_metadata": [{}],
            "history_timestamp": message.payload.timestamp,
            "restoration_index": "complete-current",
            "store_head": "complete-current",
            "session_directory_index": "absent",
            "header_version": header.version,
            "header_metadata": metadata,
            "asset_lock_count": sum(
                path.is_relative_to(root / "session-assets") for path in files
            ),
        },
        "files": {
            str(path.relative_to(root)): hashlib.sha256(data).hexdigest()
            for path, data in files.items()
        },
    }


def recovery(root, report, *, prepare_only=False):
    from loushang.appserver.protocol import SessionScopeV1

    scope = (
        SessionScopeV1.CWD
        if report["case"] == "recovery-cwd"
        else SessionScopeV1.USER_HOME
    )
    launches = 0

    def run_cli(workspace, arguments, interaction, *, exit_command):
        nonlocal launches
        launches += 1
        if launches < 3:
            # Existing G17 creator and explicit picker admission establish a
            # fresh one-Session seed. Both launches settle before measurement.
            unused = {
                "case": report["case"],
                "milestones": {},
                "spawns": [],
                "measured_prefix": report["measured_prefix"],
            }
            setup = {"status": "running", "spawns": unused["spawns"]}
            report["seed_setup"].append(setup)
            try:
                foreground(
                    workspace,
                    unused,
                    arguments=arguments,
                    interaction=interaction,
                    first_use=False,
                    exit_command=exit_command,
                )
            except BaseException:
                setup["failure_process"] = unused.get("failure_process")
                if "failure_tree" in unused:
                    setup["failure_tree"] = unused["failure_tree"]
                raise
            setup["status"] = "settled"
            setup["settled_at"] = time.perf_counter()
            return
        assert all(setup["status"] == "settled" for setup in report["seed_setup"])
        report["seed"] = validate_recovery_seed(
            root, scope.value, opaque_input=prepare_only
        )
        if prepare_only:
            return  # CLI3 belongs to a new retained owner after outer snapshot/reset.
        foreground(
            workspace,
            report,
            arguments=arguments,
            interaction=interaction,
            exit_command=exit_command,
        )

    _picker_workflow(root, scope, run_cli=run_cli)
    assert launches == 3


def restored_recovery(root, report):
    """Only CLI3; all input reset and source checks belong to the coordinator."""
    from loushang.appserver.protocol import SessionScopeV1

    scope = (
        SessionScopeV1.USER_HOME
        if report["case"] == "recovery-global"
        else SessionScopeV1.CWD
    )
    arguments = _argv(root)
    if scope is SessionScopeV1.USER_HOME:
        workspace = root / "other-workspace"
        assert workspace.is_dir(), (
            "global recovery execution workspace missing from seed"
        )
        arguments[1] = str(workspace)
    arguments.extend(["--mux", "picker"])
    history = f"G17 canonical history recovered in {scope.value}"
    foreground(
        root,
        report,
        arguments=arguments,
        interaction=lambda driver: _picker_resume(driver, history, scope, 1),
        exit_command="\x02d",
    )


@contextmanager
def measured_entries(prefix):
    """Select only test fixture launchers; never change observer sys.executable.

    Product imports, protocol clients and recovery codecs stay in the single
    fixed reference installation, independently of the measured console scripts.
    """
    with (
        patch.object(
            test_hosted_subprocess,
            "_installed_command",
            lambda: str(prefix / "bin/loushang-hosted"),
        ),
        patch.object(
            test_mux_product_terminal,
            "_installed",
            lambda: str(prefix / "bin/loushang-mux"),
        ),
        # This replaces a test module reference, not the interpreter's sys
        # object: its synthetic Product server must also use the measured wheel.
        patch.object(
            test_mux_product_terminal,
            "sys",
            SimpleNamespace(executable=str(prefix / "bin/python")),
        ),
    ):
        yield


def main(root, case, receipt, measured_prefix):
    stage = None
    if ":" in case:
        stage, case = case.split(":", 1)
        if stage not in {"prepare", "restored"} or case not in {
            "recovery-cwd",
            "recovery-global",
        }:
            raise ValueError("unsupported recovery stage")
    if sys.platform != "linux" or case not in (*CASES, "home-isolation"):
        raise ValueError("unsupported native measurement case")
    import loushang.coding

    origin = Path(loushang.coding.__file__).resolve()
    assert origin.is_relative_to(Path(sys.prefix).resolve()), (
        "installed Product required"
    )
    assert not origin.is_relative_to(ROOT / "src")
    assert Path.home().is_relative_to(root.parent), "private sample HOME required"
    os.chdir(root)
    report = {
        "schema_version": 2,
        "case": case,
        "status": "running",
        "valid": False,
        "milestones": {},
        "spawns": [],
        "observer_origin": str(origin),
        "observer_prefix": str(Path(sys.prefix).absolute()),
        "measured_prefix": str(measured_prefix),
        "seed": "empty",
        "sample_id": str(root.parent.resolve()),
        "seed_setup": [],
    }
    if stage is not None:
        report["recovery_stage"] = stage
    if stage == "restored":
        report["seed"] = "coordinator-verified-snapshot"
    publish(receipt, report)

    def operation():
        if stage == "prepare":
            recovery(root, report, prepare_only=True)
        elif stage == "restored":
            restored_recovery(root, report)
        elif case == "home-isolation":
            home_isolation(root, report)
        elif case in {"embedded", "foreground"}:
            foreground(root, report, embedded=case == "embedded")
        elif case == "local-mux":
            local_mux(root, report)
        elif case == "g14-stdio":
            with (
                stdio_observer_scope() as backend,
                closing(stdio(root, report)) as command,
            ):
                report["stdio_observer"] = backend
                asyncio.run(command)
        elif case == "product-first-use":
            product_first_use(root, report)
        else:
            recovery(root, report)

    failure = None
    try:
        with measured_entries(measured_prefix):
            _guarded(operation)
        report.update(status="observed", valid=False)  # Outer owner must still approve.
    except BaseException as error:
        failure = error
        report.update(status="failed", failure=f"{type(error).__name__}: {error}")
        raise
    finally:
        try:
            publish(receipt, report)
        except BaseException as publication_error:
            if failure is None:
                raise
            failure.add_note(
                f"observer receipt publication failed: {type(publication_error).__name__}"
            )


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]))
