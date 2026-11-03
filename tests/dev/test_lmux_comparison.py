"""Independent inventory and fail-closed checks for the optional managed policy."""

from __future__ import annotations

import copy

import pytest

from .test_g18_comparison import comparison, samples

EXPECTED = (
    "cold_frame first_completion first_member_ready cold_through_first_member "
    "warm_member_ready detach_settlement warm_attach_frame "
    "reattach_detach_settlement stop_settlement"
).split()

PRODUCT_EXPECTED = (
    "fixed_entry_through_visible_reply visible_reply approval_pending approval_details "
    "approved_tool_reply interrupt_through_idle_and_producer next_reply interrupt_through_next_reply"
).split()


@pytest.mark.parametrize("case,names", [
    ("managed-product-history-warm", ("history_frame_seconds", "history_completion_seconds")),
    ("managed-product-history-restore", ("restored_history_frame_seconds",)),
])
@pytest.mark.parametrize("fault", [None, "regression", "missing", "extra", "unfinished"])
def test_history_uses_exact_independent_inventory(case, names, fault):
    data = managed_samples()
    for item in data:
        item.update(case=case, milestones={name: 1.0 for name in names})
        if fault == "regression" and item["side"] == "b":
            item["milestones"][names[0]] = REGRESSED
    if fault == "missing":
        data.pop()
    elif fault == "extra":
        data[-1]["milestones"]["unknown_seconds"] = 1.0
    elif fault == "unfinished":
        data[-1]["status"] = "observed"
    if fault in {"missing", "extra", "unfinished"}:
        with pytest.raises(ValueError):
            comparison.compare_managed_history(data, case=case, cache_mode="warm")
    else:
        result = comparison.compare_managed_history(data, case=case, cache_mode="warm")
        assert result["verdict"] == ("pass" if fault is None else "regression")
        assert set(result["cases"][case]) == set(names)
    assert case not in comparison.NATIVE_METRICS


@pytest.mark.parametrize("fault", [None, *PRODUCT_EXPECTED, "missing", "extra", "unfinished"])
def test_first_use_policy_checks_every_metric_without_changing_old_inventory(fault):
    data = managed_samples()
    for item in data:
        item["case"] = "managed-product-first-use"
        item["milestones"] = {name + "_seconds": 1.0 for name in PRODUCT_EXPECTED}
        if fault in PRODUCT_EXPECTED and item["side"] == "b":
            item["milestones"][fault + "_seconds"] = REGRESSED
    before = copy.deepcopy(data)
    if fault == "missing":
        data.pop()
    elif fault == "extra":
        data[-1]["milestones"]["unknown_seconds"] = 1.0
    elif fault == "unfinished":
        data[-1]["status"] = "observed"
    if fault in {"missing", "extra", "unfinished"}:
        with pytest.raises(ValueError):
            comparison.compare_managed_product(data, cache_mode="warm")
    else:
        result = comparison.compare_managed_product(data, cache_mode="warm")
        assert result["verdict"] == ("pass" if fault is None else "regression")
        assert set(result["cases"]["managed-product-first-use"]) == {name + "_seconds" for name in PRODUCT_EXPECTED}
        assert data == before
    assert set(comparison.MANAGED_METRICS) == {"managed-mux"}
    assert "managed-product-first-use" not in comparison.NATIVE_METRICS


# Accepted ARD-004 regression ratio; a pin below it is no longer a regression.
REGRESSED = 1.0 * (1 + float(comparison.REGRESSION_RATIO)) + 0.01


def managed_samples(cache_mode="warm"):
    result = []
    for sample in samples(case="managed-mux", left=1.0, right=1.0):
        duration = sample.pop("elapsed_seconds")
        result.append({
            **sample, "status": "complete", "cache_mode": cache_mode,
            "milestones": {name + "_seconds": duration for name in EXPECTED},
        })
    return result


@pytest.mark.parametrize("phase", ["aa", "ab"])
@pytest.mark.parametrize("cache_mode", ["warm", "absent"])
def test_managed_comparison_exact_inventory_and_no_input_mutation(phase, cache_mode):
    data = managed_samples(cache_mode)
    before = copy.deepcopy(data)
    result = comparison.compare_managed(data, cache_mode=cache_mode, phase=phase)
    assert result["verdict"] == "pass"
    assert set(result["cases"]) == {"managed-mux"}
    assert set(result["cases"]["managed-mux"]) == {name + "_seconds" for name in EXPECTED}
    assert data == before
    for metric in result["cases"]["managed-mux"].values():
        assert all(variant["mean_seconds_descriptive"] == 1.0 for variant in metric["variants"].values())
    assert "managed-mux" not in comparison.NATIVE_METRICS
    with pytest.raises(ValueError):
        comparison.compare_native(data, cache_mode=cache_mode)


@pytest.mark.parametrize("metric", EXPECTED)
def test_each_managed_metric_regression_prevents_pass(metric):
    data = managed_samples()
    for sample in data:
        if sample["side"] == "b":
            sample["milestones"][metric + "_seconds"] = REGRESSED
    assert comparison.compare_managed(data, cache_mode="warm")["verdict"] == "regression"


@pytest.mark.parametrize("fault", [
    "missing", "duplicate", "warmup", "unfinished", "debt", "extra-metric",
    "missing-metric", "wrong-case", "wrong-cache", "nan", "boolean", "small",
])
def test_managed_invalid_or_incomplete_evidence_cannot_pass(fault):
    data = managed_samples()
    kwargs = {"cache_mode": "warm"}
    if fault == "missing":
        data.pop()
    elif fault == "duplicate":
        data.append(data[-1])
    elif fault == "warmup":
        data[0]["valid"] = False
    elif fault == "unfinished":
        data[-1]["status"] = "observed"
    elif fault == "debt":
        data[-1]["failure"] = "cleanup_pending"
    elif fault == "extra-metric":
        data[-1]["milestones"]["unreviewed_seconds"] = 1.0
    elif fault == "missing-metric":
        del data[-1]["milestones"]["stop_settlement_seconds"]
    elif fault == "wrong-case":
        data[-1]["case"] = "local-mux"
    elif fault == "wrong-cache":
        data[-1]["cache_mode"] = "absent"
    elif fault == "small":
        kwargs["pairs_per_block"] = 1
    else:
        data[-1]["milestones"]["first_completion_seconds"] = float("nan") if fault == "nan" else True
    with pytest.raises(ValueError):
        comparison.compare_managed(data, **kwargs)
