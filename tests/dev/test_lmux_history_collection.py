"""Formal history dispatch cannot promote a receipt before the original owner."""

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from .test_lmux_history_restore_validation import evidence as restore_evidence
from .test_lmux_history_warm_validation import evidence as warm_evidence
from .test_measure_g18_native import runner


def collection(root, restored):
    evidence, bounds = restore_evidence() if restored else warm_evidence()
    prefix, observer = root.parent / "install", root.parent / "observer"

    def paths(value):
        if type(value) is dict:
            return {key: paths(item) for key, item in value.items()}
        if type(value) is list:
            return [paths(item) for item in value]
        if type(value) is str:
            return value.replace("/workspace", str(root / "workspace")).replace("/install", str(prefix))
        return value

    evidence = paths(evidence)
    value = dict.fromkeys(runner.OBSERVER_FIELDS)
    value.update(schema_version=2, case=runner.HISTORY_CASES[int(restored)], status="observed", valid=False,
                 measured_prefix=str(prefix), observer_prefix=str(observer),
                 observer_origin=str(observer / "lib/loushang/coding/__init__.py"),
                 sample_id=str(root.resolve()), seed="empty", seed_setup=[], milestones={})
    if restored:
        value.update(history_generations=evidence, fixed_product_history_restore=evidence["new"]["restored_history"],
                     spawns=[*evidence["old"]["spawns"], *evidence["new"]["spawns"]])
    else:
        value.update(evidence)
    return value, dict(prefix=prefix, root=root, observer_started=bounds["earliest"], owner_settled=bounds["latest"])


@pytest.mark.parametrize("restored", [False, True])
def test_original_receipt_remains_diagnostic_after_completion(tmp_path, restored):
    original_fields = set(runner.OBSERVER_FIELDS)
    value, bounds = collection(tmp_path, restored)
    before = copy.deepcopy(value)
    completed = runner.complete_managed_history(value, **bounds)
    assert value == before and completed["valid"] is False
    assert len(completed["milestones"]) == (1 if restored else 2)
    runner.validate_observation(completed, value["case"], bounds["prefix"], tmp_path, tmp_path.parent / "observer")
    assert runner.OBSERVER_FIELDS == original_fields


@pytest.mark.parametrize("restored", [False, True])
@pytest.mark.parametrize("outcome", ["complete", "deferred", "failure", "cancel", "wrong-install"])
def test_original_run_sample_owns_promotion(tmp_path, monkeypatch, restored, outcome):
    root = tmp_path / "sample"
    value, parameters = collection(root, restored)
    prefix, observer = parameters["prefix"], tmp_path / "observer"
    if outcome == "wrong-install":
        value["observer_prefix"] = str(tmp_path / "unrelated")
    events, clock = [], iter((parameters["observer_started"], parameters["owner_settled"]))
    monkeypatch.setattr(runner, "time", SimpleNamespace(perf_counter=lambda: next(clock)))
    failure = asyncio.CancelledError() if outcome == "cancel" else RuntimeError("original cleanup failed")

    def supervise(argv, **kwargs):
        assert argv[4] == value["case"]
        assert kwargs["timeout"] == (1980 if restored else 1380)
        runner.inert.write_report(root / "native.json", value)
        if outcome in {"failure", "cancel"}:
            raise failure
        events.append("owner-return")

    original = runner.complete_managed_history

    def complete(*args, **kwargs):
        assert events == ["owner-return"]
        return original(*args, **kwargs)

    monkeypatch.setattr(runner.owner, "run_python", supervise)
    monkeypatch.setattr(runner, "complete_managed_history", complete)
    report, path = {"samples": []}, tmp_path / "report.json"

    def run():
        runner.run_sample(prefix, value["case"], root, tmp_path / "pyc", report, path,
            dict(side="a", block=0, pair=0), observer_prefix=observer, defer_validation=outcome == "deferred")

    if outcome in {"failure", "cancel", "wrong-install"}:
        with pytest.raises(ValueError if outcome == "wrong-install" else type(failure)):
            run()
    else:
        run()
    sample, = json.loads(path.read_text())["samples"]
    assert sample["valid"] is (outcome == "complete")
    if outcome in {"failure", "cancel"}:
        assert events == [] and sample["status"] == "failed"
        assert "outer_settlement" not in sample and sample["partial_observation"] == value
    elif outcome == "wrong-install":
        assert sample["status"] == "failed"
    else:
        assert sample["status"] == ("observed" if outcome == "deferred" else "complete")
        assert "outer_settlement" in sample
        assert ("history_generations" if restored else "fixed_product_history") in sample


@pytest.mark.parametrize("restored", [False, True])
@pytest.mark.parametrize("fault", ["late-owner", "missing-owner", "boolean-owner", "extra-raw", "precomputed",
                                  "wrong-seed", "wrong-summary", "wrong-sample"])
def test_failed_or_tampered_receipt_never_promotes(tmp_path, restored, fault):
    value, bounds = collection(tmp_path, restored)
    if fault == "late-owner":
        bounds["observer_started"] = 2.0
    elif fault == "missing-owner":
        bounds["owner_settled"] = None
    elif fault == "boolean-owner":
        bounds["owner_settled"] = True
    elif fault == "extra-raw":
        value["cleanup_failure"] = "OSError"
    elif fault == "precomputed":
        value["milestones"] = {"history_frame_seconds": 1.0}
    elif fault == "wrong-seed":
        value["seed_setup"] = ["unknown-seed"]
    elif fault == "wrong-sample":
        value["sample_id"] = "/other"
    else:
        completed = runner.complete_managed_history(value, **bounds)
        completed["milestones"][next(iter(completed["milestones"]))] += 1.0
        with pytest.raises(ValueError):
            runner.validate_observation(completed, value["case"], bounds["prefix"], tmp_path, tmp_path.parent / "observer")
        return
    with pytest.raises(ValueError):
        runner.complete_managed_history(value, **bounds)
