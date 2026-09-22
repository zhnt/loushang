"""Restart ordering and failure handling; not installed recovery acceptance."""

import json
from contextlib import contextmanager
from dataclasses import asdict
from types import SimpleNamespace as NS

import pytest

from loushang.hosting.service import LinuxServiceIdentityV1

from . import _lmux_history_restore as restore


@pytest.mark.parametrize("fault", [None, "start", "read", "instance", "native", "service", "ready-instance", "attach", "stop", "canonical"])
def test_restart_keeps_generation_stops_separate(tmp_path, monkeypatch, fault):
    events = []
    old_target = {"serviceId": "service", "instanceId": "old"}
    native = LinuxServiceIdentityV1(123, 100, "12345678-1234-1234-1234-123456789abc", 1000, 4, 5)
    old_native = {**asdict(native), "starttime_ticks": -1}
    if fault == "native":
        old_native = asdict(native)
    target = {"serviceId": "other" if fault == "service" else "service", "instanceId": "old" if fault == "instance" else "new"}
    identity = {"product_id": "coding", "continuity_id": "continuity", "session_id": "session",
                "scope": "user_home", "scope_fingerprint": "c" * 64}
    ready = {"status": "service_ready", **target}
    if fault == "ready-instance":
        ready["instanceId"] = "different"

    @contextmanager
    def spawn(executable):
        events.append("spawn")
        yield {"start": 2.0}

    @contextmanager
    def terminal(argv, root, environment, **kwargs):
        assert argv[-3:] == ["start", "-t", "perf"] and root == tmp_path
        try:
            yield NS(raw_output=json.dumps(ready), diagnostics=None,
                     wait=lambda **kwargs: 1 if fault == "start" else 0), None, None
        finally:
            events.append("start-closed")

    def read(environment, stage, *, native_identity):
        assert events[-1] == "start-closed"
        events.append("read")
        if fault == "read":
            raise ValueError("read failed")
        native_identity.append(native)
        return target

    def attach(root, report, environment, actual, natives, expected, *, directory):
        assert directory == "restored-elsewhere" and expected == identity
        assert actual == target and natives == [native]
        events.append("attach")
        if fault == "attach":
            raise ValueError("attach failed")
        return {"actions": {"history_frame": {"started_at": 10.0, "finished_at": 15.0}}}

    def stop(root, report, environment, actual, original):
        assert original == native and actual == target
        events.append("new-stop")
        if fault == "stop":
            raise ValueError("stop failed")
        return {"status": "stopped", "instanceId": target["instanceId"]}

    def canonical(root, restored_identity, workspace, *, receipt):
        assert events[-1] == "new-stop" and workspace == tmp_path
        events.append("canonical")
        receipt.update(started_at=20.0, completed_at=21.0)
        return {"digest": "wrong" if fault == "canonical" else "same"}

    monkeypatch.setattr(restore.probe, "observe_spawn", spawn)
    monkeypatch.setattr(restore.probe, "observed_terminal", terminal)
    monkeypatch.setattr(restore.probe, "managed_read_observation", read)
    monkeypatch.setattr(restore.probe, "_history_attach", attach)
    monkeypatch.setattr(restore.probe, "_stop_generation", stop)
    monkeypatch.setattr(restore.probe, "_terminal_environment", lambda _: {"LOUSHANG_HOME": str(tmp_path / "platform")})
    monkeypatch.setattr(restore, "read_history", canonical)
    report = {"measured_prefix": str(tmp_path / "install")}
    if fault is None:
        restore._restart(tmp_path, report, old_target, old_native, identity, 1.0, {"digest": "same"})
        assert report["restored_history"]["restored_history_frame_seconds"] == 13.0
        assert report["fixed_product_target"] == target
        assert report["restored_history"]["canonical_read"]["completed_at"] == 21.0
        assert events == ["spawn", "start-closed", "read", "attach", "new-stop", "canonical"]
    else:
        with pytest.raises((ValueError, AssertionError)):
            restore._restart(tmp_path, report, old_target, old_native, identity, 1.0, {"digest": "same"})
        assert "restored_history" not in report
    assert events.count("new-stop") == (0 if fault in {"start", "read", "instance", "native", "service", "ready-instance"} else 1)


@pytest.mark.parametrize("fault", [None, "old-failure", "old-stop", "canonical-before-stop", "canonical-reversed", "new-failure"])
def test_new_generation_cannot_start_before_old_success(tmp_path, monkeypatch, fault):
    events = []
    target = {"serviceId": "service", "instanceId": "old"}
    stop = {"status": "failed" if fault == "old-stop" else "stopped", "instanceId": "old"}
    identity, canonical, native = {"identity": "old"}, {"digest": "same"}, {"native": "old"}

    def first(root, report, *, history):
        assert root == tmp_path and history is True
        events.append("old")
        if fault == "old-failure":
            raise ValueError("old did not settle")
        report.update(fixed_product_history={"stop": stop, "canonical": canonical,
            "canonical_read": {"started_at": 1.0 if fault == "canonical-before-stop" else 3.0,
                               "completed_at": 2.5 if fault == "canonical-reversed" else 4.0},
            "seed": {"history_identity": identity}}, fixed_product_target=target,
            fixed_product_native={"stop": native}, spawns=[{"generation": "old"}],
            fixed_product_stop={"result": stop, "local_owner_settled_at": 2.0})

    def restart(root, report, old_target, old_native, expected, settled_at, old_canonical):
        assert events == ["old"] and root == tmp_path
        assert (old_target, old_native, expected, settled_at, old_canonical) == (target, native, identity, 4.0, canonical)
        events.append("new")
        if fault == "new-failure":
            raise ValueError("new failed")
        report.update(restored_history={"canonical": canonical}, spawns=[{"generation": "new"}])

    monkeypatch.setattr(restore.probe, "first_reply", first)
    monkeypatch.setattr(restore, "_restart", restart)
    report = {"measured_prefix": "install"}
    if fault is None:
        restore.restore_history(tmp_path, report)
        assert report["fixed_product_history_restore"] == {"canonical": canonical}
        assert report["spawns"] == [{"generation": "old"}, {"generation": "new"}]
    else:
        with pytest.raises((ValueError, AssertionError)):
            restore.restore_history(tmp_path, report)
        assert "fixed_product_history_restore" not in report
        assert ("new" in events) is (fault == "new-failure")
