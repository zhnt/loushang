"""Frozen delegated Work runtime compatibility over real Tasks and shared control.

Parent/child SDK Session, factory, transcript-reader, Work lookup and Blob ports
are controlled. SessionMultiAgentRuntime, MultiAgentControl, SubagentRunHandle,
original family/Work methods, original context codecs and model allowance run.
This is distinct from the original real SDK consumers.
"""

from __future__ import annotations

import asyncio
import dataclasses
import gzip
import hashlib
import importlib
import json
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

_FIXTURE = Path(__file__).parent / "fixtures" / "goal_delegation_runtime_v1.json.gz"
_EXPECTED = json.loads(gzip.decompress(_FIXTURE.read_bytes()))


def error_data(error, seen=frozenset()):
    if id(error) in seen:
        return {"cycle": type(error).__name__}
    seen = seen | {id(error)}
    return {
        "type": type(error).__module__ + "." + type(error).__qualname__,
        "message": str(error),
        "code": getattr(error, "code", None),
        "notes": list(getattr(error, "__notes__", ())),
        "suppress_context": error.__suppress_context__,
        "cause": error_data(error.__cause__, seen) if error.__cause__ else None,
        "context": error_data(error.__context__, seen) if error.__context__ else None,
    }


def freeze(value):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, BaseException):
        return error_data(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return value.name
    if dataclasses.is_dataclass(value):
        return {
            "type": type(value).__name__,
            "fields": {
                field.name: freeze(getattr(value, field.name))
                for field in dataclasses.fields(value)
            },
        }
    if isinstance(value, dict):
        return {str(k): freeze(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [freeze(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(
            [freeze(v) for v in value], key=lambda v: json.dumps(v, sort_keys=True)
        )
    return {"type": type(value).__name__}


CASES = (
    "fresh",
    "reuse",
    "inherit",
    "prepare-context-error",
    "inherit-reader-error",
    "inherit-source-change",
    "inherit-material-change",
    "parent-model-change",
    "selection-revision-change",
    "operation-mismatch",
    "wrong-step",
    "allowance-enter-error",
    "report-put-error",
    "report-read-error",
    "report-validation-error",
    "report-publish-error",
    "model-allowance-failed",
    "round-failed",
    "completion-mismatch",
    "idle-error",
    "primary-and-idle-error",
    "interrupt-error",
    "create-error",
    "create-owned-error",
    "cancel-create",
    "cancel-create-owned-error",
    "cancel-round",
    "cancel-reuse",
    "cancel-delivery",
    "cancel-inherit-read",
    "cancel-waiter",
    "duplicate-execute",
    "cancel-before-execute",
    "release-retry",
    "release-waiter-cancel",
    "close-retry",
    "repeat-release",
    "views-select-confirm",
)


class Trace:
    def __init__(self, case):
        self.case = case
        self.rows = []
        self.moment = "prepare"
        self.sdks = []
        self.children = []
        self.created = asyncio.Event()
        self.create_release = asyncio.Event()
        self.round_started = asyncio.Event()
        self.round_release = asyncio.Event()
        self.delivery_enter = asyncio.Event()
        self.delivery_release = asyncio.Event()
        self.reader_enter = asyncio.Event()
        self.reader_release = asyncio.Event()
        self.dispose_enter = asyncio.Event()
        self.dispose_release = asyncio.Event()
        self.idle_failed = False
        self.report_failed = False

    def add(self, label, **values):
        self.rows.append({"event": label, **{k: freeze(v) for k, v in values.items()}})


class BlobPort:
    def __init__(self, trace):
        self.trace = trace
        self.values = {}

    def put_bytes(self, content, **kwargs):
        from loushang.harness.artifacts.references import SessionBlobRef

        self.trace.add("blob.put", body=json.loads(content), **kwargs)
        if self.trace.case in {"report-put-error", "primary-and-idle-error"}:
            raise OSError("report put failed")
        digest = hashlib.sha256(content).hexdigest()
        sid = "foreign" if self.trace.case == "report-validation-error" else "parent"
        ref = SessionBlobRef(
            sid,
            digest,
            kwargs["logical_name"],
            kwargs["kind"],
            kwargs["media_type"],
            "private",
            len(content),
            digest,
            0.0,
            kwargs.get("source"),
        )
        self.values[digest] = content
        return ref

    def read_bytes(self, ref):
        self.trace.add("blob.read", ref=ref)
        if self.trace.case == "report-read-error":
            raise OSError("report read failed")
        return self.values[ref.blob_id]


class ManagerPort:
    def __init__(self, trace):
        from loushang.ai.types import UserMessage
        from loushang.harness.conversation.types import ConversationRecord
        from loushang.harness.transcript.kinds import AGENT_MESSAGE_KIND

        self.trace = trace
        self.header = NS(conversation_id="parent")
        self.records = (
            ConversationRecord(
                "r1",
                None,
                AGENT_MESSAGE_KIND,
                1,
                "2026-01-02T03:04:05Z",
                UserMessage(
                    role="user", timestamp=0, content="original inherited request"
                ),
            ),
        )

    def get_leaf_id(self):
        self.trace.add("manager.leaf")
        if self.trace.case == "prepare-context-error":
            raise OSError("context unavailable")
        return "r1"

    def get_branch(self, watermark):
        self.trace.add("manager.branch", watermark=watermark)
        if (
            self.trace.case == "inherit-material-change"
            and self.trace.moment == "execute"
        ):
            return (
                dataclasses.replace(
                    self.records[0],
                    payload=dataclasses.replace(
                        self.records[0].payload, content="changed history"
                    ),
                ),
            )
        return self.records

    def get_cwd(self):
        return str(self.trace.workspace)


class SessionPort:
    def __init__(self, trace, sid, model):
        self.trace = trace
        self.session_id = sid
        self.agent = NS(model=model)
        self.session_manager = ManagerPort(trace)
        self.extension_runner = None
        self.pending_message_count = 0
        self.is_streaming = False
        self.auto_retry_enabled = True
        self.auto_compaction_enabled = True

    def get_active_tool_names(self):
        return ("read", "edit", "write")

    def set_auto_retry_enabled(self, value):
        self.auto_retry_enabled = value

    def set_auto_compaction_enabled(self, value):
        self.auto_compaction_enabled = value

    async def wait_for_idle(self):
        self.trace.add("session.idle", session=self.session_id)
        if (
            self.trace.case in {"idle-error", "primary-and-idle-error"}
            and not self.trace.idle_failed
        ):
            self.trace.idle_failed = True
            raise RuntimeError("idle failed")


class SdkPort:
    def __init__(self, trace, model, **kwargs):
        self.trace = trace
        self.ref = kwargs["delegated_execution_profile"].actor_ref
        self.session = SessionPort(
            trace, "child-" + str(self.ref.path).strip("/").replace("/", "-"), model
        )
        self.disposed = False
        self.dispose_attempts = 0
        trace.sdks.append(self)
        trace.add(
            "sdk.construct",
            ref=self.ref,
            tools=kwargs.get("selected_exact_tool_names"),
            multiagent=kwargs.get("enable_multiagent"),
        )

    async def create_session(self, *, cwd):
        self.trace.add("sdk.create.enter", ref=self.ref)
        self.trace.created.set()
        if self.trace.case.startswith("cancel-create"):
            await self.trace.create_release.wait()
        if self.trace.case in {"create-error", "create-owned-error"}:
            raise ValueError("child create failed")
        self.trace.add("sdk.create.return", ref=self.ref)
        return self.session

    async def dispose_session_runtime(self):
        self.dispose_attempts += 1
        self.trace.add("sdk.dispose", ref=self.ref, attempt=self.dispose_attempts)
        if self.trace.case == "release-waiter-cancel" and self.dispose_attempts == 1:
            self.trace.dispose_enter.set()
            await self.trace.dispose_release.wait()
            raise OSError("late dispose failed")
        if (
            self.trace.case
            in {
                "create-owned-error",
                "cancel-create-owned-error",
                "release-retry",
                "close-retry",
            }
            and self.dispose_attempts == 1
        ):
            raise OSError("child dispose failed")
        self.disposed = True


class DriverPort:
    def __init__(self, trace, child):
        self.trace = trace
        self.child = child
        self.aborted = False

    def deliver(self, message):
        self.trace.add("driver.deliver", ref=self.child.ref, text=message.text)

    async def run_round(self, *, round_id, mode):
        from loushang.harness.multiagent import SubagentRoundResult

        self.trace.add(
            "driver.round.enter", ref=self.child.ref, round=round_id, mode=mode
        )
        self.child.session.is_streaming = True
        self.trace.round_started.set()
        try:
            block = self.trace.case in {
                "cancel-round",
                "cancel-delivery",
                "cancel-waiter",
                "duplicate-execute",
                "interrupt-error",
            } or (self.trace.case == "cancel-reuse" and round_id == 2)
            if block:
                await self.trace.round_release.wait()
            status = (
                "interrupted"
                if self.aborted
                else "failed"
                if self.trace.case == "round-failed"
                else "completed"
            )
            if self.trace.case == "model-allowance-failed":
                self.child.family.owner._allowance.failed = True
            self.trace.add(
                "driver.round.return", ref=self.child.ref, round=round_id, status=status
            )
            return SubagentRoundResult(status, "controlled child result", duration_ms=0)
        finally:
            self.child.session.is_streaming = False

    def abort(self):
        self.trace.add("driver.abort", ref=self.child.ref)
        if self.trace.case == "interrupt-error":
            raise OSError("abort failed")
        self.aborted = True
        self.trace.round_release.set()

    async def dispose(self):
        from loushang.harness.multiagent import SubagentDisposeResult

        self.trace.add("driver.dispose", ref=self.child.ref)
        await self.child.dispose_session_runtime()
        return SubagentDisposeResult()


class ReaderPort:
    def __init__(self, trace, manager):
        self.trace = trace
        self.manager = manager

    async def read(self, ids):
        self.trace.add("reader.read.enter", ids=ids)
        self.trace.reader_enter.set()
        if self.trace.case == "cancel-inherit-read":
            await self.trace.reader_release.wait()
        if self.trace.case == "inherit-reader-error":
            raise OSError("reader failed")
        value = NS(
            store_identity="changed-source"
            if self.trace.case == "inherit-source-change"
            else "source-A",
            records=tuple(NS(record=r) for r in self.manager.records),
        )
        self.trace.add("reader.read.return", identity=value.store_identity)
        return value


async def wait_signal(signal):
    await asyncio.wait_for(signal.wait(), 3)


def snapshot(family, work, trace):
    allowance = family.owner._allowance
    return {
        "family": {
            "active": family.active is work,
            "closing": family.closing,
            "fenced": family.fenced,
            "pending": freeze(family.cleanup_pending),
            "last_ref": freeze(family.last_ref),
            "selection_revision": family.revision,
        },
        "allowance": {
            "operation": allowance.operation_id,
            "phase": allowance.phase,
            "fenced": allowance.fenced,
            "failed": allowance.failed,
        },
        "work": {
            "cancelled": work.cancelled if work else None,
            "task_done": work.task.done() if work and work.task else None,
            "creation_done": work.creation.done() if work and work.creation else None,
            "ref": freeze(work.ref) if work else None,
            "round": work.round if work else None,
        },
        "children": [
            {
                "ref": freeze(ref),
                "session": child.session.session_id if child.session else None,
                "origin": child.origin,
                "last_operation": child.last_operation,
                "last_round": child.last_round,
                "step": child.policy.step,
                "disposed": child.sdk.disposed,
                "dispose_attempts": child.sdk.dispose_attempts,
            }
            for ref, child in family.children.items()
        ],
        "records": freeze(family.control.registry.records(include_closed=True)),
        "runtime": {
            "closed": family.runtime._closed,
            "disposing": family.runtime._disposing,
            "handles": len(family.runtime._handles),
            "cleanup_tasks": len(family.runtime._cleanup_tasks),
        },
    }


async def scenario(case, workspace):
    module = importlib.import_module("loushang.coding.adapters._goal_delegation")
    choice_module = importlib.import_module(
        "loushang.coding.adapters._goal_execution_context"
    )
    from loushang.ai.model import ModelSelection
    from loushang.coding.adapters._goal_planning_limits import PlanningCallAllowance
    from loushang.harness.multiagent import ForkTier, MultiAgentControl
    from loushang.harness.multiagent.run_handle import SubagentRunHandle
    from loushang.harness.session.multiagent import (
        SessionSubagentBinding,
        SessionSubagentCreationError,
    )
    from loushang.harnesswork.types import WorkOperation

    trace = Trace(case)
    trace.workspace = workspace
    model = ModelSelection("test", "local", "model")
    allowance = PlanningCallAllowance(total_limit=20)
    for name in ("enter", "leave"):
        original = getattr(allowance, name)

        def observed(*args, original=original, name=name):
            trace.add("allowance." + name, args=args)
            return original(*args)

        setattr(allowance, name, observed)
    parent = SessionPort(trace, "parent", model)
    runs = {}
    work_port = NS(get_run_for_operation=lambda value: runs.get(value))
    owner = NS(
        workspace=workspace,
        data_root=workspace / "data",
        _session=parent,
        _work=work_port,
        _allowance=allowance,
    )

    class FactoryPort:
        def __init__(self, **kwargs):
            self.builder = kwargs["runtime_builder"]

        async def create(self, request):
            trace.add("factory.create", ref=request.record.ref)
            child = self.builder(
                delegated_execution_profile=NS(actor_ref=request.record.ref)
            )
            driver = DriverPort(trace, child)
            try:
                await child.create_session(cwd=str(workspace))
                return SessionSubagentBinding(driver)
            except BaseException as error:
                trace.add("factory.create.error", error=error)
                try:
                    await driver.dispose()
                except BaseException as cleanup:
                    raise SessionSubagentCreationError(
                        driver, error, cleanup, ref=request.record.ref
                    ) from error
                raise

    profile = NS(
        execution_policy=choice_module.SessionExecutionPolicy(),
        system_prompt="controlled Goal system",
        tool_policy=lambda root: NS(step=None, verification=None),
    )
    blobs = BlobPort(trace)
    reader = ReaderPort(trace, parent.session_manager)
    core_init = MultiAgentControl.__init__
    handle_init = SubagentRunHandle.__init__

    def control_init(self, **kwargs):
        kwargs["clock"] = lambda: datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        return core_init(self, **kwargs)

    def handle_constructor(self, **kwargs):
        kwargs["monotonic_clock"] = lambda: 0.0
        return handle_init(self, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(patch.object(module, "CodingSubagentFactory", FactoryPort))
        stack.enter_context(
            patch.object(
                module,
                "_create_agent_session_runtime",
                lambda **kwargs: SdkPort(trace, model, **kwargs),
            )
        )
        stack.enter_context(patch.object(MultiAgentControl, "__init__", control_init))
        stack.enter_context(
            patch.object(SubagentRunHandle, "__init__", handle_constructor)
        )
        family = module.DelegatedSessions(
            owner, profile, blobs, reader, "source-A", None
        )
        reports = []

        def publish(fact):
            trace.add("context.publish", fact=fact)
            if case == "report-publish-error":
                raise OSError("publish failed")
            reports.append(fact)

        def prepare(number, choice=None):
            if choice is not None:
                family.select(choice)
            basis = NS(identity={"goal": "g", "epoch": 1})
            operation = WorkOperation(
                "op-" + str(number), "before", "parent", "coding", {}
            )
            spec = NS(method_id="method", plan_id="plan")
            turn = NS(step_id="repair", text="controlled repair")
            op, work, frozen = family.prepare(basis, operation, spec, turn)
            trace.add("prepared", operation=op, frozen=frozen)
            return (
                op,
                work,
                NS(run_id="run-" + str(number), step_id="repair", publish=publish),
            )

        async def execute(op, work, context):
            try:
                await work.execute(op, context)
            except BaseException as error:
                trace.add("execute.error", error=error)
            else:
                runs[op.operation_id] = NS(status="completed")
                trace.add("execute.return")

        work = None
        try:
            if case in {
                "reuse",
                "cancel-reuse",
                "release-retry",
                "release-waiter-cancel",
                "close-retry",
                "repeat-release",
                "views-select-confirm",
            }:
                old_case = trace.case
                trace.case = "warmup"
                op, work, context = prepare(1)
                await execute(op, work, context)
                trace.case = old_case
                trace.round_started.clear()
                trace.round_release.clear()
            if case in {
                "release-retry",
                "release-waiter-cancel",
                "close-retry",
                "repeat-release",
                "views-select-confirm",
            }:
                ref = family.last_ref
                if case == "views-select-confirm":
                    trace.add("views", value=family.views())
                    family.select(choice_module.SessionChoice("reuse", target=ref))
                    trace.add("selected", revision=family.revision)
                    next_op, next_work, next_context = prepare(2)
                    trace.add("confirm.current", value=family.confirm(next_work.frozen))
                    family.select(choice_module.SessionChoice("fresh"))
                    trace.add("confirm.changed", value=family.confirm(next_work.frozen))
                elif case == "release-waiter-cancel":
                    task = asyncio.create_task(family.release(ref))
                    await wait_signal(trace.dispose_enter)
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        trace.add("release.waiter.cancelled")
                    trace.dispose_release.set()
                    await asyncio.gather(
                        *tuple(family.runtime._cleanup_tasks), return_exceptions=True
                    )
                    trace.add("release.retained", state=snapshot(family, work, trace))
                    await family.release(ref)
                    trace.add("release.retry.return")
                else:
                    action = (
                        family.close
                        if case == "close-retry"
                        else lambda: family.release(ref)
                    )
                    try:
                        await action()
                    except BaseException as error:
                        trace.add(
                            "release-or-close.error",
                            error=error,
                            state=snapshot(family, work, trace),
                        )
                    await action()
                    trace.add("release-or-close.retry.return")
                trace.add("before.cleanup", state=snapshot(family, work, trace))
                return trace
            if case == "prepare-context-error":
                try:
                    prepare(
                        1, choice_module.SessionChoice("inherit", tier=ForkTier.all())
                    )
                except BaseException as error:
                    trace.add("prepare.error", error=error)
                return trace
            inherited = case.startswith("inherit-") or case in {
                "inherit",
                "cancel-inherit-read",
            }
            op, work, context = prepare(
                2 if case == "cancel-reuse" or case == "reuse" else 1,
                choice_module.SessionChoice("inherit", tier=ForkTier.all())
                if inherited
                else None,
            )
            trace.moment = "execute"
            if case == "parent-model-change":
                parent.agent.model = ModelSelection("test", "local", "changed")
            if case == "selection-revision-change":
                family.select(choice_module.SessionChoice("fresh"))
            if case == "operation-mismatch":
                op = dataclasses.replace(op, payload={})
            if case == "wrong-step":
                context.step_id = "other"
            if case == "allowance-enter-error":
                allowance.phase = "planning"
            if case == "cancel-before-execute":
                trace.add(
                    "cancel.result", outcome=await work.cancel_and_wait(op, context)
                )
            if case == "completion-mismatch":
                original = family.runtime.await_completion

                async def mismatch(**kwargs):
                    return dataclasses.replace(await original(**kwargs), round_id=99)

                stack.enter_context(
                    patch.object(family.runtime, "await_completion", mismatch)
                )
            if case == "cancel-delivery":
                # A real reuse delivery runs while the original family gate is
                # held. A cancellation caller must wait for this delivery.
                trace.case = "warmup"
                first_op, first, first_context = prepare(9)
                await execute(first_op, first, first_context)
                trace.case = case
                op, work, context = prepare(10)
                trace.round_started.clear()
                trace.round_release.clear()
                original = family.runtime.send_message

                async def delayed(**kwargs):
                    trace.add("delivery.enter")
                    trace.delivery_enter.set()
                    await trace.delivery_release.wait()
                    return await original(**kwargs)

                stack.enter_context(
                    patch.object(family.runtime, "send_message", delayed)
                )
            caller = asyncio.create_task(execute(op, work, context))
            if case.startswith("cancel-create"):
                await wait_signal(trace.created)
                outcome = await work.cancel_and_wait(op, context)
                trace.add("cancel.result", outcome=outcome)
            elif case in {
                "cancel-round",
                "cancel-reuse",
                "cancel-waiter",
                "duplicate-execute",
                "interrupt-error",
            }:
                await wait_signal(trace.round_started)
                if case == "duplicate-execute":
                    try:
                        await work.execute(op, context)
                    except BaseException as error:
                        trace.add("duplicate.error", error=error)
                    trace.round_release.set()
                elif case == "cancel-waiter":
                    caller.cancel()
                    await caller
                    trace.add(
                        "waiter.cancelled",
                        inner_done=work.task.done(),
                        state=snapshot(family, work, trace),
                    )
                    trace.add(
                        "cancel.result", outcome=await work.cancel_and_wait(op, context)
                    )
                elif case == "interrupt-error":
                    trace.add(
                        "cancel.result", outcome=await work.cancel_and_wait(op, context)
                    )
                    trace.round_release.set()
                else:
                    trace.add(
                        "cancel.result", outcome=await work.cancel_and_wait(op, context)
                    )
            elif case == "cancel-delivery":
                await wait_signal(trace.delivery_enter)
                canceller = asyncio.create_task(work.cancel_and_wait(op, context))
                await asyncio.sleep(0)
                trace.add("cancel.waiting_for_delivery", done=canceller.done())
                assert not canceller.done()
                trace.delivery_release.set()
                trace.add("cancel.result", outcome=await canceller)
            elif case == "cancel-inherit-read":
                await wait_signal(trace.reader_enter)
                canceller = asyncio.create_task(work.cancel_and_wait(op, context))
                await asyncio.sleep(0)
                trace.add("cancel.waiting_for_reader", done=canceller.done())
                assert not canceller.done()
                trace.reader_release.set()
                trace.add("cancel.result", outcome=await canceller)
            await asyncio.wait_for(caller, 4)
            trace.add("before.cleanup", state=snapshot(family, work, trace))
        except BaseException as error:
            trace.add("scenario.unexpected", error=error)
        finally:
            trace.create_release.set()
            trace.round_release.set()
            trace.delivery_release.set()
            trace.reader_release.set()
            trace.dispose_release.set()
            trace.add("observer.cleanup")
            try:
                await family.close()
            except BaseException as error:
                trace.add("observer.close.error", error=error)
                # Original retained handle is retried after a failed abort port.
                if trace.case == "interrupt-error":
                    trace.case = "observer-cleanup"
                try:
                    await family.close()
                except BaseException as again:
                    trace.add("observer.close.retry.error", error=again)
            trace.add("after.cleanup", state=snapshot(family, work, trace))
    return trace


@pytest.mark.parametrize("case", CASES)
def test_goal_delegation_runtime(case, tmp_path, monkeypatch):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    trace = None
    unexpected = None
    try:
        trace = asyncio.run(scenario(case, tmp_path))
    except BaseException as error:
        unexpected = error_data(error)
    if trace is not None:
        unexpected = next(
            (
                row["error"]
                for row in trace.rows
                if row["event"] == "scenario.unexpected"
            ),
            unexpected,
        )
    value = {"trace": trace.rows if trace else [], "unexpected": unexpected}
    assert unexpected is None, unexpected
    assert value == _EXPECTED[case], case
