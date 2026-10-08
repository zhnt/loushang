"""Fixed Product first-reply scenario for the existing guarded PTY collector.

Call inside the original evidence process/_guarded ownership scope. This is
test composition, not an untouched provider benchmark. Its measured prefix
and helpers must pass the collector's existing provenance checks beforehand.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from ._g18_native_probe import (
    abrupt_terminal,
    assert_active_terminal,
    managed_completion_frame,
    managed_history_confirmation,
    managed_history_observation,
    managed_read_observation,
    managed_reply_observation,
    observe_spawn,
    observed_terminal,
)
from ._lmux_adopted_process import AdoptedLeader, stop_command
from ._lmux_product_frames import (
    approval_details_visible,
    approval_pending_visible,
    assert_no_completed_reply,
    denied_tool_reply_completed,
    reply_completed,
    reply_streaming,
    target_state_visible,
    tool_reply_completed,
)
from .test_mux_product_terminal import _see
from .test_mux_terminal_process import _terminal_environment


def _history_attach(root, report, environment, target, native, identity, *, directory="elsewhere"):
    from ._lmux_history_frames import history_frame_visible

    executable = str(Path(report["measured_prefix"]) / "bin/lmux")
    if directory not in {"elsewhere", "restored-elsewhere"}:
        raise ValueError("unsupported fixed history directory")
    elsewhere = root / directory
    elsewhere.mkdir(mode=0o700)
    with observe_spawn(executable) as spawned, observed_terminal(
        [executable, "attach", "-t", "perf"], elsewhere, environment,
        failure_report=report, settlements=report.setdefault("terminal_settlements", []),
    ) as (driver, master, original):
        report.setdefault("spawns", []).append(spawned)
        driver.read_until(history_frame_visible, timeout=40)
        visible = time.perf_counter()
        assert_active_terminal(master, original)
        offset, completion_start = len(driver.raw_output), time.perf_counter()
        driver.write("/he")
        driver.read_until(lambda output: managed_completion_frame(output, after=offset), timeout=40)
        completed = time.perf_counter()
        driver.write("\x7f\x7f\x7f")
        driver.write("\x02d")
        assert driver.wait(timeout=20) == 0, driver.diagnostics
    final_native = []
    final = managed_history_confirmation(environment, target, identity, native_identity=final_native)
    assert all(final[key] == target[key] for key in ("instanceId", "serviceId", "muxId", "members"))
    assert final_native == native and not list(elsewhere.iterdir())
    _record_native(report, "history-detached", final_native[0])
    return {"history_frame_seconds": visible - spawned["start"],
            "history_completion_seconds": completed - completion_start,
            "actions": {"history_frame": {"started_at": spawned["start"], "finished_at": visible},
                        "history_completion": {"started_at": completion_start, "finished_at": completed}},
            "detached": final}


def _record_native(report, stage, identity):
    """Serialize an already observed identity, never reopen or signal it."""
    from dataclasses import asdict
    report.setdefault("fixed_product_native", {})[stage] = asdict(identity)


def _stop_generation(root, report, environment, target, native):
    """One exact generation; the caller guards against repeating this attempt."""
    executable = str(Path(report["measured_prefix"]) / "bin/lmux")
    stop_started = time.perf_counter()
    leader = AdoptedLeader(native)
    stop_error = None
    try:
        _record_native(report, "stop", native)
        completed = stop_command([executable, "stop", "--server", target["serviceId"], "--yes"],
                                 cwd=root, env=environment, leader=leader)
        results = [json.loads(line) for line in completed.stdout.splitlines()]
        assert len(results) == 2 and results[0]["action"] == "stop_preview"
        assert results[1] == {"status": "stopped", "instanceId": target["instanceId"]}
        stop_observed = time.perf_counter()
    except BaseException as error:
        stop_error = error
        raise
    finally:
        try:
            leader.close()
        except BaseException as cleanup:
            report.setdefault("fixed_product_cleanup_failure", {"type": type(cleanup).__name__[:128]})
            if stop_error is None:
                raise
            stop_error.add_note("first reply leader close failed: " + type(cleanup).__name__)
    report["fixed_product_stop"] = {
        "started_at": stop_started, "observed_at": stop_observed,
        "local_owner_settled_at": time.perf_counter(),
        "service_id": target["serviceId"], "result": results[1],
    }
    return results[1]  # Original outer evidence process still owes settlement.


def first_use(root, report):
    """Three fresh scenarios under the caller's original guarded owner.

    This only produces observations. The collector must validate every receipt
    and its own physical settlement before accepting a sample.
    """
    report["fixed_product_scenarios"] = {}
    for name, options, result_key in (
        ("reply", {}, "fixed_product_first_reply"),
        ("approval", {"tool_approval": True}, "fixed_product_tool_approval"),
        ("interrupt", {"delayed_final": True, "interrupt_next_turn": True},
         "fixed_product_interrupt_next_turn"),
    ):
        workspace = root / name
        workspace.mkdir(mode=0o700)
        child = {
            "measured_prefix": report["measured_prefix"], "workspace": str(workspace),
            "status": "running", "valid": False, "spawns": [],
            "started_at": time.perf_counter(),
        }
        report["fixed_product_scenarios"][name] = child
        try:
            first_reply(workspace, child, **options)
            result = child[result_key]
            timing = result["next_turn"] if name == "interrupt" else result
            child["actions"] = timing["actions"]
            child["milestones"] = {
                key + "_seconds": timing[
                    "spawn_through_visible_reply_seconds"
                    if key == "fixed_entry_through_visible_reply" else key + "_seconds"
                ]
                for key in child["actions"]
            }
            child.update(status="observed", finished_at=time.perf_counter())
        except BaseException as error:
            child.update(status="failed", failure=type(error).__name__)
            raise  # Never continue into the next fresh scenario after failure.
    report["spawns"] = [spawn for child in report["fixed_product_scenarios"].values() for spawn in child["spawns"]]
    report["milestones"] = {key: value for child in report["fixed_product_scenarios"].values()
                            for key, value in child["milestones"].items()}


def _fixed_product_trace(root, instance_id):
    """Read only bounded test observations; never supply lifecycle authority."""
    from ._hosted_boundary_trace import MAX_RECORD_BYTES, MAX_RECORDS

    paths = tuple((root / "lmux-test-observations").glob("boundary-*.jsonl"))
    assert len(paths) == 1, "expected one fixed Product observation stream"
    limit = MAX_RECORD_BYTES * MAX_RECORDS
    with paths[0].open("rb") as stream:
        payload = stream.read(limit + 1)
    assert len(payload) <= limit and payload.endswith(b"\n")
    rows = [json.loads(line) for line in payload.splitlines()]
    assert len(rows) < MAX_RECORDS, "saturated trace is incomplete evidence"
    assert [row["sequence"] for row in rows] == list(range(len(rows)))
    selected = [row for row in rows if row["phase"] == "fixed_product_selected"]
    assert len(selected) == 1 and selected[0]["instance_id"] == instance_id
    return rows


def _tool_effect_witness(root, instance_id, *, executed, not_before_ns=None, evidence=None):
    """A model echo is not a tool effect; only the fixed handler emits this."""
    rows = _fixed_product_trace(root, instance_id)
    effects = [row["call_id"] for row in rows if row["phase"] == "tool_executed"]
    assert effects == (["lmux-call-1"] if executed else []), "tool effect count or identity mismatch"
    if not_before_ns is not None:
        assert executed
        effect = [row for row in rows if row["phase"] == "tool_executed"]
        assert type(effect[0]["monotonic_ns"]) is int
        assert effect[0]["monotonic_ns"] >= not_before_ns, "tool executed before this approval"
    if evidence is not None:
        evidence.extend({"instance_id": instance_id, "call_id": row["call_id"],
                         "monotonic_ns": row["monotonic_ns"], "sequence": row["sequence"]}
                        for row in rows if row["phase"] == "tool_executed")
    return tuple(effects)


def _producer_witness(root, instance_id, *, settled, not_before_ns=None, evidence=None):
    rows = _fixed_product_trace(root, instance_id)
    producers = [(row["phase"], row["call_id"]) for row in rows
                 if row["phase"] in {"producer_started", "producer_settled"}]
    expected = [("producer_started", "lmux-call-1")]
    if settled:
        expected.append(("producer_settled", "lmux-call-1"))
    assert producers == expected
    if not_before_ns is not None:
        assert settled
        finished = [row for row in rows if row["phase"] == "producer_settled"]
        assert len(finished) == 1 and type(finished[0]["monotonic_ns"]) is int
        assert finished[0]["monotonic_ns"] >= not_before_ns, "producer settled before this interrupt"
    if evidence is not None:
        evidence.extend({"instance_id": instance_id, "call_id": row["call_id"],
                         "phase": row["phase"], "monotonic_ns": row["monotonic_ns"],
                         "sequence": row["sequence"]}
                        for row in rows if row["phase"] in {"producer_started", "producer_settled"})
    return "lmux-call-1"


def _interrupt_next_turn(root, report, environment, target, native, interrupted_nonce):
    """Borrow the caller's service; this function owns only its terminal."""
    executable = str(Path(report["measured_prefix"]) / "bin/lmux")
    elsewhere = root / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    next_nonce = uuid.uuid4().hex
    assert next_nonce != interrupted_nonce
    expected = "LMUX_REPLY_" + next_nonce
    with observe_spawn(executable) as spawned, observed_terminal([executable, "attach", "-t", "perf"], elsewhere, environment,
                           failure_report=report, settlements=report.setdefault("terminal_settlements", [])) as (driver, master, original):
        report.setdefault("spawns", []).append(spawned)
        driver.read_until(lambda output: target_state_visible(output, running=True), timeout=40)
        assert_active_terminal(master, original)
        attached_native = []
        attached = managed_read_observation(environment, "reattached", native_identity=attached_native)
        assert all(attached[key] == target[key] for key in ("instanceId", "serviceId", "muxId", "members"))
        assert attached_native == native
        _record_native(report, "reattached", attached_native[0])
        before_producer, after_producer = [], []
        _producer_witness(root, target["instanceId"], settled=False, evidence=before_producer)
        offset, interrupted = len(driver.raw_output), time.perf_counter()
        interrupt_sent_ns = time.monotonic_ns()
        driver.write("\x03")
        driver.read_until(lambda output: target_state_visible(output, running=False, after=offset), timeout=40)
        _producer_witness(root, target["instanceId"], settled=True, not_before_ns=interrupt_sent_ns,
                          evidence=after_producer)
        settled = time.perf_counter()
        offset, sent = len(driver.raw_output), time.perf_counter()
        driver.write("reply " + next_nonce + "\r")  # One attempt, never retry busy/lost replies.
        driver.read_until(lambda output: reply_completed(output, expected, after=offset), timeout=40)
        visible = time.perf_counter()
        driver.write("\x02d")
        assert driver.wait(timeout=20) == 0, driver.diagnostics
    confirmation = managed_reply_observation(environment, target, expected, interrupted_nonce=interrupted_nonce)
    final_native = []
    final = managed_read_observation(environment, "detached", native_identity=final_native)
    assert all(final[key] == target[key] for key in ("instanceId", "serviceId", "muxId", "members"))
    assert final_native == native and not list(elsewhere.iterdir())
    _record_native(report, "final-detached", final_native[0])
    return {
        "interrupt_through_idle_and_producer_seconds": settled - interrupted,
        "next_reply_seconds": visible - sent,
        "interrupt_through_next_reply_seconds": visible - interrupted,
        "actions": {
            "interrupt_through_idle_and_producer": {"started_at": interrupted, "finished_at": settled},
            "next_reply": {"started_at": sent, "finished_at": visible},
            "interrupt_through_next_reply": {"started_at": interrupted, "finished_at": visible},
        },
        "next_reply_confirmation": confirmation,
        "interrupted_nonce": interrupted_nonce, "next_nonce": next_nonce,
        "interrupt_sent_ns": interrupt_sent_ns,
        "producer_before": before_producer, "producer_after": after_producer,
        "reattached": attached, "detached": final,
    }


def _natural_completion(root, report, environment, target, native, nonce):
    """Release only the fixed producer; obtain both replies through public TUI/IPC."""
    from ._lmux_completion_gate import release

    release(root / "lmux-test-observations/completion-gates", target["instanceId"], nonce)
    elsewhere = root / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    expected = "LMUX_REPLY_" + nonce
    next_nonce = uuid.uuid4().hex
    assert next_nonce != nonce
    executable = str(Path(report["measured_prefix"]) / "bin/lmux")
    with observe_spawn(executable) as spawned, observed_terminal([executable, "attach", "-t", "perf"], elsewhere, environment,
                           failure_report=report, settlements=report.setdefault("terminal_settlements", [])) as (driver, master, original):
        report.setdefault("spawns", []).append(spawned)
        driver.read_until(lambda output: reply_completed(output, expected, after=0), timeout=40)
        assert_active_terminal(master, original)
        attached_native = []
        attached = managed_read_observation(environment, "reattached", native_identity=attached_native)
        assert all(attached[key] == target[key] for key in ("instanceId", "serviceId", "muxId", "members"))
        assert attached_native == native
        phases = [row["phase"] for row in _fixed_product_trace(root, target["instanceId"])
                  if row.get("call_id") == "lmux-call-1"]
        assert phases == ["producer_started", "gate_released", "final_emitted", "producer_settled"]
        offset = len(driver.raw_output)
        driver.write("reply " + next_nonce + "\r")
        driver.read_until(lambda output: reply_completed(output, "LMUX_REPLY_" + next_nonce, after=offset), timeout=40)
        driver.write("\x02d")
        assert driver.wait(timeout=20) == 0, driver.diagnostics
    confirmation = managed_reply_observation(environment, target, "LMUX_REPLY_" + next_nonce,
                                            natural_nonce=nonce)
    assert not list(elsewhere.iterdir())
    return {"original_producer_phases": phases, "two_turn_confirmation": confirmation,
            "original_request_resent": False}


def _approve_first_tool(driver, root, target):
    _tool_effect_witness(root, target["instanceId"], executed=False)
    offset, submitted = len(driver.raw_output), time.perf_counter()
    driver.write("approval\r")
    driver.read_until(lambda output: approval_pending_visible(output, after=offset), timeout=40)
    pending = time.perf_counter()
    _tool_effect_witness(root, target["instanceId"], executed=False)
    offset, opened = len(driver.raw_output), time.perf_counter()
    driver.write("/question\r")
    driver.read_until(lambda output: approval_details_visible(output, after=offset), timeout=40)
    presented = time.perf_counter()
    _tool_effect_witness(root, target["instanceId"], executed=False)
    offset = len(driver.raw_output)
    driver.write("\x1b")
    driver.read_until(lambda output: approval_pending_visible(output, after=offset), timeout=40)
    _tool_effect_witness(root, target["instanceId"], executed=False)
    offset, approved = len(driver.raw_output), time.perf_counter()
    approved_sent_ns = time.monotonic_ns()
    driver.write("/approve\r")
    driver.read_until(lambda output: tool_reply_completed(output, after=offset), timeout=40)
    completed = time.perf_counter()
    _tool_effect_witness(root, target["instanceId"], executed=True, not_before_ns=approved_sent_ns)
    return {
        "approval_pending_seconds": pending - submitted,
        "approval_details_seconds": presented - opened,
        "approved_tool_reply_seconds": completed - approved,
        "actions": {
            "approval_pending": {"started_at": submitted, "finished_at": pending},
            "approval_details": {"started_at": opened, "finished_at": presented},
            "approved_tool_reply": {"started_at": approved, "finished_at": completed},
        },
        "approved_sent_ns": approved_sent_ns,
    }


def _denial_receipt(root, target, *, not_before_ns):
    from ._hosted_boundary_trace import MAX_RECORD_BYTES, MAX_RECORDS

    paths = tuple((root / "lmux-interaction-observations").glob("boundary-*.jsonl"))
    assert len(paths) == 1
    limit = MAX_RECORD_BYTES * MAX_RECORDS
    with paths[0].open("rb") as stream:
        payload = stream.read(limit + 1)
    assert len(payload) <= limit and payload.endswith(b"\n")
    rows = [json.loads(line) for line in payload.splitlines()]
    assert len(rows) == 2 and [row["sequence"] for row in rows] == [0, 1]
    assert [row["phase"] for row in rows] == ["interaction_sent", "interaction_accepted"]
    keys = ("attachment_id", "controller_generation", "member_id", "interaction_id", "outcome")
    assert all(rows[0][key] == rows[1][key] for key in keys)
    assert rows[0]["outcome"] == "deny"
    assert rows[0]["member_id"] == target["members"][0]["memberId"]
    assert rows[0]["interaction_id"] and rows[0]["attachment_id"]
    assert type(rows[0]["controller_generation"]) is int and rows[0]["controller_generation"] > 0
    assert all(type(row["monotonic_ns"]) is int for row in rows)
    assert not_before_ns <= rows[0]["monotonic_ns"] <= rows[1]["monotonic_ns"]


def _deny_first_tool(driver, root, target):
    """Deny once without reviewing; never infer zero effects from model text."""
    _tool_effect_witness(root, target["instanceId"], executed=False)
    offset = len(driver.raw_output)
    driver.write("approval\r")
    driver.read_until(lambda output: approval_pending_visible(output, after=offset), timeout=40)
    _tool_effect_witness(root, target["instanceId"], executed=False)
    offset = len(driver.raw_output)
    denied_sent_ns = time.monotonic_ns()
    driver.write("/deny\r")
    driver.read_until(lambda output: denied_tool_reply_completed(output, after=offset), timeout=40)
    _tool_effect_witness(root, target["instanceId"], executed=False)
    return denied_sent_ns


def first_reply(root, report, *, admission_diagnostic=False, delayed_final=False, interrupt_next_turn=False, tool_approval=False, tool_denial=False, transport_loss=False, natural_completion=False, history=False):
    if history and any((admission_diagnostic, delayed_final, interrupt_next_turn, tool_approval, tool_denial, transport_loss, natural_completion)):
        raise ValueError("history requires a fresh independent scenario")
    if natural_completion and (not transport_loss or not delayed_final or interrupt_next_turn):
        raise ValueError("natural completion requires a distinct delayed transport loss scenario")
    if transport_loss and not (delayed_final and (interrupt_next_turn or natural_completion)):
        raise ValueError("transport loss requires the running interrupt/next-turn scenario")
    if tool_approval and tool_denial:
        raise ValueError("tool approval and denial are distinct scenarios")
    if (tool_approval or tool_denial) and (admission_diagnostic or delayed_final or interrupt_next_turn):
        raise ValueError("tool approval uses a fresh independent Session")
    if interrupt_next_turn and not delayed_final:
        raise ValueError("interrupt scenario requires the delayed first turn")
    if admission_diagnostic and delayed_final:
        raise ValueError("delayed-final acceptance must not enable admission tracing")
    prefix = Path(report["measured_prefix"])
    environment = _terminal_environment(root)
    environment.pop("LOUSHANG_TMPDIR", None)
    if tool_approval or tool_denial:
        config = root / ".loushang"
        config.mkdir(mode=0o700)
        with (config / "settings.json").open("x", encoding="utf-8") as stream:
            json.dump({"tools": {"ask_tools": ["lmux_evidence"]}}, stream)
    (root / "lmux-test-observations").mkdir(mode=0o700)
    if natural_completion:
        (root / "lmux-test-observations/completion-gates").mkdir(mode=0o700)
    if tool_denial:
        (root / "lmux-interaction-observations").mkdir(mode=0o700)
    nonce = uuid.uuid4().hex
    expected = "LMUX_REPLY_" + nonce
    argv = [str(prefix / "bin/python"), "-I", str(Path(__file__).with_name("_lmux_product_entry.py")),
            *(["--admission-diagnostic"] if admission_diagnostic else []),
            *(["--interaction-diagnostic"] if tool_denial else []),
            "new", "-s", "perf"]
    if admission_diagnostic:
        report["diagnostic_instrumentation"] = "admission-proxy-not-for-performance"
    primary = None
    stopped = False
    target = None
    native = []
    stop_attempted = False

    def exact_stop():
        nonlocal stop_attempted
        if stop_attempted or target is None or len(native) != 1:
            raise RuntimeError("exact stop unavailable; original outer owner must settle")
        stop_attempted = True
        return _stop_generation(root, report, environment, target, native[0])

    try:
        terminal = abrupt_terminal if transport_loss else observed_terminal
        with observe_spawn(argv[0]) as spawned, terminal(
            argv, root, environment, failure_report=report,
            **({} if transport_loss else {"settlements": report.setdefault("terminal_settlements", [])}),
        ) as (driver, master, original):
            started = spawned["start"]
            report.setdefault("spawns", []).append(spawned)
            _see(driver, "perf |")
            assert_active_terminal(master, original)
            driver.write("/new user_home FirstUse\r")
            _see(driver, "*1")
            target = managed_read_observation(environment, "first-member", native_identity=native)
            assert len(target["members"]) == 1
            report["fixed_product_target"] = target
            _record_native(report, "first-member", native[0])
            before_send = driver.raw_output
            offset, sent = len(before_send), time.perf_counter()
            if tool_denial:
                denied_sent_ns = _deny_first_tool(driver, root, target)
            elif tool_approval:
                tool_steps = _approve_first_tool(driver, root, target)
            elif not history:
                driver.write(("gated " if natural_completion else "delayed " if delayed_final else "reply ") + nonce + "\r")
            if delayed_final:
                def still_streaming(output):
                    assert not reply_completed(output, expected, after=offset), "blocked final reported complete"
                    return reply_streaming(output, expected, after=offset)
                driver.read_until(still_streaming, timeout=40)
            elif not (tool_approval or tool_denial or history):
                driver.read_until(lambda output: reply_completed(output, expected, after=offset), timeout=40)
            visible = time.perf_counter()
            if transport_loss:
                assert driver.is_alive(), "client exited before transport hangup"
                exit_status = driver.hangup_transport(timeout=20)
                # Destroyed stdout/termios may fail during interpreter shutdown.
                # Record that outcome; service continuity must still be proven below.
                assert type(exit_status) is int and exit_status >= 0, driver.diagnostics
            else:
                driver.write("\x02d")
                assert driver.wait(timeout=20) == 0, driver.diagnostics
        # The original client/driver have settled before any observer takes a
        # controller. Only normal detach proves mode restoration; a destroyed
        # PTY cannot provide that observation. Never count a later snapshot as a
        # replacement timestamp for a missing visible completion frame.
        if delayed_final:
            assert_no_completed_reply(driver.raw_output, expected, before_send=before_send)
        confirmation = (managed_history_observation(environment, target) if history else
                        managed_reply_observation(environment, target, "Tool lmux_evidence requires approval", tool_denial=True)
                        if tool_denial else managed_reply_observation(environment, target, "LMUX_TOOL_COMPLETED", tool_approval=True)
                        if tool_approval else managed_reply_observation(environment, target, expected, pending=True,
                            **({"natural_nonce": nonce} if natural_completion else {}))
                        if delayed_final else managed_reply_observation(environment, target, expected))
        later_native = []
        observed = managed_read_observation(environment, "detached", native_identity=later_native)
        assert all(observed[key] == target[key] for key in ("instanceId", "serviceId", "muxId", "members"))
        assert len(native) == 1 and later_native == native
        _record_native(report, "detached", later_native[0])
        report["fixed_product_detached"] = observed
        if delayed_final:
            _producer_witness(root, target["instanceId"], settled=False)
        next_turn = (_interrupt_next_turn(root, report, environment, target, native, nonce)
                     if interrupt_next_turn else None)
        natural_result = (_natural_completion(root, report, environment, target, native, nonce)
                          if natural_completion else None)
        history_result = (_history_attach(root, report, environment, target, native, confirmation["history_identity"])
                          if history else None)
        result = exact_stop()
        stopped = True
        if history:
            from loushang.appserver.protocol import SessionIdentityV1, SessionScopeV1

            from ._lmux_history_canonical import read_history
            identity = dict(confirmation["history_identity"])
            identity["scope"] = SessionScopeV1(identity["scope"])
            canonical_read = {}
            canonical = read_history(Path(environment["LOUSHANG_HOME"]) / "data/sessions",
                                     SessionIdentityV1(**identity), root, receipt=canonical_read)
            report["fixed_product_history"] = {"seed": confirmation, "attach": history_result,
                                               "canonical": canonical, "stop": result,
                                               "canonical_read": canonical_read}
            return
        if tool_denial:
            _denial_receipt(root, target, not_before_ns=denied_sent_ns)
            _tool_effect_witness(root, target["instanceId"], executed=False)
            report["fixed_product_tool_denial"] = {
                "confirmation": confirmation, "stop": result, "tool_execution_count": 0,
            }
            return
        if tool_approval:
            effects = []
            _tool_effect_witness(root, target["instanceId"], executed=True,
                                 not_before_ns=tool_steps["approved_sent_ns"], evidence=effects)
            report["fixed_product_tool_approval"] = {
                **tool_steps, "confirmation": confirmation, "stop": result,
                "tool_call_id": "lmux-call-1", "tool_execution_count": 1,
                "tool_effects": effects,
            }
            return
        if delayed_final:
            producer = _producer_witness(root, target["instanceId"], settled=True)
            report["fixed_product_natural_completion" if natural_completion else "fixed_product_interrupt_next_turn" if interrupt_next_turn else "fixed_product_delayed_final"] = {
                "request_nonce": nonce,
                "pending_confirmation": confirmation, "stop": result,
                "producer": producer, "producer_settled": True,
                "full_text_not_completed": True,
                **({"next_turn": next_turn} if interrupt_next_turn else {}),
                **({"natural_completion": natural_result} if natural_completion else {}),
            }
            return
        report["fixed_product_first_reply"] = {
            "request_nonce": nonce,
            "visible_reply_seconds": visible - sent,
            "spawn_through_visible_reply_seconds": visible - started,
            "actions": {
                "visible_reply": {"started_at": sent, "finished_at": visible},
                "fixed_entry_through_visible_reply": {"started_at": started, "finished_at": visible},
            },
            "confirmation": confirmation, "stop": result,
            "composition": "managed-infrastructure-with-fixed-test-product",
        }
    except BaseException as error:
        primary = error
        raise
    finally:
        if not stopped:
            try:
                if stop_attempted:
                    # Never reopen an already consumed or close-unknown owner.
                    raise RuntimeError("exact stop incomplete; original outer owner must settle")
                exact_stop()
            except BaseException as cleanup:
                report.setdefault("fixed_product_cleanup_failure", {"type": type(cleanup).__name__[:128]})
                if primary is None:
                    raise
                primary.add_note("first reply fallback cleanup failed: " + type(cleanup).__name__)
