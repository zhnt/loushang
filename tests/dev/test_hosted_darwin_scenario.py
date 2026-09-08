"""Whole-scenario registry ownership; fake native operations, real scope files."""

from __future__ import annotations

import os
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.coding import _hosted_darwin_observer as module

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX observation registry")


def _scenario(tmp_path, monkeypatch):
    ledger = runpy.run_path(str(Path(module.__file__).resolve().parents[2] / "scripts/dev/_evidence_observation.py"))
    outer = ledger["create"](tmp_path, observation=True)
    owner, calls = module.NativeScenario(ledger, outer["path"]), []
    native = module.NativeObservation

    class FakeObservation(native):
        def start(self):
            index = len(owner.observations)
            self.started = {"witness": 1000 + index}
            self.chain = SimpleNamespace(cli=2000 + index, pids=[2000 + index, 3000 + index],
                                         resume=lambda **kw: calls.append(("resume", index)))
            self.chain_ready = True
            self.driver = SimpleNamespace(index=index)

        def settle(self):
            assert not self.witness_ended, "physical settlement must not repeat"
            self.activate()
            self._complete_scope(self.ticket["path"])
            self.closed = self.witness_ended = True
            calls.append(("released", self.driver.index))
            return True

    monkeypatch.setattr(module, "NativeObservation", FakeObservation)
    monkeypatch.setattr(module, "_assert_observation", lambda observation, budget: calls.append(("verdict", budget)))
    return owner, ledger, outer, calls


def test_three_cli_scopes_close_individually_but_parent_stays_admitted(tmp_path, monkeypatch):
    owner, ledger, outer, calls = _scenario(tmp_path, monkeypatch)
    for index in range(3):
        owner.observe(tmp_path, cancel_recovery=index == 1)
        assert ledger["_read"](outer["path"])["phase"] == "admitted"
        assert all(ledger["_read"](item.ticket["path"])["phase"] == "closed" for item in owner.observations)
    assert len({item.receipts for item in owner.observations}) == 3
    assert {tuple(item.parent_proof[1]) for item in owner.observations} == {(1001,)}
    assert owner.close_step()
    ledger["require_closed"](outer)
    assert calls.count(("released", 1)) == calls.count(("released", 2)) == calls.count(("released", 3)) == 1
    with pytest.raises(RuntimeError, match="closed"):
        owner.observe(tmp_path)


@pytest.mark.parametrize("previous", [0, 2])
def test_failed_interaction_still_settles_its_cli_and_closes_whole_scope(tmp_path, monkeypatch, previous):
    owner, ledger, outer, calls = _scenario(tmp_path, monkeypatch)
    for _ in range(previous):
        owner.observe(tmp_path)

    def fail(driver):
        raise AssertionError("history mismatch")

    with pytest.raises(AssertionError, match="history mismatch"):
        owner.observe(tmp_path, interaction=fail)
    assert ("released", 1) in calls
    assert ledger["_read"](outer["path"])["phase"] == "admitted"
    owner.close()
    ledger["require_closed"](outer)
    assert len([call for call in calls if call[0] == "released"]) == previous + 1


def test_unsettled_second_cli_prevents_outer_completion(tmp_path, monkeypatch):
    owner, ledger, outer, _ = _scenario(tmp_path, monkeypatch)
    owner.observe(tmp_path)
    pending = module.NativeObservation(tmp_path, ledger, outer["path"],
                                       close_parent=False, receipt_name="witness-1")
    owner.observations.append(pending)
    pending.start()
    pending.parent_proof = owner.parent_proof
    pending.activate()
    finish = pending.settle
    pending.settle = lambda: False
    assert not owner.close_step()
    assert ledger["_read"](outer["path"])["phase"] == "admitted"
    assert ledger["_read"](pending.ticket["path"])["phase"] == "admitted"
    pending.settle = finish
    assert owner.close_step()
    ledger["require_closed"](outer)


@pytest.mark.parametrize("committed", [False, True])
def test_parent_publication_retry_keeps_all_cli_proofs_without_releasing_again(tmp_path, monkeypatch, committed):
    owner, ledger, outer, calls = _scenario(tmp_path, monkeypatch)
    for _ in range(3):
        owner.observe(tmp_path)
    complete, faults = ledger["complete"], []

    def interrupted(path):
        if path == outer["path"] and not faults:
            faults.append(path)
            if committed:
                complete(path)
            raise OSError("parent publication interrupted")
        complete(path)

    ledger["complete"] = interrupted
    owner.close()
    ledger["require_closed"](outer)
    assert len([call for call in calls if call[0] == "released"]) == 3
    assert len(owner.observations) == 3


def test_scenario_unknown_completion_cannot_be_cleared_by_later_file_success(tmp_path, monkeypatch):
    owner, ledger, outer, _ = _scenario(tmp_path, monkeypatch)
    owner.observe(tmp_path)
    complete = ledger["complete"]
    ledger["complete"] = lambda path: (_ for _ in ()).throw(ValueError("changed identity"))

    class StopControl(BaseException):
        pass

    def stop(delay):
        raise StopControl

    monkeypatch.setattr(module.time, "sleep", stop)
    with pytest.raises(StopControl):
        owner.close()
    ledger["complete"] = complete
    assert not owner.close_step()
    assert ledger["_read"](outer["path"])["phase"] == "unknown"
    with pytest.raises(RuntimeError):
        owner.observe(tmp_path)


def test_recovery_seed_and_relaunch_use_owned_cli_without_generic_terminal(tmp_path, monkeypatch):
    from tests.coding import test_hosted_entry_evidence as recovery

    owner, ledger, outer, calls = _scenario(tmp_path, monkeypatch)
    monkeypatch.setattr(recovery, "foreground_terminal", lambda *a, **kw: pytest.fail("generic terminal bypass"))
    monkeypatch.setattr(recovery, "_recovery_interaction", lambda driver, **kw: calls.append(("history", kw)))

    def workflow(root, *, observer=None, recovery_cli=None):
        assert observer == owner.observe
        assert recovery_cli == owner.recovery_cli
        recovery_cli(root, create=True)
        observer(root, cancel_recovery=True)
        recovery_cli(root, create=False, historical="preserved")

    monkeypatch.setattr(recovery, "_observe_recovery_cancel", workflow)
    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(module, "runpy", SimpleNamespace(run_path=lambda path: ledger))
    monkeypatch.setenv(ledger["ENVIRONMENT_KEY"], str(outer["path"]))
    monkeypatch.setattr(module, "NativeScenario", lambda actual_ledger, parent: owner)
    module.scenario(tmp_path, "recovery-cancel")
    ledger["require_closed"](outer)
    assert [value for name, value in calls if name == "history"] == [
        {"create": True, "historical": None}, {"create": False, "historical": "preserved"},
    ]
