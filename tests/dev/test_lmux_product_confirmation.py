"""Strict snapshot value binding, independent of IPC/native authenticity."""

import copy

import pytest

from .test_measure_g18_native import runner


@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("fault", [None, "early", "late", "instance", "member", "extra-record", "wrong-request",
                                  "running", "session", "scope", "fingerprint", "bool-time", "extra-flag"])
def test_confirmation_requires_original_target_exact_records_and_post_detach_order(pending, fault):
    target = {"stage": "first-member", "observed_at": 1.0, "instanceId": "a" * 32,
              "serviceId": "b" * 64, "muxId": "mux-1", "members": [{"memberId": "member-1", "sessionId": "session-1"}]}
    records = [{"kind": "user", "text": ("delayed " if pending else "reply ") + "c" * 32}]
    reply = "LMUX_REPLY_" + "c" * 32
    if not pending:
        records.append({"kind": "assistant", "text": reply})
    value = {**copy.deepcopy(target), "stage": "detached", "observed_at": 5.0,
             "pendingConfirmed" if pending else "replyConfirmed": True,
             "snapshot": {"confirmed_at": 6.0, "running": pending, "expected_reply": reply,
                          "records": copy.deepcopy(records), "identity": {
                              "product_id": "coding", "continuity_id": "continuity-1",
                              "session_id": "session-1", "scope": "user_home", "scope_fingerprint": "d" * 64}}}
    snapshot = value["snapshot"]
    if fault == "early":
        value["observed_at"] = 2.0
    elif fault == "late":
        snapshot["confirmed_at"] = 10.0
    elif fault == "instance":
        value["instanceId"] = "e" * 32
    elif fault == "member":
        value["members"][0]["memberId"] = "other"
    elif fault == "extra-record":
        snapshot["records"].append({"kind": "user", "text": "another"})
    elif fault == "wrong-request":
        snapshot["records"][0]["text"] = "reply " + "e" * 32
    elif fault == "running":
        snapshot["running"] = not pending
    elif fault == "session":
        snapshot["identity"]["session_id"] = "other"
    elif fault == "scope":
        snapshot["identity"]["scope"] = "cwd"
    elif fault == "fingerprint":
        snapshot["identity"]["scope_fingerprint"] = "invalid"
    elif fault == "bool-time":
        snapshot["confirmed_at"] = True
    elif fault == "extra-flag":
        value["replyConfirmed" if pending else "pendingConfirmed"] = True
    parameters = dict(expected_reply=reply, records=records, earliest=3.0, latest=9.0, pending=pending)
    if fault is None:
        runner.validate_managed_product_confirmation(value, target, **parameters)
    else:
        with pytest.raises(ValueError):
            runner.validate_managed_product_confirmation(value, target, **parameters)
