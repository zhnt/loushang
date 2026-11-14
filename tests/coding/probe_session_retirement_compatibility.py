"""Explicit fixed Root/Continuity retirement observations over controlled owners."""

from __future__ import annotations

import asyncio
import gzip
import inspect
import json
import pickle
import weakref
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.continuity as continuity
from loushang.coding.runtime.agent_session_runtime import AgentSessionRuntime
from loushang.harness.session.product_runtime import ProductSessionRuntime

EXPECTED = Path(__file__).parent / "fixtures" / "session_retirement_v1.json.gz"
SLOT = "_loushang_coding_continuity"
CASES = (
    "root-success",
    "root-no-factory-selection",
    "root-loop-mismatch",
    "root-empty-foreign-loop",
    "root-selection-fence-error",
    "root-on-loop-error",
    "root-factory-fence-error",
    "root-drain-error",
    "root-fence-drain-error",
    "root-super-error",
    "root-fence-super-error",
    "root-planning-error",
    "root-history-error",
    "root-factory-close-error",
    "root-continuity-error",
    "root-selection-close-error",
    "root-all-tail-errors",
    "root-retry-super",
    "root-cancel-drain",
    "root-cancel-super",
    "root-cancel-planning",
    "root-double-cancel",
    "root-real-continuity",
    "composition-layout",
    "composition-success",
    "composition-owned-view",
    "composition-unowned-view",
    "composition-hub-retry",
    "composition-binder-retry",
    "composition-owned-retry",
    "composition-publication-retry",
    "composition-task-cancel-retry",
    "reservation-empty",
    "reservation-success",
    "reservation-construction-error",
    "reservation-generation-base",
    "reservation-binder-error",
    "reservation-all-fail",
    "reservation-partial-pair",
    "reservation-task-cancel-retry",
    "outer-unknown",
    "outer-foreign-composition",
    "outer-foreign-reservation",
    "outer-composition",
    "outer-reservation",
    "outer-reservation-errors",
    "outer-slot-replacement",
    "outer-lookup-typeerror",
    "outer-delete-getattr-typeerror",
    "outer-delattr-typeerror",
    "outer-delattr-attributeerror",
    "outer-composition-cancel",
    "outer-composition-cancel-inner-error",
    "outer-reservation-cancel",
    "outer-reservation-cancel-codes",
)


class InputError(RuntimeError):
    __module__ = "__a174_input__"


class InputBase(BaseException):
    __module__ = "__a174_input__"


def error_value(error, seen=None):
    if error is None:
        return None
    seen = set() if seen is None else seen
    if id(error) in seen:
        return {"cycle": True}
    seen.add(id(error))
    return {
        "type": type(error).__module__ + "." + type(error).__qualname__,
        "args": list(error.args),
        "code": getattr(error, "code", None),
        "notes": list(getattr(error, "__notes__", ())),
        "message": str(error),
        "cause": error_value(error.__cause__, seen.copy()),
        "context": error_value(error.__context__, seen.copy()),
        "suppress": error.__suppress_context__,
    }


async def observe_root(case, monkeypatch):
    trace = []
    faults = {}
    flags = {"selection_closed": False, "factory_closed": False}
    entered = {
        "drain": asyncio.Event(),
        "super": asyncio.Event(),
        "planning": asyncio.Event(),
        "factory-close": asyncio.Event(),
    }
    release = asyncio.Event()
    configs = {
        "root-selection-fence-error": {"selection-fence"},
        "root-on-loop-error": {"on-loop"},
        "root-factory-fence-error": {"factory-fence"},
        "root-drain-error": {"drain"},
        "root-fence-drain-error": {"factory-fence", "drain"},
        "root-super-error": {"super"},
        "root-fence-super-error": {"factory-fence", "super"},
        "root-planning-error": {"planning"},
        "root-history-error": {"history"},
        "root-factory-close-error": {"factory-close"},
        "root-continuity-error": {"continuity"},
        "root-selection-close-error": {"selection-close"},
        "root-all-tail-errors": {
            "factory-fence",
            "planning",
            "history",
            "factory-close",
            "continuity",
            "selection-close",
        },
        "root-retry-super": {"super"},
    }
    for label in configs.get(case, set()):
        faults[label] = InputBase(label) if label == "drain" else InputError(label)
    calls = {}

    def sync(label):
        trace.append(label)
        calls[label] = calls.get(label, 0) + 1
        if label in faults and not (case == "root-retry-super" and calls[label] > 1):
            raise faults[label]

    async def phase(label):
        sync(label)
        if label in entered:
            entered[label].set()
        if case == "root-cancel-" + label or (
            case == "root-double-cancel" and label in {"planning", "factory-close"}
        ):
            await release.wait()

    class Selection:
        def fence(self):
            sync("selection-fence")

        def close(self):
            sync("selection-close")
            flags["selection_closed"] = True

    class Factory:
        def _on_loop(self):
            sync("on-loop")

        def fence(self):
            sync("factory-fence")

        async def close(self):
            await phase("factory-close")
            flags["factory_closed"] = True

    class Planning:
        async def close(self):
            await phase("planning")

    owner = object.__new__(AgentSessionRuntime)
    owner._resume_history_reads = {object()} if case == "root-loop-mismatch" else set()
    owner._resume_history_loop = (
        object()
        if case in {"root-loop-mismatch", "root-empty-foreign-loop"}
        else asyncio.get_running_loop()
    )
    owner._resume_history_closed = False
    owner._owned_transcript_factory = (
        None if case == "root-no-factory-selection" else Factory()
    )
    owner._product_owner_selection = (
        None if case == "root-no-factory-selection" else Selection()
    )
    owner._resume_planning = Planning()
    initial_factory = owner._owned_transcript_factory
    initial_selection = owner._product_owner_selection
    initial_planning = owner._resume_planning

    async def drain(*, error_prefix):
        trace.append(["drain-prefix", error_prefix])
        await phase("drain")

    owner._lifecycle = SimpleNamespace(drain_retained_preparations=drain)

    async def history():
        await phase("history")

    owner._drain_resume_history_reads = history
    metadata = {"sentinel": "same-object"}

    async def base(self, *, metadata=None):
        trace.append(
            ["metadata-is-input", self is owner and metadata is input_metadata]
        )
        await phase("super")

    input_metadata = metadata
    monkeypatch.setattr(ProductSessionRuntime, "dispose_session_runtime", base)

    async def shutdown(runtime):
        assert runtime is owner
        await phase("continuity")

    if case == "root-real-continuity":
        composition = make_composition(trace)
        setattr(owner, SLOT, composition)
    else:
        monkeypatch.setattr(continuity, "shutdown_coding_continuity", shutdown)
    caught = None
    retry = None
    try:
        if case.startswith("root-cancel-") or case == "root-double-cancel":
            label = (
                case.removeprefix("root-cancel-")
                if case != "root-double-cancel"
                else "planning"
            )
            task = asyncio.create_task(owner.dispose_session_runtime(metadata=metadata))
            assert await asyncio.wait_for(entered[label].wait(), 3) is True
            assert task.cancel("first")
            if case == "root-double-cancel":
                assert (
                    await asyncio.wait_for(entered["factory-close"].wait(), 3) is True
                )
                assert task.cancel("second")
            try:
                await task
            except BaseException as exc:
                caught = exc
        else:
            await owner.dispose_session_runtime(metadata=metadata)
    except BaseException as exc:
        caught = exc
    if case == "root-retry-super":
        assert (
            caught is faults["super"]
            and not flags["factory_closed"]
            and not flags["selection_closed"]
        )
        first = {
            "error": error_value(caught),
            "trace": list(trace),
            "flags": dict(flags),
        }
        caught = None
        try:
            await owner.dispose_session_runtime(metadata=metadata)
        except BaseException as exc:
            caught = exc
        retry = first
    expected_failure = {
        "root-selection-fence-error": "selection-fence",
        "root-on-loop-error": "on-loop",
        "root-factory-fence-error": "factory-fence",
        "root-drain-error": "drain",
        "root-fence-drain-error": "drain",
        "root-super-error": "super",
        "root-fence-super-error": "factory-fence",
        "root-planning-error": "planning",
        "root-history-error": "history",
        "root-factory-close-error": "factory-close",
        "root-continuity-error": "continuity",
        "root-selection-close-error": "selection-close",
        "root-all-tail-errors": "factory-fence",
    }
    if case in expected_failure:
        assert caught is faults[expected_failure[case]], error_value(caught)
    elif case.startswith("root-cancel-") or case == "root-double-cancel":
        assert isinstance(caught, asyncio.CancelledError)
    elif case == "root-loop-mismatch":
        assert (
            type(caught) is RuntimeError
            and str(caught) == "coding_resume_history_loop_changed"
        )
        assert trace == []
    else:
        assert caught is None, error_value(caught)
    return {
        "trace": trace,
        "error": error_value(caught),
        "flags": flags,
        "closed": owner._resume_history_closed,
        "factory_same": owner._owned_transcript_factory is initial_factory,
        "selection_same": owner._product_owner_selection is initial_selection,
        "planning_same": owner._resume_planning is initial_planning,
        "factory_present": owner._owned_transcript_factory is not None,
        "selection_present": owner._product_owner_selection is not None,
        "retry": retry,
        "slot_present": hasattr(owner, SLOT),
    }


def make_composition(
    trace, *, failing=None, blocked=None, replace=None, publication=False
):
    faults = {} if failing is None else failing
    calls = {}

    async def phase(label):
        trace.append(label)
        calls[label] = calls.get(label, 0) + 1
        if blocked is not None and label == blocked["label"] and calls[label] == 1:
            blocked["entered"].set()
            await blocked["release"].wait()
        if replace is not None and label == "hub":
            setattr(replace[0], SLOT, replace[1])
        if label in faults and calls[label] == 1:
            raise faults[label]

    class Hub:
        async def close(self):
            await phase("hub")

    class Binder:
        async def dispose(self, value):
            assert value is binding
            await phase("binder")

    class Publication:
        async def shutdown(self):
            await phase("publication")

    def owned():
        trace.append("owned")
        calls["owned"] = calls.get("owned", 0) + 1
        if "owned" in faults and calls["owned"] == 1:
            raise faults["owned"]

    binding = object()
    obj = continuity.CodingContinuityComposition(
        binding,
        Binder(),
        Hub(),
        plugin_publication=Publication() if publication else None,
        owned_cleanup=owned,
    )
    return obj


def comp_flags(obj):
    return [obj._core_shutdown, obj._owned_cleanup_complete, obj._shutdown]


async def observe_composition(case):
    trace = []
    if case == "composition-layout":
        obj = continuity.CodingContinuityComposition(None, None, None)
        raw = pickle.dumps(obj, protocol=4)
        restored = pickle.loads(raw)
        return {
            "class": type(obj).__module__ + "." + type(obj).__qualname__,
            "fields": [x.name for x in fields(obj)],
            "own_annotations": list(type(obj).__annotations__),
            "signature": str(inspect.signature(type(obj))),
            "dict_keys": list(vars(obj)),
            "weakref": weakref.ref(obj)() is obj,
            "pickle": raw.hex(),
            "restored_same_class": type(restored) is type(obj),
            "restored_values": vars(restored),
        }
    label = {
        "composition-hub-retry": "hub",
        "composition-binder-retry": "binder",
        "composition-owned-retry": "owned",
        "composition-publication-retry": "publication",
    }.get(case)
    fault = InputError(label) if label else None
    blocked = (
        {"label": "hub", "entered": asyncio.Event(), "release": asyncio.Event()}
        if case == "composition-task-cancel-retry"
        else None
    )
    obj = make_composition(
        trace,
        failing={label: fault} if label else {},
        blocked=blocked,
        publication=case == "composition-publication-retry",
    )
    obj.runtime_owned = case == "composition-owned-view"
    caught = None
    try:
        if blocked:
            task = asyncio.create_task(obj.shutdown())
            assert await asyncio.wait_for(blocked["entered"].wait(), 3) is True
            task.cancel("component")
            try:
                await task
            except BaseException as exc:
                caught = exc
        elif case in {"composition-owned-view", "composition-unowned-view"}:
            await obj.dispose()
        else:
            await obj.shutdown()
    except BaseException as exc:
        caught = exc
    first = {
        "error": error_value(caught),
        "flags": comp_flags(obj),
        "trace": list(trace),
    }
    if fault is not None:
        assert caught is fault
    elif blocked:
        assert isinstance(caught, asyncio.CancelledError)
    else:
        assert caught is None
    if case.endswith("retry"):
        await obj.shutdown()
        assert comp_flags(obj) == [True, True, True]
    elif case == "composition-success":
        await obj.shutdown()
        assert trace == ["hub", "binder", "owned"]
    return {"first": first, "final_flags": comp_flags(obj), "trace": trace}


def make_reservation(trace, *, failing=(), blocked=None):
    faults = {
        label: InputBase(label)
        if label in {"generation", "construction"}
        else InputError(label)
        for label in failing
    }
    calls = {}

    async def phase(label):
        trace.append(label)
        calls[label] = calls.get(label, 0) + 1
        if blocked is not None and label == "construction" and calls[label] == 1:
            blocked["entered"].set()
            await blocked["release"].wait()
        if label in faults and calls[label] == 1:
            raise faults[label]

    class Cleanup:
        async def retry(self):
            await phase("construction")

    class Generation:
        async def dispose(self):
            await phase("generation")

    class Binder:
        async def dispose(self, value):
            assert value is binding
            await phase("base")

    binding = object()
    obj = continuity._CodingContinuityBindingReservation(
        Binder(), binding, Generation(), Cleanup(), object()
    )
    return obj


def reservation_refs(obj):
    return [
        obj.construction_cleanup is not None,
        obj.generation is not None,
        obj.binder is not None,
        obj.binding is not None,
        obj.generation_authority is not None,
    ]


async def observe_reservation(case):
    trace = []
    failures = {
        "reservation-construction-error": ("construction",),
        "reservation-generation-base": ("generation",),
        "reservation-binder-error": ("base",),
        "reservation-all-fail": ("construction", "generation", "base"),
    }.get(case, ())
    blocked = (
        {"entered": asyncio.Event(), "release": asyncio.Event()}
        if case == "reservation-task-cancel-retry"
        else None
    )
    obj = make_reservation(trace, failing=failures, blocked=blocked)
    if case == "reservation-empty":
        obj.construction_cleanup = obj.generation = obj.binder = obj.binding = None
    if case == "reservation-partial-pair":
        obj.binding = None
    if blocked:
        task = asyncio.create_task(obj.retry_cleanup())
        assert await asyncio.wait_for(blocked["entered"].wait(), 3) is True
        task.cancel("reservation")
        codes = await task
        assert not task.cancelled()
    else:
        codes = await obj.retry_cleanup()
    first = {"codes": codes, "refs": reservation_refs(obj), "trace": list(trace)}
    if failures or blocked:
        assert codes
        second = await obj.retry_cleanup()
        assert second == ()
    return {"first": first, "final_refs": reservation_refs(obj), "trace": trace}


async def observe_outer(case):
    trace = []
    reads = 0
    successor = object()

    class Runtime:
        def __getattribute__(self, name):
            nonlocal reads
            if name == SLOT:
                reads += 1
                if case == "outer-lookup-typeerror" or (
                    case == "outer-delete-getattr-typeerror" and reads > 1
                ):
                    raise TypeError("slot lookup")
            return object.__getattribute__(self, name)

        def __delattr__(self, name):
            if name == SLOT:
                trace.append("delete")
                if case == "outer-delattr-typeerror":
                    raise TypeError("slot delete")
                if case == "outer-delattr-attributeerror":
                    raise AttributeError("slot delete")
            object.__delattr__(self, name)

    runtime = Runtime()
    blocked = {"label": "hub", "entered": asyncio.Event(), "release": asyncio.Event()}
    reservation_block = {"entered": asyncio.Event(), "release": asyncio.Event()}
    if case in {"outer-unknown", "outer-lookup-typeerror"}:
        obj = object()
    elif case in {"outer-foreign-composition", "outer-foreign-reservation"}:
        base = (
            continuity.CodingContinuityComposition.__bases__[0]
            if case.endswith("composition")
            else continuity._CodingContinuityBindingReservation.__bases__[0]
        )

        class Foreign(base):
            async def shutdown(self):
                trace.append("wrong-foreign-shutdown")

            async def retry_cleanup(self):
                trace.append("wrong-foreign-retry")
                return ()

        obj = Foreign()
    elif case.startswith("outer-reservation"):
        failed = (
            ("construction", "generation", "base")
            if case == "outer-reservation-errors"
            else ("construction",)
            if case == "outer-reservation-cancel-codes"
            else ()
        )
        obj = make_reservation(
            trace,
            failing=failed,
            blocked=reservation_block if "cancel" in case else None,
        )
    else:
        fail = (
            {"hub": InputError("hub")}
            if case == "outer-composition-cancel-inner-error"
            else {}
        )
        obj = make_composition(
            trace,
            failing=fail,
            blocked=blocked if "cancel" in case else None,
            replace=(runtime, successor) if case == "outer-slot-replacement" else None,
        )
    setattr(runtime, SLOT, obj)
    caught = None
    try:
        if "cancel" in case:
            task = asyncio.create_task(continuity.shutdown_coding_continuity(runtime))
            event = (
                reservation_block["entered"]
                if case.startswith("outer-reservation")
                else blocked["entered"]
            )
            assert await asyncio.wait_for(event.wait(), 3) is True
            assert task.cancel("caller")
            (reservation_block if case.startswith("outer-reservation") else blocked)[
                "release"
            ].set()
            try:
                await task
            except BaseException as exc:
                caught = exc
        else:
            await continuity.shutdown_coding_continuity(runtime)
    except BaseException as exc:
        caught = exc
    if "cancel" in case and case != "outer-composition-cancel-inner-error":
        assert isinstance(caught, asyncio.CancelledError), error_value(caught)
    elif case == "outer-composition-cancel-inner-error":
        assert isinstance(caught, InputError), error_value(caught)
    elif case == "outer-reservation-errors":
        assert type(caught) is continuity.ContinuityPluginLifecycleError
        assert caught.code == "coding_continuity_binding_cleanup_retryable"
    elif case in {
        "outer-lookup-typeerror",
        "outer-delete-getattr-typeerror",
        "outer-delattr-typeerror",
    }:
        assert type(caught) is TypeError
    else:
        assert caught is None, error_value(caught)
    current = vars(runtime).get(SLOT)
    assert not any(value.startswith("wrong-foreign") for value in trace)
    return {
        "trace": trace,
        "error": error_value(caught),
        "slot_reads": reads,
        "slot": "old"
        if current is obj
        else "successor"
        if current is successor
        else "absent",
        "composition_flags": comp_flags(obj)
        if isinstance(obj, continuity.CodingContinuityComposition)
        else None,
        "reservation_refs": reservation_refs(obj)
        if isinstance(obj, continuity._CodingContinuityBindingReservation)
        else None,
    }


@pytest.mark.parametrize("case", CASES)
def test_retirement(case, monkeypatch):
    if case.startswith("root-"):
        observed = asyncio.run(observe_root(case, monkeypatch))
    elif case.startswith("composition-"):
        observed = asyncio.run(observe_composition(case))
    elif case.startswith("reservation-"):
        observed = asyncio.run(observe_reservation(case))
    else:
        observed = asyncio.run(observe_outer(case))
    observed = json.loads(json.dumps(observed))
    assert observed == json.loads(gzip.decompress(EXPECTED.read_bytes()))[case]
