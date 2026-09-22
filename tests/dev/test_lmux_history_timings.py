"""History timing subset is independent of helper assertions and sample validity."""

import pytest

from .test_measure_g18_native import runner


def evidence():
    attached = {"actions": {
        "history_frame": {"started_at": 10.0, "finished_at": 12.0},
        "history_completion": {"started_at": 14.0, "finished_at": 15.0}},
        "history_frame_seconds": 2.0, "history_completion_seconds": 1.0,
        "detached": {}}
    restored = {"action": {"started_at": 1.0, "finished_at": 12.0},
                "restored_history_frame_seconds": 11.0}
    return attached, dict(attach_started_at=10.0, restored=restored,
                          service_started_at=1.0, authenticated_at=8.0)


def test_warm_and_restore_share_attach_but_not_metric_start():
    attached, bounds = evidence()
    runner.validate_managed_history_timings(attached, attach_started_at=10.0)
    runner.validate_managed_history_timings(attached, **bounds)


@pytest.mark.parametrize("fault", ["attach-start", "restore-attach-start", "sum-segments",
                                  "wrong-final-frame", "authentication-late", "service-late",
                                  "completion-before-frame", "completion-duration", "missing",
                                  "extra", "extra-restored", "extra-action", "missing-restored"])
def test_endpoint_and_inventory_faults(fault):
    attached, bounds = evidence()
    restored = bounds["restored"]
    if fault == "attach-start":
        bounds["attach_started_at"] = 9.0
    elif fault == "restore-attach-start":
        restored["action"]["started_at"] = 10.0
        restored["restored_history_frame_seconds"] = 2.0
    elif fault == "sum-segments":
        restored["restored_history_frame_seconds"] = 9.0  # Loses auth-to-attach gap.
    elif fault == "wrong-final-frame":
        restored["action"]["finished_at"] = 13.0
        restored["restored_history_frame_seconds"] = 12.0
    elif fault == "authentication-late":
        bounds["authenticated_at"] = 11.0
    elif fault == "service-late":
        bounds["service_started_at"] = 9.0
    elif fault == "completion-before-frame":
        attached["actions"]["history_completion"]["started_at"] = 11.0
        attached["history_completion_seconds"] = 4.0
    elif fault == "completion-duration":
        attached["history_completion_seconds"] = 2.0
    elif fault == "missing":
        attached.pop("history_completion_seconds")
    elif fault == "extra":
        attached["unknown_seconds"] = 2.0
    elif fault == "extra-restored":
        restored["unknown_seconds"] = 2.0
    elif fault == "extra-action":
        restored["action"]["observed_at"] = 12.0
    else:
        restored.pop("action")
    with pytest.raises(ValueError):
        runner.validate_managed_history_timings(attached, **bounds)


@pytest.mark.parametrize("field", ["attach_started_at", "service_started_at", "authenticated_at",
                                  "started_at", "finished_at", "duration", "completion"])
@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), -1, 10**400, "1", None])
def test_invalid_time_never_passes(field, bad):
    attached, bounds = evidence()
    if field in bounds:
        bounds[field] = bad
    elif field == "duration":
        bounds["restored"]["restored_history_frame_seconds"] = bad
    elif field == "completion":
        attached["history_completion_seconds"] = bad
    else:
        bounds["restored"]["action"][field] = bad
    with pytest.raises(ValueError):
        runner.validate_managed_history_timings(attached, **bounds)


def test_warm_cannot_silently_drop_restart_inputs():
    attached, _ = evidence()
    with pytest.raises(ValueError):
        runner.validate_managed_history_timings(attached, attach_started_at=10.0,
                                                service_started_at=1.0)
