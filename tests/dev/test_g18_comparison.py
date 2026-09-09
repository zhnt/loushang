from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/dev/_g18_comparison.py"
SPEC = importlib.util.spec_from_file_location("_g18_comparison", SCRIPT)
comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparison)

# Independent inventory from the reviewed 41-metric comparison contract.
NATIVE_EXPECTED = {
    "embedded": "ready_frame first_command spawn_through_first_command panel_close_observation settlement",
    "foreground": "ready_frame first_command spawn_through_first_command settlement",
    "local-mux": "server_ready attach_frame first_command spawn_through_first_command detach_settlement stop_settlement",
    "g14-stdio": "protocol_ready first_command settlement",
    "recovery-cwd": "ready_frame history_visible first_command spawn_through_first_command settlement",
    "recovery-global": "ready_frame history_visible first_command spawn_through_first_command settlement",
    "product-first-use": "server_ready review_attach_frame dev_attach_frame reattach_frame first_model spawn_through_first_model first_approval first_tool interrupt review_detach_settlement dev_detach_settlement reattach_detach_settlement settlement",
}


def native_samples(*, cache_mode="warm", left=1.0, right=1.0, blocks=2, pairs=10):
    result = []
    for case, metrics in NATIVE_EXPECTED.items():
        for sample in samples(
            case=case, left=left, right=right, blocks=blocks, pairs=pairs
        ):
            duration = sample.pop("elapsed_seconds")
            result.append(
                {
                    **sample,
                    "status": "complete",
                    "cache_mode": cache_mode,
                    "milestones": {
                        metric + "_seconds": duration for metric in metrics.split()
                    },
                }
            )
    return result


@pytest.mark.parametrize("cache_mode", ["warm", "absent"])
@pytest.mark.parametrize("phase", ["aa", "ab"])
def test_native_policy_checks_all_41_metrics_without_mutating_inputs(cache_mode, phase):
    import copy

    data = native_samples(cache_mode=cache_mode)
    before = copy.deepcopy(data)
    result = comparison.compare_native(data, cache_mode=cache_mode, phase=phase)
    assert result["verdict"] == "pass"
    assert data == before
    assert set(result["cases"]) == set(NATIVE_EXPECTED)
    assert sum(len(metrics) for metrics in result["cases"].values()) == 41
    for case, names in NATIVE_EXPECTED.items():
        assert set(result["cases"][case]) == {
            name + "_seconds" for name in names.split()
        }


@pytest.mark.parametrize(
    "case,metric",
    [
        (case, name + "_seconds")
        for case, names in NATIVE_EXPECTED.items()
        for name in names.split()
    ],
)
def test_any_native_metric_regression_is_not_hidden_by_gains_elsewhere(case, metric):
    data = native_samples(right=0.5)
    for sample in data:
        if sample["case"] == case and sample["side"] == "b":
            sample["milestones"][metric] = math.nextafter(1.1, math.inf)
    result = comparison.compare_native(data, cache_mode="warm")
    assert result["verdict"] == "regression"
    assert result["cases"][case][metric]["verdict"] == "regression"


@pytest.mark.parametrize(
    "fault",
    [
        "missing-case",
        "missing-metric",
        "extra-metric",
        "unknown-case",
        "mixed-cache",
        "unfinished",
        "warmup-failed",
        "duplicate",
        "missing-sample",
        "nan",
        "boolean",
    ],
)
def test_native_comparison_rejects_partial_or_mixed_evidence(fault):
    data = native_samples()
    if fault == "missing-case":
        data = [sample for sample in data if sample["case"] != "local-mux"]
    elif fault == "missing-metric":
        del data[-1]["milestones"]["reattach_detach_settlement_seconds"]
    elif fault == "extra-metric":
        data[-1]["milestones"]["unreviewed_seconds"] = 1.0
    elif fault == "unknown-case":
        data[-1]["case"] = "not-a-case"
    elif fault == "mixed-cache":
        data[-1]["cache_mode"] = "absent"
    elif fault == "unfinished":
        data[-1]["status"] = "observed"
    elif fault == "warmup-failed":
        data[0]["valid"] = False
    elif fault == "duplicate":
        data.append(data[-1])
    elif fault == "missing-sample":
        data.pop()
    else:
        data[-1]["milestones"]["first_model_seconds"] = (
            float("nan") if fault == "nan" else True
        )
    with pytest.raises(ValueError):
        comparison.compare_native(data, cache_mode="warm")


def test_native_aa_uses_all_four_group_medians_but_ab_preserves_real_gains():
    data = native_samples(left=10.0, right=7.0)
    assert (
        comparison.compare_native(data, cache_mode="warm", phase="aa")["verdict"]
        == "inconclusive"
    )
    assert (
        comparison.compare_native(data, cache_mode="warm", phase="ab")["verdict"]
        == "pass"
    )
    with pytest.raises(ValueError, match="twenty pairs"):
        comparison.compare_native(data, cache_mode="warm", blocks=1, pairs_per_block=1)
    with pytest.raises(ValueError, match="explicit aa"):
        comparison.compare_native(data, cache_mode="warm", phase="unknown")


def test_same_wheel_help_calibration_has_no_candidate_gain_requirement():
    result = comparison.compare_case(
        samples(left=10.0, right=10.0), case="cli-help", phase="aa"
    )
    assert result["verdict"] == "pass"
    assert result["required_gain_fraction"] is None


@pytest.mark.parametrize("blocks,pairs", [(4, 5), (20, 1), (True, 20), (2, True)])
def test_native_policy_rejects_unreviewed_grouping(blocks, pairs):
    with pytest.raises(ValueError):
        comparison.compare_native(
            native_samples(blocks=blocks, pairs=pairs),
            cache_mode="warm",
            blocks=blocks,
            pairs_per_block=pairs,
        )


def samples(*, case="cli-help", left=10.0, right=7.0, blocks=2, pairs=10):
    return [
        dict(
            case=case,
            valid=True,
            failure=None,
            block=block,
            pair=pair,
            side=side,
            warmup=pair == -1,
            elapsed_seconds=left if side == "a" else right,
        )
        for block in range(blocks)
        for pair in range(-1, pairs)
        for side in ("a", "b")
    ]


def test_large_real_gain_is_not_misclassified_as_cross_variant_instability():
    result = comparison.compare_case(samples(), case="cli-help")
    assert result["verdict"] == "pass"
    assert result["improvement_fraction"] == pytest.approx(0.3)
    assert all(side["stable"] for side in result["variants"].values())


@pytest.mark.parametrize(
    "case,right,expected",
    [
        ("cli-help", 8.0, "target-not-met"),
        ("hosted-tui-help", 7.0, "pass"),
        ("import-coding", 11.1, "regression"),
        ("mux-help", 10.5, "pass"),
    ],
)
def test_frozen_targets_and_no_regression_limits(case, right, expected):
    assert (
        comparison.compare_case(samples(case=case, right=right), case=case)["verdict"]
        == expected
    )


def test_candidate_block_drift_is_inconclusive_not_a_pass():
    data = samples()
    for sample in data:
        if sample["side"] == "b" and sample["block"] == 1:
            sample["elapsed_seconds"] = 5.0
    assert comparison.compare_case(data, case="cli-help")["verdict"] == "inconclusive"


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate",
        "failure",
        "warmup-failure",
        "nan",
        "zero",
        "wrong-warmup",
    ],
)
def test_missing_duplicated_failed_or_invalid_samples_are_never_ignored(fault):
    data = samples()
    if fault == "missing":
        data.pop()
    elif fault == "duplicate":
        data.append(data[-1])
    elif fault in {"failure", "warmup-failure"}:
        data[-1 if fault == "failure" else 0]["valid"] = False
    elif fault in {"nan", "zero"}:
        data[-1]["elapsed_seconds"] = float("nan") if fault == "nan" else 0
    else:
        data[-1]["warmup"] = True
    with pytest.raises(ValueError):
        comparison.compare_case(data, case="cli-help")


@pytest.mark.parametrize(
    "case,metric",
    [
        ("foreground", "first_command_seconds"),
        ("unknown", "elapsed_seconds"),
        ("cli-help", "child_user_seconds"),
    ],
)
def test_unfrozen_case_or_metric_is_not_silently_given_a_policy(case, metric):
    with pytest.raises(ValueError, match="unfrozen"):
        comparison.compare_case(samples(case=case), case=case, metric=metric)


@pytest.mark.parametrize(
    "case,left,boundary,rejected",
    [
        ("cli-help", 3.0, 2.1, "target-not-met"),
        ("import-coding", 0.3, 0.33, "regression"),
        ("import-harness", 0.1, 0.12, "regression"),
    ],
)
def test_exact_gain_and_regression_boundary_and_next_float(
    case, left, boundary, rejected
):
    assert (
        comparison.compare_case(
            samples(case=case, left=left, right=boundary), case=case
        )["verdict"]
        == "pass"
    )
    assert (
        comparison.compare_case(
            samples(case=case, left=left, right=math.nextafter(boundary, math.inf)),
            case=case,
        )["verdict"]
        == rejected
    )


@pytest.mark.parametrize("minimum,boundary", [(0.3, 0.33), (0.1, 0.12)])
@pytest.mark.parametrize("outside", [False, True])
def test_stability_span_boundary_is_exact(minimum, boundary, outside):
    data = samples(case="import-harness", left=minimum, right=minimum)
    for sample in data:
        if sample["block"] == 1:
            sample["elapsed_seconds"] = (
                math.nextafter(boundary, math.inf) if outside else boundary
            )
    result = comparison.compare_case(data, case="import-harness")
    assert result["verdict"] == ("inconclusive" if outside else "pass")


def test_preflight_cannot_be_reported_as_full_comparison():
    with pytest.raises(ValueError, match="twenty pairs"):
        comparison.compare_case(samples(), case="cli-help", blocks=1, pairs_per_block=1)


@pytest.mark.parametrize("low,high", [(0.9, 1.1), (0.09, 0.11)])
@pytest.mark.parametrize("outside", [False, True])
def test_mad_relative_and_absolute_boundaries(low, high, outside):
    data = samples(case="import-harness")
    for sample in data:
        sample["elapsed_seconds"] = (
            low
            if sample["pair"] < 5
            else (math.nextafter(high, math.inf) if outside else high)
        )
    result = comparison.compare_case(data, case="import-harness")
    assert result["verdict"] == ("inconclusive" if outside else "pass")
