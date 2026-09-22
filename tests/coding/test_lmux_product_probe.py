"""Orchestration fault tests, not installed Product acceptance."""

import json
import time
from contextlib import contextmanager
from types import SimpleNamespace as NS

import pytest

from . import _lmux_product_probe as probe


@pytest.mark.parametrize("fault", [None, "premature", "duplicate", "wrong-call", "wrong-instance", "echo-only"])
def test_tool_effect_is_exact_handler_execution_not_model_echo(tmp_path, fault):
    from ._hosted_boundary_trace import BoundaryTrace

    root = tmp_path / "lmux-test-observations"
    root.mkdir(mode=0o700)
    trace = BoundaryTrace(root)
    trace.emit("fixed_product_selected", instance_id="other" if fault == "wrong-instance" else "instance")
    if fault == "wrong-instance":
        with pytest.raises(AssertionError):
            probe._tool_effect_witness(tmp_path, "instance", executed=False)
        return
    assert probe._tool_effect_witness(tmp_path, "instance", executed=False) == ()
    if fault == "echo-only":
        trace.emit("model_echo", call_id="lmux-call-1")
    else:
        trace.emit("tool_executed", call_id="lmux-call-2" if fault == "wrong-call" else "lmux-call-1")
    if fault == "duplicate":
        trace.emit("tool_executed", call_id="lmux-call-1")
    if fault is None:
        assert probe._tool_effect_witness(tmp_path, "instance", executed=True) == ("lmux-call-1",)
    else:
        with pytest.raises(AssertionError):
            probe._tool_effect_witness(tmp_path, "instance", executed=fault != "premature")


@pytest.mark.parametrize("fault", [None, "early", "duplicate", "wrong-call"])
def test_effect_receipt_retains_original_trace_only_after_validation(tmp_path, monkeypatch, fault):
    row = {"phase": "tool_executed", "call_id": "other" if fault == "wrong-call" else "lmux-call-1",
           "monotonic_ns": 9 if fault == "early" else 11, "sequence": 3}
    monkeypatch.setattr(probe, "_fixed_product_trace", lambda *args: [row, row] if fault == "duplicate" else [row])
    receipt = []
    if fault is None:
        assert probe._tool_effect_witness(tmp_path, "instance", executed=True, not_before_ns=10, evidence=receipt) == ("lmux-call-1",)
        assert receipt == [{"instance_id": "instance", "call_id": "lmux-call-1", "monotonic_ns": 11, "sequence": 3}]
    else:
        with pytest.raises(AssertionError):
            probe._tool_effect_witness(tmp_path, "instance", executed=True, not_before_ns=10, evidence=receipt)
        assert receipt == []


@pytest.mark.parametrize("fault", [None, "wrong-instance", "wrong-call", "duplicate-start", "missing-settlement", "early-settlement"])
def test_producer_witness_requires_same_instance_and_exact_phase_order(tmp_path, fault):
    from ._hosted_boundary_trace import BoundaryTrace

    root = tmp_path / "lmux-test-observations"
    root.mkdir(mode=0o700)
    trace = BoundaryTrace(root)
    trace.emit("fixed_product_selected", instance_id="other" if fault == "wrong-instance" else "instance")
    trace.emit("producer_started", call_id="lmux-call-2" if fault == "wrong-call" else "lmux-call-1")
    if fault == "duplicate-start":
        trace.emit("producer_started", call_id="lmux-call-1")
    if fault == "early-settlement":
        trace.emit("producer_settled", call_id="lmux-call-1")
    if fault in {"wrong-instance", "wrong-call", "duplicate-start", "early-settlement"}:
        with pytest.raises(AssertionError):
            probe._producer_witness(tmp_path, "instance", settled=False)
        return
    assert probe._producer_witness(tmp_path, "instance", settled=False) == "lmux-call-1"
    if fault == "missing-settlement":
        with pytest.raises(AssertionError):
            probe._producer_witness(tmp_path, "instance", settled=True)
    else:
        trace.emit("producer_settled", call_id="lmux-call-1")
        assert probe._producer_witness(tmp_path, "instance", settled=True) == "lmux-call-1"
        with pytest.raises(AssertionError, match="before this interrupt"):
            probe._producer_witness(tmp_path, "instance", settled=True, not_before_ns=time.monotonic_ns() + 1)


@pytest.mark.parametrize("fault", [None, "early", "duplicate", "wrong-call"])
def test_producer_receipt_retains_original_phases_after_validation(tmp_path, monkeypatch, fault):
    rows = [
        {"phase": "producer_started", "call_id": "lmux-call-1", "monotonic_ns": 5, "sequence": 1},
        {"phase": "producer_settled", "call_id": "other" if fault == "wrong-call" else "lmux-call-1",
         "monotonic_ns": 9 if fault == "early" else 11, "sequence": 2},
    ]
    if fault == "duplicate":
        rows.append(dict(rows[-1]))
    monkeypatch.setattr(probe, "_fixed_product_trace", lambda *args: rows)
    receipt = []
    if fault is None:
        assert probe._producer_witness(tmp_path, "instance", settled=True, not_before_ns=10, evidence=receipt) == "lmux-call-1"
        assert receipt == [{**row, "instance_id": "instance"} for row in rows]
    else:
        with pytest.raises(AssertionError):
            probe._producer_witness(tmp_path, "instance", settled=True, not_before_ns=10, evidence=receipt)
        assert receipt == []


@pytest.mark.parametrize("fault", [None, "snapshot", "leader-close", "stop-receipt", "fallback", "frame", "first-read", "adopt", "record-error", "record-interrupt"])
@pytest.mark.parametrize("scenario", ["reply", "delayed", "interrupt", "tool", "denial", "hangup", "natural", "history"])
def test_first_reply_publishes_only_after_snapshot_and_exact_stop(tmp_path, monkeypatch, fault, scenario):
    delayed_final = scenario in {"delayed", "interrupt", "hangup", "natural"}
    interrupt_next_turn = scenario in {"interrupt", "hangup"}
    transport_loss = scenario in {"hangup", "natural"}
    natural_completion = scenario == "natural"
    history = scenario == "history"
    tool_approval = scenario == "tool"
    tool_denial = scenario == "denial"
    events = []
    from loushang.hosting.service import LinuxServiceIdentityV1
    native = LinuxServiceIdentityV1(123, 100, "12345678-1234-1234-1234-123456789abc", 1000, 4, 5)
    target = {"instanceId": "instance", "serviceId": "service", "muxId": "mux",
              "members": [{"memberId": "member", "sessionId": "session"}]}

    class Driver:
        raw_output = ""
        diagnostics = None

        def write(self, text):
            events.append("write")

        def read_until(self, predicate, **kwargs):
            events.append("frame")
            if fault == "frame":
                raise ValueError("frame timeout")

        def wait(self, **kwargs):
            events.append("terminal-wait")
            return 0

        def hangup_transport(self, **kwargs):
            events.append("transport-hangup")
            return 0

        def is_alive(self):
            return True

    @contextmanager
    def terminal(*args, **kwargs):
        try:
            yield Driver(), None, None
        finally:
            events.append("terminal-closed")

    @contextmanager
    def observe_spawn(executable):
        yield {"start": time.perf_counter(), "pid": 123,
               "argv": [executable, "test-entry"], "cwd": str(tmp_path)}

    def observation(environment, stage, *, native_identity=None):
        if fault == "first-read":
            raise ValueError("no authenticated identity")
        if native_identity is not None:
            native_identity.append(native)
        return dict(target)

    def confirm(*args, **kwargs):
        if natural_completion:
            assert len(kwargs.pop("natural_nonce")) == 32
        assert kwargs == ({"tool_denial": True} if tool_denial else {"tool_approval": True} if tool_approval else {"pending": True} if delayed_final else {})
        assert events[-1] == "terminal-closed"
        events.append("snapshot")
        if fault in {"snapshot", "fallback"}:
            raise ValueError("snapshot failure")
        return {"pendingConfirmed" if delayed_final else "replyConfirmed": True}

    def producer(root, instance, *, settled):
        assert instance == "instance" and "snapshot" in events
        assert ("leader-close" in events) is settled
        events.append("producer-settled" if settled else "producer-live")
        return "lmux-call-1"

    def stop(*args, **kwargs):
        events.append("stop")
        if fault == "stop-receipt":
            raise TimeoutError("lost stop receipt")
        if fault == "fallback":
            raise OSError("private details must not enter report")
        return NS(stdout="\n".join(map(json.dumps, [
            {"action": "stop_preview"}, {"status": "stopped", "instanceId": "instance"},
        ])))

    def close():
        events.append("leader-close")
        if fault == "leader-close":
            raise OSError("leader close unknown")

    def adopt(identity):
        assert identity is native and "terminal-closed" in events
        events.append("adopt")
        if fault == "adopt":
            raise ValueError("original leader already exited")
        return NS(close=close)

    monkeypatch.setattr(probe, "observed_terminal", terminal)
    monkeypatch.setattr(probe, "observe_spawn", observe_spawn)
    monkeypatch.setattr(probe, "abrupt_terminal", terminal)
    monkeypatch.setattr(probe, "assert_active_terminal", lambda *args: None)
    monkeypatch.setattr(probe, "_see", lambda *args: None)
    monkeypatch.setattr(probe, "_terminal_environment", lambda root: {"LOUSHANG_HOME": str(root / "platform")})
    monkeypatch.setattr(probe, "managed_read_observation", observation)
    monkeypatch.setattr(probe, "managed_reply_observation", confirm)
    def history_seed(*args):
        confirm()
        return {"history_identity": {"product_id": "coding", "continuity_id": "continuity", "session_id": "session",
                                     "scope": "user_home", "scope_fingerprint": "a" * 64}}
    def history_attach(*args):
        assert events[-1] == "snapshot" and "stop" not in events
        if fault == "frame":
            raise ValueError("history frame timeout")
        return {"history_frame_seconds": 1.0}
    from . import _lmux_history_canonical
    def canonical(root, identity, workspace, *, receipt):
        assert events[-1] == "leader-close"
        assert root == tmp_path / "platform/data/sessions" and workspace == tmp_path
        receipt.update(started_at=1.0, completed_at=2.0)
        return {"verified": True}
    monkeypatch.setattr(probe, "managed_history_observation", history_seed)
    monkeypatch.setattr(probe, "_history_attach", history_attach)
    monkeypatch.setattr(_lmux_history_canonical, "read_history", canonical)
    monkeypatch.setattr(probe, "AdoptedLeader", adopt)
    monkeypatch.setattr(probe, "stop_command", stop)
    record = probe._record_native
    record_error = KeyboardInterrupt() if fault == "record-interrupt" else OSError("record failed")
    def record_native(report, stage, identity):
        if stage == "stop" and fault in {"record-error", "record-interrupt"}:
            raise record_error
        record(report, stage, identity)
    monkeypatch.setattr(probe, "_record_native", record_native)
    monkeypatch.setattr(probe, "_producer_witness", producer)
    def next_turn(*args):
        assert events[-1] == "producer-live"
        events.append("next-turn")
        return {"next_reply_confirmation": {"replyConfirmed": True}}
    monkeypatch.setattr(probe, "_interrupt_next_turn", next_turn)
    monkeypatch.setattr(probe, "_natural_completion", next_turn)
    def approve_tool(*args):
        if fault == "frame":
            raise ValueError("tool frame timeout")
        events.append("tool-approved")
        return {"approved_tool_reply_seconds": 1.0, "approved_sent_ns": 0}
    monkeypatch.setattr(probe, "_approve_first_tool", approve_tool)
    monkeypatch.setattr(probe, "_deny_first_tool", approve_tool)
    monkeypatch.setattr(probe, "_denial_receipt", lambda *args, **kwargs: None)
    def effect(*args, **kwargs):
        assert "leader-close" in events
        assert kwargs["executed"] is (not tool_denial)
        return () if tool_denial else ("lmux-call-1",)
    monkeypatch.setattr(probe, "_tool_effect_witness", effect)
    report = {"measured_prefix": str(tmp_path / "install")}
    key = ("fixed_product_history" if history else "fixed_product_natural_completion" if natural_completion else "fixed_product_tool_denial" if tool_denial else "fixed_product_tool_approval" if tool_approval else "fixed_product_interrupt_next_turn" if interrupt_next_turn
           else "fixed_product_delayed_final" if delayed_final else "fixed_product_first_reply")
    if fault is None:
        probe.first_reply(tmp_path, report, delayed_final=delayed_final, interrupt_next_turn=interrupt_next_turn, tool_approval=tool_approval, tool_denial=tool_denial, transport_loss=transport_loss, natural_completion=natural_completion, history=history)
        assert ("transport-hangup" in events) is transport_loss
        assert report[key]["stop"]["instanceId"] == "instance"
        assert report["fixed_product_target"] == target
        assert report["fixed_product_detached"] == target
        stopped = report["fixed_product_stop"]
        assert stopped["started_at"] <= stopped["observed_at"] <= stopped["local_owner_settled_at"]
        assert stopped["result"] == report[key]["stop"]
        assert "outer_owner_settled_at" not in stopped
        assert events[-1] == ("producer-settled" if delayed_final else "leader-close")
        if delayed_final:
            assert "fixed_product_first_reply" not in report
        if scenario == "reply":
            value = report[key]
            actions = value["actions"]
            reply = actions["visible_reply"]
            cumulative = actions["fixed_entry_through_visible_reply"]
            assert cumulative["started_at"] == report["spawns"][0]["start"]
            assert cumulative["started_at"] <= reply["started_at"] <= reply["finished_at"]
            assert cumulative["finished_at"] == reply["finished_at"]
            assert value["visible_reply_seconds"] == reply["finished_at"] - reply["started_at"]
            assert value["spawn_through_visible_reply_seconds"] == cumulative["finished_at"] - cumulative["started_at"]
    else:
        with pytest.raises({"snapshot": ValueError, "fallback": ValueError, "frame": ValueError,
                            "first-read": ValueError, "adopt": ValueError,
                            "leader-close": OSError, "stop-receipt": TimeoutError,
                            "record-error": OSError, "record-interrupt": KeyboardInterrupt}[fault]) as caught:
            probe.first_reply(tmp_path, report, delayed_final=delayed_final, interrupt_next_turn=interrupt_next_turn, tool_approval=tool_approval, tool_denial=tool_denial, transport_loss=transport_loss, natural_completion=natural_completion, history=history)
        assert key not in report
        if fault in {"first-read", "adopt", "leader-close", "stop-receipt", "fallback", "record-error", "record-interrupt"}:
            assert "fixed_product_stop" not in report
        assert events.count("adopt") == (0 if fault == "first-read" else 1)
        assert events.count("stop") == (0 if fault in {"first-read", "adopt", "record-error", "record-interrupt"} else 1)
        if fault in {"record-error", "record-interrupt"}:
            assert events.count("leader-close") == 1
            assert caught.value is record_error
    if fault == "fallback":
        assert report["fixed_product_cleanup_failure"] == {"type": "OSError"}


@pytest.mark.parametrize("fault", [None, "pending", "details", "back", "reply", "effect-before", "effect-after"])
def test_tool_approval_requires_details_and_no_premature_effect(tmp_path, monkeypatch, fault):
    writes, reads, effects = [], [], []

    class Driver:
        raw_output = ""

        def write(self, text):
            writes.append(text)

        def read_until(self, *args, **kwargs):
            phase = ("pending", "details", "back", "reply")[len(reads)]
            reads.append(phase)
            if fault == phase:
                raise TimeoutError(phase)

    def effect(root, instance, *, executed, not_before_ns=None):
        assert instance == "instance"
        effects.append(executed)
        if executed:
            assert writes[-1] == "/approve\r" and reads[-1] == "reply"
            assert type(not_before_ns) is int
        else:
            assert "/approve\r" not in writes
        if fault == ("effect-after" if executed else "effect-before"):
            raise AssertionError("effect evidence mismatch")

    monkeypatch.setattr(probe, "_tool_effect_witness", effect)
    if fault is None:
        clock = iter([10.0, 12.0, 20.0, 23.0, 30.0, 34.0])
        monkeypatch.setattr(probe.time, "perf_counter", lambda: next(clock))
        result = probe._approve_first_tool(Driver(), tmp_path, {"instanceId": "instance"})
        assert set(result) == {"approval_pending_seconds", "approval_details_seconds", "approved_tool_reply_seconds", "approved_sent_ns", "actions"}
        assert result["actions"] == {
            "approval_pending": {"started_at": 10.0, "finished_at": 12.0},
            "approval_details": {"started_at": 20.0, "finished_at": 23.0},
            "approved_tool_reply": {"started_at": 30.0, "finished_at": 34.0},
        }
        assert [result[key + "_seconds"] for key in result["actions"]] == [2.0, 3.0, 4.0]
        assert writes == ["approval\r", "/question\r", "\x1b", "/approve\r"]
        assert effects == [False, False, False, False, True]
    else:
        with pytest.raises((TimeoutError, AssertionError)):
            probe._approve_first_tool(Driver(), tmp_path, {"instanceId": "instance"})
    assert writes.count("/approve\r") <= 1
    if fault in {"pending", "details", "back", "effect-before"}:
        assert "/approve\r" not in writes


@pytest.mark.parametrize("fault", [None, "pending", "reply", "before", "after"])
def test_denial_is_once_without_review_and_requires_zero_effects(tmp_path, monkeypatch, fault):
    writes, reads, checks = [], [], []

    class Driver:
        raw_output = ""

        def write(self, text):
            writes.append(text)

        def read_until(self, *args, **kwargs):
            phase = ("pending", "reply")[len(reads)]
            reads.append(phase)
            if phase == fault:
                raise TimeoutError(phase)

    def effect(*args, executed):
        assert executed is False
        checks.append(False)
        if fault == ("after" if "/deny\r" in writes else "before"):
            raise AssertionError("unexpected effect")

    monkeypatch.setattr(probe, "_tool_effect_witness", effect)
    if fault is None:
        probe._deny_first_tool(Driver(), tmp_path, {"instanceId": "instance"})
        assert writes == ["approval\r", "/deny\r"] and len(checks) == 3
    else:
        with pytest.raises((TimeoutError, AssertionError)):
            probe._deny_first_tool(Driver(), tmp_path, {"instanceId": "instance"})
    assert writes.count("/deny\r") <= 1
    assert "/question\r" not in writes and "/approve\r" not in writes


def test_effect_after_last_zero_check_but_before_approval_is_rejected(tmp_path, monkeypatch):
    from ._hosted_boundary_trace import BoundaryTrace

    clock, checks, writes = [10], [], []
    monkeypatch.setattr(probe.time, "monotonic_ns", lambda: clock[0])
    root = tmp_path / "lmux-test-observations"
    root.mkdir(mode=0o700)
    trace = BoundaryTrace(root)
    trace.emit("fixed_product_selected", instance_id="instance")
    original = probe._tool_effect_witness

    def effect(*args, **kwargs):
        result = original(*args, **kwargs)
        if not kwargs["executed"]:
            checks.append(False)
            if len(checks) == 4:
                trace.emit("tool_executed", call_id="lmux-call-1")
                clock[0] = 100
        return result

    class Driver:
        raw_output = ""

        def write(self, text):
            writes.append(text)

        def read_until(self, *args, **kwargs):
            pass

    monkeypatch.setattr(probe, "_tool_effect_witness", effect)
    with pytest.raises(AssertionError, match="before this approval"):
        probe._approve_first_tool(Driver(), tmp_path, {"instanceId": "instance"})
    assert checks == [False] * 4 and writes.count("/approve\r") == 1


@pytest.mark.parametrize("fault", [None, "reattach", "idle", "producer", "early-settled", "reply", "snapshot", "native"])
def test_interrupt_next_turn_never_retries_and_closes_terminal_before_snapshot(tmp_path, monkeypatch, fault):
    events, writes, reads = [], [], []
    from loushang.hosting.service import LinuxServiceIdentityV1
    native = LinuxServiceIdentityV1(123, 100, "12345678-1234-1234-1234-123456789abc", 1000, 4, 5)
    target = {"instanceId": "instance", "serviceId": "service", "muxId": "mux", "members": []}

    class Driver:
        raw_output = ""
        diagnostics = None

        def read_until(self, *args, **kwargs):
            phase = ("reattach", "idle", "reply")[len(reads)]
            reads.append(phase)
            if fault == phase:
                raise TimeoutError(phase)

        def write(self, text):
            writes.append(text)

        def wait(self, **kwargs):
            return 0

    @contextmanager
    def terminal(argv, cwd, env, **kwargs):
        assert argv[-3:] == ["attach", "-t", "perf"] and cwd == tmp_path / "elsewhere"
        try:
            yield Driver(), None, None
        finally:
            events.append("terminal-closed")

    def observe(env, stage, *, native_identity):
        native_identity.append(object() if fault == "native" else native)
        return target

    @contextmanager
    def spawn(executable):
        yield {"start": 1.0, "pid": 456, "argv": [executable, "attach", "-t", "perf"],
               "cwd": str(tmp_path / "elsewhere")}

    def producer(root, instance, *, settled, not_before_ns=None, evidence=None):
        if evidence is not None:
            evidence.append({"phase": "producer_started"})
        if not settled:
            assert reads == ["reattach"] and writes == []
            if fault == "early-settled":
                raise AssertionError("reattach settled producer before interrupt")
            return
        assert reads[-1] == "idle" and writes == ["\x03"]
        assert type(not_before_ns) is int
        if fault == "producer":
            raise AssertionError("producer not settled")
        if evidence is not None:
            evidence.append({"phase": "producer_settled"})

    def confirm(env, actual, expected, *, interrupted_nonce):
        assert events == ["terminal-closed"] and actual is target
        assert interrupted_nonce == "a" * 32 and expected == "LMUX_REPLY_" + "b" * 32
        if fault == "snapshot":
            raise AssertionError("snapshot mismatch")
        return {"replyConfirmed": True}

    monkeypatch.setattr(probe, "observed_terminal", terminal)
    monkeypatch.setattr(probe, "assert_active_terminal", lambda *args: None)
    monkeypatch.setattr(probe, "managed_read_observation", observe)
    monkeypatch.setattr(probe, "observe_spawn", spawn)
    monkeypatch.setattr(probe, "managed_reply_observation", confirm)
    monkeypatch.setattr(probe, "_producer_witness", producer)
    monkeypatch.setattr(probe.uuid, "uuid4", lambda: NS(hex="b" * 32))
    report = {"measured_prefix": str(tmp_path / "install")}
    if fault is None:
        clock = iter([10.0, 12.0, 20.0, 25.0])
        monkeypatch.setattr(probe.time, "perf_counter", lambda: next(clock))
        result = probe._interrupt_next_turn(tmp_path, report, {}, target, [native], "a" * 32)
        assert result["next_reply_confirmation"]["replyConfirmed"] is True
        assert result["interrupted_nonce"] == "a" * 32 and result["next_nonce"] == "b" * 32
        assert result["producer_before"] == [{"phase": "producer_started"}]
        assert result["producer_after"] == [{"phase": "producer_started"}, {"phase": "producer_settled"}]
        assert report["spawns"][0]["argv"][-3:] == ["attach", "-t", "perf"]
        assert result["actions"] == {
            "interrupt_through_idle_and_producer": {"started_at": 10.0, "finished_at": 12.0},
            "next_reply": {"started_at": 20.0, "finished_at": 25.0},
            "interrupt_through_next_reply": {"started_at": 10.0, "finished_at": 25.0},
        }
        # The cumulative interval includes the eight-second observation/input gap.
        assert result["interrupt_through_next_reply_seconds"] == 15.0
        assert result["interrupt_through_idle_and_producer_seconds"] + result["next_reply_seconds"] == 7.0
        assert writes == ["\x03", "reply " + "b" * 32 + "\r", "\x02d"]
    else:
        with pytest.raises((TimeoutError, AssertionError)):
            probe._interrupt_next_turn(tmp_path, report, {}, target, [native], "a" * 32)
    assert events == ["terminal-closed"]
    assert sum(text.startswith("reply ") for text in writes) <= 1
    assert writes.count("\x03") <= 1
