"""Do not accept a warm measurement with unfinished or incomplete seed work."""

import pytest

from .test_measure_g18_native import runner


def evidence():
    value = dict(started_at=1.0, finished_at=130.0, detached_at=131.0, rounds=[
        dict(round=index, started_at=2.0 + index, acknowledged_at=2.1 + index,
             settled_at=2.5 + index, snapshot_reads=1) for index in range(128)])
    bounds = dict(terminal_settled_at=0.5, connection_settled_at=132.0, attach_started_at=133.0)
    bounds["verification"] = dict(started_at=0.5, deadline=660.5, completed_at=131.5)
    value["attachment"] = dict(deadline=660.5, attach_started_at=0.6, attached_at=0.8,
                               attach_deadline=30.6, detach_started_at=130.5, detach_deadline=160.5)
    return value, bounds


def test_complete_seed_precedes_measured_attach():
    value, bounds = evidence()
    runner.validate_managed_history_seed(value, **bounds)


@pytest.mark.parametrize("fault", ["missing-round", "extra-round", "wrong-round", "boolean-round",
                                  "zero-reads", "excess-reads", "boolean-reads", "round-overlap",
                                  "ack-before-start", "settle-before-ack", "late-last-round",
                                  "late-terminal", "late-detach", "late-connection", "total-deadline",
                                  "round-deadline", "extra", "missing", "extra-round-field"])
def test_seed_failures_cannot_be_hidden_by_successful_attach(fault):
    value, bounds = evidence()
    row = value["rounds"][1]
    if fault == "missing-round":
        value["rounds"].pop()
    elif fault == "extra-round":
        value["rounds"].append(dict(row))
    elif fault == "wrong-round":
        row["round"] = 0
    elif fault == "boolean-round":
        row["round"] = True
    elif fault.endswith("reads"):
        row["snapshot_reads"] = {"zero-reads": 0, "excess-reads": 81, "boolean-reads": True}[fault]
    elif fault == "round-overlap":
        row["started_at"] = 2.4
    elif fault == "ack-before-start":
        row["acknowledged_at"] = 2.9
    elif fault == "settle-before-ack":
        row["settled_at"] = 3.05
    elif fault == "late-last-round":
        value["rounds"][-1]["settled_at"] = 130.5
    elif fault == "late-terminal":
        bounds["terminal_settled_at"] = 1.5
    elif fault == "late-detach":
        value["detached_at"] = 132.5
    elif fault == "late-connection":
        bounds["connection_settled_at"] = 133.5
    elif fault == "total-deadline":
        value.update(finished_at=601.0, detached_at=602.0)
        value["attachment"].update(detach_started_at=601.5, detach_deadline=631.5)
        bounds.update(connection_settled_at=603.0, attach_started_at=604.0)
        bounds["verification"]["completed_at"] = 602.5
    elif fault == "round-deadline":
        # Remain ordered and inside the total budget, but exceed one round's limit.
        value["rounds"][-1].update(started_at=129.0, acknowledged_at=130.0, settled_at=169.0)
        value.update(finished_at=170.0, detached_at=171.0)
        value["attachment"].update(detach_started_at=170.5, detach_deadline=200.5)
        bounds.update(connection_settled_at=172.0, attach_started_at=173.0)
        bounds["verification"]["completed_at"] = 171.5
    elif fault == "extra":
        value["accepted"] = True
    elif fault == "missing":
        value.pop("detached_at")
    else:
        row["replayed"] = False
    with pytest.raises(ValueError):
        runner.validate_managed_history_seed(value, **bounds)


def test_late_detach_cannot_pass_by_delaying_every_later_owner():
    value, bounds = evidence()
    value["detached_at"] = 1000.0
    bounds.update(connection_settled_at=1001.0, attach_started_at=1002.0)
    with pytest.raises(ValueError, match="deadline"):
        runner.validate_managed_history_seed(value, **bounds)


@pytest.mark.parametrize("fault", ["missing", "extra", "extended", "different-deadline",
                                  "late-return", "return-before-detach", "connection-before-return",
                                  "admission-after-attach", "admission-before-terminal"])
def test_verification_deadline_is_the_original_admitted_budget(fault):
    value, bounds = evidence()
    verification = bounds["verification"]
    if fault == "missing":
        verification.pop("deadline")
    elif fault == "extra":
        verification["accepted"] = True
    elif fault == "extended":
        verification["deadline"] += 1
    elif fault == "different-deadline":
        value["attachment"]["deadline"] += 1
    elif fault == "late-return":
        verification["completed_at"] = verification["deadline"]
        bounds.update(connection_settled_at=700.0, attach_started_at=701.0)
    elif fault == "return-before-detach":
        verification["completed_at"] = 130.9
    elif fault == "connection-before-return":
        bounds["connection_settled_at"] = 131.4
    else:
        verification["started_at"] = 0.7 if fault == "admission-after-attach" else 0.4
        verification["deadline"] = verification["started_at"] + 660
        value["attachment"]["deadline"] = verification["deadline"]
    with pytest.raises(ValueError):
        runner.validate_managed_history_seed(value, **bounds)


@pytest.mark.parametrize("field", ["started_at", "deadline", "completed_at"])
@pytest.mark.parametrize("bad", [True, float("inf"), float("nan"), 10**400, -1, None])
def test_invalid_verification_times_are_rejected(field, bad):
    value, bounds = evidence()
    bounds["verification"][field] = bad
    with pytest.raises(ValueError):
        runner.validate_managed_history_seed(value, **bounds)


@pytest.mark.parametrize("field", ["started_at", "finished_at", "detached_at", "terminal_settled_at",
                                  "connection_settled_at", "attach_started_at",
                                  "round-start", "round-ack", "round-settle"])
@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), -1, 10**400, None])
def test_all_seed_times_are_finite_and_typed(field, bad):
    value, bounds = evidence()
    if field.startswith("round-"):
        key = {"round-start": "started_at", "round-ack": "acknowledged_at", "round-settle": "settled_at"}[field]
        value["rounds"][0][key] = bad
    else:
        (value if field in value else bounds)[field] = bad
    with pytest.raises(ValueError):
        runner.validate_managed_history_seed(value, **bounds)
