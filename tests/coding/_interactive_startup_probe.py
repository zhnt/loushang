"""Linux embedded startup pilot; external frame/input observations, not acceptance.

The Product is a fresh ordinary module entrypoint. All test imports occur only
in the observer before the spawn clock. No production hooks or model IO are used.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from threading import Event, Lock, Thread

FRAME_END = "\x1b[?2026l"
DRAFT = "G18draftQ7"


def composer_text(visible: str, *, width: int = 99) -> str | None:
    """Read the bottom composer, joining only full-width soft-wrap continuations."""
    lines = visible.splitlines()
    prompts = [
        i for i, line in enumerate(lines) if line == "›" or line.startswith("› ")
    ]
    if not prompts:
        return None
    index = prompts[-1]
    previous = lines[index]
    value = previous[2:]
    index += 1
    while index < len(lines) and lines[index].startswith("  "):
        if len(previous) != width:
            return None
        previous = lines[index]
        value += previous[2:]
        index += 1
    if index >= len(lines) or lines[index] != "":
        return None
    footer = "\n".join(lines[index + 1 :])
    if "Loading session" not in footer and " | idle" not in footer:
        return None
    return value


class ScheduledEdits:
    """Fixed-cadence sender independent of frame replay and previous echoes.

    Each edit appends two characters to a cumulative unique draft. Coalesced
    frames can prove earlier characters remain visible, without overwriting them.
    This workload measures editing, not first-turn-after-ready latency.
    """

    def __init__(
        self,
        write: Callable[[str], None],
        *,
        count: int = 100,
        interval: float = 0.1,
        anchor: float | None = None,
    ):
        self.write = write
        self.count = count
        self.interval = interval
        self.anchor = time.perf_counter() if anchor is None else anchor
        self.rows: list[dict] = []
        self.lock = Lock()
        self.stop = Event()
        self.done = Event()
        self.failure: BaseException | None = None
        self.thread = Thread(target=self._send, name="startup-edit-observer")

    def _send(self) -> None:
        start = self.anchor
        token = DRAFT
        try:
            for index in range(self.count):
                planned = start + index * self.interval
                if self.stop.wait(max(0.0, planned - time.perf_counter())):
                    return
                chunk = f"{index:02x}"
                token += chunk
                with self.lock:
                    sent = time.perf_counter()
                    self.rows.append(
                        dict(
                            token=token,
                            planned=planned,
                            sent=sent,
                            echo=None,
                            written=False,
                        )
                    )
                    self.write(chunk)
                    self.rows[-1]["written"] = True
        except BaseException as error:
            self.failure = error
        finally:
            self.done.set()

    def observe(self, visible: str, now: float) -> None:
        draft = composer_text(visible)
        with self.lock:
            for row in self.rows:
                if (
                    row["echo"] is None
                    and now >= row["sent"]
                    and draft is not None
                    and draft.startswith(row["token"])
                ):
                    row["echo"] = now

    def last_echo_observed(self) -> bool:
        with self.lock:
            return len(self.rows) == self.count and self.rows[-1]["echo"] is not None

    def report(self, ready: float | None) -> dict:
        with self.lock:
            rows = [dict(row) for row in self.rows]
        for row in rows:
            row["echo_seconds"] = (
                None if row["echo"] is None else row["echo"] - row["sent"]
            )
            row["pacing_lag_seconds"] = row["sent"] - row["planned"]
        observed = [
            row["echo_seconds"] for row in rows if row["echo_seconds"] is not None
        ]
        sent_count = sum(row.get("written", True) for row in rows)
        phases = {}
        if ready is not None:
            groups: dict[str, list[dict]] = {
                "echo_before_observed_ready": [],
                "pending_across_observed_ready": [],
                "sent_after_observed_ready": [],
            }
            for row in rows:
                key = (
                    "sent_after_observed_ready"
                    if row["sent"] >= ready
                    else "echo_before_observed_ready"
                    if row["echo"] is not None and row["echo"] < ready
                    else "pending_across_observed_ready"
                )
                groups[key].append(row)
            for key, group in groups.items():
                delays = [
                    row["echo_seconds"]
                    for row in group
                    if row["echo_seconds"] is not None
                ]
                phases[key] = dict(
                    count=len(group),
                    missing_count=len(group) - len(delays),
                    mean_echo_seconds=sum(delays) / len(delays) if delays else None,
                    max_echo_seconds=max(delays) if delays else None,
                )
        return dict(
            workload="fixed-cadence-cumulative-append-v1",
            anchor=self.anchor,
            overdue_policy="catch-up-immediately; reject sender lag over 25ms",
            unsent_count=self.count - sent_count,
            attempted_count=len(rows),
            sender_failure=None
            if self.failure is None
            else f"{type(self.failure).__name__}: {self.failure}",
            sender_schedule_valid=(
                len(rows) == self.count
                and self.failure is None
                and all(row["pacing_lag_seconds"] <= 0.025 for row in rows)
            ),
            interval_seconds=self.interval,
            planned_count=self.count,
            sent_count=sent_count,
            observed_count=len(observed),
            missing_count=len(rows) - len(observed),
            missing_count_basis="attempted edits without observed echo, including failed writes",
            mean_observed_echo_seconds=sum(observed) / len(observed)
            if observed
            else None,
            max_observed_echo_seconds=max(observed) if observed else None,
            max_pacing_lag_seconds=max(
                (row["pacing_lag_seconds"] for row in rows), default=None
            ),
            spans_ready=(
                bool(rows)
                and ready is not None
                and rows[0]["sent"] < ready < rows[-1]["sent"]
            ),
            rows=rows,
            by_observed_ready=phases,
        )


def wait_for_frame(driver, predicate: Callable[[str], bool], *, timeout: float) -> str:
    """Replay immutable snapshots without holding the terminal reader lock."""
    deadline = time.monotonic() + timeout
    while True:
        output = driver.raw_output
        # The shared driver retains one million characters. Reject saturation
        # instead of interpreting offsets into a silently truncated transcript.
        if len(output) >= 1_000_000:
            raise ValueError("startup terminal output exceeded observation bound")
        if predicate(output):
            return output
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("startup frame observation timed out")
        # Settlement evidence can arrive in the trace without a new frame.
        # Re-evaluate the snapshot until the overall deadline expires.
        with suppress(TimeoutError):
            driver.read_until(
                lambda current, previous=output: current != previous,
                timeout=min(0.05, remaining),
            )


def completed_frame(output: str, *, after: int = 0) -> str | None:
    from tests.coding._g18_native_probe import _replay_embedded_output

    end = output.rfind(FRAME_END)
    if end < after:
        return None
    return "\n".join(_replay_embedded_output(output[:end]).visible_lines)


def frame_matches(output: str, *needles: str, after: int = 0) -> bool:
    visible = completed_frame(output, after=after)
    return visible is not None and all(needle in visible for needle in needles)


class StartupWitnesses:
    """Observe every completed frame, independently of predicate wait order.

    Times are observer detection bounds, not Product timestamps. Frames received
    in the same read share a timestamp; we do not invent sub-read precision.
    """

    def __init__(self) -> None:
        self.consumed = 0
        self.first_frame: float | None = None
        self.ready: float | None = None
        self.echo: float | None = None
        self.input_boundary: int | None = None
        self.visible: str | None = None
        self.frames = 0
        self.replay_seconds = 0.0
        self.max_replay_seconds = 0.0
        self.input_frame_processing_seconds = 0.0
        self.max_input_frame_processing_seconds = 0.0
        self._screen = None
        self.on_frame: Callable[[str, float], None] | None = None

    def input_sent(self, output: str) -> None:
        if self.input_boundary is not None:
            raise ValueError("startup draft may only be sent once")
        if DRAFT in output:
            raise ValueError("startup draft already exists before input")
        self.input_boundary = len(output)

    def observe(self, output: str, now: float) -> None:
        from tests.coding._g18_native_probe import _replay_embedded_output

        if len(output) < self.consumed:
            raise ValueError("terminal observation must retain its prefix")
        while (end := output.find(FRAME_END, self.consumed)) >= 0:
            replay_start = time.perf_counter()
            self._screen = _replay_embedded_output(
                output[self.consumed : end], screen=self._screen
            )
            visible = "\n".join(self._screen.visible_lines)
            replay_seconds = time.perf_counter() - replay_start
            self.frames += 1
            self.replay_seconds += replay_seconds
            self.max_replay_seconds = max(self.max_replay_seconds, replay_seconds)
            self.visible = visible
            if self.on_frame is not None:
                self.on_frame(visible, now)
            if self.first_frame is None and all(
                text in visible for text in ("Welcome to Loushang CLI", "›")
            ):
                self.first_frame = now
            if self.ready is None and " | idle" in visible:
                self.ready = now
            if (
                self.echo is None
                and self.input_boundary is not None
                and end >= self.input_boundary
                and "› " + DRAFT in visible
            ):
                self.echo = now
            if self.input_boundary is not None and end >= self.input_boundary:
                processing = time.perf_counter() - replay_start
                self.input_frame_processing_seconds += processing
                self.max_input_frame_processing_seconds = max(
                    self.max_input_frame_processing_seconds, processing
                )
            self.consumed = end + len(FRAME_END)


def resume_milestones(
    trace: list[dict], *, spawn_started: float, input_submitted: float
) -> dict:
    """Validate and project one instrumented writable Resume timeline."""

    required = (
        "resume_history_ready",
        "resume_plan_started",
        "resume_input_accepted",
        "resume_plan_ready",
        "resume_input_durable",
        "model_input",
        "resume_process_resources",
    )
    phases: dict[str, dict] = {}
    for row in trace:
        phase = row.get("phase")
        if phase in required or phase == "resume_background_plan_ready":
            if phase in phases:
                raise RuntimeError(f"duplicate Resume milestone trace: {phase}")
            phases[phase] = row
    missing = set(required) - phases.keys()
    if missing:
        raise RuntimeError(
            "missing Resume milestone trace: " + ", ".join(sorted(missing))
        )
    timestamps = []
    for phase in required:
        value = phases[phase].get("ns")
        if type(value) is not int:
            raise RuntimeError(f"invalid Resume milestone timestamp: {phase}")
        timestamps.append(value)
    origin_ns = int(spawn_started * 1_000_000_000)
    submitted_ns = int(input_submitted * 1_000_000_000)
    ordered = [
        submitted_ns,
        phases["resume_input_accepted"]["ns"],
        phases["resume_plan_ready"]["ns"],
        phases["resume_input_durable"]["ns"],
        phases["model_input"]["ns"],
        phases["resume_process_resources"]["ns"],
    ]
    if phases["resume_history_ready"]["ns"] < origin_ns or ordered != sorted(
        ordered
    ):
        raise RuntimeError("Resume milestone trace is not monotonic")
    resources = phases["resume_process_resources"]
    if (
        type(resources.get("cpu_seconds")) not in {int, float}
        or type(resources.get("peak_rss_kib")) is not int
        or type(resources.get("open_fds")) is not int
    ):
        raise RuntimeError("invalid Resume process resource trace")
    return {
        "history_ready_seconds": (
            phases["resume_history_ready"]["ns"] - origin_ns
        )
        / 1_000_000_000,
        "input_acceptance_seconds": (
            phases["resume_input_accepted"]["ns"] - submitted_ns
        )
        / 1_000_000_000,
        "plan_ready_seconds": (
            phases["resume_plan_ready"]["ns"] - submitted_ns
        )
        / 1_000_000_000,
        "input_durable_seconds": (
            phases["resume_input_durable"]["ns"] - submitted_ns
        )
        / 1_000_000_000,
        "model_transport_seconds": (
            phases["model_input"]["ns"] - submitted_ns
        )
        / 1_000_000_000,
        "background_plan_status": phases.get(
            "resume_background_plan_ready", {}
        ).get("status", "not_observed"),
        "cpu_seconds": resources["cpu_seconds"],
        "peak_rss_kib": resources["peak_rss_kib"],
        "open_fds_at_exit": resources["open_fds"],
        "fsync_calls": resources.get("fsync_calls"),
        "fsync_seconds": resources.get("fsync_seconds"),
        "resume_writer_acquire_seconds": resources.get(
            "resume_writer_acquire_seconds"
        ),
        "full_model_input_rebuilds": resources.get(
            "full_model_input_rebuilds"
        ),
    }


def measure(
    root: Path,
    source: Path,
    python: Path,
    *,
    profile: bool = False,
    installed: bool = False,
    synthetic: bool = False,
    seed: Path | None = None,
    resume: bool = False,
    workspace: Path | None = None,
    edit_train: bool = False,
) -> dict:
    from tests.coding._g18_native_probe import observe_spawn
    from tests.coding.test_hosted_legacy_evidence import _private_environment
    from tests.tui.terminal_process_support import (
        spawn_terminal_process,
        terminal_test_environment,
    )

    if synthetic and (not installed or profile):
        raise ValueError("synthetic pilot requires unprofiled installed entrypoint")
    if resume and (seed is None or not synthetic):
        raise ValueError("Resume milestones require a synthetic seeded pilot")
    if edit_train and (synthetic or profile):
        raise ValueError(
            "fixed editing is a separate unprofiled workload, not a first-turn probe"
        )
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    workspace = workspace or root / "project"
    workspace.mkdir(parents=True, exist_ok=True)
    env = terminal_test_environment(source, base=_private_environment(root))
    if installed:
        env.pop("PYTHONPATH", None)
    env.update(
        TMPDIR=str(root),
        LOUSHANG_RUNTIME_DIR=str(root / "runtime"),
        LOUSHANG_TMPDIR=str(root / "scratch"),
    )
    command = [str(python), "-m", "loushang.coding.cli", "--tui"]
    if installed:
        command = [str(python.parent / "loushang"), "--tui"]
    if profile:
        command = [
            str(python),
            "-m",
            "cProfile",
            "-o",
            str(root / "startup.pstats"),
            "-m",
            "loushang.coding.cli",
            "--tui",
        ]
    if synthetic:
        command = [
            str(python),
            "-I",
            str(Path(__file__).with_name("_interactive_model_child.py")),
            str(python.parent / "loushang"),
            str(root / "model-trace.jsonl"),
            "--tui",
            "--model",
            "baidu-qianfan:openai-completions-cn:ernie-5.1",
        ]
    if seed is not None:
        # Writable Resume validates that the file name remains bound to the
        # transcript header. Keep the generated canonical name when isolating
        # the seed inside this sample root.
        # The transcript store and its machine state must not share a parent
        # domain. The private environment lives below ``root``; use a unique
        # sibling data root so repeated samples also have distinct blob and
        # Writer authority domains.
        if resume:
            data_root = root.parent / f"{root.name}-data"
            data_root.mkdir(mode=0o700)
            session_root = data_root / "sessions"
            session_root.mkdir(mode=0o700)
        else:
            session_root = root
        restored = session_root / seed.name
        shutil.copy2(seed, restored)
        command.extend(["--resume" if resume else "--session", str(restored)])
        if resume:
            command.extend(["--session-dir", str(session_root)])
    result = {
        "schema": 3,
        "classification": "startup-pilot-not-performance-acceptance",
        "source": str(source),
        "argv": command,
        "instrumented": profile or synthetic,
        "synthetic": synthetic,
        "seed": str(seed) if seed is not None else None,
        "resume": resume,
        "installation": str(python.parent.parent) if installed else None,
        "metrics": {},
        "status": "started",
    }
    metrics = result["metrics"]
    driver = None
    train: ScheduledEdits | None = None
    try:
        with observe_spawn(command[0]) as spawn:
            with spawn_terminal_process(
                command, cwd=workspace, env=env, columns=100, rows=30
            ) as driver:
                result["spawn"] = spawn
                import termios

                witnesses = StartupWitnesses()

                def observe(out: str) -> StartupWitnesses:
                    witnesses.observe(out, time.perf_counter())
                    return witnesses

                wait_for_frame(
                    driver,
                    lambda out: observe(out).first_frame is not None,
                    timeout=35,
                )
                metrics["first_frame_seconds"] = witnesses.first_frame - spawn["start"]
                # Exclude kernel echo as the draft visibility witness.
                active = termios.tcgetattr(driver._master_fd)
                assert not active[3] & (termios.ECHO | termios.ICANON)
                before = driver.raw_output
                result["input_sent_after_observed_loading_frame"] = frame_matches(
                    before, "Loading session"
                )
                sent = time.perf_counter()
                result["input_sent_seconds"] = sent - spawn["start"]
                witnesses.input_sent(before)
                driver.write(DRAFT)
                if edit_train:
                    train = ScheduledEdits(driver.write, anchor=sent)
                    witnesses.on_frame = train.observe
                    # Start on the fixed input boundary, never after initial echo:
                    # otherwise a slow baseline would omit its initial input stall.
                    train.thread.start()
                wait_for_frame(
                    driver,
                    lambda out: observe(out).echo is not None,
                    timeout=35,
                )
                metrics["initial_echo_seconds"] = witnesses.echo - sent
                if edit_train:
                    assert train is not None
                    try:
                        wait_for_frame(
                            driver,
                            lambda out: (
                                observe(out) is not None
                                and train.done.is_set()
                                and (
                                    train.failure is not None
                                    or train.last_echo_observed()
                                )
                            ),
                            timeout=15,
                        )
                        if train.failure is not None:
                            raise train.failure
                    finally:
                        train.stop.set()
                        train.thread.join()
                        witnesses.on_frame = None
                wait_for_frame(
                    driver,
                    lambda out: (
                        observe(out).ready is not None
                        and all(
                            text in (witnesses.visible or "")
                            for text in (" | idle", "› " + DRAFT)
                        )
                    ),
                    timeout=35,
                )
                metrics["ready_observed_seconds"] = witnesses.ready - spawn["start"]
                result["startup_observer"] = {
                    "completed_frames": witnesses.frames,
                    "replay_seconds": witnesses.replay_seconds,
                    "max_frame_replay_seconds": witnesses.max_replay_seconds,
                    "input_frame_processing_seconds": witnesses.input_frame_processing_seconds,
                    "max_input_frame_processing_seconds": witnesses.max_input_frame_processing_seconds,
                    "timestamp_basis": "snapshot-before-replay",
                }
                if seed is not None:
                    wait_for_frame(
                        driver,
                        lambda out: frame_matches(
                            out, "G18 history sentinel 15", "› " + DRAFT
                        ),
                        timeout=10,
                    )
                # Readiness and echo are independently witnessed; timestamps
                # still include external polling and frame-replay overhead.
                cleared = len(driver.raw_output)
                driver.write("\x15")  # Default Ctrl-U clears the retained draft.
                wait_for_frame(
                    driver,
                    lambda out: (
                        frame_matches(out, " | idle", "›", after=cleared)
                        and DRAFT not in (completed_frame(out) or "")
                    ),
                    timeout=10,
                )
                if synthetic:
                    from tests.coding._interactive_model_child import INPUT, REPLY

                    submitted_after = len(driver.raw_output)
                    submitted = time.perf_counter()
                    driver.write(INPUT + "\r")
                    wait_for_frame(
                        driver,
                        lambda out: frame_matches(out, REPLY, after=submitted_after),
                        timeout=60 if resume else 35,
                    )
                    if resume:
                        assert (
                            "Allow this action once"
                            not in driver.raw_output[submitted_after:]
                        )
                        metrics["resume_approval_prompted"] = False
                    metrics["first_reply_seconds"] = time.perf_counter() - submitted
                    metrics["spawn_through_reply_seconds"] = (
                        time.perf_counter() - spawn["start"]
                    )

                    def settled(out):
                        if not frame_matches(
                            out, "› ", REPLY, after=submitted_after
                        ):
                            return False
                        lines = (root / "model-trace.jsonl").read_text().splitlines()
                        expected_phase = (
                            "model_input" if resume else "prompt_returned"
                        )
                        return any(
                            json.loads(line)["phase"] == expected_phase
                            for line in lines
                        )

                    wait_for_frame(driver, settled, timeout=25)
                    metrics["prompt_settled_observed_seconds"] = (
                        time.perf_counter() - submitted
                    )
                    result["synthetic_trace"] = [
                        json.loads(line)
                        for line in (root / "model-trace.jsonl")
                        .read_text()
                        .splitlines()
                    ]
                    assert (
                        sum(
                            row["phase"] == "model_input"
                            for row in result["synthetic_trace"]
                        )
                        == 1
                    )
                quit_at = time.perf_counter()
                driver.write("/quit\r")
                assert driver.wait(timeout=25) == 0, driver.diagnostics
                if synthetic and resume:
                    result["synthetic_trace"] = [
                        json.loads(line)
                        for line in (root / "model-trace.jsonl")
                        .read_text()
                        .splitlines()
                    ]
                    metrics["resume_milestones"] = resume_milestones(
                        result["synthetic_trace"],
                        spawn_started=spawn["start"],
                        input_submitted=submitted,
                    )
                metrics["exit_seconds"] = time.perf_counter() - quit_at
                output = driver.raw_output
                for mode in ("2004", "1004"):
                    assert (
                        output.rfind(f"\x1b[?{mode}l")
                        > output.find(f"\x1b[?{mode}h")
                        >= 0
                    )
                assert driver.diagnostics.termination is None
            assert not driver.diagnostics.reader_alive
        result["status"] = "complete"
    except BaseException as error:
        result["status"] = "failed"
        result["error_type"] = type(error).__name__
        result["error"] = str(error)[:1000]
        raise
    finally:
        if train is not None:
            train.stop.set()
            if train.thread.ident is not None:
                train.thread.join()
            result["edit_train"] = train.report(witnesses.ready)
        if driver is not None:
            # Synthetic draft and isolated configuration only. Bound retained IO.
            (root / "terminal.txt").write_text(driver.raw_output[-65536:])
        (root / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--installed", action="store_true")
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--seed", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--edit-train", action="store_true")
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("this pilot requires Linux")
    print(
        json.dumps(
            measure(
                args.root,
                args.source.resolve(),
                args.python,
                profile=args.profile,
                installed=args.installed,
                synthetic=args.synthetic,
                seed=args.seed,
                resume=args.resume,
                workspace=args.workspace,
                edit_train=args.edit_train,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    main()
