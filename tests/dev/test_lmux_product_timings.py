"""Pure timing subset tests; no claim of whole-sample acceptance."""

import pytest

from .test_measure_g18_native import runner


def values(scenario):
    intervals = {
        "reply": {"fixed_entry_through_visible_reply": (1.0, 9.0), "visible_reply": (6.0, 9.0)},
        "approval": {"approval_pending": (1.0, 2.0), "approval_details": (4.0, 6.0),
                     "approved_tool_reply": (8.0, 11.0)},
        "interrupt": {"interrupt_through_idle_and_producer": (10.0, 12.0),
                      "next_reply": (20.0, 25.0), "interrupt_through_next_reply": (10.0, 25.0)},
    }[scenario]
    return ({key: {"started_at": start, "finished_at": end} for key, (start, end) in intervals.items()},
            {key + "_seconds": end - start for key, (start, end) in intervals.items()})


@pytest.mark.parametrize("scenario", ["reply", "approval", "interrupt"])
@pytest.mark.parametrize("fault", [None, "missing", "extra", "boolean", "nan", "negative", "duration", "reversed", "extra-endpoint"])
def test_exact_timing_subset(scenario, fault):
    actions, milestones = values(scenario)
    first = next(iter(actions))
    if fault == "missing":
        milestones.pop(first + "_seconds")
    elif fault == "extra":
        milestones["unknown_seconds"] = 1.0
    elif fault in {"boolean", "nan", "negative"}:
        actions[first]["started_at"] = {"boolean": True, "nan": float("nan"), "negative": -1.0}[fault]
    elif fault == "duration":
        milestones[first + "_seconds"] += 1.0
    elif fault == "reversed":
        actions[first]["started_at"] = actions[first]["finished_at"] + 1.0
    elif fault == "extra-endpoint":
        actions[first]["observed_at"] = 1.0
    if fault is None:
        runner.validate_managed_product_timings(actions, milestones, scenario)
    else:
        with pytest.raises(ValueError):
            runner.validate_managed_product_timings(actions, milestones, scenario)


@pytest.mark.parametrize("scenario", ["reply", "approval", "interrupt"])
def test_matching_durations_do_not_hide_wrong_shared_endpoints_or_order(scenario):
    actions, milestones = values(scenario)
    if scenario == "reply":
        actions["fixed_entry_through_visible_reply"]["finished_at"] += 1.0
    elif scenario == "approval":
        actions["approval_details"]["started_at"] = 1.0
    else:
        # Summing the two segments loses the eight-second gap.
        actions["interrupt_through_next_reply"]["finished_at"] = 17.0
    for name, action in actions.items():
        milestones[name + "_seconds"] = action["finished_at"] - action["started_at"]
    with pytest.raises(ValueError):
        runner.validate_managed_product_timings(actions, milestones, scenario)


@pytest.mark.parametrize("value", [True, float("inf"), float("-inf"), float("nan"), 10**400, -1.0, "1"])
@pytest.mark.parametrize("target", ["endpoint", "duration"])
def test_invalid_numeric_values_are_rejected_without_conversion_overflow(value, target):
    actions, milestones = values("reply")
    if target == "endpoint":
        actions["visible_reply"]["started_at"] = value
    else:
        milestones["visible_reply_seconds"] = value
    with pytest.raises(ValueError):
        runner.validate_managed_product_timings(actions, milestones, "reply")


@pytest.mark.parametrize("scenario", [None, [], {}, "unknown"])
def test_unknown_scenario_fails_before_inspecting_payload(scenario):
    with pytest.raises(ValueError, match="unknown"):
        runner.validate_managed_product_timings(None, None, scenario)
