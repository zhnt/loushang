"""A warm generation needs all independent proofs, not just passing timings."""

import copy

import pytest

from .test_lmux_history_confirmation import evidence as confirmation_evidence
from .test_lmux_history_receipts import evidence as canonical_evidence
from .test_lmux_history_seed_receipts import evidence as seed_evidence
from .test_lmux_history_terminal_validation import evidence as terminal_evidence
from .test_measure_g18_native import runner


def evidence():
    child, bounds = terminal_evidence(False)
    snapshot, target, identity_bounds = confirmation_evidence()
    target["observed_at"] = 2.0
    identity = identity_bounds["identity"]
    snapshot.update(observed_at=143.0, connection_settled_at=145.0)
    snapshot["history_snapshot"]["confirmed_at"] = 144.0
    child["spawns"][1]["start"] = 136.0
    child["terminal_settlements"][1].update(termios_restored_at=141.0, settled_at=142.0)

    def shift(value):
        if type(value) is float:
            return value + 3
        if type(value) is dict:
            return {key: shift(item) for key, item in value.items()}
        if type(value) is list:
            return [shift(item) for item in value]
        return value

    seeded, seed_bounds = seed_evidence()
    seeded, seed_bounds = shift(seeded), shift(seed_bounds)
    seed = dict(copy.deepcopy(target), stage="detached", observed_at=3.25,
                history_seed=seeded, history_identity=dict(identity),
                connection_settled_at=135.0, verification=seed_bounds["verification"])
    stop = dict(started_at=146.0, observed_at=147.0, local_owner_settled_at=148.0,
                service_id=target["serviceId"], result=dict(status="stopped", instanceId=target["instanceId"]))
    canonical, _ = canonical_evidence(bounds["workspace"] / "platform/data/sessions")
    canonical.update(started_at=149.0, completed_at=150.0, identity=dict(identity), workspace=str(bounds["workspace"]))
    native = dict(pid=500, start_ticks=1000, boot_id="12345678-1234-1234-1234-123456789abc",
                  user_id=1000, pid_namespace_device=4, pid_namespace_inode=5)
    attached = dict(history_frame_seconds=2.0, history_completion_seconds=1.0, detached=snapshot,
                    actions=dict(history_frame=dict(started_at=136.0, finished_at=138.0),
                                 history_completion=dict(started_at=139.0, finished_at=140.0)))
    child.update(status="observed", valid=False, measured_prefix=str(bounds["prefix"]),
        fixed_product_target=target,
        fixed_product_detached=dict(copy.deepcopy(target), stage="detached", observed_at=135.5),
        fixed_product_stop=stop,
        fixed_product_native={stage: dict(native) for stage in ("first-member", "detached", "history-detached", "stop")},
        fixed_product_history=dict(seed=seed, attach=attached, canonical=dict(canonical["canonical"]),
                                   stop=dict(stop["result"]), canonical_read=canonical))
    bounds.pop("restored")
    bounds["latest"] = 151.0
    return child, bounds


def test_complete_warm_generation_joins_all_proofs():
    child, bounds = evidence()
    assert runner.validate_managed_history_warm(child, **bounds) == {
        "history_frame_seconds": 2.0, "history_completion_seconds": 1.0}
    assert child["valid"] is False


@pytest.mark.parametrize("fault", ["cleanup-failure", "valid", "wrong-status", "wrong-prefix",
                                  "native-replaced", "native-missing", "native-boolean", "wrong-stop",
                                  "stop-before-read-close", "canonical-before-stop", "late-canonical",
                                  "wrong-root", "changed-canonical", "late-seed-close", "early-detached",
                                  "wrong-detached", "late-frame", "late-auth", "seed-missing-verification"])
def test_partial_success_never_accepts_a_warm_generation(fault):
    child, bounds = evidence()
    result = child["fixed_product_history"]
    if fault == "cleanup-failure":
        child["cleanup_failure"] = "OSError"
    elif fault == "valid":
        child["valid"] = True
    elif fault == "wrong-status":
        child["status"] = "failed"
    elif fault == "wrong-prefix":
        child["measured_prefix"] = "/other"
    elif fault == "native-replaced":
        child["fixed_product_native"]["stop"]["start_ticks"] += 1
    elif fault == "native-missing":
        child["fixed_product_native"].pop("history-detached")
    elif fault == "native-boolean":
        child["fixed_product_native"]["stop"]["user_id"] = True
    elif fault == "wrong-stop":
        child["fixed_product_stop"]["result"]["instanceId"] = "d" * 32
    elif fault == "stop-before-read-close":
        child["fixed_product_stop"]["started_at"] = 144.5
    elif fault == "canonical-before-stop":
        result["canonical_read"]["started_at"] = 147.5
    elif fault == "late-canonical":
        result["canonical_read"]["completed_at"] = 152.0
    elif fault == "wrong-root":
        result["canonical_read"]["root"] = "/other"
    elif fault == "changed-canonical":
        result["canonical"]["sha256"] = "0" * 64
    elif fault == "late-seed-close":
        result["seed"]["connection_settled_at"] = 136.5
    elif fault == "early-detached":
        child["fixed_product_detached"]["observed_at"] = 134.5
    elif fault == "wrong-detached":
        child["fixed_product_detached"]["serviceId"] = "d" * 64
    elif fault == "late-frame":
        result["attach"]["actions"]["history_completion"]["finished_at"] = 141.5
        result["attach"]["history_completion_seconds"] = 2.5
    elif fault == "late-auth":
        child["fixed_product_target"]["observed_at"] = 2.5
    else:
        result["seed"].pop("verification")
    with pytest.raises(ValueError):
        runner.validate_managed_history_warm(child, **bounds)
