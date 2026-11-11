"""Actual original activation owners, real Tasks/Events, controlled inner effects."""

from __future__ import annotations

import asyncio
import gc
import gzip
import json
import weakref
from pathlib import Path
from unittest.mock import patch

import pytest

from loushang.harness.continuity.activation import CallbackPreparedActivationLease
from loushang.harness.continuity.plugin_provider import (
    ContinuityPluginGenerationGate,
    _GenerationActivationLease,
)
from loushang.harness.continuity.types import ContinuityTarget

HERE = Path(__file__).parent
COMMON = (
    "async-success",
    "consume-error",
    "inner-published-error",
    "cancel-consume",
    "consume-abort-interleave",
    "abort-caller-cancel",
    "abort-self-cancel",
    "abort-retry",
    "sync-abort",
    "event-clear",
    "event-set",
    "event-set-with-error",
    "event-set-real-closed-loop",
)
CASES = (
    tuple((route, case) for route in ("callback", "generation") for case in COMMON)
    + tuple(("callback", case) for case in ("sync-success", "no-abort"))
    + tuple(
        ("generation", case)
        for case in (
            "strict-sync-consume",
            "late-properties",
            "admit-reject-retry",
            "gate-closed",
            "closed-priority",
            "attempt-priority",
            "complete-before",
            "complete-after",
            "complete-with-consume-error",
            "unregister-consume",
            "unregister-abort",
            "unregister-and-complete",
            "no-new-self-cycle",
        )
    )
)


def error_data(error, seen=frozenset()):
    if id(error) in seen:
        return {"cycle": type(error).__name__}
    seen = seen | {id(error)}
    return {
        "type": type(error).__module__ + "." + type(error).__qualname__,
        "message": str(error),
        "notes": list(getattr(error, "__notes__", ())),
        "cause": error_data(error.__cause__, seen) if error.__cause__ else None,
        "context": error_data(error.__context__, seen) if error.__context__ else None,
        "suppress_context": error.__suppress_context__,
    }


class Observation:
    def __init__(self, route, case):
        self.route, self.case = route, case
        self.trace = []
        self.lease = None
        self.gate = None
        self.tokens = {}
        self.counts = {}
        self.actors = {}
        self.inner = Inner(self)
        self.gate = Gate(self)
        if case in {"sync-success", "strict-sync-consume"}:
            self.inner.consume = self.inner.sync_consume
        if case == "sync-abort":
            self.inner.abort = self.inner.sync_abort
        self.lease = (
            CallbackPreparedActivationLease(
                target=ContinuityTarget("source", "one"),
                disposition="in_place",
                consume=self.inner.consume,
                abort=None if case == "no-abort" else self.inner.abort,
            )
            if route == "callback"
            else _GenerationActivationLease(self.inner, self.gate)
        )
        if route == "generation":
            assert self.gate._register_lease(self.lease)
        assert self.inner.reads == 0, (
            "constructing Generation must not read inner properties"
        )

    def task(self, task):
        if task is None:
            return None
        if task not in self.tokens:
            self.tokens[task] = "owned" + str(len(self.tokens))
        return {
            "id": self.tokens[task],
            "done": task.done(),
            "cancelled": task.cancelled(),
            "cancelling": task.cancelling(),
        }

    def state(self):
        lease = self.lease
        return {
            "flags": None
            if lease is None
            else {
                name: getattr(lease, name)
                for name in (
                    "_consumed",
                    "_consume_attempted",
                    "_closed",
                    "_consuming",
                    "_abort_requested",
                )
            },
            "done": None if lease is None else lease._consume_done.is_set(),
            "abort_task": None if lease is None else self.task(lease._abort_task),
            "gate": {
                "inflight": self.gate._in_flight,
                "drained": self.gate._drained.is_set(),
                "closing": self.gate.closing,
                "registered": lease in self.gate._leases
                if lease is not None
                else False,
                "lease_count": len(self.gate._leases),
            },
        }

    def log(self, event, **data):
        self.trace.append({"event": event, **data, "state": self.state()})

    def count(self, name):
        self.counts[name] = self.counts.get(name, 0) + 1
        return self.counts[name]

    def spawn(self, label, operation):
        entered = asyncio.Event()

        async def run():
            entered.set()
            return await operation()

        task = asyncio.create_task(run(), name="probe:" + label)
        self.actors[label] = task
        return task, entered

    async def joined(self, label, task):
        try:
            result = await task
        except BaseException as error:
            self.trace.append(
                {
                    "event": "outcome",
                    "label": label,
                    "error": error_data(error),
                    "actor_cancelled": task.cancelled(),
                    "actor_cancelling": task.cancelling(),
                    "state": self.state(),
                }
            )
            return error
        self.trace.append(
            {
                "event": "outcome",
                "label": label,
                "result": result,
                "actor_cancelled": task.cancelled(),
                "actor_cancelling": task.cancelling(),
                "state": self.state(),
            }
        )
        return result

    async def call(self, label, method):
        task, _ = self.spawn(label, method)
        return await self.joined(label, task)


class Inner:
    def __init__(self, o):
        self.o = o
        self.reads = 0
        self.target_value = ContinuityTarget("source", "one")
        self.disposition_value = "in_place"
        self.public_consumed = False
        self.consume_started = asyncio.Event()
        self.abort_started = asyncio.Event()
        self.consume_gate = asyncio.Event()
        self.abort_gate = asyncio.Event()
        self.consume_gate.set()
        self.abort_gate.set()

    @property
    def target(self):
        self.reads += 1
        self.o.log("inner.target")
        return self.target_value

    @property
    def disposition(self):
        self.reads += 1
        self.o.log("inner.disposition")
        return self.disposition_value

    @property
    def consumed(self):
        self.reads += 1
        self.o.log("inner.consumed")
        return self.public_consumed

    async def consume(self):
        self.o.count("consume")
        self.o.log("inner.consume.enter")
        self.consume_started.set()
        await self.consume_gate.wait()
        if self.o.case in {
            "consume-error",
            "inner-published-error",
            "attempt-priority",
            "complete-with-consume-error",
            "event-set-with-error",
        }:
            if self.o.case == "inner-published-error":
                self.public_consumed = True
            self.o.log("inner.consume.error")
            raise RuntimeError("consume failed")
        self.public_consumed = True
        self.o.log("inner.consume.done")
        return "published"

    async def abort(self):
        n = self.o.count("abort")
        self.o.log("inner.abort.enter")
        self.abort_started.set()
        await self.abort_gate.wait()
        if self.o.case == "abort-self-cancel":
            asyncio.current_task().cancel("owned-self-cancel")
            await asyncio.sleep(0)
        if self.o.case == "abort-retry" and n == 1:
            self.o.log("inner.abort.error")
            raise RuntimeError("abort failed")
        self.o.log("inner.abort.done")

    def sync_consume(self):
        self.o.count("consume")
        self.public_consumed = True
        self.o.log("inner.consume.sync")
        return "published"

    def sync_abort(self):
        self.o.count("abort")
        self.o.log("inner.abort.sync")


class Gate(ContinuityPluginGenerationGate):
    def __init__(self, o):
        super().__init__()
        self.o = o
        self.rejects = 0

    def admit(self):
        self.o.log("gate.admit.before")
        if self.o.case == "admit-reject-retry" and self.rejects == 0:
            self.rejects += 1
            raise OSError("admit failed")
        call = super().admit()
        self.o.log("gate.admit.after")
        return call

    def _complete_call(self):
        self.o.log("gate.complete.before")
        if self.o.case in {
            "complete-before",
            "complete-with-consume-error",
            "unregister-and-complete",
        }:
            raise OSError("complete failed")
        super()._complete_call()
        self.o.log("gate.complete.after")
        if self.o.case == "complete-after":
            raise OSError("complete acknowledgement failed")

    def _unregister_lease(self, lease):
        self.o.log("gate.unregister.before")
        if self.o.case in {
            "unregister-consume",
            "unregister-abort",
            "unregister-and-complete",
        }:
            raise OSError("unregister failed")
        super()._unregister_lease(lease)
        self.o.log("gate.unregister.after")


async def exercise(route, case):
    o = Observation(route, case)
    o.log("constructed")
    foreign_loop = None
    if case == "no-new-self-cycle":
        enabled = gc.isenabled()
        gc.disable()
        try:
            await o.lease.consume()
            reference = weakref.ref(o.lease)
            o.lease = None
            o.trace.append(
                {
                    "event": "weakref",
                    "collected_without_gc": reference() is None,
                    "gate_count": len(o.gate._leases),
                }
            )
            assert reference() is None, "completed Generation acquired a new self-cycle"
        finally:
            if enabled:
                gc.enable()
    elif case == "late-properties":
        for value in (0, 1):
            if value:
                o.inner.target_value = ContinuityTarget("changed", "two")
                o.inner.disposition_value = "relaunch"
                o.inner.public_consumed = True
            target = o.lease.target
            disposition = o.lease.disposition
            consumed = o.lease.consumed
            o.trace.append(
                {
                    "event": "properties",
                    "target": [target.provider_id, target.opaque_id],
                    "disposition": disposition,
                    "consumed": consumed,
                }
            )
        await o.call("abort-internal-false", o.lease.abort)
    elif case in {
        "event-clear",
        "event-set",
        "event-set-with-error",
        "event-set-real-closed-loop",
    }:
        if case == "event-set-real-closed-loop":
            foreign_loop = asyncio.new_event_loop()
            future = foreign_loop.create_future()
            future.add_done_callback(lambda _future: None)
            foreign_loop.close()
            o.lease._consume_done._waiters.append(future)
            result = await o.call("consume", o.lease.consume)
            assert (
                isinstance(result, RuntimeError)
                and str(result) == "Event loop is closed"
            )
        else:
            name = "clear" if case == "event-clear" else "set"

            def fail():
                o.log("event." + name + ".error")
                raise RuntimeError("event " + name + " failed")

            with patch.object(o.lease._consume_done, name, fail):
                await o.call("consume", o.lease.consume)
    elif case == "consume-abort-interleave":
        o.inner.consume_gate.clear()
        consume, _ = o.spawn("consume", o.lease.consume)
        await o.inner.consume_started.wait()
        abort, entered = o.spawn("abort-wait", o.lease.abort)
        await entered.wait()
        o.log("abort-waits-consume")
        await o.call("second-consume", o.lease.consume)
        abort.cancel("caller-abort")
        await o.joined("abort-wait", abort)
        o.inner.consume_gate.set()
        await o.joined("consume", consume)
        await o.call("abort-after-success", o.lease.abort)
    elif case == "cancel-consume":
        o.inner.consume_gate.clear()
        task, _ = o.spawn("consume", o.lease.consume)
        await o.inner.consume_started.wait()
        task.cancel("caller-consume")
        await o.joined("consume", task)
        await o.call("abort-after-cancel", o.lease.abort)
    elif case == "abort-caller-cancel":
        o.inner.abort_gate.clear()
        first, _ = o.spawn("abort-one", o.lease.abort)
        await o.inner.abort_started.wait()
        owned = o.lease._abort_task
        second, entered = o.spawn("abort-two", o.lease.abort)
        await entered.wait()
        first.cancel("caller-abort")
        await o.joined("abort-one", first)
        o.log("owned-still-running")
        assert o.lease._abort_task is owned and not owned.cancelled()
        o.inner.abort_gate.set()
        await o.joined("abort-two", second)
        await o.call("abort-three", o.lease.abort)
        assert o.lease._abort_task is owned and o.counts["abort"] == 1
    elif case in {
        "abort-retry",
        "abort-self-cancel",
        "sync-abort",
        "no-abort",
        "unregister-abort",
    }:
        await o.call("abort-one", o.lease.abort)
        task = o.lease._abort_task
        await o.call("consume-after-abort", o.lease.consume)
        await o.call("abort-two", o.lease.abort)
        if case == "abort-self-cancel":
            assert (
                task is not None
                and task.cancelled()
                and o.lease._abort_task is task
                and o.counts["abort"] == 1
            )
        if case == "no-abort":
            assert o.lease._abort_task is None and not o.counts.get("abort")
    elif case in {"closed-priority", "gate-closed"}:
        if case == "closed-priority":
            await o.call("abort", o.lease.abort)
        o.gate.begin_close(security=True)
        o.log("gate.closed")
        await o.call("consume", o.lease.consume)
    elif case == "admit-reject-retry":
        await o.call("consume-one", o.lease.consume)
        assert not o.lease._consume_attempted
        await o.call("consume-two", o.lease.consume)
    elif case == "attempt-priority":
        await o.call("consume-one", o.lease.consume)
        o.gate.begin_close(security=True)
        await o.call("consume-two", o.lease.consume)
        await o.call("abort", o.lease.abort)
    else:
        await o.call("consume-one", o.lease.consume)
        if case in {"consume-error", "inner-published-error", "strict-sync-consume"}:
            o.trace.append({"event": "public-consumed", "value": o.lease.consumed})
            await o.call("consume-two", o.lease.consume)
            await o.call("abort", o.lease.abort)
        elif case in {"async-success", "sync-success"}:
            await o.call("consume-two", o.lease.consume)
            await o.call("close", o.lease.close)
    o.log("final")
    # Settle only probe-created/stdlib shield waiters; no new Product retry policy.
    pending = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]
    if pending:
        o.inner.consume_gate.set()
        o.inner.abort_gate.set()
        await asyncio.gather(*pending, return_exceptions=True)
    return {"route": route, "case": case, "trace": o.trace, "counts": o.counts}


@pytest.mark.parametrize(
    "route,case", CASES, ids=[route + ":" + case for route, case in CASES]
)
def test_activation_runtime(route, case):
    value = asyncio.run(exercise(route, case))
    expected = json.loads(
        gzip.decompress(
            (HERE / "fixtures" / "activation_lease_runtime_v1.json.gz").read_bytes()
        )
    )[route + ":" + case]
    assert json.dumps(value, sort_keys=True) == json.dumps(expected, sort_keys=True)
