"""Failure/target boundaries of native observation orchestration, with fake IO."""

from __future__ import annotations

import copy
import json
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from . import _g18_native_probe as probe


@pytest.fixture
def body_io(monkeypatch):
    state = {"frame_error": None, "cleanup_error": None, "mutate": None, "events": []}
    members = [{"memberId": "member-1", "sessionId": "session-1"},
               {"memberId": "member-2", "sessionId": "session-2"}]

    class Driver:
        raw_output = ""
        diagnostics = None

        def write(self, text):
            state["events"].append(("write", text))

        def read_until(self, predicate, **kwargs):
            if state["frame_error"] is not None:
                raise state["frame_error"]

        def wait(self, **kwargs):
            return 0

    @contextmanager
    def terminal(*args, **kwargs):
        state["events"].append("terminal-open")
        try:
            yield Driver(), None, None
        finally:
            state["events"].append("terminal-closed")

    @contextmanager
    def spawn(*args):
        yield {"start": time.perf_counter()}

    def observation(environment, stage, *, native_identity=None):
        if native_identity is not None:
            native_identity.append(object())
        value = {"stage": stage, "observed_at": time.perf_counter(),
                 "instanceId": "a" * 32, "serviceId": "b" * 64, "muxId": "mux-perf",
                 "members": copy.deepcopy(members[:1] if stage == "first-member" else members)}
        if state["mutate"]:
            state["mutate"](stage, value)
        return value

    def command(argv, **kwargs):
        state["events"].append(("command", tuple(argv[1:])))
        if "--all" in argv and state["cleanup_error"] is not None:
            raise state["cleanup_error"]
        return SimpleNamespace(returncode=0, stderr="", stdout="\n".join(map(json.dumps, [
            {"action": "stop_preview"}, {"status": "stopped", "instanceId": "a" * 32},
        ])))

    monkeypatch.setattr(probe, "observed_terminal", terminal)
    monkeypatch.setattr(probe, "observe_spawn", spawn)
    monkeypatch.setattr(probe, "assert_active_terminal", lambda *args: None)
    monkeypatch.setattr(probe, "managed_read_observation", observation)
    monkeypatch.setattr(probe, "_terminal_environment", lambda root: {})
    monkeypatch.setattr(probe.subprocess, "run", command)
    from . import _lmux_adopted_process as adopted

    monkeypatch.setattr(adopted, "AdoptedLeader", lambda identity: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(adopted, "stop_command", command)
    return state


def report(tmp_path):
    return {"measured_prefix": str(tmp_path / "install"), "spawns": [], "milestones": {}}


def test_adopted_close_failure_is_not_hidden_by_callers_exception(tmp_path, monkeypatch, body_io):
    from . import _lmux_adopted_process as adopted

    failure = OSError("pidfd close unknown")

    def close():
        raise failure

    monkeypatch.setattr(adopted, "AdoptedLeader", lambda identity: SimpleNamespace(close=close))
    try:
        raise LookupError("unrelated caller exception")
    except LookupError:
        with pytest.raises(OSError) as caught:
            probe.managed_mux(tmp_path, report(tmp_path))
    assert caught.value is failure


@pytest.mark.parametrize("primary", [TimeoutError("original frame timeout"), KeyboardInterrupt()])
def test_failed_fallback_keeps_original_error_and_bounded_diagnostic(tmp_path, body_io, primary):
    body_io.update(frame_error=primary, cleanup_error=OSError("sensitive details must not be copied"))
    value = report(tmp_path)
    with pytest.raises(type(primary)) as caught:
        probe.managed_mux(tmp_path, value)
    assert caught.value is primary
    assert value["managed_cleanup_failure"] == {"type": "OSError"}
    assert "sensitive" not in repr(value)
    assert "stop_settlement_seconds" not in value["milestones"]
    assert body_io["events"].index("terminal-closed") < next(
        index for index, event in enumerate(body_io["events"]) if isinstance(event, tuple) and event[0] == "command"
    )


@pytest.mark.parametrize("stage,key", [
    ("second-member", "instanceId"), ("detached", "muxId"),
    ("reattached", "members"), ("second-member", "duplicate"),
])
def test_native_body_rejects_target_or_member_replacement_before_success(tmp_path, body_io, stage, key):
    def mutate(current, value):
        if current == stage:
            if key == "members":
                value["members"][0]["sessionId"] = "replacement"
            elif key == "duplicate":
                value["members"][1]["memberId"] = value["members"][0]["memberId"]
            else:
                value[key] = "replacement"

    body_io["mutate"] = mutate
    value = report(tmp_path)
    with pytest.raises(AssertionError):
        probe.managed_mux(tmp_path, value)
    assert body_io["events"][-1] == ("command", ("stop", "--all", "--yes"))
    assert "stop_settlement_seconds" not in value["milestones"]


def test_native_body_leaves_ninth_metric_to_outer_physical_settlement(tmp_path, body_io):
    value = report(tmp_path)
    probe.managed_mux(tmp_path, value)
    assert len(value["milestones"]) == 8
    assert "stop_settlement_seconds" not in value["milestones"]
    assert value["managed_stop"]["result"] == {"status": "stopped", "instanceId": "a" * 32}
    assert len(value["managed_observations"]) == 4
    assert body_io["events"][-1] == ("command", ("stop", "--server", "b" * 64, "--yes"))
