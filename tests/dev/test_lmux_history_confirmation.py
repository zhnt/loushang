"""Tail equality never substitutes for full canonical history or ownership."""

import copy

import pytest

from tests.coding._lmux_history_recipe import OMITTED, history_turn

from .test_measure_g18_native import runner


def evidence():
    target = dict(stage="first-member", observed_at=1.0, instanceId="a" * 32,
                  serviceId="b" * 64, muxId="mux", members=[dict(memberId="member", sessionId="session")])
    identity = dict(product_id="coding", continuity_id="continuity", session_id="session",
                    scope="user_home", scope_fingerprint="c" * 64)
    rows = [dict(kind="status", text=OMITTED)] + [dict(kind=kind, text=text)
        for index in range(121, 128) for kind, text in zip(("user", "assistant"), history_turn(index))]
    value = dict(copy.deepcopy(target), stage="detached", observed_at=3.0, connection_settled_at=5.0,
                 history_snapshot=dict(confirmed_at=4.0, identity=dict(identity), running=False, records=rows))
    return value, target, dict(identity=identity, earliest=2.0, latest=6.0)


def test_exact_fixed_tail_after_terminal_and_before_stop():
    value, target, bounds = evidence()
    runner.validate_managed_history_confirmation(value, target, **bounds)


@pytest.mark.parametrize("field", ["instanceId", "serviceId", "muxId", "members"])
def test_correct_tail_from_other_target_is_not_accepted(field):
    value, target, bounds = evidence()
    value[field] = "other"
    with pytest.raises(ValueError):
        runner.validate_managed_history_confirmation(value, target, **bounds)


@pytest.mark.parametrize("field", ["product_id", "continuity_id", "session_id", "scope", "scope_fingerprint"])
def test_all_session_fields_must_match(field):
    value, target, bounds = evidence()
    value["history_snapshot"]["identity"][field] = "other"
    with pytest.raises(ValueError):
        runner.validate_managed_history_confirmation(value, target, **bounds)


@pytest.mark.parametrize("fault", ["text", "role", "reorder", "missing-status", "extra", "running", "boolean-idle",
                                  "early-snapshot", "early-observation", "late-close", "extra-field", "missing-time"])
def test_tail_and_lifecycle_receipt_faults(fault):
    value, target, bounds = evidence()
    snapshot = value["history_snapshot"]
    if fault == "text":
        snapshot["records"][2]["text"] += "wrong"
    elif fault == "role":
        snapshot["records"][1]["kind"] = "assistant"
    elif fault == "reorder":
        snapshot["records"][1:3], snapshot["records"][3:5] = snapshot["records"][3:5], snapshot["records"][1:3]
    elif fault == "missing-status":
        snapshot["records"].pop(0)
    elif fault == "extra":
        snapshot["records"].append(dict(kind="user", text="unexpected"))
    elif fault in {"running", "boolean-idle"}:
        snapshot["running"] = True if fault == "running" else 0
    elif fault == "early-snapshot":
        snapshot["confirmed_at"] = 2.5
    elif fault == "early-observation":
        value["observed_at"] = 1.5
    elif fault == "late-close":
        value["connection_settled_at"] = 6.5
    elif fault == "extra-field":
        snapshot["accepted"] = True
    else:
        snapshot.pop("confirmed_at")
    with pytest.raises(ValueError):
        runner.validate_managed_history_confirmation(value, target, **bounds)


@pytest.mark.parametrize("field", ["earliest", "latest", "observed_at", "confirmed_at", "connection_settled_at"])
@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), -1, 10**400, None])
def test_timing_fields_fail_closed(field, bad):
    value, target, bounds = evidence()
    if field in bounds:
        bounds[field] = bad
    elif field == "confirmed_at":
        value["history_snapshot"][field] = bad
    else:
        value[field] = bad
    with pytest.raises(ValueError):
        runner.validate_managed_history_confirmation(value, target, **bounds)
