"""The ARD-004 re-evaluation must never masquerade as a new measurement."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts/dev/reevaluate_g18_comparison.py"
)
SPEC = importlib.util.spec_from_file_location("reevaluate_g18_comparison", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

COMPARISON = module._support("_g18_comparison")


def campaign(*, cases=("managed-mux",), cache_mode="warm", samples=None):
    if samples is None:
        samples = [
            {
                "case": cases[0],
                "side": side,
                "block": block,
                "pair": pair,
                "warmup": pair == -1,
                "valid": True,
                "failure": None,
                "status": "complete",
                "cache_mode": cache_mode,
                # MANAGED_METRICS already carries the _seconds suffix.
                "milestones": {
                    name: 1.0 for name in COMPARISON.MANAGED_METRICS["managed-mux"]
                },
            }
            for block in range(2)
            for pair in range(-1, 10)
            for side in ("a", "b")
        ]
    return {
        "schema_version": 3,
        "status": "complete-record-only",
        "cases": list(cases),
        "blocks": 2,
        "pairs_per_block": 10,
        "samples": samples,
        "comparison": {"verdict": "inconclusive", "phase": "aa", "cache_mode": cache_mode},
    }


def write(tmp_path, value, name="report.json"):
    path = tmp_path / name
    path.write_text(json.dumps(value))
    return path


def test_reevaluation_records_contract_change_and_never_claims_acceptance(tmp_path):
    source = write(tmp_path, campaign())
    out = tmp_path / "reevaluation.json"
    value = module.reevaluate(source, out)
    assert value["verdict"] == "pass"
    assert value["source_verdict_before"] == "inconclusive"
    assert value["record_kind"] == "g18-contract-reevaluation-not-a-new-measurement"
    assert value["claims"]["is_new_measurement"] is False
    assert value["claims"]["is_performance_acceptance"] is False
    assert value["contract"]["stability_ratio"] == str(COMPARISON.STABILITY_RATIO)
    assert value["contract"]["regression_ratio"] == str(COMPARISON.REGRESSION_RATIO)
    # The original report must be byte-identical after re-evaluation.
    assert module.digest(source) == value["source_report_sha256"]


def test_reevaluation_binds_the_exact_source_bytes(tmp_path):
    source = write(tmp_path, campaign())
    first = module.reevaluate(source, tmp_path / "a.json")
    # Any byte change to the source changes the recorded binding.
    data = json.loads(source.read_text())
    data["samples"][0]["milestones"]["cold_frame_seconds"] = 1.5
    source.write_text(json.dumps(data))
    second = module.reevaluate(source, tmp_path / "b.json")
    assert first["source_report_sha256"] != second["source_report_sha256"]


def test_reevaluation_refuses_to_overwrite(tmp_path):
    source = write(tmp_path, campaign())
    out = tmp_path / "out.json"
    out.write_text("{}")
    with pytest.raises(ValueError, match="refusing to overwrite"):
        module.reevaluate(source, out)


@pytest.mark.parametrize("status", ["running", "failed", "paused"])
def test_reevaluation_refuses_an_incomplete_campaign(tmp_path, status):
    data = campaign()
    data["status"] = status
    with pytest.raises(ValueError, match="completed uninterrupted campaign"):
        module.reevaluate(write(tmp_path, data), tmp_path / "out.json")


def test_reevaluation_accepts_one_uninterrupted_checkpoint_segment(tmp_path):
    # A --checkpoint campaign that never resumed has exactly one segment and
    # stays automatically eligible.
    data = campaign()
    data["segments"] = [{"number": 0, "first_index": 0, "next_index": 44}]
    data["segmented_acceptance"] = {
        "eligible_for_automatic_acceptance": True,
        "reason": "single uninterrupted segment; original gates still required",
    }
    assert module.reevaluate(write(tmp_path, data), tmp_path / "out.json")["verdict"] == "pass"


@pytest.mark.parametrize(
    "segments,acceptance",
    [
        ([{"number": 0}, {"number": 1}], {"eligible_for_automatic_acceptance": True}),
        ([{"number": 0}], {"eligible_for_automatic_acceptance": False}),
        ([{"number": 0}], None),
    ],
)
def test_reevaluation_refuses_a_resumed_or_ineligible_campaign(
    tmp_path, segments, acceptance
):
    data = campaign()
    data["segments"] = segments
    if acceptance is not None:
        data["segmented_acceptance"] = acceptance
    with pytest.raises(ValueError, match="calibration audit"):
        module.reevaluate(write(tmp_path, data), tmp_path / "out.json")


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("blocks", 1, "two-block ten-pair"),
        ("pairs_per_block", 5, "two-block ten-pair"),
        ("cases", ["not-a-case"], "frozen comparison policy"),
    ],
)
def test_reevaluation_refuses_an_unfrozen_policy(tmp_path, field, value, message):
    data = campaign()
    data[field] = value
    with pytest.raises(ValueError, match=message):
        module.reevaluate(write(tmp_path, data), tmp_path / "out.json")


def test_reevaluation_refuses_a_missing_phase_or_cache_condition(tmp_path):
    data = campaign()
    data["comparison"] = {}
    with pytest.raises(ValueError, match="phase or cache condition"):
        module.reevaluate(write(tmp_path, data), tmp_path / "out.json")


def test_reevaluation_does_not_mutate_the_source_file(tmp_path):
    source = write(tmp_path, campaign())
    before = copy.deepcopy(json.loads(source.read_text()))
    module.reevaluate(source, tmp_path / "out.json")
    assert json.loads(source.read_text()) == before


def test_regression_beyond_the_accepted_ratio_is_still_reported(tmp_path):
    # Phase "ab" with a stable candidate that sits above the accepted ratio.
    # (In a real A/A both sides are the same wheel, so the cross-side
    # "calibrated" rule legitimately rejects a large split like this one.)
    samples = campaign()["samples"]
    regressed = 1.0 * (1 + float(COMPARISON.REGRESSION_RATIO)) + 0.05
    for sample in samples:
        for name in COMPARISON.MANAGED_METRICS["managed-mux"]:
            sample["milestones"][name] = regressed if sample["side"] == "b" else 1.0
            # Small symmetric dispersion keeps both sides internally stable.
            sample["milestones"][name] += 0.001 * (sample["pair"] % 3)
    data = campaign(samples=samples)
    data["comparison"] = {"verdict": "inconclusive", "phase": "ab", "cache_mode": "warm"}
    source = write(tmp_path, data)
    value = module.reevaluate(source, tmp_path / "out.json")
    assert value["verdict"] == "regression"
    assert value["comparison"]["cases"]["managed-mux"]["cold_frame_seconds"]["verdict"] == (
        "regression"
    )
