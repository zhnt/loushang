"""Finite original Work-scope ordering, using controlled domain/Session ports.

Execute the real ScopedSessionWork program. Existing Work-shell tests supply the
real cancellation/idle ownership evidence; injected CancelledError here is only
an exception-scope observation. Expected records were frozen on the original source only; this carrier never captures.
"""

from __future__ import annotations

import asyncio
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding.adapters import _goal_planning_work as coding

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "planning_scope_custody_v1.json.gz"
CASES = [
    ("planning", "planning", "unread", {}, None),
    ("repair-inspect", "repair", "inspect", {}, None),
    ("repair-edit", "repair", "repair", {}, None),
    ("repair-alias", "repair", "change", {}, "alias"),
    ("unsupported", "repair", "unknown", {}, None),
    ("unhashable-alias", "repair", "repair", {}, "list-alias"),
    ("missing-getter", "planning", None, {}, "missing"),
    ("empty-reservation", "repair", "repair", {}, "empty"),
    ("reservation-failure", "repair", "repair", {"execution:1": "value"}, None),
    ("enter-failure", "repair", "repair", {"enter:1": "value"}, None),
    ("step-read-failure", "repair", "repair", {"step:1": "value"}, None),
    ("alias-failure", "repair", "repair", {"aliases:1": "value"}, "bad-alias"),
    ("initial-policy-failure", "repair", "repair", {"policy:1": "value"}, None),
    ("configure-failure", "repair", "repair", {"configure:1": "value"}, None),
    ("delegate-failure", "planning", None, {"execute:1": "value"}, None),
    ("repair-allowance-failed", "repair", "repair", {}, "failed"),
    ("planning-allowance-failed", "planning", None, {}, "failed"),
    ("idle-failure", "repair", "repair", {"idle:1": "value"}, None),
    ("release-failure", "repair", "repair", {"release:1": "value"}, None),
    ("leave-failure", "repair", "repair", {"leave:1": "value"}, None),
    ("cleanup-policy-failure", "repair", "repair", {"policy:2": "value"}, None),
    ("last-policy-failure", "repair", "repair", {"policy:3": "value"}, None),
    (
        "delegate-idle-leave",
        "repair",
        "repair",
        {"execute:1": "value", "idle:1": "value", "leave:1": "value"},
        None,
    ),
    (
        "delegate-release",
        "repair",
        "repair",
        {"execute:1": "value", "release:1": "value"},
        None,
    ),
    ("idle-cancel", "repair", "repair", {"idle:1": "cancel"}, None),
    (
        "delegate-interrupt-release",
        "repair",
        "repair",
        {"execute:1": "interrupt", "release:1": "value"},
        None,
    ),
    (
        "delegate-cancel-policy",
        "repair",
        "repair",
        {"execute:1": "cancel", "policy:2": "value"},
        None,
    ),
    ("direct-cancel", "repair", "repair", {}, "cancel-only"),
    ("direct-cancel-error", "repair", "repair", {"cancel:1": "value"}, "cancel-only"),
]


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def observe(case):
    name, phase, step, requested, mode = case
    trace, fired, counts = [], [], {}
    errors = {
        key: (
            asyncio.CancelledError(key)
            if kind == "cancel"
            else KeyboardInterrupt(key)
            if kind == "interrupt"
            else ValueError(key)
        )
        for key, kind in requested.items()
    }
    reservation, result = object(), object()

    def event(key, *values):
        trace.append([key, *values])
        counts[key] = counts.get(key, 0) + 1
        occurrence = f"{key}:{counts[key]}"
        if occurrence in errors:
            fired.append(occurrence)
            raise errors[occurrence]

    class Policy:
        def __init__(self):
            self.value = None

        @property
        def step(self):
            return self.value

        @step.setter
        def step(self, value):
            event("policy", value)
            self.value = value

    class Allowance:
        def __init__(self):
            self.phase = None
            self.fenced = False
            self.failed = mode == "failed"
            self.stream = object()

        def enter(self, operation_id, selected_phase):
            event("enter", operation_id, selected_phase)
            self.phase = selected_phase

        def leave(self, operation_id):
            event("leave", operation_id)
            self.phase = None

    class Session:
        def __init__(self):
            self.configured = False
            self.runtime = SimpleNamespace(execution_configuration=self)

        def configure_execution(self, value, **options):
            event(
                "configure",
                value is reservation,
                list(options["tool_names"]),
                options["stream_fn"] is allowance.stream,
                options["additional_policy"] is policy,
            )
            self.configured = True

        async def wait_for_idle(self):
            event("idle")

        def release_execution(self, value):
            event("release", value is reservation)
            self.configured = False

    class Delegate:
        async def execute(self, operation, context):
            event("execute", operation is operation_value, context is context_value)
            return result

        async def cancel_and_wait(self, operation, context):
            event("cancel", operation is operation_value, context is context_value)
            return result

    class Context:
        @property
        def step_id(self):
            event("step")
            return step

    class BadAliases:
        def get(self, value, default):
            event("aliases", value, default)
            return default

    def execution():
        event("execution")
        return None if mode == "empty" else reservation

    def graph(error, seen=None):
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
                (key for key, value in errors.items() if value is error), None
            ),
            "suppress": error.__suppress_context__,
            "notes": list(getattr(error, "__notes__", [])),
            "cause": graph(error.__cause__, seen),
            "context": graph(error.__context__, seen),
        }

    allowance, policy, session = Allowance(), Policy(), Session()
    operation_value = SimpleNamespace(operation_id="operation-1")
    context_value = Context()
    work = coding.ScopedSessionWork(
        Delegate(),
        session=session,
        allowance=allowance,
        policy=policy,
        phase=phase,
        execution=None if mode == "missing" else execution,
        step_aliases={"change": "repair"}
        if mode == "alias"
        else {"repair": []}
        if mode == "list-alias"
        else None,
    )
    if mode == "bad-alias":
        work.step_aliases = BadAliases()

    async def run():
        value = None
        error = None
        try:
            value = await (
                work.cancel_and_wait(operation_value, context_value)
                if mode == "cancel-only"
                else work.execute(operation_value, context_value)
            )
        except BaseException as caught:
            error = caught
        assert sorted(fired) == sorted(requested), (name, fired, requested, trace)
        if requested:
            assert error is not None, (name, trace)
        if not requested and name not in {
            "unsupported",
            "missing-getter",
            "empty-reservation",
            "repair-allowance-failed",
            "unhashable-alias",
        }:
            assert error is None and value is result, (name, error, trace)
        if name in {
            "unsupported",
            "missing-getter",
            "empty-reservation",
            "repair-allowance-failed",
        }:
            assert isinstance(error, coding.GoalError), (name, error, trace)
        if name == "unhashable-alias":
            assert type(error) is TypeError and any(
                item[0] == "idle" for item in trace
            ), (name, error, trace)
        return {
            "name": name,
            "trace": trace,
            "error": graph(error),
            "returned_original": value is result,
            "phase": allowance.phase,
            "fenced": allowance.fenced,
            "failed": allowance.failed,
            "step": policy.value,
            "configured": session.configured,
            "fired": fired,
        }

    return asyncio.run(run())


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_original_ordering(case):
    expected = json.loads(gzip.decompress(FIXTURE.read_bytes()))
    assert canonical(observe(case)) == canonical(expected[case[0]])
