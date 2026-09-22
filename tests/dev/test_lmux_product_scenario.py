"""Complete synthetic child receipts; independent of installed provenance."""

import copy

import pytest

from .test_lmux_product_terminal_validation import sample
from .test_measure_g18_native import runner


def scenario_value(tmp_path, scenario):
    child, parameters = sample(tmp_path, scenario)
    target = {"stage": "first-member", "observed_at": 2.05, "instanceId": "a" * 32,
              "serviceId": "b" * 64, "muxId": "mux-1", "members": [{"memberId": "member-1", "sessionId": "session-1"}]}
    identity = {"product_id": "coding", "continuity_id": "continuity-1", "session_id": "session-1",
                "scope": "user_home", "scope_fingerprint": "d" * 64}

    def observation(stage, at):
        return {**copy.deepcopy(target), "stage": stage, "observed_at": at}

    def confirm(records, expected, *, at=4.1, pending=False):
        return {**observation("detached", at), "pendingConfirmed" if pending else "replyConfirmed": True,
                "snapshot": {"confirmed_at": at + 0.1, "running": pending, "expected_reply": expected,
                             "identity": dict(identity), "records": [{"kind": kind, "text": text} for kind, text in records]}}

    intervals = {
        "reply": {"fixed_entry_through_visible_reply": (2.0, 2.8), "visible_reply": (2.1, 2.8)},
        "approval": {"approval_pending": (2.1, 2.2), "approval_details": (2.3, 2.4), "approved_tool_reply": (2.5, 2.8)},
        "interrupt": {"interrupt_through_idle_and_producer": (6.2, 6.4), "next_reply": (6.5, 6.8),
                      "interrupt_through_next_reply": (6.2, 6.8)},
    }[scenario]
    actions = {name: {"started_at": start, "finished_at": end} for name, (start, end) in intervals.items()}
    milestones = {name + "_seconds": end - start for name, (start, end) in intervals.items()}
    timing = {**milestones, "actions": copy.deepcopy(actions)}
    child.update(actions=actions, milestones=milestones, fixed_product_target=target,
                 fixed_product_detached=observation("detached", 4.3))
    native = {"pid": 123, "start_ticks": 100, "boot_id": "12345678-1234-1234-1234-123456789abc",
              "user_id": 1000, "pid_namespace_device": 4, "pid_namespace_inode": 5}
    child["fixed_product_native"] = {stage: dict(native) for stage in
        ("first-member", "detached", "stop", "reattached", "final-detached")[:5 if scenario == "interrupt" else 3]}
    stop, nonce, next_nonce = dict(child["fixed_product_stop"]["result"]), "c" * 32, "e" * 32
    reply = "LMUX_REPLY_" + nonce
    if scenario == "reply":
        timing["spawn_through_visible_reply_seconds"] = timing.pop("fixed_entry_through_visible_reply_seconds")
        child["fixed_product_first_reply"] = {**timing, "request_nonce": nonce, "stop": stop,
            "composition": "managed-infrastructure-with-fixed-test-product",
            "confirmation": confirm([("user", "reply " + nonce), ("assistant", reply)], reply)}
    elif scenario == "approval":
        child["fixed_product_tool_approval"] = {**timing, "stop": stop, "approved_sent_ns": 2_600_000_000,
            "tool_call_id": "lmux-call-1", "tool_execution_count": 1,
            "tool_effects": [{"instance_id": "a" * 32, "call_id": "lmux-call-1", "monotonic_ns": 2_700_000_000, "sequence": 3}],
            "confirmation": confirm([("user", "approval"), ("assistant", ""), ("assistant", "LMUX_TOOL_COMPLETED")], "LMUX_TOOL_COMPLETED")}
    else:
        producer = {"instance_id": "a" * 32, "call_id": "lmux-call-1", "phase": "producer_started",
                    "monotonic_ns": 2_500_000_000, "sequence": 1}
        timing.update(interrupted_nonce=nonce, next_nonce=next_nonce, interrupt_sent_ns=6_300_000_000,
            producer_before=[producer], producer_after=[dict(producer), {**producer, "phase": "producer_settled", "sequence": 2, "monotonic_ns": 6_350_000_000}],
            reattached=observation("reattached", 6.1), detached=observation("detached", 8.3),
            next_reply_confirmation=confirm([("user", "delayed " + nonce), ("assistant", ""),
                ("user", "reply " + next_nonce), ("assistant", "LMUX_REPLY_" + next_nonce)], "LMUX_REPLY_" + next_nonce, at=8.1))
        child["fixed_product_interrupt_next_turn"] = {"request_nonce": nonce, "stop": stop,
            "producer": "lmux-call-1", "producer_settled": True, "full_text_not_completed": True,
            "pending_confirmation": confirm([("user", "delayed " + nonce)], reply, pending=True), "next_turn": timing}
    return child, dict(prefix=parameters["prefix"], workspace=parameters["workspace"])


@pytest.mark.parametrize("scenario", ["reply", "approval", "interrupt"])
@pytest.mark.parametrize("fault", [None, "missing", "extra", "extra-result", "extra-timing", "late-action", "snapshot-record", "snapshot-early", "stop-copy", "raw-duration", "detached-instance"])
def test_complete_scenario_reuses_all_evidence_gates(tmp_path, scenario, fault):
    child, parameters = scenario_value(tmp_path, scenario)
    key = {"reply": "fixed_product_first_reply", "approval": "fixed_product_tool_approval", "interrupt": "fixed_product_interrupt_next_turn"}[scenario]
    result = child[key]
    timing = result["next_turn"] if scenario == "interrupt" else result
    confirmation = result["pending_confirmation"] if scenario == "interrupt" else result["confirmation"]
    if fault == "missing":
        del child["fixed_product_detached"]
    elif fault == "extra":
        child["failure"] = "late error"
    elif fault == "extra-result":
        result["failure"] = "late error"
    elif fault == "extra-timing":
        timing["failure"] = "late error"
    elif fault == "late-action":
        child["terminal_settlements"][-1]["termios_restored_at"] = child["spawns"][-1]["start"]
    elif fault == "snapshot-record":
        confirmation["snapshot"]["records"].append({"kind": "user", "text": "extra"})
    elif fault == "snapshot-early":
        confirmation["observed_at"] = 2.9
    elif fault == "stop-copy":
        result["stop"]["instanceId"] = "f" * 32
    elif fault == "raw-duration":
        timing[next(name for name in timing if name.endswith("_seconds"))] += 1
    elif fault == "detached-instance":
        child["fixed_product_detached"]["instanceId"] = "f" * 32
    if fault is None:
        runner.validate_managed_product_scenario(child, scenario, **parameters)
    else:
        with pytest.raises(ValueError):
            runner.validate_managed_product_scenario(child, scenario, **parameters)


@pytest.mark.parametrize("fault", ["early-effect", "duplicate-effect", "bool-count"])
def test_tool_success_requires_unique_post_approval_effect(tmp_path, fault):
    child, parameters = scenario_value(tmp_path, "approval")
    result = child["fixed_product_tool_approval"]
    if fault == "early-effect":
        result["tool_effects"][0]["monotonic_ns"] = 2_400_000_000
    elif fault == "duplicate-effect":
        result["tool_effects"] *= 2
    else:
        result["tool_execution_count"] = True
    with pytest.raises(ValueError):
        runner.validate_managed_product_scenario(child, "approval", **parameters)


@pytest.mark.parametrize("scenario", ["reply", "approval", "interrupt"])
@pytest.mark.parametrize("fault", ["missing", "extra", "changed-start", "bool-uid", "bad-boot", "stop-pid"])
def test_original_native_identity_is_preserved_through_stop(tmp_path, scenario, fault):
    child, parameters = scenario_value(tmp_path, scenario)
    natives = child["fixed_product_native"]
    if fault == "missing":
        del natives["detached"]
    elif fault == "extra":
        natives["unknown"] = dict(natives["first-member"])
    elif fault == "changed-start":
        natives["detached"]["start_ticks"] += 1
    elif fault == "bool-uid":
        for item in natives.values():
            item["user_id"] = 1
        natives["stop"]["user_id"] = True
    elif fault == "bad-boot":
        for item in natives.values():
            item["boot_id"] = "invalid"
    else:
        natives["stop"]["pid"] += 1
    with pytest.raises(ValueError, match="native identity"):
        runner.validate_managed_product_scenario(child, scenario, **parameters)


@pytest.mark.parametrize("fault", ["same-nonce", "early-settle", "different-producer", "different-continuity"])
def test_interrupt_cannot_replay_or_change_original_producer_and_session(tmp_path, fault):
    child, parameters = scenario_value(tmp_path, "interrupt")
    timing = child["fixed_product_interrupt_next_turn"]["next_turn"]
    if fault == "same-nonce":
        timing["next_nonce"] = timing["interrupted_nonce"]
    elif fault == "early-settle":
        timing["producer_after"][1]["monotonic_ns"] = 6_100_000_000
    elif fault == "different-producer":
        timing["producer_after"][0]["sequence"] = 0
    else:
        timing["next_reply_confirmation"]["snapshot"]["identity"]["continuity_id"] = "other"
    with pytest.raises(ValueError):
        runner.validate_managed_product_scenario(child, "interrupt", **parameters)
