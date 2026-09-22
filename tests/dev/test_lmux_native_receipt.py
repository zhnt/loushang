from __future__ import annotations

import copy
import json

import pytest

from .test_lmux_comparison import EXPECTED
from .test_measure_g18_native import observation, runner


def managed_receipt(prefix, root, observer=None):
    value = observation(prefix, root, observer)
    value.update(
        case="managed-mux", authenticated_instance_id="a" * 32,
        milestones={name + "_seconds": 1.0 for name in EXPECTED},
        managed_stop={"started_at": 18.0, "result": {"status": "stopped", "instanceId": "a" * 32}},
        spawns=[
            {"pid": 101, "start": 10.0, "argv": [str(prefix / "bin/lmux"), "new", "-s", "perf"],
             "cwd": str(root / "workspace")},
            {"pid": 102, "start": 15.0, "argv": [str(prefix / "bin/lmux"), "attach", "-t", "perf"],
             "cwd": str(root / "workspace/elsewhere")},
        ],
    )
    members = [{"memberId": "member-1", "sessionId": "session-1"},
               {"memberId": "member-2", "sessionId": "session-2"}]
    value["managed_observations"] = [
        {"stage": stage, "observed_at": at, "instanceId": "a" * 32,
         "serviceId": "b" * 64, "muxId": "mux-perf", "members": copy.deepcopy(members[:count])}
        for stage, at, count in (("first-member", 12.0, 1), ("second-member", 13.0, 2),
                                 ("detached", 14.0, 2), ("reattached", 16.0, 2))
    ]
    value["managed_actions"] = {
        name: {"started_at": start, "finished_at": end}
        for name, start, end in (("first_completion", 10.1, 10.2),
                                 ("first_member_ready", 10.2, 11.0),
                                 ("warm_member_ready", 12.0, 13.0),
                                 ("detach_settlement", 13.0, 14.0),
                                 ("reattach_detach_settlement", 16.0, 17.0))
    }
    for name, action in value["managed_actions"].items():
        value["milestones"][name + "_seconds"] = action["finished_at"] - action["started_at"]
    value["milestones"]["cold_frame_seconds"] = 10.1 - 10.0
    return value


def test_managed_receipt_preserves_old_default_cases_and_exact_member_sequence(tmp_path):
    value = managed_receipt(tmp_path, tmp_path)
    original = copy.deepcopy(value)
    runner.validate_observation(value, "managed-mux", tmp_path, tmp_path, tmp_path)
    assert value == original
    assert "managed-mux" not in runner.CASES  # Explicit opt-in never changes old defaults.
    # Preserve the original intent (opt-in cases never leak into the defaults).
    # The optional tuple legitimately grew when the history cases were added, so
    # assert membership rather than a frozen snapshot of the whole tuple.
    assert set(runner.OPTIONAL_CASES) >= {"managed-mux", "managed-product-first-use"}
    assert set(runner.HISTORY_CASES).isdisjoint(runner.CASES)
    assert set(runner.OPTIONAL_CASES).isdisjoint(runner.CASES)


@pytest.mark.parametrize("fault", [
    "wrong-install", "same-cwd", "wrong-argv", "missing-frame-metric", "extra-metric",
    "no-live-query", "old-instance", "new-service", "new-mux", "replaced-first",
    "reordered-tabs", "duplicate-session", "missing-member", "stale-query",
    "query-before-frame", "attach-before-detach", "wrong-stop", "early-stop", "dirty-seed",
    "late-attach-frame", "late-cold-frame", "missing-action", "duration-mismatch", "late-detach",
])
def test_managed_receipt_rejects_incomplete_or_mismatched_evidence(tmp_path, fault):
    value = managed_receipt(tmp_path, tmp_path)
    records = value["managed_observations"]
    if fault == "wrong-install":
        value["measured_prefix"] = "/wrong"
    elif fault == "same-cwd":
        value["spawns"][1]["cwd"] = value["spawns"][0]["cwd"]
    elif fault == "wrong-argv":
        value["spawns"][1]["argv"][-1] = "other"
    elif fault == "missing-frame-metric":
        del value["milestones"]["warm_attach_frame_seconds"]
    elif fault == "extra-metric":
        value["milestones"]["unreviewed_seconds"] = 1.0
    elif fault == "no-live-query":
        records.pop(2)
    elif fault == "old-instance":
        records[-1]["instanceId"] = "c" * 32
    elif fault == "new-service":
        records[-1]["serviceId"] = "c" * 64
    elif fault == "new-mux":
        records[-1]["muxId"] = "other"
    elif fault == "replaced-first":
        records[1]["members"][0]["memberId"] = "other"
    elif fault == "reordered-tabs":
        records[-1]["members"].reverse()
    elif fault == "duplicate-session":
        records[1]["members"][1]["sessionId"] = "session-1"
    elif fault == "missing-member":
        records[-1]["members"].pop()
    elif fault == "stale-query":
        records[-1]["observed_at"] = 13.0
    elif fault == "query-before-frame":
        records[0]["observed_at"] = 10.5
    elif fault == "attach-before-detach":
        value["spawns"][1]["start"] = 13.5
    elif fault == "wrong-stop":
        value["managed_stop"]["result"]["instanceId"] = "c" * 32
    elif fault == "early-stop":
        value["managed_stop"]["started_at"] = 15.0
    elif fault == "late-attach-frame":
        value["milestones"]["warm_attach_frame_seconds"] = 10000.0
    elif fault == "late-cold-frame":
        value["milestones"]["cold_frame_seconds"] = 2.0
    elif fault == "missing-action":
        del value["managed_actions"]["warm_member_ready"]
    elif fault == "duration-mismatch":
        value["milestones"]["warm_member_ready_seconds"] = 0.5
    elif fault == "late-detach":
        value["managed_actions"]["reattach_detach_settlement"]["finished_at"] = 19.0
        value["milestones"]["reattach_detach_settlement_seconds"] = 3.0
    else:
        value["seed"] = "recovered"
    with pytest.raises(ValueError):
        runner.validate_observation(value, "managed-mux", tmp_path, tmp_path, tmp_path)


def test_original_outer_owner_completes_stop_then_validates_and_retains_queries(tmp_path, monkeypatch):
    prefix, observer, root = tmp_path / "install", tmp_path / "observer", tmp_path / "sample"
    clock = iter((9.0, 20.0))
    monkeypatch.setattr(runner.time, "perf_counter", lambda: next(clock))

    def supervise(*args, **kwargs):
        value = managed_receipt(prefix, root, observer)
        del value["milestones"]["stop_settlement_seconds"]
        (root / "native.json").write_text(json.dumps(value))

    monkeypatch.setattr(runner.owner, "run_python", supervise)
    report = {"samples": []}
    runner.run_sample(prefix, "managed-mux", root, tmp_path / "pyc", report,
                      tmp_path / "report.json", dict(side="a", block=0, pair=0), observer_prefix=observer)
    (sample,) = report["samples"]
    assert sample["valid"] is True and sample["status"] == "complete"
    assert sample["milestones"]["stop_settlement_seconds"] == 2.0
    assert [entry["stage"] for entry in sample["managed_observations"]] == [
        "first-member", "second-member", "detached", "reattached",
    ]
