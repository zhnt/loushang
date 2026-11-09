"""Explicit fixed original custody observations outside default test discovery.

Actual asyncio Tasks, Task.cancel(), native Lifecycle/PreparedOperation and exact
Root DTO/debt objects are used. Root/domain services, Product admission, Session
and cleanup owner effects are controlled ports; native files/Writer/Model are not
proved here. Completed factory is a controlled already-finished Future on 3.11,
not Python 3.12 eager_task_factory. Rejected coroutine cleanup belongs to observer.
No recapture. Original immutable source and raw observations remain outside Product.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from loushang.coding import resume_continuation as domain
from loushang.coding._resume_cleanup import CodingResumeContinuationCleanupFailure
from loushang.coding.runtime import agent_session_runtime as code
from loushang.harness.session.lifecycle import (
    SessionLifecycleHooks,
    SessionLifecycleRuntime,
    SessionLifecycleTransition,
)
from tests.coding.probe_native_release_readers_compatibility import error_graph

CASES = (
    "abort",
    "consume",
    "stale",
    "wrapper-error",
    "bind-error",
    "transition-error",
    "debt",
    "debt-fail-once",
    "abort-fail-once",
    "prepare-fail",
    "host-bind-fail",
    "cancel-prepare",
    "double-cancel-prepare",
    "cancel-late-success",
    "cancel-late-abort-fails",
    "cancel-prepare-debt",
    "cancel-delivery",
    "double-cancel-delivery",
    "delivery-rejected",
    "delivery-postcommit-fail",
    "duplicate-delivery",
    "foreign-root",
    "foreign-operation-abort",
    "closed-consume",
    "closed-prepare",
    "wrong-loop",
    "busy-before-admit",
    "prune-before-admit",
    "factory-prepare",
    "factory-delivery",
    "completed-factory",
    "completed-factory-failure",
    "drain-cancel-prepare",
    "drain-error-preparation",
    "drain-operation-failure",
    "drain-debt-failure",
    "drain-prepare-delivery",
)


def observe(case, base, patch):
    async def scenario():
        trace = []
        out = []
        sessions = []
        operations = []
        rejected = []
        drivers = []
        debts = []
        foreign_loops = []
        domain_calls = 0
        dispose_calls = 0
        debt_calls = 0
        factory_calls = 0
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        release = asyncio.Event()
        delivery_entered = asyncio.Event()
        delivery_cancelled = asyncio.Event()
        delivery_release = asyncio.Event()
        retained = hasattr(SessionLifecycleRuntime, "prepare_retained_candidate")
        Wrapper = code.CodingRuntimePreparedResume

        def ledger(root, key):
            names = (
                {
                    "tasks": "_retained_preparation_tasks",
                    "deliveries": "_retained_delivery_tasks",
                    "operations": "_retained_prepared_operations",
                    "debts": "_retained_preparation_debts",
                    "loop": "_retained_preparation_loop",
                }
                if retained
                else {
                    "tasks": "_resume_activation_tasks",
                    "deliveries": "_resume_delivery_tasks",
                    "operations": "_resume_prepared_operations",
                    "debts": "_resume_cleanup_debts",
                    "loop": "_resume_activation_loop",
                }
            )
            return getattr(root.lifecycle if retained else root, names[key])

        def set_loop(root, loop):
            setattr(
                root.lifecycle if retained else root,
                "_retained_preparation_loop" if retained else "_resume_activation_loop",
                loop,
            )

        def op_name(op):
            if op not in operations:
                operations.append(op)
            return "op-" + str(operations.index(op) + 1)

        def snapshot(root):
            return {
                "tasks": sorted(
                    [
                        {
                            "done": t.done(),
                            "cancelled": t.cancelled(),
                            "cancelling": getattr(t, "cancelling", lambda: 0)(),
                        }
                        for t in ledger(root, "tasks")
                    ],
                    key=str,
                ),
                "deliveries": sorted(
                    [
                        [op_name(op), task.done(), task.cancelled()]
                        for op, task in ledger(root, "deliveries").items()
                    ]
                ),
                "operations": sorted(
                    [
                        [op_name(op), op.consumed, op._state]
                        for op in ledger(root, "operations")
                    ]
                ),
                "debts": [
                    {
                        "same": debt in debts,
                        "owner": debt.original_owner.name,
                        "error": str(debt.original_error),
                    }
                    for debt in ledger(root, "debts")
                ],
                "loop_bound": ledger(root, "loop") is asyncio.get_running_loop(),
                "current": getattr(root.current_session, "name", None),
            }

        def value(v):
            if isinstance(v, Wrapper):
                return {
                    "wrapper": True,
                    "root": v._root is root,
                    "operation": op_name(v._operation),
                    "continuation": v.continuation is continuations[-1],
                    "consumed": v.consumed,
                }
            if hasattr(v, "current"):
                return {
                    "current": getattr(v.current, "name", None),
                    "previous": getattr(v.previous, "name", None),
                    "cancelled": v.cancelled,
                    "payload": v.payload,
                }
            return v

        async def capture(label, fn):
            try:
                result = await fn()
                error = None
            except BaseException as exc:
                result = None
                error = error_graph(exc, lambda s: s.replace(str(base), "<ROOT>"))
                error["code"] = getattr(exc, "code", None)
            out.append(
                {
                    "label": label,
                    "value": value(result),
                    "error": error,
                    "state": snapshot(root),
                }
            )
            return result

        class Session:
            def __init__(self, name):
                self.name = name
                self.disposed = False
                sessions.append(self)

            def set_extension_runtime_host(self, host):
                trace.append(["host-bind", self.name, host is root])
                if case == "host-bind-fail":
                    raise OSError("host binding rejected")

            async def dispose(self):
                nonlocal dispose_calls
                dispose_calls += 1
                trace.append(["dispose", self.name, dispose_calls])
                if (
                    case
                    in (
                        "abort-fail-once",
                        "cancel-late-abort-fails",
                        "drain-operation-failure",
                    )
                    and dispose_calls == 1
                ):
                    raise OSError("candidate dispose failed once")
                self.disposed = True

        class DebtOwner:
            name = "native-debt-owner"

            async def dispose_runtime_profile(self):
                nonlocal debt_calls
                debt_calls += 1
                trace.append(["debt-retry", debt_calls])
                if case in ("debt-fail-once", "drain-debt-failure") and debt_calls == 1:
                    raise OSError("original debt retry failed")

        def make_debt():
            debt = CodingResumeContinuationCleanupFailure(
                original_owner=DebtOwner(),
                original_error=OSError("native preparation failed"),
                cleanup_error=OSError("native cleanup failed"),
            )
            debts.append(debt)
            return debt

        async def before(previous, transition):
            trace.append(["before", getattr(previous, "name", None), transition.reason])

        async def prepare_session(session, previous, transition):
            trace.append(["prepare-session", session.name])
            if case == "delivery-rejected":
                raise PermissionError("native activation denied")
            if case in (
                "cancel-delivery",
                "double-cancel-delivery",
                "duplicate-delivery",
            ):
                delivery_entered.set()
                try:
                    await delivery_release.wait()
                except asyncio.CancelledError:
                    trace.append(["delivery-cancel"])
                    delivery_cancelled.set()
                    await delivery_release.wait()
                    raise

        async def activate(session, previous, transition):
            trace.append(["activate", session.name])
            if case == "delivery-postcommit-fail":
                raise OSError("activation failed after delivery")
            if case == "drain-prepare-delivery":
                delivery_entered.set()
                try:
                    await delivery_release.wait()
                except asyncio.CancelledError:
                    trace.append(["delivery-cancel"])
                    raise

        async def dispose(session):
            await session.dispose()

        async def after(result, transition):
            trace.append(["after", getattr(result.current, "name", None)])

        def build_root():
            instance = object.__new__(code.AgentSessionRuntime)
            instance._lifecycle = SessionLifecycleRuntime(
                store=NS(),
                hooks=SessionLifecycleHooks(
                    before_transition=before,
                    prepare_session=prepare_session,
                    activate_session=activate,
                    dispose_session=dispose,
                    after_commit=after,
                ),
            )
            instance._owned_transcript_factory = object()
            instance._product_owner_selection = NS(
                resume_epoch_fingerprint=lambda path: "b" * 64
            )
            instance._embedded_resume_approval_owner = None
            instance._resume_history_closed = False
            if not retained:
                instance._resume_activation_tasks = set()
                instance._resume_delivery_tasks = {}
                instance._resume_prepared_operations = set()
                instance._resume_cleanup_debts = []
                instance._resume_activation_loop = None
            return instance

        root = build_root()
        continuations = []
        attempt = NS(epoch_fingerprint="b" * 64)
        plan = NS(workspace_root=str(base))

        async def native_prepare(**kwargs):
            nonlocal domain_calls
            domain_calls += 1
            trace.append(["domain", domain_calls])
            kwargs["require_current_admission"](attempt)
            if case in ("prepare-fail", "completed-factory-failure"):
                raise OSError("native prepare rejected")
            if case in ("debt", "debt-fail-once", "drain-debt-failure"):
                raise make_debt()
            if case in (
                "cancel-prepare",
                "double-cancel-prepare",
                "cancel-late-success",
                "cancel-late-abort-fails",
                "cancel-prepare-debt",
                "drain-cancel-prepare",
                "drain-error-preparation",
            ):
                entered.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    trace.append(["domain-cancel"])
                    cancelled.set()
                    await release.wait()
                    if case == "cancel-prepare-debt":
                        raise make_debt()
                    if case == "drain-error-preparation":
                        raise OSError("native preparation failed during drain")
                    if case not in ("cancel-late-success", "cancel-late-abort-fails"):
                        raise
            session = Session("session-" + str(domain_calls))
            continuation = NS(
                session=session, attempt_id="attempt", input_record_id="input"
            )
            continuations.append(continuation)
            return continuation

        patch.setattr(domain, "prepare_coding_resume_continuation", native_prepare)
        patch.setattr(code, "_bind_owned_session_manager", lambda factory: factory)
        kwargs = dict(
            session_file=base / "saved.jsonl",
            plan=plan,
            current_owner_inputs=(),
            attempt=attempt,
            input_record_id="input",
            text="continue",
            created_at=None,
            require_current_admission=lambda observed: trace.append(
                ["admit", observed is attempt]
            ),
            require_current_epoch_settlement=lambda *args: None,
        )

        def prepare_root(**changes):
            return root.prepare_resume_continuation(**(kwargs | changes))

        if case == "wrapper-error":

            def fail_wrapper(*args):
                trace.append(["wrapper-error"])
                raise ValueError("wrapper construction failed")

            patch.setattr(code, "CodingRuntimePreparedResume", fail_wrapper)
        if case == "transition-error":

            def fail_transition(*args, **kwargs):
                trace.append(["transition-error"])
                raise OSError("transition value failed")

            patch.setattr(code, "SessionLifecycleTransition", fail_transition)
        if case == "bind-error":

            async def bypass(transition, build):
                session = Session("bypassed")
                return await ordinary_prepare(
                    transition, lambda previous: ready(session)
                )

            ordinary_prepare = root.lifecycle._prepare_candidate
            patch.setattr(root.lifecycle, "_prepare_candidate", bypass)

        async def ready(v):
            return v

        loop = asyncio.get_running_loop()
        old_factory = loop.get_task_factory()

        def factory(loop, coro, **options):
            nonlocal factory_calls
            factory_calls += 1
            name = coro.cr_code.co_name
            trace.append(["factory", name])
            if (case == "factory-prepare" and name == "prepare") or (
                case == "factory-delivery" and name == "consume"
            ):
                rejected.append(coro)
                raise OSError("task factory rejected " + name)
            if (
                case in ("completed-factory", "completed-factory-failure")
                and name == "prepare"
            ):
                result = loop.create_future()
                try:
                    coro.send(None)
                except StopIteration as done:
                    result.set_result(done.value)
                except BaseException as exc:
                    result.set_exception(exc)
                else:
                    coro.close()
                    raise AssertionError("completed factory unexpectedly suspended")
                return result
            return asyncio.Task(coro, loop=loop, **options)

        loop.set_task_factory(factory)

        def drive(coro):
            task = asyncio.Task(coro, loop=loop)
            drivers.append(task)
            return task

        async def barrier(task, event):
            waiter = drive(event.wait())
            try:
                await asyncio.wait((task, waiter), return_when=asyncio.FIRST_COMPLETED)
                if not event.is_set():
                    await task
                    raise AssertionError("expected barrier not reached")
            finally:
                waiter.cancel()
                await asyncio.gather(waiter, return_exceptions=True)

        async def drain():
            await root._drain_resume_activations()

        try:
            if case == "closed-prepare":
                root._resume_history_closed = True
                await capture("prepare", prepare_root)
            elif case == "wrong-loop":
                foreign = asyncio.new_event_loop()
                foreign_loops.append(foreign)
                set_loop(root, foreign)
                await capture("prepare", prepare_root)
                await capture("drain", drain)
                set_loop(root, None)
            elif case in (
                "cancel-prepare",
                "double-cancel-prepare",
                "cancel-late-success",
                "cancel-late-abort-fails",
                "cancel-prepare-debt",
            ):
                task = drive(prepare_root())
                await barrier(task, entered)
                trace.append(["before-cancel", snapshot(root)])
                task.cancel()
                await barrier(task, cancelled)
                if case == "double-cancel-prepare":
                    task.cancel()
                release.set()
                await capture("prepare-waiter", lambda: task)
                await capture("drain", drain)
            elif case in ("drain-cancel-prepare", "drain-error-preparation"):
                task = drive(prepare_root())
                await barrier(task, entered)
                closing = drive(drain())
                await barrier(closing, cancelled)
                if case == "drain-cancel-prepare":
                    closing.cancel()
                    await capture("first-drain", lambda: closing)
                release.set()
                await capture("prepare-waiter", lambda: task)
                if case == "drain-error-preparation":
                    await capture("first-drain", lambda: closing)
                await capture("second-drain", drain)
            else:
                prepared = await capture("prepare", prepare_root)
                if prepared is not None:
                    operation = prepared._operation
                    op_name(operation)
                    if (
                        case == "consume"
                        or case == "delivery-rejected"
                        or case == "delivery-postcommit-fail"
                    ):
                        await capture("consume", prepared.consume)
                    elif case in (
                        "cancel-delivery",
                        "double-cancel-delivery",
                        "duplicate-delivery",
                    ):
                        task = drive(prepared.consume())
                        await barrier(task, delivery_entered)
                        trace.append(["delivery-held", snapshot(root)])
                        if case == "duplicate-delivery":
                            await capture("second-consume", prepared.consume)
                        task.cancel()
                        await barrier(task, delivery_cancelled)
                        if case == "double-cancel-delivery":
                            task.cancel()
                        delivery_release.set()
                        await capture("delivery-waiter", lambda: task)
                    elif case == "drain-prepare-delivery":
                        delivery = drive(prepared.consume())
                        await barrier(delivery, delivery_entered)
                        preparation = drive(prepare_root())
                        # A callback barrier runs after preparation has queued on the held native transition.
                        turn = loop.create_future()
                        loop.call_soon(turn.set_result, None)
                        await turn
                        trace.append(["both-held", snapshot(root)])
                        await capture("drain", drain)
                        await capture("delivery-waiter", lambda: delivery)
                        await capture("prepare-waiter", lambda: preparation)
                    elif case in ("busy-before-admit", "prune-before-admit"):
                        original_set = ledger(root, "operations")
                        if case == "prune-before-admit":
                            await capture("consume", prepared.consume)
                        await capture(
                            "prepare-invalid-admit",
                            lambda: prepare_root(require_current_admission=None),
                        )
                        trace.append(
                            [
                                "set-replaced",
                                ledger(root, "operations") is not original_set,
                            ]
                        )
                    elif case == "foreign-root":
                        await capture(
                            "foreign-consume",
                            lambda: root._consume_resume_preparation(
                                replace(prepared, _root=object())
                            ),
                        )
                        await capture(
                            "foreign-abort",
                            lambda: root._abort_resume_preparation(
                                replace(prepared, _root=object())
                            ),
                        )
                    elif case == "foreign-operation-abort":
                        other = build_root()
                        foreign = await other.lifecycle._prepare_candidate(
                            SessionLifecycleTransition(reason="resume"),
                            lambda previous: ready(Session("foreign")),
                        )
                        await capture(
                            "foreign-abort",
                            lambda: replace(prepared, _operation=foreign).abort(),
                        )
                    elif case == "closed-consume":
                        root._resume_history_closed = True
                        await capture("consume", prepared.consume)
                        await capture("abort", prepared.abort)
                    elif case == "stale":
                        root.lifecycle._host._current = Session("successor")
                        await capture("consume", prepared.consume)
                    elif case == "factory-delivery":
                        await capture("consume", prepared.consume)
                    elif case in ("abort-fail-once", "drain-operation-failure"):
                        if case == "abort-fail-once":
                            await capture("abort", prepared.abort)
                        else:
                            await capture("first-drain", drain)
                    else:
                        await capture("abort", prepared.abort)
                if case in ("debt-fail-once", "drain-debt-failure"):
                    await capture("first-drain", drain)
                await capture("drain", drain)
            trace.append(
                ["rejected-coroutines-closed", [c.cr_frame is None for c in rejected]]
            )
            for coro in rejected:
                coro.close()
            trace.append(["sessions", [[s.name, s.disposed] for s in sessions]])
            return {"outputs": out, "trace": trace, "final": snapshot(root)}
        finally:
            release.set()
            delivery_release.set()
            for task in drivers:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*drivers, return_exceptions=True)
            for coro in rejected:
                coro.close()
            loop.set_task_factory(old_factory)
            for foreign in foreign_loops:
                foreign.close()

    return asyncio.run(scenario())


@pytest.mark.parametrize("case", CASES)
def test_original_prepared_operation_custody(case, tmp_path, monkeypatch):
    fixture = json.loads(
        (
            Path(__file__).with_name("fixtures") / "prepared_operation_custody_v1.json"
        ).read_text()
    )
    assert observe(case, tmp_path, monkeypatch) == fixture["observations"][case]
