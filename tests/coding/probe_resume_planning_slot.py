"""Freeze real Task behavior at the original Product planning-slot boundary."""

from __future__ import annotations

import asyncio
import gc
import json
from pathlib import Path
from types import SimpleNamespace
from weakref import ref

import pytest

import loushang.coding.runtime.resume_planning as product
import loushang.harness.session.agent_product_runtime as core
from loushang.harness.resources.loader import ResourceLoader

EVIDENCE = Path(__file__).parent
EXPECTED = EVIDENCE / "fixtures" / "resume_planning_slot_v1.jsonl"
SCENARIOS = (
    "pending-duplicate",
    "completed-duplicate",
    "changed-key",
    "worker-error",
    "falsey-error",
    "worker-cancel",
    "cancel-error",
    "cancel-result",
    "discard-double-caller-cancel",
    "close-double-caller-cancel",
    "task-factory-rejection-retry",
    "late-callback-replacement",
    "late-callback-close",
    "cancel-lock-wait",
    "source-stale",
    "owner-stale",
    "source-error",
    "owner-error",
    "weak-loader",
    "close-first",
    "cross-loop",
)


def _error(error, seen=None):
    if error is None:
        return None
    seen = set() if seen is None else seen
    if id(error) in seen:
        return {"cycle": True}
    seen.add(id(error))
    return {
        "type": "<probe.FalseyError>"
        if isinstance(error, _FalseyError)
        else f"{type(error).__module__}.{type(error).__qualname__}",
        "args": list(error.args),
        "notes": getattr(error, "__notes__", []),
        "suppress": error.__suppress_context__,
        "cause": _error(error.__cause__, seen.copy()),
        "context": _error(error.__context__, seen.copy()),
    }


class _FalseyError(RuntimeError):
    def __bool__(self):
        return False


def _state(slot):
    return {
        "fields": list(vars(slot)),
        "loop_bound": slot._loop is not None,
        "loop_current": slot._loop is asyncio.get_running_loop(),
        "task": None
        if slot._task is None
        else {
            "done": slot._task.done(),
            "cancelled": slot._task.cancelled(),
        },
        "plan": None if slot._plan is None else slot._plan.plan_id,
        "key": None
        if slot._key is None
        else [
            slot._key[0],
            "live" if slot._key[1]() is not None else "dead",
            slot._key[2],
            slot._key[3],
        ],
        "closed": slot._closed,
    }


async def _settled(task):
    event = asyncio.Event()
    # Bypass only the deliberate late-callback Task subclass's capture hook.
    asyncio.Task.add_done_callback(task, lambda _done: event.set())
    await event.wait()


async def _exercise(name):
    trace = []
    slot = product.ResumePlanningSlot()
    result = {"initial": _state(slot)}
    loader = ResourceLoader(user_resource_roots=())
    gate = asyncio.Event()
    cancelled = asyncio.Event()
    baseline_seen = asyncio.Event()
    shield_events = [asyncio.Event() for _ in range(8)]
    created = []
    held = []
    mode = {
        "work": name,
        "baseline": "first",
        "reject": name == "task-factory-rejection-retry",
    }
    counts = {"shield": 0}

    class HeldTask(asyncio.Task):
        def add_done_callback(self, callback, *, context=None):
            held.append((self, callback))

    class TaskApi:
        def __getattr__(self, attr):
            return getattr(asyncio, attr)

        def create_task(self, work):
            trace.append(["create_task"])
            created.append(work)
            if mode["reject"]:
                loop = asyncio.get_running_loop()
                previous = loop.get_task_factory()

                def reject(_loop, coroutine, **kwargs):
                    trace.append(["native-factory-reject", coroutine is work])
                    raise OSError(5, "controlled-task-factory")

                loop.set_task_factory(reject)
                try:
                    return asyncio.create_task(work)
                finally:
                    loop.set_task_factory(previous)
            if name.startswith("late-callback"):
                return HeldTask(work, loop=asyncio.get_running_loop())
            return asyncio.create_task(work)

        def shield(self, task):
            number = counts["shield"]
            counts["shield"] += 1
            trace.append(["shield", number + 1])
            shield_events[number].set()
            return asyncio.shield(task)

    def baseline(*args, **kwargs):
        trace.append(
            [
                "baseline",
                mode["baseline"],
                [[item.owner_id, item.fingerprint] for item in kwargs["owner_inputs"]],
            ]
        )
        baseline_seen.set()
        return SimpleNamespace(plan_id=mode["baseline"])

    async def worker(number, identity):
        trace.append(["worker", number, identity])
        try:
            await gate.wait()
        except asyncio.CancelledError:
            trace.append(["worker-cancelled", number])
            cancelled.set()
            if mode["work"] in {
                "discard-double-caller-cancel",
                "close-double-caller-cancel",
            }:
                await gate.wait()
            elif mode["work"] == "cancel-error":
                raise RuntimeError("controlled-cancel-error")
            elif mode["work"] != "cancel-result":
                raise
        if mode["work"] == "worker-error":
            raise RuntimeError("controlled-worker")
        if mode["work"] == "falsey-error":
            raise _FalseyError("controlled-falsey")
        if mode["work"] == "worker-cancel":
            raise asyncio.CancelledError("controlled-worker")
        trace.append(["worker-result", number, identity])
        return SimpleNamespace(plan_id=identity)

    number = 0

    def plan(*args, **kwargs):
        nonlocal number
        number += 1
        trace.append(["factory", number, mode["baseline"], kwargs["priority"]])
        return worker(number, mode["baseline"])

    def check_source(*args):
        trace.append(["source-check"])
        if name == "source-stale":
            raise product.ResumePlanStaleError("controlled-stale")
        if name == "source-error":
            raise ValueError("controlled-source")

    def check_owner(*args):
        trace.append(["owner-check"])
        if name == "owner-stale":
            raise product.ResumePlanStaleError("controlled-stale")
        if name == "owner-error":
            raise ValueError("controlled-owner")

    async def start():
        await slot.start(
            object(),
            object(),
            workspace_root=Path("/model-workspace"),
            resource_loader=loader,
            subject_digest="a" * 64,
            policy_digest="b" * 64,
            max_work_units=200,
            time_budget_seconds=5.0,
        )

    async def outcome(operation):
        try:
            await operation
        except BaseException as error:
            return _error(error)
        return None

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(product, "asyncio", TaskApi(), raising=False)
        patch.setattr(core, "asyncio", TaskApi())
        patch.setattr(product, "build_session_activation_plan", baseline)
        patch.setattr(product, "plan_coding_resume_async", plan)
        patch.setattr(product, "require_current_resume_plan_source", check_source)
        patch.setattr(product, "require_current_resume_plan_inputs", check_owner)
        try:
            if name == "close-first":
                await slot.close()
                result["closed_first"] = _state(slot)
                result["start_error"] = await outcome(start())
            elif name == "cross-loop":
                await slot.discard()
                result["bound"] = _state(slot)
            elif name == "cancel-lock-wait":
                async with slot._transition:
                    task = asyncio.create_task(start())
                    await baseline_seen.wait()
                    task.cancel("lock-wait")
                    result["cancel"] = await outcome(task)
                result["after"] = _state(slot)
            elif name == "task-factory-rejection-retry":
                result["rejected"] = await outcome(start())
                result["coroutine_closed"] = created[0].cr_frame is None
                result["after_reject"] = _state(slot)
                mode["reject"] = False
                await start()
                task = slot._task
                gate.set()
                await _settled(task)
                result["after_retry"] = _state(slot)
            else:
                await start()
                task = slot._task
                started = asyncio.Event()
                # Register a real event-loop turn after the already-scheduled worker.
                asyncio.get_running_loop().call_soon(started.set)
                await started.wait()
                result["started"] = _state(slot)
                if name == "pending-duplicate":
                    await start()
                    result["same_task"] = slot._task is task
                    result["discard"] = await outcome(slot.discard())
                elif name == "changed-key":
                    mode["baseline"] = "second"
                    await start()
                    result["new_task"] = slot._task is not task
                    result["old_cancelled"] = task.cancelled()
                    task = slot._task
                    gate.set()
                    await _settled(task)
                elif name in {"cancel-error", "cancel-result"}:
                    result["discard"] = await outcome(slot.discard())
                elif name.endswith("double-caller-cancel"):
                    operation = (
                        slot.close() if name.startswith("close") else slot.discard()
                    )
                    caller = asyncio.create_task(operation)
                    await cancelled.wait()
                    caller.cancel("first")
                    await shield_events[1].wait()
                    caller.cancel("second")
                    await shield_events[2].wait()
                    gate.set()
                    result["caller_error"] = await outcome(caller)
                    result["cancel_count"] = caller.cancelling()
                elif name.startswith("late-callback"):
                    gate.set()
                    await _settled(task)
                    if name.endswith("replacement"):
                        mode["baseline"] = "second"
                        gate.clear()
                        await start()
                        new_task = slot._task
                        held[0][1](task)
                        result["late_preserves_new"] = slot._task is new_task
                        gate.set()
                        await _settled(new_task)
                        held[1][1](new_task)
                    else:
                        await slot.close()
                        held[0][1](task)
                else:
                    gate.set()
                    await _settled(task)
                    result["task_error_observed"] = not task._log_traceback
                    if name == "completed-duplicate":
                        await start()
                        result["same_plan"] = slot._plan is task.result()
                    if name in {
                        "source-stale",
                        "owner-stale",
                        "source-error",
                        "owner-error",
                    }:
                        try:
                            current = slot.current(object(), current_owner_inputs=())
                            result["current"] = (
                                None if current is None else current.plan_id
                            )
                        except BaseException as error:
                            result["current_error"] = _error(error)
                    if name == "weak-loader":
                        weak = ref(loader)
                        loader = None
                        gc.collect()
                        result["loader_collected"] = weak() is None
                result["after"] = _state(slot)
        finally:
            gate.set()
            result["final_close_error"] = await outcome(slot.close())
            for task, callback in held:
                if task.done():
                    callback(task)
            result["final"] = _state(slot)
    result["trace"] = trace
    return result, slot


def _observe(name):
    result, slot = asyncio.run(_exercise(name))
    if name == "cross-loop":

        async def other_loop():
            try:
                slot.current(object(), current_owner_inputs=())
            except BaseException as error:
                return _error(error)

        result["cross_loop_error"] = asyncio.run(other_loop())
    return result


def _guard():
    root = Path(__file__).resolve().parents[2]
    for module, name in (
        (product, "src/loushang/coding/runtime/resume_planning.py"),
        (core, "src/loushang/harness/session/agent_product_runtime.py"),
    ):
        assert Path(module.__file__).resolve() == root / name


_RECORDS = [json.loads(line) for line in EXPECTED.read_text().splitlines()[1:]]


@pytest.mark.parametrize("record", _RECORDS, ids=lambda record: record["name"])
def test_replay(record):
    _guard()
    assert _observe(record["name"]) == record["result"]


def test_actual_hosted_background_slot_retains_plan_and_closes_waiter(
    tmp_path, monkeypatch
):
    from loushang.appserver.protocol import SessionScopeV1
    from loushang.coding.bootstrap import create_services
    from loushang.coding.control import SettingsManager
    from loushang.coding.hosted_catalog import (
        CodingHostedScopeV1,
        CodingHostedSessionCatalogV1,
    )
    from loushang.coding.hosted_resume import CodingDeferredHostedSessionV1
    from tests.coding.test_hosted_catalog import _intent

    _guard()
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))

    async def scenario():
        loader = ResourceLoader(user_resource_roots=())
        scope = CodingHostedScopeV1(SessionScopeV1.CWD, tmp_path / "sessions", tmp_path)
        catalog = CodingHostedSessionCatalogV1((scope,), owned_transcripts=False)
        candidate = claimed = binding = None
        created = await catalog.create_candidate(_intent(scope))
        created_claim = await created.claim()
        manager = created_claim.opaque_binding.take_manager()
        try:
            path = manager.session_file
            session_id = manager.get_header().conversation_id
            assert path is not None
        finally:
            await manager.dispose_runtime_profile()
            await created_claim.close()
            await created.close()
        before = path.read_bytes()
        try:
            rows = await catalog.list_identities((scope.discovery_scope,), limit=256)
            assert len(rows) == 1
            candidate = await catalog.open_history_candidate(
                rows[0].reference, max_bytes=1024 * 1024
            )
            claimed = await candidate.claim()
            source = claimed.opaque_binding.take_resume_source()
            assert source.history.header_preview.header.conversation_id == session_id
            services = create_services(
                resource_loader=loader,
                settings_manager=SettingsManager(
                    global_settings_path=tmp_path / "global-settings.json",
                    project_settings_path=tmp_path / "project-settings.json",
                ),
            )
            # No Product activation is requested; this dependency is never borrowed.
            binding = CodingDeferredHostedSessionV1(
                source,
                services=services,
                model=None,
                stream_fn=None,
                tools=None,
                output_capture_factory=None,
                product_owner_selection=None,
            )
            await binding.start_background_planning()
            slot = binding._planning
            assert slot is not None
            task = slot._task
            assert task is not None
            settled = asyncio.Event()
            task.add_done_callback(lambda _done: settled.set())
            await settled.wait()
            plan = slot._plan
            assert task.exception() is None
            assert plan is not None
            assert plan.session_id == session_id
            assert (
                slot.current(source.history, current_owner_inputs=plan.owner_inputs)
                is plan
            )
            assert binding._active is None
            assert path.read_bytes() == before
            await binding.close()
            assert slot._task is None and slot._plan is None and slot._closed
            assert path.read_bytes() == before
        finally:
            if binding is not None:
                await binding.close()
            if claimed is not None:
                await claimed.close()
            if candidate is not None:
                await candidate.close()
            await catalog.close()
            await loader.close_catalog_preview_tasks()

    asyncio.run(scenario())
