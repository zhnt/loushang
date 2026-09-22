"""Restart acceptance requires old and new generation lifetimes separately."""

import copy

import pytest

from .test_lmux_history_terminal_validation import evidence as terminal_evidence
from .test_lmux_history_warm_validation import evidence as warm_evidence
from .test_measure_g18_native import runner


def evidence():
    old, bounds = warm_evidence()
    new, _ = terminal_evidence(True)
    for spawn, start in zip(new["spawns"], (151.0, 157.0)):
        spawn["start"] = start
    new["line_terminal_settlements"][0].update(termios_restored_at=153.0, settled_at=154.0)
    new["terminal_settlements"][0].update(termios_restored_at=162.0, settled_at=163.0)
    target = dict(copy.deepcopy(old["fixed_product_target"]), instanceId="d" * 32, observed_at=155.0)
    native = dict(old["fixed_product_native"]["stop"], pid=501, start_ticks=1200)
    attached = copy.deepcopy(old["fixed_product_history"]["attach"])
    attached["actions"] = dict(history_frame=dict(started_at=157.0, finished_at=159.0),
                               history_completion=dict(started_at=160.0, finished_at=161.0))
    attached["detached"].update(instanceId=target["instanceId"], observed_at=164.0, connection_settled_at=166.0)
    attached["detached"]["history_snapshot"]["confirmed_at"] = 165.0
    stop = dict(started_at=167.0, observed_at=168.0, local_owner_settled_at=169.0,
                service_id=target["serviceId"], result=dict(status="stopped", instanceId=target["instanceId"]))
    canonical = copy.deepcopy(old["fixed_product_history"]["canonical_read"])
    canonical.update(started_at=170.0, completed_at=171.0)
    new.update(status="observed", valid=False, measured_prefix=str(bounds["prefix"]),
        fixed_product_target=target, authenticated_at=156.0,
        start_command=dict(started_at=151.0, settled_at=154.5, exit_status=0,
                           result=dict(status="service_ready", serviceId=target["serviceId"], instanceId=target["instanceId"])),
        fixed_product_native={stage: dict(native) for stage in ("restored", "history-detached", "stop")},
        fixed_product_stop=stop,
        restored_history=dict(attach=attached, canonical=dict(canonical["canonical"]), canonical_read=canonical,
            stop=dict(stop["result"]), action=dict(started_at=151.0, finished_at=159.0), restored_history_frame_seconds=8.0))
    bounds["latest"] = 172.0
    return dict(old=old, new=new), bounds


def test_both_complete_generations_and_actual_restart_gap():
    generations, bounds = evidence()
    assert runner.validate_managed_history_restore(generations, **bounds) == {"restored_history_frame_seconds": 8.0}
    assert all(child["valid"] is False for child in generations.values())


@pytest.mark.parametrize("fault", ["old-failed", "new-failed", "new-cleanup", "old-canonical-late", "missing-line",
                                  "same-instance", "same-native", "namespace-changed", "native-changed-on-stop",
                                  "wrong-ready", "ready-before-line-close", "auth-before-ready", "wrong-service",
                                  "changed-session", "changed-scope", "old-stop-reused", "canonical-before-stop",
                                  "new-canonical-changed", "late-canonical", "attach-duration", "late-completion"])
def test_one_generation_cannot_substitute_for_the_other(fault):
    generations, bounds = evidence()
    old, new = generations["old"], generations["new"]
    result = new["restored_history"]
    if fault == "old-failed":
        old["status"] = "failed"
    elif fault == "new-failed":
        new["status"] = "failed"
    elif fault == "new-cleanup":
        new["cleanup_failure"] = "OSError"
    elif fault == "old-canonical-late":
        old["fixed_product_history"]["canonical_read"]["completed_at"] = 151.5
    elif fault == "missing-line":
        new.pop("line_terminal_settlements")
    elif fault == "same-instance":
        new["fixed_product_target"]["instanceId"] = old["fixed_product_target"]["instanceId"]
        new["start_command"]["result"]["instanceId"] = new["fixed_product_target"]["instanceId"]
    elif fault == "same-native":
        new["fixed_product_native"] = {stage: dict(old["fixed_product_native"]["stop"]) for stage in new["fixed_product_native"]}
    elif fault == "namespace-changed":
        for native in new["fixed_product_native"].values():
            native["pid_namespace_inode"] += 1
    elif fault == "native-changed-on-stop":
        new["fixed_product_native"]["stop"]["pid"] += 1
    elif fault == "wrong-ready":
        new["start_command"]["result"]["serviceId"] = "e" * 64
    elif fault == "ready-before-line-close":
        new["start_command"]["settled_at"] = 153.5
    elif fault == "auth-before-ready":
        new["authenticated_at"] = 154.0
    elif fault == "wrong-service":
        new["fixed_product_target"]["serviceId"] = "e" * 64
        new["start_command"]["result"]["serviceId"] = "e" * 64
    elif fault == "changed-session":
        new["fixed_product_target"]["members"][0]["sessionId"] = "other"
    elif fault == "changed-scope":
        result["attach"]["detached"]["history_snapshot"]["identity"]["scope_fingerprint"] = "e" * 64
    elif fault == "old-stop-reused":
        new["fixed_product_stop"] = copy.deepcopy(old["fixed_product_stop"])
        result["stop"] = dict(old["fixed_product_stop"]["result"])
    elif fault == "canonical-before-stop":
        result["canonical_read"]["started_at"] = 168.5
    elif fault == "new-canonical-changed":
        result["canonical"]["sha256"] = "e" * 64
    elif fault == "late-canonical":
        result["canonical_read"]["completed_at"] = 172.5
    elif fault == "attach-duration":
        result["action"]["started_at"] = 157.0
        result["restored_history_frame_seconds"] = 2.0
    else:
        result["attach"]["actions"]["history_completion"]["finished_at"] = 162.5
        result["attach"]["history_completion_seconds"] = 2.5
    with pytest.raises(ValueError):
        runner.validate_managed_history_restore(generations, **bounds)
