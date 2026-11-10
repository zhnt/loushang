"""Actual Hosted Work programs with controlled Session/activation effect ports.

Real Session, Task cancellation, Model Input and Writer proof stays with the
original consumers. These cases freeze only fault ordering and retained state.
"""

from __future__ import annotations

import asyncio
import gzip
import json
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.appserver.protocol import AckV1
from loushang.appservice.execution_guard import ExecutionControlV1
from loushang.coding import _hosted_execution_work as ordinary
from loushang.coding import hosted_resume as resume
from tests.coding.test_hosted_execution import _message

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "hosted_work_custody_v1.json.gz"
CASES = [
    ("ordinary-success", "ordinary", "success", {}),
    ("ordinary-command", "ordinary", "command", {}),
    ("ordinary-rejected", "ordinary", "rejected", {}),
    ("ordinary-failure-precedence", "ordinary", "failure", {}),
    ("ordinary-missing", "ordinary", "missing", {}),
    ("ordinary-assistant-error", "ordinary", "error", {}),
    ("ordinary-assistant-aborted", "ordinary", "aborted", {}),
    ("ordinary-observer-last-message", "ordinary", "scan", {}),
    ("ordinary-turn-interrupt", "ordinary", "turn-interrupt", {}),
    ("ordinary-pre-cancel", "ordinary", "pre-cancel", {}),
    ("ordinary-title-cancelled", "ordinary", "success", {"title_wait:1": "cancel"}),
    ("ordinary-run-cancelled", "ordinary", "success", {"execute:1": "cancel"}),
    (
        "ordinary-run-unbind",
        "ordinary",
        "success",
        {"execute:1": "value", "unbind:1": "value"},
    ),
    (
        "ordinary-cancel-abort-unbind",
        "ordinary",
        "success",
        {"execute:1": "cancel", "abort_retry:1": "value", "unbind:1": "value"},
    ),
    ("resume-success", "resume", "success", {}),
    ("resume-missing", "resume", "missing", {}),
    ("resume-assistant-error", "resume", "error", {}),
    ("resume-assistant-aborted", "resume", "aborted", {}),
    ("resume-observer-last-message", "resume", "scan", {}),
    ("resume-turn-interrupt", "resume", "turn-interrupt", {}),
    ("resume-pre-cancel", "resume", "pre-cancel", {}),
    ("resume-activation-cancelled", "resume", "success", {"activate:1": "cancel"}),
    ("resume-run-cancelled", "resume", "success", {"published:1": "cancel"}),
    (
        "resume-cancel-abort",
        "resume",
        "success",
        {"published:1": "cancel", "abort:1": "value"},
    ),
    (
        "resume-run-unbind",
        "resume",
        "success",
        {"published:1": "value", "unbind:1": "value"},
    ),
]
CASES += [
    (f"ordinary-fault-{event}", "ordinary", "success", {f"{event}:1": "value"})
    for event in (
        "title_wait",
        "subscribe",
        "bind",
        "execute",
        "unbind",
        "settle",
        "unsubscribe",
        "title_start",
        "check_cancel",
    )
]
CASES += [
    (f"resume-fault-{event}", "resume", "success", {f"{event}:1": "value"})
    for event in (
        "activate",
        "subscribe",
        "bind",
        "published",
        "unbind",
        "settle",
        "unsubscribe",
        "title_start",
        "check_cancel",
    )
]
CASES += [
    (
        f"ordinary-cancel-fault-{event}",
        "ordinary",
        "success",
        {"execute:1": "cancel", f"{event}:1": "value"},
    )
    for event in (
        "abort",
        "abort_retry",
        "abort_command",
        "abort_compaction",
        "abort_branch_summary",
    )
]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def observe(case):
    name, kind, mode, requested = case
    trace, counts, fired = [], {}, []
    failures = {
        key: asyncio.CancelledError(key) if error == "cancel" else ValueError(key)
        for key, error in requested.items()
    }

    def event(key, *values):
        trace.append([key, *values])
        counts[key] = counts.get(key, 0) + 1
        occurrence = f"{key}:{counts[key]}"
        if occurrence in failures:
            fired.append(occurrence)
            raise failures[occurrence]

    def error_data(error, seen=None):
        if error is None:
            return None
        seen = set() if seen is None else seen
        if id(error) in seen:
            return {"cycle": True}
        seen.add(id(error))
        return {
            "type": f"{type(error).__module__}.{type(error).__qualname__}",
            "args": list(error.args),
            "identity": next(
                (key for key, value in failures.items() if value is error), None
            ),
            "notes": list(getattr(error, "__notes__", [])),
            "suppress": error.__suppress_context__,
            "cause": error_data(error.__cause__, seen),
            "context": error_data(error.__context__, seen),
        }

    def outcome_data(value):
        if value is None:
            return None
        legacy = value.legacy_result
        assert type(legacy) is AckV1
        return {
            "type": f"{type(value).__module__}.{type(value).__qualname__}",
            "status": value.status.value,
            "error_code": value.error_code,
            "legacy_result": {
                "type": f"{type(legacy).__module__}.{type(legacy).__qualname__}",
                "fields": {
                    field.name: getattr(legacy, field.name) for field in fields(legacy)
                },
            },
        }

    def cancel_requested():
        event("check_cancel")
        return mode == "pre-cancel"

    class Agent:
        def __init__(self):
            self.callback = None
            self.active = False

        def subscribe(self, callback):
            event("subscribe")
            self.callback = callback
            self.active = True

            def unsubscribe():
                event("unsubscribe")
                self.active = False

            return unsubscribe

        def emit(self):
            if mode in {"missing", "command", "rejected", "failure"}:
                return
            messages = [_message(mode if mode in {"error", "aborted"} else "stop")]
            if mode == "scan":
                messages = [_message("error"), object(), _message("stop"), object()]
            event("agent_event")
            assert self.callback is not None
            self.callback({"type": "agent_end", "messages": messages}, object())

    class Session:
        def __init__(self):
            self.agent = Agent()
            self.is_streaming = False

        async def execute_prompt(self, text, *, source, check_cancelled):
            event("execute", text, source, check_cancelled.__self__ is work)
            check_cancelled()
            self.is_streaming = True
            if mode == "turn-interrupt":
                assert control._turn_interrupt is not None
                event("interrupt_result", control._turn_interrupt())
            self.agent.emit()
            self.is_streaming = False
            return SimpleNamespace(
                failure_code="original_failure" if mode == "failure" else None,
                accepted=mode not in {"rejected", "failure"},
                model_started=mode != "command",
            )

        async def _run_published_resume_input(self, *, attempt_id, input_record_id):
            event("published", attempt_id, input_record_id)
            self.is_streaming = True
            if mode == "turn-interrupt":
                assert control._turn_interrupt is not None
                event("interrupt_result", control._turn_interrupt())
            self.agent.emit()
            self.is_streaming = False

        async def settle_execution(self, *, interrupted):
            event("settle", interrupted)

        def abort(self):
            event("abort")
            self.is_streaming = False
            return True

        def abort_retry(self):
            event("abort_retry")

        def abort_command(self):
            event("abort_command")

        def abort_compaction(self):
            event("abort_compaction")

        def abort_branch_summary(self):
            event("abort_branch_summary")

    class Binding:
        async def activate(self, text, **arguments):
            event(
                "activate",
                text,
                arguments["scope"] is scope,
                arguments["subject_control"] is subject_control,
                arguments["subject_digest"],
                arguments["submission_id"],
            )
            return resume._ActivatedHostedResumeV1(session, "attempt-1", "input-1")

        def start_title_if_unnamed(self):
            event("title_start")

    class Control(ExecutionControlV1):
        def bind_turn_interrupt(self, callback):
            event("bind")
            original_unbind = super().bind_turn_interrupt(callback)

            def unbind():
                event("unbind")
                original_unbind()

            return unbind

    async def wait_for_title():
        event("title_wait")

    def start_title():
        event("title_start")

    session, control = Session(), Control()
    scope, subject_control = object(), object()
    if kind == "ordinary":
        work = ordinary.CodingExecutionWorkV1(
            session,
            "original input",
            cancel_requested,
            wait_for_title=wait_for_title,
            start_title=start_title,
        )
    else:
        work = resume._HostedResumeExecutionWorkV1(
            Binding(),
            "original input",
            cancel_requested,
            scope,
            subject_control,
            "subject-1",
            "submission-1",
        )

    def state():
        fields = vars(work)
        observed = fields.get("_agent_outcome", fields.get("_outcome"))
        return {
            "interrupted": work._interrupted,
            "held_session": (fields.get("_session") is session)
            if kind == "resume"
            else work.session is session,
            "observed": outcome_data(observed),
            "unsubscribe_retained": work._unsubscribe is not None,
            "unbind_retained": work._unbind_turn is not None,
            "subscription_active": session.agent.active,
            "control_bound": control._turn_interrupt is not None,
            "start_title_retained": fields.get("_start_title") is not None,
        }

    async def run():
        result, error = None, None
        try:
            result = await work.run(control)
        except BaseException as caught:
            error = caught
        records = {
            "run": {
                "outcome": outcome_data(result),
                "error": error_data(error),
                "state": state(),
            }
        }
        settled = []
        for _ in range(2):
            error = None
            try:
                await work.settle()
            except BaseException as caught:
                error = caught
            settled.append({"error": error_data(error), "state": state()})
        assert sorted(fired) == sorted(requested), (name, fired, requested, trace)
        if requested:
            assert records["run"]["error"] is not None or any(
                item["error"] is not None for item in settled
            ), (name, records, trace)
        elif kind == "ordinary" and mode == "pre-cancel":
            assert (
                records["run"]["error"]["type"] == "asyncio.exceptions.CancelledError"
                and result is None
            ), (name, records, trace)
        else:
            assert records["run"]["error"] is None and result is not None, (
                name,
                records,
                trace,
            )
            expected_status = (
                ordinary.ExecutionStatusV1.INTERRUPTED
                if mode in {"pre-cancel", "aborted"}
                else ordinary.ExecutionStatusV1.FAILED
                if mode in {"missing", "error", "failure", "rejected"}
                else ordinary.ExecutionStatusV1.SUCCEEDED
            )
            assert result.status is expected_status, (name, records, trace)
        records.update(name=name, trace=trace, settlements=settled, fired=fired)
        return records

    return asyncio.run(run())


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_original_ordering(case):
    expected = json.loads(gzip.decompress(FIXTURE.read_bytes()))
    assert canonical(observe(case)) == canonical(expected[case[0]])
