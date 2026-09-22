from __future__ import annotations

import copy
import json
import os
import stat
from types import SimpleNamespace

import pytest

from .test_measure_g18_native import runner


def observation():
    return {
        "case": "managed-mux", "status": "observed", "valid": False,
        "authenticated_instance_id": "a" * 32,
        "milestones": {"cold_frame_seconds": 1.0},
        "managed_stop": {
            "started_at": 12.0,
            "result": {"status": "stopped", "instanceId": "a" * 32},
        },
    }


def test_stop_measurement_includes_outer_settlement_without_mutating_receipt():
    value = observation()
    original = copy.deepcopy(value)
    completed = runner.complete_managed_stop(value, observer_started=10.0, owner_settled=15.0)
    assert completed["milestones"] == {"cold_frame_seconds": 1.0, "stop_settlement_seconds": 3.0}
    assert completed["valid"] is False  # Remaining provenance checks must still run.
    assert value == original


@pytest.mark.parametrize("fault", [
    "before-launch", "after-settlement", "nan", "boolean", "wrong-instance",
    "unproven-instance", "requested", "unclean", "missing", "extra",
    "premature-duration", "failed-observer", "premature-valid",
])
def test_stop_measurement_rejects_unproven_or_premature_completion(fault):
    value = observation()
    stop = value["managed_stop"]
    if fault == "before-launch":
        stop["started_at"] = 9.0
    elif fault == "after-settlement":
        stop["started_at"] = 15.0
    elif fault == "nan":
        stop["started_at"] = float("nan")
    elif fault == "boolean":
        stop["started_at"] = True
    elif fault == "wrong-instance":
        stop["result"]["instanceId"] = "b" * 32
    elif fault == "unproven-instance":
        del value["authenticated_instance_id"]
    elif fault in {"requested", "unclean"}:
        stop["result"]["status"] = "stop_requested" if fault == "requested" else "exited_unclean"
    elif fault == "missing":
        del stop["result"]
    elif fault == "extra":
        stop["result"]["other"] = True
    elif fault == "premature-duration":
        value["milestones"]["stop_settlement_seconds"] = 0.1
    elif fault == "failed-observer":
        value["status"] = "failed"
    else:
        value["valid"] = True
    with pytest.raises(ValueError):
        runner.complete_managed_stop(value, observer_started=10.0, owner_settled=15.0)


@pytest.mark.parametrize("failure", [RuntimeError("cleanup debt"), KeyboardInterrupt()])
def test_outer_owner_failure_never_completes_managed_stop(tmp_path, monkeypatch, failure):
    def supervise(*args, **kwargs):
        raise failure

    monkeypatch.setattr(runner.owner, "run_python", supervise)
    monkeypatch.setattr(
        runner, "complete_managed_stop",
        lambda *args, **kwargs: pytest.fail("failed owner must not publish settlement"),
    )
    report, path = {"samples": []}, tmp_path / "report.json"
    with pytest.raises(type(failure)) as caught:
        runner.run_sample(
            tmp_path / "install", "managed-mux", tmp_path / "sample",
            tmp_path / "pyc", report, path, dict(side="a", block=0, pair=0),
            observer_prefix=tmp_path / "observer",
        )
    assert caught.value is failure
    (sample,) = json.loads(path.read_text())["samples"]
    assert sample["status"] == "failed" and sample["valid"] is False
    assert "stop_settlement_seconds" not in sample.get("milestones", {})


@pytest.mark.skipif(os.name != "posix", reason="POSIX managed ancestor modes")
@pytest.mark.parametrize("case", ["managed-mux", "managed-product-first-use"])
def test_managed_sample_parent_is_private_with_group_writable_umask(tmp_path, monkeypatch, case):
    sample_root = tmp_path / "sample"
    failure = RuntimeError("stop before launching")

    def supervise(*args, **kwargs):
        assert stat.S_IMODE(sample_root.stat().st_mode) == 0o700
        assert stat.S_IMODE((sample_root / "workspace").stat().st_mode) == 0o700
        raise failure

    monkeypatch.setattr(runner.owner, "run_python", supervise)
    previous = os.umask(0o002)
    try:
        with pytest.raises(RuntimeError) as caught:
            runner.run_sample(
                tmp_path / "install", case, sample_root,
                tmp_path / "pyc", {"samples": []}, tmp_path / "report.json",
                dict(side="a", block=0, pair=0), observer_prefix=tmp_path / "observer",
            )
        assert caught.value is failure
    finally:
        os.umask(previous)


@pytest.mark.skipif(os.name != "posix", reason="POSIX managed ancestor modes")
@pytest.mark.parametrize("case", ["managed-mux", "managed-product-first-use"])
def test_fixed_collector_creates_private_parent_before_control(tmp_path, monkeypatch, case):
    output, scratch = tmp_path / "output", tmp_path / "scratch"
    output.mkdir()
    scratch.mkdir(mode=0o700)
    failure = RuntimeError("stop before slot execution")

    def run(side, operation):
        root = scratch / "sample-1"
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
        assert (root / "control").is_dir()
        raise failure

    monkeypatch.setattr(
        runner.bytecode_policy, "BytecodePolicy",
        lambda *_: SimpleNamespace(external=lambda side: output / side),
    )
    slot = SimpleNamespace(run=run, receipt={})
    report = {"scratch": str(scratch), "samples": []}
    previous = os.umask(0o002)
    try:
        with pytest.raises(RuntimeError) as caught:
            runner.collect_fixed_native(
                slot, "warm", [case], 1, 1, tmp_path / "observer",
                {}, {}, output, report, output / "report.json",
            )
        assert caught.value is failure
    finally:
        os.umask(previous)
