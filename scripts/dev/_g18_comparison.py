"""Pure G18 paired-sample comparison; callers must validate provenance first.

This module neither starts Product processes nor changes runtime budgets. A
passing statistical verdict alone is not a delivery or platform acceptance.
"""

from __future__ import annotations

import math
import statistics
from fractions import Fraction

PRIORITY_HELP = {"cli-help", "hosted-tui-help"}
A_ELAPSED_CASES = {
    "import-harness",
    "import-coding",
    "import-cli",
    "cli-help",
    "cli-version",
    "tui-help",
    "hosted-help",
    "hosted-tui-help",
    "mux-help",
    "plugin-help",
}

# Reviewed pre-candidate policy: each cache condition checks all 41 metrics.
NATIVE_METRICS = {
    "embedded": (
        "ready_frame_seconds",
        "first_command_seconds",
        "spawn_through_first_command_seconds",
        "panel_close_observation_seconds",
        "settlement_seconds",
    ),
    "foreground": (
        "ready_frame_seconds",
        "first_command_seconds",
        "spawn_through_first_command_seconds",
        "settlement_seconds",
    ),
    "local-mux": (
        "server_ready_seconds",
        "attach_frame_seconds",
        "first_command_seconds",
        "spawn_through_first_command_seconds",
        "detach_settlement_seconds",
        "stop_settlement_seconds",
    ),
    "g14-stdio": (
        "protocol_ready_seconds",
        "first_command_seconds",
        "settlement_seconds",
    ),
    "recovery-cwd": (
        "ready_frame_seconds",
        "history_visible_seconds",
        "first_command_seconds",
        "spawn_through_first_command_seconds",
        "settlement_seconds",
    ),
    "recovery-global": (
        "ready_frame_seconds",
        "history_visible_seconds",
        "first_command_seconds",
        "spawn_through_first_command_seconds",
        "settlement_seconds",
    ),
    "product-first-use": (
        "server_ready_seconds",
        "review_attach_frame_seconds",
        "dev_attach_frame_seconds",
        "reattach_frame_seconds",
        "first_model_seconds",
        "spawn_through_first_model_seconds",
        "first_approval_seconds",
        "first_tool_seconds",
        "interrupt_seconds",
        "review_detach_settlement_seconds",
        "dev_detach_settlement_seconds",
        "reattach_detach_settlement_seconds",
        "settlement_seconds",
    ),
}


def compare_case(
    samples,
    *,
    case,
    metric="elapsed_seconds",
    blocks=2,
    pairs_per_block=10,
    phase="ab",
):
    """Apply the pre-candidate frozen policy, never cross-variant stability.

    Every declared pair and warmup must exist exactly once and have succeeded.
    Small diagnostic/preflight runs cannot produce a passing comparison.
    Threshold arithmetic is exact over each input's round-trip decimal spelling;
    no epsilon, rounding-to-pass or ambient Decimal context is used.
    """
    if case not in A_ELAPSED_CASES or metric != "elapsed_seconds":
        raise ValueError("unfrozen case/metric policy")
    return _compare(
        samples,
        case=case,
        metric=metric,
        blocks=blocks,
        pairs_per_block=pairs_per_block,
        phase=phase,
        required_gain=Fraction(3, 10)
        if phase == "ab" and case in PRIORITY_HELP
        else None,
    )


def compare_native(samples, *, cache_mode, phase="ab", blocks=2, pairs_per_block=10):
    """All native cases/metrics in one condition, after caller provenance gates."""
    if (
        type(blocks) is not int
        or type(pairs_per_block) is not int
        or blocks != 2
        or pairs_per_block != 10
    ):
        raise ValueError(
            "native policy requires exactly two blocks of ten pairs (twenty pairs)"
        )
    if cache_mode not in {"warm", "absent"}:
        raise ValueError("explicit native cache condition required")
    for sample in samples:
        case = sample.get("case")
        milestones = sample.get("milestones")
        if (
            type(case) is not str
            or case not in NATIVE_METRICS
            or sample.get("cache_mode") != cache_mode
            or sample.get("status") != "complete"
            or type(milestones) is not dict
            or set(milestones) != set(NATIVE_METRICS[case])
        ):
            raise ValueError(
                "incomplete native case, cache condition or metric inventory"
            )
    results = {}
    for case, metrics in NATIVE_METRICS.items():
        results[case] = {}
        for metric in metrics:
            projected = [
                {**sample, metric: sample["milestones"][metric]}
                for sample in samples
                if sample["case"] == case
            ]
            results[case][metric] = _compare(
                projected,
                case=case,
                metric=metric,
                blocks=blocks,
                pairs_per_block=pairs_per_block,
                phase=phase,
                required_gain=None,
            )
    verdicts = {
        value["verdict"] for metrics in results.values() for value in metrics.values()
    }
    return dict(
        cache_mode=cache_mode,
        phase=phase,
        cases=results,
        verdict="regression"
        if "regression" in verdicts
        else "inconclusive"
        if "inconclusive" in verdicts
        else "pass",
    )


def _compare(samples, *, case, metric, blocks, pairs_per_block, phase, required_gain):
    if phase not in {"aa", "ab"}:
        raise ValueError("explicit aa calibration or ab comparison required")
    if type(blocks) is not int or type(pairs_per_block) is not int:
        raise ValueError("integer block/pair counts required")
    if blocks < 2 or pairs_per_block < 1 or blocks * pairs_per_block < 20:
        raise ValueError("two blocks and at least twenty pairs required")
    expected = {
        (block, pair, side)
        for block in range(blocks)
        for pair in range(-1, pairs_per_block)
        for side in ("a", "b")
    }
    observed = {}
    for sample in samples:
        if sample.get("case") != case:
            continue
        if (
            sample.get("valid") is not True
            or sample.get("failure") is not None
            or type(sample.get("block")) is not int
            or type(sample.get("pair")) is not int
            or type(sample.get("warmup")) is not bool
            or sample["warmup"] != (sample["pair"] == -1)
        ):
            raise ValueError("failed or malformed sample cannot be compared")
        key = sample["block"], sample["pair"], sample.get("side")
        if key not in expected or key in observed:
            raise ValueError("duplicate or unexpected sample identity")
        duration = sample.get(metric)
        if (
            type(duration) not in (int, float)
            or not math.isfinite(duration)
            or duration <= 0
        ):
            raise ValueError("missing or invalid measurement")
        observed[key] = Fraction(str(duration))
    if observed.keys() != expected:
        raise ValueError("missing declared pairs or warmups")
    variants = {}
    for side in ("a", "b"):
        groups = [
            [observed[block, pair, side] for pair in range(pairs_per_block)]
            for block in range(blocks)
        ]
        medians = [statistics.median(group) for group in groups]
        mads = [
            statistics.median(abs(item - median) for item in group)
            for group, median in zip(groups, medians, strict=True)
        ]
        stable = max(medians) - min(medians) <= max(
            min(medians) / 10, Fraction(1, 50)
        ) and all(
            mad <= max(median / 10, Fraction(1, 100))
            for mad, median in zip(mads, medians, strict=True)
        )
        ordered = sorted(item for group in groups for item in group)
        variants[side] = {
            "stable": stable,
            "block_medians": medians,
            "block_mads": mads,
            "median_seconds": statistics.median(ordered),
            "p95_seconds_descriptive": ordered[(95 * len(ordered) + 99) // 100 - 1],
            "samples": len(ordered),
        }
    baseline = variants["a"]["median_seconds"]
    candidate = variants["b"]["median_seconds"]
    improvement = 1 - candidate / baseline
    regression_limit = max(baseline / 10, Fraction(1, 50))
    all_medians = [
        value for variant in variants.values() for value in variant["block_medians"]
    ]
    calibrated = max(all_medians) - min(all_medians) <= max(
        min(all_medians) / 10, Fraction(1, 50)
    )
    if not all(variant["stable"] for variant in variants.values()) or (
        phase == "aa" and not calibrated
    ):
        verdict = "inconclusive"
    elif candidate - baseline > regression_limit:
        verdict = "regression"
    elif required_gain is not None and candidate > baseline * (1 - required_gain):
        verdict = "target-not-met"
    else:
        verdict = "pass"
    return {
        "case": case,
        "metric": metric,
        "phase": phase,
        "verdict": verdict,
        "variants": {
            side: {
                key: [float(item) for item in value]
                if type(value) is list
                else float(value)
                if isinstance(value, Fraction)
                else value
                for key, value in facts.items()
            }
            for side, facts in variants.items()
        },
        "improvement_fraction": float(improvement),
        "required_gain_fraction": float(required_gain)
        if required_gain is not None
        else None,
        "regression_limit_seconds": float(regression_limit),
    }
