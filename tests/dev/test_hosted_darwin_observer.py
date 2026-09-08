"""Darwin chain-admission and retained physical-proof negative controls."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.coding import _hosted_darwin_observer as module


def _chain(monkeypatch, *, fault=None):
    # These tests simulate Darwin signals and process state; never depend on
    # the runner's signal constants (Windows has no SIGSTOP or SIGCONT).
    # Replace this module's reference only, not the shared stdlib module.
    monkeypatch.setattr(module, "signal", SimpleNamespace(SIGSTOP=17, SIGCONT=19, SIGINT=2))
    table = {90: (80, "S"), 100: (90, "S"), 101: (100, "S")}
    sent, watched = [], []

    def kill(pid, sig):
        sent.append((pid, sig))
        assert pid == 100 or "T" in table[100][1]
        table[pid] = (table[pid][0], "T" if sig == module.signal.SIGSTOP else "S")

    def watch(pids):
        watched.append(list(pids))
        if fault == "fence":
            table[101] = (99, "T")
        return SimpleNamespace(exited=lambda: set())

    monkeypatch.setattr(module, "process_table", lambda: dict(table))
    monkeypatch.setattr(module.os, "kill", kill)
    monkeypatch.setattr(module, "DarwinExitWatch", watch)
    if fault == "ancestry":
        table[100] = (99, "S")
    elif fault == "branch":
        table[102] = (100, "S")
    return module.FrozenChain(100, 90), sent, watched, table


@pytest.mark.parametrize("force", [False, True])
def test_chain_freezes_parent_before_child_and_resumes_cli_last(monkeypatch, force):
    chain, sent, watched, _ = _chain(monkeypatch)
    chain.admit()
    assert watched == [[100, 101]]
    assert sent == [(100, module.signal.SIGSTOP), (101, module.signal.SIGSTOP)]
    chain.resume(force_exit=force)
    assert sent[2:] == ([(100, module.signal.SIGCONT)] if force else
                        [(101, module.signal.SIGCONT), (100, module.signal.SIGCONT)])
    assert chain.stopped == ({101} if force else set())


@pytest.mark.parametrize("fault", ["ancestry", "branch", "fence"])
def test_chain_rejects_changed_identity_or_topology_without_resuming(monkeypatch, fault):
    chain, sent, _, _ = _chain(monkeypatch, fault=fault)
    with pytest.raises(RuntimeError):
        chain.admit()
    assert all(sig == module.signal.SIGSTOP for _, sig in sent)
    if fault == "ancestry":
        assert not sent
    elif fault == "branch":
        assert sent == [(100, module.signal.SIGSTOP)]


def _observation(tmp_path, monkeypatch):
    calls, ended, table = [], set(), {101: (100, "Z")}
    receipts = {}
    observation = object.__new__(module.NativeObservation)
    observation.unknown, observation.admitted, observation.requested = False, True, True
    observation.close_parent, observation.resumed = True, True
    observation.parent_proof = None
    observation.exit_command = "/exit\r"
    observation.chain_ready, observation.witness_ended, observation.parent_closed = True, False, False
    observation.finished, observation.reaped, observation.closed = None, False, False
    observation.receipts = tmp_path
    observation.started = {"baseline": [1, 2]}
    observation.ticket = {"path": tmp_path / "scope.json"}
    observation.parent_scope = tmp_path / "outer.json"
    observation.ledger = {"complete": lambda path: calls.append(Path(path).stem + "-closed")}
    observation.chain = SimpleNamespace(
        cli=100, pids=[100, 101],
        watch=SimpleNamespace(exited=lambda: set(ended), close=lambda: calls.append("watch-closed")),
    )
    observation.driver = SimpleNamespace(wait=lambda **kw: calls.append("witness-wait") or 0,
                                         close=lambda: calls.append("driver-closed"))
    monkeypatch.setattr(module, "process_table", lambda: dict(table))
    monkeypatch.setattr(module, "_read", lambda root, name: receipts.get(name))
    monkeypatch.setattr(module, "_command", lambda root, name, pid: calls.append(name))
    return observation, calls, ended, table, receipts


def test_observer_requires_exit_note_absence_modes_and_reap_before_release(tmp_path, monkeypatch):
    observation, calls, ended, table, receipts = _observation(tmp_path, monkeypatch)
    receipts["exited-retained"] = {"code": 0, "modes": [1, 2]}
    assert not observation.settle_step() and not calls
    ended.update({100, 101})
    assert not observation.settle_step() and not calls  # Zombie is not absence.
    table.clear()
    assert not observation.settle_step()
    assert calls == ["reap.request"]
    receipts["reaped"] = {"pid": 100, "code": 0}
    assert observation.settle_step()
    assert calls[-6:] == ["scope-closed", "release", "witness-wait", "driver-closed", "watch-closed", "outer-closed"]


@pytest.mark.parametrize("fault", ["identity", "unknown"])
def test_observer_cannot_release_without_matching_physical_proof(tmp_path, monkeypatch, fault):
    observation, calls, ended, table, receipts = _observation(tmp_path, monkeypatch)
    ended.update({100, 101})
    table.clear()
    receipts["exited-retained"] = {"code": 0, "modes": [1, 2]}
    receipts["reaped"] = {"pid": 101, "code": 0}
    if fault == "unknown":
        observation.unknown = True
        assert not observation.settle_step()
    else:
        with pytest.raises(RuntimeError):
            observation.settle_step()
    assert "release" not in calls and "scope-closed" not in calls


@pytest.mark.parametrize("fault", ["parent-gone", "parent-running", "reparented"])
def test_resume_rechecks_current_parent_and_keeps_changed_identity_unknown(monkeypatch, fault):
    chain, sent, _, table = _chain(monkeypatch)
    chain.admit()
    original = dict(table)
    if fault == "parent-gone":
        table.pop(100)
    elif fault == "parent-running":
        table[100] = (90, "S")
    else:
        table[101] = (99, "T")
    with pytest.raises(RuntimeError):
        chain.resume(force_exit=False)
    table.clear()
    table.update(original)
    with pytest.raises(RuntimeError, match="unknown"):
        chain.resume(force_exit=False)
    assert all(sig == module.signal.SIGSTOP for _, sig in sent)


def test_exited_witness_receipt_cannot_authorize_any_child_signal(tmp_path, monkeypatch):
    sent = []
    ledger = {"create": lambda *a, **kw: {"path": tmp_path / "scope.json"},
              "ENVIRONMENT_KEY": "G17_NATIVE_OBSERVATION"}
    monkeypatch.setattr(module, "spawn_terminal_process", lambda *a, **kw: SimpleNamespace(
        diagnostics=SimpleNamespace(pid=90, exit_status=0)))
    monkeypatch.setattr(module, "_installed", lambda: "unused-cli")
    monkeypatch.setattr(module, "_terminal_environment", lambda root: {})
    monkeypatch.setattr(module, "_read", lambda *a: {"pid": 100, "witness": 90, "baseline": []})
    monkeypatch.setattr(module.os, "kill", lambda *args: sent.append(args))
    observation = module.NativeObservation(tmp_path, ledger, tmp_path / "outer.json")
    with pytest.raises(RuntimeError, match="witness identity"):
        observation.start()
    assert not sent and not observation.chain_ready


def test_witness_spawn_preserves_picker_workspace_and_mux_arguments(tmp_path, monkeypatch):
    arguments = ["--workspace", str(tmp_path / "elsewhere"), "--mux", "picker"]
    ledger = {"create": lambda *a, **kw: {"path": tmp_path / "scope.json"},
              "ENVIRONMENT_KEY": "G17_NATIVE_OBSERVATION"}
    observed = []

    def spawn(argv, **options):
        observed.append(argv)
        raise RuntimeError("test stops before native spawn")

    monkeypatch.setattr(module, "spawn_terminal_process", spawn)
    monkeypatch.setattr(module, "_installed", lambda: "installed-cli")
    monkeypatch.setattr(module, "_terminal_environment", lambda root: {})
    observation = module.NativeObservation(tmp_path, ledger, tmp_path / "outer.json", arguments=arguments)
    with pytest.raises(RuntimeError, match="before native spawn"):
        observation.start()
    assert observed[0][-len(arguments) - 1:] == ["installed-cli", *arguments]


def test_foreground_detach_intent_is_sent_by_owner_not_interaction(tmp_path, monkeypatch):
    observation, calls, _, _, _ = _observation(tmp_path, monkeypatch)
    observation.exit_command, observation.requested = "\x02d", False
    observation.force_exit = observation.cancel_start = observation.cancel_recovery = False
    observation.driver.write = calls.append
    assert not observation.settle_step()
    assert calls == ["\x02d"]


def test_known_terminal_failure_reclaims_then_preserves_failed_evidence(tmp_path, monkeypatch):
    observation, calls, ended, table, receipts = _observation(tmp_path, monkeypatch)
    ended.update({100, 101})
    table.clear()
    receipts["exited-retained"] = {"code": 1, "modes": [9, 9]}
    receipts["reaped"] = {"pid": 100, "code": 1}
    assert observation.settle_step()
    assert observation.mode_restored is False
    assert observation.finished["code"] == 1
    assert calls[-1] == "outer-closed"


@pytest.mark.parametrize("scope", ["scope", "outer"])
@pytest.mark.parametrize("committed", [False, True])
def test_scope_completion_io_retry_retains_physical_proof_without_repeating_actions(
    tmp_path, monkeypatch, scope, committed,
):
    observation, calls, ended, table, receipts = _observation(tmp_path, monkeypatch)
    ended.update({100, 101})
    table.clear()
    receipts["exited-retained"] = {"code": 0, "modes": [1, 2]}
    receipts["reaped"] = {"pid": 100, "code": 0}
    closed, failures = set(), []

    def complete(path):
        name = Path(path).stem
        if name == scope and not failures:
            failures.append(name)
            if committed:
                closed.add(name)
            raise OSError("publication acknowledgement lost")
        closed.add(name)

    observation.ledger["complete"] = complete
    with pytest.raises(module.ReceiptIOError):
        observation.settle_step()
    assert observation.reaped and not observation.unknown
    assert observation.settle_step()
    assert closed == {"scope", "outer"}
    assert calls.count("reap.request") == 1
    assert calls.count("release") == 1
    assert calls.count("witness-wait") == 1


@pytest.mark.parametrize("committed", [False, True])
@pytest.mark.parametrize("scope", ["scope", "outer"])
def test_scope_admission_io_retry_reuses_frozen_chain(tmp_path, monkeypatch, committed, scope):
    observation, calls, _, _, _ = _observation(tmp_path, monkeypatch)
    observation.admitted = False
    observation.started["witness"] = 90
    records, failures = {}, []
    records[observation.ticket["path"]] = {"token": "scope", "phase": "open"}
    records[observation.parent_scope] = {"token": "outer", "phase": "open"}

    def admit(path, controller, children):
        value = {"token": path.stem, "phase": "admitted", "controller": controller, "children": children}
        if path.stem == scope and not failures:
            failures.append(path)
            if committed:
                records[path] = value
            raise OSError("admission publication interrupted")
        records[path] = value

    observation.ledger.update({"_read": records.__getitem__, "admit": admit})
    with pytest.raises(module.ReceiptIOError):
        observation.settle_step()
    assert observation.chain_ready and not observation.admitted
    assert not observation.settle_step()
    assert observation.admitted and not calls


def test_successful_physical_settlement_still_reports_budget_crossed_inside_last_step(monkeypatch):
    clock = [0.0]

    def finish():
        clock[0] = 26.0
        return True

    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    observation = SimpleNamespace(settle_step=finish)
    assert module.NativeObservation.settle(observation) is False
