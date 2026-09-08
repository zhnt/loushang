"""Darwin native CLI observation under retained first-party supervision.

No generic terminal fallback may run while this observer owes physical proof.
Numeric child signals are used only while their actual parents remain stopped;
the CLI itself is reserved by the witness until explicit reap authorization.
"""

from __future__ import annotations

import json
import os
import runpy
import signal
import sys
import time
from contextlib import suppress
from pathlib import Path

from loushang.tui.cell_width import strip_control_sequences
from tests.tui.terminal_process_support import spawn_terminal_process

from ._hosted_darwin_api import DarwinExitWatch, DarwinWatchEventError
from ._hosted_darwin_witness import ReceiptIOError
from ._hosted_terminal import process_table
from .test_hosted_client import _argv
from .test_hosted_client_terminal import _installed
from .test_mux_terminal_process import _terminal_environment


def _until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise TimeoutError("native observation barrier pending")
        time.sleep(0.01)


def _progress(phase, index):
    # Fixed test-owned labels only: no argv, environment or terminal contents.
    # Diagnostics must never interrupt the retained cleanup owner.
    with suppress(OSError, ValueError):
        print(f"native scenario CLI {index}: {phase}", flush=True)


def _read(root, name):
    try:
        if (root / "failed").exists():
            raise RuntimeError("native CLI witness failed")
        path = root / name
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as source:
            raw = source.read(4097)
        if len(raw) > 4096:
            raise RuntimeError("native witness receipt exceeds bound")
        return json.loads(raw)
    except OSError as error:
        raise ReceiptIOError("native observer receipt pending") from error


def _command(root, name, pid):
    try:
        pending = root / (name + ".pending")
        pending.write_text(str(pid), encoding="utf-8")
        pending.replace(root / name)
    except OSError as error:
        raise ReceiptIOError("native observer command pending") from error


class FrozenChain:
    def __init__(self, cli, witness):
        self.cli, self.witness = cli, witness
        self.pids, self.stopped = [], set()
        self.watch = None
        self.invalid = False

    def admit(self):
        try:
            self._admit()
        except BaseException:
            self.invalid = True
            raise

    def _admit(self):
        parent, current = self.witness, self.cli
        while True:
            self._verify_signal_target(current, parent)
            # CLI reserved by witness; every later parent was confirmed stopped.
            self.pids.append(current)
            os.kill(current, signal.SIGSTOP)
            self.stopped.add(current)
            _until(lambda current=current, parent=parent: self._stopped(current, parent))
            children = [pid for pid, (owner, _) in process_table().items() if owner == current]
            if not children:
                break
            if len(children) != 1 or len(self.pids) >= 8:
                raise RuntimeError("native Hosted process chain is ambiguous")
            parent, current = current, children[0]
        if len(self.pids) < 2:
            raise RuntimeError("ready observation lacks actual Hosted child")
        self.watch = DarwinExitWatch(self.pids)
        table = process_table()
        for index, pid in enumerate(self.pids):
            owner = self.witness if index == 0 else self.pids[index - 1]
            expected = self.pids[index + 1:index + 2]
            if (table.get(pid, (None, ""))[0] != owner or "T" not in table[pid][1]
                    or sorted(key for key, (ppid, _) in table.items() if ppid == pid) != expected):
                raise RuntimeError("native frozen chain changed during watch admission")

    @staticmethod
    def _stopped(pid, parent):
        entry = process_table().get(pid)
        if entry is None or entry[0] != parent or "Z" in entry[1]:
            raise RuntimeError("native process disappeared during stop")
        return "T" in entry[1]

    def _verify_signal_target(self, pid, parent):
        if self.invalid:
            raise RuntimeError("native chain identity remains unknown")
        table = process_table()
        entry, owner = table.get(pid), table.get(parent)
        if (entry is None or entry[0] != parent or "Z" in entry[1]
                or owner is None or "Z" in owner[1]
                or (pid != self.cli and "T" not in owner[1])):
            raise RuntimeError("native signal authority lost its retained parent")
        if self.watch is not None and self.watch.exited():
            raise RuntimeError("native chain exited before resume")

    def resume(self, *, force_exit):
        try:
            self._resume(force_exit=force_exit)
        except BaseException:
            self.invalid = True
            raise

    def _resume(self, *, force_exit):
        # Descendants first, CLI last. For the fault case leave every Hosted
        # process stopped so only Product's actual forced cleanup can end it.
        targets = [self.cli] if force_exit else list(reversed(self.pids))
        for pid in targets:
            if pid in self.stopped:
                index = self.pids.index(pid)
                self._verify_signal_target(pid, self.witness if index == 0 else self.pids[index - 1])
                os.kill(pid, signal.SIGCONT)
                self.stopped.remove(pid)


class NativeObservation:
    def __init__(self, root, ledger, parent_scope, *, force_exit=False, cancel_start=False,
                 cancel_recovery=False, close_parent=True, receipt_name="witness",
                 arguments=None, exit_command="/exit\r"):
        self.root, self.ledger = root, ledger
        self.parent_scope = parent_scope
        self.receipts = root / receipt_name
        self.receipts.mkdir()
        self.force_exit, self.cancel_start = force_exit, cancel_start
        self.cancel_recovery, self.close_parent = cancel_recovery, close_parent
        self.parent_proof = None
        self.arguments = tuple(_argv(root) if arguments is None else arguments)
        self.exit_command = exit_command
        self.driver = self.started = self.chain = self.finished = None
        self.admitted = self.requested = self.reaped = self.closed = self.unknown = False
        self.chain_ready = self.witness_ended = self.parent_closed = False
        self.mode_restored = False
        self.active_modes_valid = False
        self.resumed = False
        self.ticket = ledger["create"](root, parent=parent_scope, observation=True)

    def start(self):
        cancelled = self.cancel_start or self.cancel_recovery
        script = "_hosted_recovery_cancel.py" if self.cancel_recovery else "_hosted_start_cancel.py"
        executable = ([sys.executable, "-I", str(Path(__file__).with_name(script))]
                      if cancelled else [_installed()])
        environment = _terminal_environment(self.root)
        environment[self.ledger["ENVIRONMENT_KEY"]] = str(self.ticket["path"])
        self.driver = spawn_terminal_process(
            [sys.executable, "-I", "-S", str(Path(__file__).with_name("_hosted_darwin_witness.py")),
             str(self.receipts), *executable, *self.arguments],
            cwd=self.root, env=environment, columns=100, rows=30,
        )
        _until(lambda: _read(self.receipts, "started") is not None, 15)
        self.started = _read(self.receipts, "started")
        diagnostics = self.driver.diagnostics
        if diagnostics.exit_status is not None or self.started["witness"] != diagnostics.pid:
            raise RuntimeError("native witness identity mismatch")
        self.driver.read_until(
            lambda out: (self.root / "recovery-held").is_file() if self.cancel_recovery else
            ("G17 publication held" if self.cancel_start else "/exit ends app")
            in strip_control_sequences(out), timeout=35,
        )
        _command(self.receipts, "sample.request", self.started["pid"])
        _until(lambda: _read(self.receipts, "sample") is not None)
        active = _read(self.receipts, "sample")["modes"]
        if cancelled:
            self.active_modes_valid = active == self.started["baseline"]
        else:
            import termios

            self.active_modes_valid = (active != self.started["baseline"]
                                       and not active[3] & (termios.ECHO | termios.ICANON))
        self.chain = FrozenChain(self.started["pid"], self.started["witness"])
        self.chain.admit()
        self.chain_ready = True

    def _admit_scope(self, path, controller, children):
        try:
            current = self.ledger["_read"](path)
            expected = {"token": Path(path).stem, "phase": "admitted",
                        "controller": controller, "children": children}
            if current == expected:
                return  # Atomic publication succeeded before a lost ack.
            self.ledger["admit"](path, controller, children)
        except OSError as error:
            raise ReceiptIOError("native observation admission pending") from error

    def _complete_scope(self, path):
        try:
            self.ledger["complete"](path)
        except OSError as error:
            raise ReceiptIOError("native observation completion pending") from error

    def activate(self):
        if self.unknown or not self.chain_ready:
            raise RuntimeError("native chain has no activation proof")
        if not self.admitted:
            self._admit_scope(self.ticket["path"], self.chain.cli, self.chain.pids[1:])
            controller, children = self.parent_proof or (os.getpid(), [self.started["witness"]])
            self._admit_scope(self.parent_scope, controller, children)
            self.admitted = True
        if not self.resumed:
            self.chain.resume(force_exit=self.force_exit)
            self.resumed = True

    def settle_step(self):
        if self.unknown or not self.chain_ready:
            return False
        if not self.admitted:
            self.activate()
        if not self.requested:
            self.activate()
            if self.cancel_start or self.cancel_recovery:
                self.chain._verify_signal_target(self.chain.cli, self.chain.witness)
                os.kill(self.chain.cli, signal.SIGINT)  # Unreaped witness child.
            else:
                self.driver.write(self.exit_command)
            self.requested = True
        if self.finished is None:
            ended = self.chain.watch.exited()
            finished = _read(self.receipts, "exited-retained")
            if ended != set(self.chain.pids) or finished is None:
                return False
            table = process_table()
            if any(pid in table for pid in self.chain.pids[1:]):
                return False  # A zombie child is not a reaped Hosted process.
            # Failed user evidence is not unknown process identity. Preserve the
            # exact mismatch, reclaim the known-exited chain, then fail the test.
            self.mode_restored = finished["modes"] == self.started["baseline"]
            self.finished = finished
        if not self.reaped:
            _command(self.receipts, "reap.request", self.chain.cli)
            reaped = _read(self.receipts, "reaped")
            if reaped is None:
                return False
            if reaped != {"pid": self.chain.cli, "code": self.finished["code"]}:
                raise RuntimeError("native CLI reap receipt changed identity")
            if self.chain.cli in process_table():
                return False
            self.reaped = True
        if not self.closed:
            self._complete_scope(self.ticket["path"])
            self.closed = True
        if not self.witness_ended:
            _command(self.receipts, "release", self.chain.cli)
            if self.driver.wait(timeout=5) != 0:
                raise RuntimeError("native witness failed after physical proof")
            self.driver.close()
            self.chain.watch.close()
            self.witness_ended = True
        if self.close_parent and not self.parent_closed:
            self._complete_scope(self.parent_scope)
            self.parent_closed = True
        return True

    def settle(self):
        # Keep this exact observer/watch/driver stack until proof. Neither a
        # timeout nor an assertion may reach generic PID/tree cleanup instead.
        previous = signal.signal(signal.SIGINT, lambda *_: None)
        budget_deadline = time.monotonic() + 25
        deadline, exceeded = budget_deadline, False
        try:
            while True:
                try:
                    if self.settle_step():
                        return not exceeded and time.monotonic() <= budget_deadline
                except (ReceiptIOError, TimeoutError):
                    pass
                except BaseException as error:
                    self.retain_failure(error)
                if time.monotonic() >= deadline:
                    exceeded = True
                    with suppress(OSError, ValueError):
                        print("native CLI observation pending; owner retained", flush=True)
                    deadline = time.monotonic() + 5
                time.sleep(0.01)
        finally:
            signal.signal(signal.SIGINT, previous)

    def retain_failure(self, error):
        self.unknown = True
        trace = error.__traceback__
        while trace is not None and trace.tb_next is not None:
            trace = trace.tb_next
        location = (f"{Path(trace.tb_frame.f_code.co_filename).name}:{trace.tb_lineno}"
                    if trace is not None else "unknown")
        with suppress(OSError, ValueError):
            print(f"native observation unknown: {type(error).__name__} at {location}", flush=True)
            if isinstance(error, DarwinWatchEventError):
                print(f"native watch masks: registered={error.registered}, "
                      f"flags={error.flags:#x}, notes={error.notes:#x}", flush=True)
            self.ledger["unknown"](self.ticket["path"])


def _assert_observation(observation, budget_ok):
    assert budget_ok, "native exit exceeded its user budget"
    assert observation.mode_restored, "native CLI did not restore terminal modes"
    assert observation.active_modes_valid, "native CLI terminal activation was invalid"
    cancelled = observation.cancel_start or observation.cancel_recovery
    expected = 130 if cancelled else 1 if observation.force_exit else 0
    assert observation.finished["code"] == expected
    assert observation.driver.diagnostics.termination is None
    assert not observation.driver.diagnostics.reader_alive
    if cancelled:
        output = observation.driver.raw_output
        assert "G17 terminal invoked" not in output and "/exit ends app" not in strip_control_sequences(output)
        assert "hosted_interrupted" in output
    if observation.cancel_start:
        assert all(message in output for message in (
            "hosted_interrupted", "G17 publication cancelled", "G17 late lease returned",
        ))


class NativeScenario:
    """One retained outer scope spanning every CLI in a user workflow."""

    def __init__(self, ledger, parent):
        self.ledger, self.parent = ledger, parent
        self.observations = []
        self.parent_proof = None
        self.closed = False
        self.unknown = False

    def observe(self, root, *, interaction=None, **options):
        if self.closed or self.unknown or len(self.observations) >= 8:
            raise RuntimeError("native scenario is closed or exceeds its CLI bound")
        observation = NativeObservation(
            root, self.ledger, self.parent, close_parent=False,
            receipt_name=f"witness-{len(self.observations)}", **options,
        )
        self.observations.append(observation)
        index = len(self.observations)
        try:
            try:
                _progress("starting", index)
                observation.start()
                if self.parent_proof is None:
                    self.parent_proof = (os.getpid(), [observation.started["witness"]])
                observation.parent_proof = self.parent_proof
                while True:
                    try:
                        observation.activate()
                        break
                    except ReceiptIOError:
                        time.sleep(0.01)
            except BaseException as error:
                observation.retain_failure(error)
                raise
            _progress("active", index)
            if interaction is not None:
                interaction(observation.driver)
        finally:
            _progress("settling", index)
            budget_ok = observation.settle()
        _progress("released", index)
        _assert_observation(observation, budget_ok)

    def recovery_cli(self, root, *, create, historical=None):
        from .test_hosted_entry_evidence import _recovery_interaction

        self.observe(root, interaction=lambda driver: _recovery_interaction(
            driver, create=create, historical=historical,
        ))

    def picker_cli(self, root, arguments, interaction, *, exit_command):
        self.observe(root, arguments=arguments, interaction=interaction, exit_command=exit_command)

    def close_step(self):
        if self.unknown:
            return False
        for observation in self.observations:
            if observation.unknown:
                return False
            if not observation.witness_ended:
                observation.settle()
            if not observation.witness_ended or not observation.closed:
                return False
        if self.observations:
            self.observations[0]._complete_scope(self.parent)
        else:
            try:
                self.ledger["require_closed"](
                    {"path": self.parent, "token": self.parent.stem}, not_started=True,
                )
            except RuntimeError as error:
                if isinstance(error.__cause__, OSError):
                    raise ReceiptIOError("empty native scenario completion pending") from error
                raise
        self.closed = True
        return True

    def close(self):
        previous = signal.signal(signal.SIGINT, lambda *_: None)
        next_report = time.monotonic() + 5
        try:
            while not self.closed:
                try:
                    if self.close_step():
                        return
                except ReceiptIOError:
                    pass
                except BaseException:
                    self.unknown = True
                    with suppress(OSError, ValueError):
                        self.ledger["unknown"](self.parent)
                if not self.closed:
                    if time.monotonic() >= next_report:
                        with suppress(OSError, ValueError):
                            print("native scenario completion pending; owner retained", flush=True)
                        next_report = time.monotonic() + 5
                    time.sleep(0.01)
        finally:
            signal.signal(signal.SIGINT, previous)


def scenario(root, case):
    assert sys.platform == "darwin"
    repository = Path(__file__).resolve().parents[2]
    ledger = runpy.run_path(str(repository / "scripts/dev/_evidence_observation.py"))
    parent = Path(os.environ[ledger["ENVIRONMENT_KEY"]])
    owner = NativeScenario(ledger, parent)
    try:
        if case == "recovery-cancel":
            from .test_hosted_entry_evidence import _observe_recovery_cancel

            _observe_recovery_cancel(root, observer=owner.observe, recovery_cli=owner.recovery_cli)
        elif case in {"cwd", "home"}:
            from loushang.appserver.protocol import SessionScopeV1

            from .test_hosted_client_terminal import _picker_workflow

            scope = SessionScopeV1.CWD if case == "cwd" else SessionScopeV1.USER_HOME
            _picker_workflow(root, scope, run_cli=owner.picker_cli)
        else:
            assert case in {"real", "start-cancel", "forced-exit"}
            owner.observe(root, force_exit=case == "forced-exit", cancel_start=case == "start-cancel")
    finally:
        owner.close()
